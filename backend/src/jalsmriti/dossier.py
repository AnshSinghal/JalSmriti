"""Evidence dossiers: facts by code, the letter by an agent, numbers checked, translated, signed.

  1. Code assembles the facts (satellite metrics, evidence provenance, the right authority and laws).
  2. A Strands agent on Amazon Nova drafts a formal, respectful letter, fetching facts through tools. It may use
     only those facts; code then checks that every number in the letter is one the code supplied, and asks again
     (once) with the problem spelled out. If Bedrock is unavailable, a plain template letter is used instead.
  3. Amazon Translate (or Nova, for Nepali / Assamese / Odia) writes the second language; numbers re-checked.
  4. The PDF is rendered, both the content and the PDF are hashed, and the attestation is signed with AWS KMS.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from . import config as C
from .translate import LANG_NAMES, normalise_digits

log = logging.getLogger(__name__)


class DraftError(Exception):
    pass


def build_facts(lake: dict, area, evidence: list[dict], recipient: dict, laws: list[str]) -> dict:
    m = lake.get("metrics") or {}
    ret = (m.get("retention") or {})
    q = m.get("quality") or {}
    sl = m.get("storageLost") or {}
    built_years = [int(y) for y in (m.get("builtByYear") or {})]
    series = m.get("series") or []
    f = {
        "lakeName": lake.get("name"), "lakeId": lake["lakeId"], "lat": lake["lat"], "lon": lake["lon"],
        "areaName": (area.names.get("en") if area else None) or (lake.get("admin") or {}).get("city"),
        "state": (area.state if area else None) or (lake.get("admin") or {}).get("state"),
        "historicHa": m.get("historicHa"), "lostHa": m.get("lostHa"), "lostPct": m.get("lostPct"),
        "builtHa": m.get("builtHa"), "builtPct": m.get("builtPct"), "builtYear": max(built_years) if built_years else None,
        "retentionPct": round(100 * ret["ratio"]) if ret.get("ratio") is not None else None,
        "weedPct": q.get("weedPct"), "qualityDate": q.get("date"),
        "storageLowML": sl.get("millionLitresLow"), "storageHighML": sl.get("millionLitresHigh"),
        "grade": (m.get("grade") or {}).get("grade"), "score": (m.get("grade") or {}).get("score"),
        "evidenceCount": len(evidence), "verifiedCount": sum(1 for e in evidence if e.get("status") == "verified"),
        "firstSeason": series[0]["season"] if series else None, "lastSeason": series[-1]["season"] if series else None,
        "recipient": recipient.get("name"), "laws": laws, "today": date.today().strftime("%d %B %Y").lstrip("0"),
        "evidenceKinds": sorted({c for e in evidence for c in (e.get("categories") or []) if c not in ("other", "healthy")}),
        "series": [{"season": s["season"], "waterHa": s["waterHa"], "source": s.get("source")} for s in series],
    }
    return {k: v for k, v in f.items() if v is not None}


# ------------------------------------------------------------------------------------------ number check
_MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                        "September", "October", "November", "December"], 1)}


def _forms(v) -> set[str]:
    out: set[str] = set()
    if isinstance(v, bool) or v is None:
        return out
    if isinstance(v, (int, float)):
        fv = float(v)
        out |= {str(v), f"{fv:g}", f"{fv:.1f}", str(round(fv)), f"{fv:,.0f}".replace(",", "")}
        if fv.is_integer():
            out.add(str(int(fv)))
    elif isinstance(v, str):
        out |= set(re.findall(r"\d+(?:\.\d+)?", v.replace(",", "")))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            y, mo, d = v.split("-")
            out |= {y, str(int(mo)), mo, str(int(d)), d}
        mm = re.fullmatch(r"(\d{1,2}) ([A-Z][a-z]+) (\d{4})", v)
        if mm and mm.group(2) in _MONTHS:
            out |= {str(_MONTHS[mm.group(2)]), f"{_MONTHS[mm.group(2)]:02d}", f"{int(mm.group(1)):02d}"}
    elif isinstance(v, dict):
        for x in v.values():
            out |= _forms(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            out |= _forms(x)
    return out


def allowed_numbers(facts: dict) -> set[str]:
    ok = set()
    for k, v in facts.items():
        ok |= _forms(v)
    ok |= {str(i) for i in range(0, 11)} | {"1984", "2020", "30", "100"}
    return ok


def unsupported_numbers(text: str, facts: dict) -> list[str]:
    t = normalise_digits(text).replace(",", "")
    found = re.findall(r"(?<![\w.])\d+(?:\.\d+)?", t)
    ok = allowed_numbers(facts)
    return sorted({n for n in found if n not in ok and n.rstrip("0").rstrip(".") not in ok})


# ------------------------------------------------------------------------------------------ drafting
SYSTEM = """You draft formal, respectful complaint letters from a citizen of India or Nepal to a public authority
about a lake, tank, pond or wetland that has been damaged or encroached. Rules:
- Use ONLY facts returned by your tools. Never invent numbers, dates, names, laws, causes or people.
- Do not accuse any named person or organisation; describe what the satellite record and the photos show.
- Say plainly that the satellite figures are approximate (30 m pixels) and ask the authority to verify on the ground.
- Ask for specific actions: a site inspection; survey and demarcation of the water body's full extent; removal of
  encroachments and dumping as the law provides; protection of inflow and outflow channels; a written reply.
- Plain, polite English. Body under 260 words, in short paragraphs. Do not include a salutation line with a
  personal name; start with "Respected Sir/Madam,". End with "Yours faithfully," and nothing after it.
Return ONLY a JSON object: {"subject": "...(under 18 words)", "body": "...", "asks": ["...", "..."]} with 3-5 asks."""


def _make_agent(model_id: str, facts: dict, evidence: list[dict], recipient: dict):
    from botocore.config import Config
    from strands import Agent, tool
    from strands.models import BedrockModel

    @tool
    def get_lake_facts() -> str:
        """Satellite facts about the water body, computed by code (areas in hectares, percentages, seasons)."""
        keep = {k: v for k, v in facts.items() if k not in ("series", "laws", "recipient")}
        return json.dumps(keep, ensure_ascii=False)

    @tool
    def get_evidence_summary() -> str:
        """Citizen photo evidence: date, what the photo shows, and whether an NGO verifier confirmed it."""
        return json.dumps([{"date": (e.get("capturedAt") or e.get("createdAt") or "")[:10], "shows": e.get("categories"),
                            "verified": e.get("status") == "verified"} for e in evidence[:12]], ensure_ascii=False)

    @tool
    def get_recipient_and_laws() -> str:
        """Who the letter is addressed to and the laws that apply to water bodies here."""
        return json.dumps({"recipient": recipient.get("name"), "laws": facts.get("laws", [])}, ensure_ascii=False)

    model = BedrockModel(model_id=model_id, region_name=C.REGION, temperature=0.2, max_tokens=1400, streaming=False,
                         boto_client_config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 2}))
    return Agent(model=model, system_prompt=SYSTEM, tools=[get_lake_facts, get_evidence_summary, get_recipient_and_laws],
                 callback_handler=None)


def _clean(d: dict) -> dict | None:
    subject = str(d.get("subject") or "").strip()
    body = str(d.get("body") or "").strip()
    asks = [str(a).strip() for a in (d.get("asks") or []) if str(a).strip()][:5]
    if not subject or not body:
        return None
    return {"subject": subject, "body": body, "asks": asks}


def template_letter(facts: dict) -> dict:
    """Plain letter used when no model is available (or locally). Every number comes from the facts."""
    name = facts.get("lakeName", "the water body")
    parts = ["Respected Sir/Madam,",
             f"I write about {name} ({facts['lat']:.5f} N, {facts['lon']:.5f} E). Open satellite records show that it "
             f"held water across about {facts.get('historicHa', 0):g} ha between 1984 and 2020, and that about "
             f"{facts.get('lostHa', 0):g} ha of that water spread has since been lost."]
    if facts.get("builtHa"):
        parts.append(f"About {facts['builtHa']:g} ha of the old lake bed now appears built over.")
    if facts.get("retentionPct") is not None:
        parts.append(f"In recent seasons the water body held about {facts['retentionPct']}% of the water it held in "
                     f"past years of similar monsoon rain.")
    if facts.get("weedPct") is not None and facts["weedPct"] >= 20:
        qd = facts.get("qualityDate") or ""
        try:
            qd = date.fromisoformat(qd[:10]).strftime("%d %B %Y").lstrip("0")
        except ValueError:
            pass
        parts.append(f"On {qd}, floating weeds covered about {facts['weedPct']:g}% of its water surface.")
    parts.append("These figures come from satellite pixels of 10 to 30 m and are approximate; I request that they be "
                 "verified on the ground.")
    n, v = facts.get("evidenceCount") or 0, facts.get("verifiedCount") or 0
    if n:
        photos = "1 photograph" if n == 1 else f"{n} photographs"
        checked = "" if not v else (" It has been checked by a verifier." if n == 1 and v == 1 else
                                    f" {v} of them have been checked by a verifier.")
        parts.append(f"Citizens have recorded {photos} at the site, attached with their capture details in this dossier.{checked}")
    parts.append("Water bodies like this one store monsoon rain and protect the surrounding neighbourhoods from "
                 "flooding. I request your office to act on the points below and to send a written reply.")
    parts.append("Yours faithfully,")
    return {"subject": f"Request for inspection and protection of {name}",
            "body": "\n\n".join(parts),
            "asks": ["Inspect the site and verify the findings in this dossier.",
                     "Survey and demarcate the full extent of the water body.",
                     "Remove encroachments and stop dumping as the law provides.",
                     "Protect the inflow and outflow channels.",
                     "Send a written reply on the action taken."]}


def draft_letter(facts: dict, evidence: list[dict], recipient: dict, agent_factory=None) -> dict:
    if C.LOCAL and agent_factory is None:
        return {**template_letter(facts), "model": "template (local stack)", "attempts": 0}
    factory = agent_factory or (lambda mid: _make_agent(mid, facts, evidence, recipient))
    last = None
    for mid in C.TEXT_MODEL_IDS:
        try:
            agent = factory(mid)
            ask, problem = "Draft the letter now. Fetch the facts, evidence and recipient with your tools first.", None
            for attempt in (1, 2):
                if problem:
                    ask = f"Your draft had a problem: {problem}. Rewrite it using only tool facts; return only the JSON."
                from .bedrock import parse_json
                d = _clean(parse_json(str(agent(ask))) or {})
                if not d:
                    problem = "it was not a JSON object with subject, body and asks"
                    continue
                bad = unsupported_numbers("\n".join([d["subject"], d["body"], *d["asks"]]), facts)
                if bad:
                    problem = f"it used numbers that are not in the facts: {', '.join(bad)}"
                    continue
                return {**d, "model": mid, "attempts": attempt}
            last = DraftError(problem)
        except Exception as ex:
            last = ex
            log.warning("agent with %s failed: %s", mid, str(ex)[:300])
    log.warning("falling back to the template letter: %s", last)
    return {**template_letter(facts), "model": "template (AI unavailable)", "attempts": 0, "aiError": str(last)[:200]}


def translate_letter(letter: dict, lang: str) -> dict | None:
    from .translate import translate
    if lang == "en":
        return None
    joined = letter["subject"] + "\n\n" + letter["body"] + ("\n\n" + "\n".join(letter.get("asks", [])) if letter.get("asks") else "")
    r = translate(joined, lang)
    parts = r["text"].split("\n\n")
    subject = parts[0].strip()
    n_asks = len(letter.get("asks", []))
    asks = []
    body_parts = parts[1:]
    if n_asks and body_parts:
        tail = body_parts[-1].split("\n")
        if len(tail) >= n_asks:
            asks = [a.strip() for a in tail[-n_asks:]]
            rest = "\n".join(tail[:-n_asks]).strip()
            body_parts = body_parts[:-1] + ([rest] if rest else [])
    return {"subject": subject, "body": "\n\n".join(body_parts).strip(), "asks": asks, "engine": r["engine"],
            "machine": r["machine"], "language": lang, "languageName": LANG_NAMES.get(lang, lang)}

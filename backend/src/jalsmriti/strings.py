"""Words the server writes in the reader's language: place reports (PDF), narration (Amazon Polly) and rain emails.

The website's dictionaries (web/src/i18n/*.ts) are the only source of these words. `npm run export:strings` in web/
copies the keys the server needs into data/ui_strings.json, so the PDF, the email and the page say the same thing in
the same words. A key missing in a language falls back to English, then to the default given by the caller.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

LANGS = ("en", "hi", "kn", "ta", "te", "ml", "ne")
_PATH = Path(__file__).resolve().parent / "data" / "ui_strings.json"


@lru_cache(maxsize=1)
def _all() -> dict:
    try:
        return json.loads(_PATH.read_text("utf-8"))
    except FileNotFoundError:
        return {}


def lang_or_en(lang: str | None) -> str:
    return lang if lang in LANGS else "en"


def has(lang: str, key: str) -> bool:
    return key in (_all().get(lang) or {}) or key in (_all().get("en") or {})


def t(lang: str | None, key: str, en: str | None = None, **vars) -> str:
    """The text for `key` in `lang` with {placeholders} filled in."""
    d = _all()
    s = (d.get(lang_or_en(lang)) or {}).get(key) or (d.get("en") or {}).get(key) or en or key
    for name, v in vars.items():
        s = s.replace("{" + name + "}", str(v))
    return s


def num(v, digits: int | None = None) -> str:
    """Like the website's ha(): up to one decimal under 100, Indian digit grouping above (12,34,567)."""
    if v is None:
        return "-"
    v = float(v)
    d = digits if digits is not None else (0 if abs(v) >= 100 else 1)
    s = f"{round(v, d):.{d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    neg = s.startswith("-")
    whole, _, frac = s.lstrip("-").partition(".")
    if len(whole) > 3:   # en-IN grouping: last three digits, then pairs
        head, tail = whole[:-3], whole[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + pairs + [tail])
    return ("-" if neg else "") + whole + (("." + frac) if frac else "")


def day(iso: str | date | None, lang: str | None = "en") -> str:
    """'5 Sep 2022' in the reader's language (month names come from the dictionaries)."""
    if not iso:
        return "-"
    if isinstance(iso, str):
        try:
            d = datetime.fromisoformat(iso.replace("Z", "+00:00")).date() if len(iso) > 10 else date.fromisoformat(iso)
        except ValueError:
            return iso
    elif isinstance(iso, datetime):
        d = iso.date()
    else:
        d = iso
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{d.day} {t(lang, f'month.{d.month}', months[d.month - 1])} {d.year}"


def tier_label(tier: str | None, lang: str | None) -> str:
    return t(lang, f"place.memory.{tier or 'unknown'}")


def finding_text(f: dict, lang: str | None) -> str:
    """Port of the website's useFindingText(): the finding from its key and numbers, else the stored English."""
    v = f.get("vars")
    if v is None:
        return f.get("text") or ""
    key = f"f.{f.get('key')}"
    if f.get("key") == "lost":
        s = t(lang, "f.lost", lostHa=num(v.get("lostHa")), lostPct=round(v.get("lostPct") or 0))
        now = [t(lang, f"lc.{k}", ha=num(n)) for k, n in (v.get("now") or {}).items()]
        if now:
            s += " " + t(lang, "f.lostNow", list=", ".join(now))
        if (v.get("again") or 0) >= 0.3:
            s += " " + t(lang, "f.lostAgain", again=num(v["again"]))
        return s
    if not has(lang_or_en(lang), key):
        return f.get("text") or ""
    filled = {k: (num(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else day(str(x), lang) if k == "date" else str(x))
              for k, x in v.items()}
    return t(lang, key, **filled)


def action_text(a: dict, lang: str | None) -> str:
    """An action from actions.for_place(): {"key": "act....", "vars": {...}}; dates are formatted for the reader."""
    vars_ = {}
    for k, x in (a.get("vars") or {}).items():
        if k == "dates":
            vars_[k] = ", ".join(day(d, lang) for d in x)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            vars_[k] = num(x)
        else:
            vars_[k] = str(x)
    return t(lang, a["key"], **vars_)

"""Cedar authorization for every action that changes something, with plain-language explanations.

decision() returns which policy allowed or denied the request so the app (and the audit log) can say *why*,
e.g. "Denied by no-self-verification: nobody can verify evidence they uploaded themselves."
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parent / "policies"
NS = "JalSmriti"

RULES = {
    "citizens-add-evidence": "Any signed-in person can add photo evidence to a lake.",
    "citizens-create-dossiers": "Any signed-in person can create an evidence dossier for a lake.",
    "anyone-signed-in-watches": "Any signed-in person can watch a lake and get email alerts.",
    "anyone-signed-in-follows-places": "Any signed-in person can follow a place and get an email before heavy rain.",
    "citizens-record-rti": "Any signed-in person can record a Right to Information request they filed about a lake.",
    "citizens-report-standing-water": "Any signed-in person can report standing water with a photo.",
    "verifiers-review-water-reports": "Verifiers (NGO accounts) can confirm or reject standing-water reports in their own areas, with a note.",
    "no-self-review-of-water-reports": "Nobody can review a standing-water report they made themselves.",
    "creators-mark-submitted": "Only the person who created a dossier can record that it was submitted.",
    "verifiers-review-in-jurisdiction": "Verifiers (NGO accounts) can verify or reject evidence in their own areas, with a note.",
    "no-self-verification": "Nobody can verify evidence they uploaded themselves.",
    "officers-respond-in-jurisdiction": "Officers can respond to dossiers about their own areas, with a note.",
    "respond-only-after-submission": "Officers respond only to dossiers that were actually submitted.",
    "officials-see-their-queue": "Verifiers and officers see the review queue of their own areas.",
    "officials-see-their-audit-log": "Verifiers and officers see the audit log of their own areas.",
    "evidence-is-never-deleted": "Evidence is never deleted: the record stays complete (rejected items are marked, not removed).",
}
ROLES = ("citizen", "verifier", "officer", "admin")


@lru_cache(maxsize=1)
def _policies():
    text = (POLICY_DIR / "jalsmriti.cedar").read_text()
    ids = re.findall(r'@id\("([^"]+)"\)', text)
    return text, {f"policy{i}": pid for i, pid in enumerate(ids)}


@lru_cache(maxsize=1)
def _schema():
    return json.loads((POLICY_DIR / "jalsmriti.cedarschema.json").read_text())


def policy_text() -> str:
    return _policies()[0]


def _uid(t: str, i: str) -> dict:
    return {"type": f"{NS}::{t}", "id": i}


def user_entity(user: dict) -> dict:
    return {"uid": _uid("User", user["id"]), "attrs": {"role": user.get("role", "citizen"),
                                                      "jurisdictions": list(user.get("jurisdictions", []))}, "parents": []}


def lake_entity(lake_id: str, area: str, kind: str = "lake") -> dict:
    return {"uid": _uid("Lake", lake_id), "attrs": {"area": area or "other", "kind": kind}, "parents": []}


def area_entity(area: str) -> dict:
    return {"uid": _uid("Area", area), "attrs": {"id": area}, "parents": []}


def _stub_user(uid: str) -> dict:
    return {"uid": _uid("User", uid), "attrs": {"role": "citizen", "jurisdictions": []}, "parents": []}


def evidence_entity(ev: dict) -> tuple[dict, dict]:
    res = {"uid": _uid("Evidence", ev["evidenceId"]),
           "attrs": {"area": ev.get("areaId") or "other", "lake": ev["lakeId"], "status": ev.get("status", "new"),
                     "uploader": {"__entity": _uid("User", ev["uploaderId"])}}, "parents": []}
    return res, _stub_user(ev["uploaderId"])


def report_entity(r: dict) -> tuple[dict, dict]:
    """A citizen's standing-water report (waterlog.py)."""
    res = {"uid": _uid("Report", r["reportId"]),
           "attrs": {"area": r.get("areaId") or "other", "status": r.get("status", "live"),
                     "reporter": {"__entity": _uid("User", r["uploaderId"])}}, "parents": []}
    return res, _stub_user(r["uploaderId"])


def dossier_entity(d: dict) -> tuple[dict, dict]:
    res = {"uid": _uid("Dossier", d["dossierId"]),
           "attrs": {"area": d.get("areaId") or "other", "lake": d["lakeId"], "status": d.get("status", "draft"),
                     "creator": {"__entity": _uid("User", d["creatorId"])}}, "parents": []}
    return res, _stub_user(d["creatorId"])


# ------------------------------------------------------------------------------------------ users
def parse_groups(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(g) for g in raw]
    s = str(raw).strip()
    if s.startswith("["):
        try:
            v = json.loads(s)
            if isinstance(v, list):
                return [str(g) for g in v]
        except json.JSONDecodeError:
            pass
        s = s.strip("[]")
    return [g.strip().strip('"') for g in re.split(r"[,\s]+", s) if g.strip().strip('"')]


def user_from_claims(claims: dict) -> dict:
    groups = parse_groups(claims.get("cognito:groups"))
    role = next((r for r in ("admin", "officer", "verifier") if r in groups), "citizen")
    juris = [j.strip().lower() for j in str(claims.get("custom:jurisdictions") or "").split(",") if j.strip()]
    sub = claims.get("sub") or claims.get("cognito:username")
    return {"id": sub, "username": claims.get("cognito:username") or claims.get("username"), "role": role,
            "groups": groups, "jurisdictions": juris, "email": claims.get("email"),
            "emailVerified": str(claims.get("email_verified", "")).lower() == "true",
            "pseudonym": pseudonym(sub, role)}


def pseudonym(sub: str | None, role: str = "citizen") -> str:
    """Stable public name that reveals nothing about the person (e.g. 'Citizen 7F3A', 'Verifier 21C0')."""
    import hashlib
    if not sub:
        return "Anonymous"
    prefix = {"verifier": "Verifier", "officer": "Officer", "admin": "Administrator"}.get(role, "Citizen")
    return prefix + " " + hashlib.sha256(f"jalsmriti:{sub}".encode()).hexdigest()[:4].upper()


# ------------------------------------------------------------------------------------------ decisions
def decide(user: dict, action: str, resource: dict, context: dict | None = None, extra: list | None = None):
    import cedarpy
    text, idmap = _policies()
    ue = user_entity(user)
    request = {"principal": f'{NS}::User::"{user["id"]}"', "action": f'{NS}::Action::"{action}"',
               "resource": f'{resource["uid"]["type"]}::"{resource["uid"]["id"]}"', "context": context or {}}
    entities = [ue, resource] + [e for e in (extra or []) if e["uid"] != ue["uid"]]
    result = cedarpy.is_authorized(request, text, entities, schema=_schema())
    reasons = [idmap.get(r, r) for r in result.diagnostics.reasons]
    allowed = result.decision == cedarpy.Decision.Allow
    errors = [str(e) for e in result.diagnostics.errors]
    return allowed, reasons, errors


def decision(user: dict, action: str, resource: dict, context: dict | None = None, extra: list | None = None) -> dict:
    allowed, reasons, errors = decide(user, action, resource, context, extra)
    if allowed:
        why = "Allowed by " + ", ".join(reasons)
    elif reasons:
        why = "Denied by " + ", ".join(reasons)
    else:
        why = "Denied: no rule lets this account do this here"
    rule = " ".join(RULES.get(r, r) for r in reasons) if reasons else \
        f"No rule lets the {user.get('role', 'citizen')} role do this here."
    if not allowed and not reasons and (context or {}).get("hasNote") is False:
        # say so when the missing note is the only thing in the way
        if decide(user, action, resource, {**context, "hasNote": True}, extra)[0]:
            why = "Denied: a note of at least 10 characters is required"
            rule = "Write a note of at least 10 characters: reviews and responses are part of the public record."
    return {"allowed": allowed, "explanation": why, "policies": reasons, "rule": rule, "errors": errors}

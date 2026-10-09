"""An append-only, tamper-evident record per water body.

Every piece of evidence, every verification decision, every dossier and every official response is appended as an
entry whose hash covers the previous entry's hash (a hash chain). Changing or deleting any past entry breaks every
hash after it, which anyone can check through /v1/lakes/{id}/ledger. Appends are atomic (a DynamoDB transaction
moves the chain head only if nobody else moved it first), and Cedar forbids deletes outright.
"""
from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal

from . import config as C
from . import store

GENESIS = "0" * 64


def _norm(v):
    """Numbers hash the same before and after a DynamoDB round trip (27.0 -> 27, 6 decimals)."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        v = round(v, 6)
        return int(v) if v.is_integer() else v
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in v.items() if x is not None}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    return v


def canonical(obj) -> bytes:
    return json.dumps(_norm(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entry_hash(entry: dict) -> str:
    body = {k: entry[k] for k in ("lakeId", "seq", "prevHash", "kind", "subjectId", "payloadSha256", "actor", "at")}
    return sha256_hex(canonical(body))


def append(lake_id: str, kind: str, subject_id: str, payload_sha256: str, actor: str, tries: int = 6) -> dict:
    """Append one entry; retries if another writer appended at the same moment."""
    import boto3
    from boto3.dynamodb.types import TypeSerializer
    ser = TypeSerializer()
    client = boto3.client("dynamodb", region_name=C.REGION)
    for attempt in range(tries):
        head = store.get(f"LEDGER#{lake_id}", "HEAD") or {"seq": 0, "hash": GENESIS}
        entry = {"lakeId": lake_id, "seq": int(head["seq"]) + 1, "prevHash": head["hash"], "kind": kind,
                 "subjectId": subject_id, "payloadSha256": payload_sha256, "actor": actor, "at": store.now_iso()}
        entry["hash"] = entry_hash(entry)
        item = {"PK": f"LEDGER#{lake_id}", "SK": f"{entry['seq']:08d}", **entry}
        head_cond = "attribute_not_exists(PK)" if head["seq"] == 0 else "seq = :old"
        upd = {"Update": {"TableName": C.TABLE_NAME, "Key": {"PK": {"S": f"LEDGER#{lake_id}"}, "SK": {"S": "HEAD"}},
                          "UpdateExpression": "SET seq = :new, #h = :hash, updatedAt = :at",
                          "ExpressionAttributeNames": {"#h": "hash"},
                          "ExpressionAttributeValues": {":new": ser.serialize(entry["seq"]), ":hash": ser.serialize(entry["hash"]),
                                                        ":at": ser.serialize(entry["at"]),
                                                        **({":old": ser.serialize(int(head["seq"]))} if head["seq"] else {})},
                          "ConditionExpression": head_cond}}
        put = {"Put": {"TableName": C.TABLE_NAME, "Item": {k: ser.serialize(store.to_ddb(v)) for k, v in item.items()},
                       "ConditionExpression": "attribute_not_exists(PK)"}}
        try:
            client.transact_write_items(TransactItems=[put, upd])
            return entry
        except client.exceptions.TransactionCanceledException:
            time.sleep(0.05 * (2 ** attempt))
    raise RuntimeError("ledger busy, try again")


def entries(lake_id: str, cap: int = 2000) -> list[dict]:
    items = store.query_all(f"LEDGER#{lake_id}", sk_prefix="0", cap=cap)
    return sorted(items, key=lambda e: e["seq"])


def verify(lake_id: str) -> dict:
    """Recompute every hash and link; report the first broken entry, if any."""
    es = entries(lake_id)
    prev = GENESIS
    for e in es:
        if e.get("prevHash") != prev:
            return {"ok": False, "entries": len(es), "brokenAt": e["seq"], "why": "link to previous entry does not match"}
        if entry_hash(e) != e.get("hash"):
            return {"ok": False, "entries": len(es), "brokenAt": e["seq"], "why": "entry content does not match its hash"}
        prev = e["hash"]
    head = store.get(f"LEDGER#{lake_id}", "HEAD")
    if es and head and head.get("hash") != prev:
        return {"ok": False, "entries": len(es), "brokenAt": es[-1]["seq"], "why": "chain head does not match last entry"}
    return {"ok": True, "entries": len(es), "head": prev}

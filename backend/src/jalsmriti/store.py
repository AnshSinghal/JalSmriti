"""One DynamoDB table (on-demand) for everything JalSmriti keeps.

Key design (PK / SK):
  AREA#{id}      META              area status, stats and layer manifest
  AREA#{id}      LAKE#{lakeId}     lake summary row for lists and the map
  LAKE#{id}      META              full lake analysis
  EVID#{id}      META              one piece of citizen evidence      GSI1 LAKE#..  GSI2 USER#..  GSI3 QUEUE#EVID#{area}
  DOSS#{id}      META              one evidence dossier / complaint   GSI1 LAKE#..  GSI2 USER#..  GSI3 QUEUE#DOSS#{area}
  LEDGER#{lake}  HEAD | {seq}      append-only hash chain of evidence and decisions for a lake
  WATCH#{lake}   USER#{sub}        an email alert subscription (SNS)  GSI2 USER#..
  WATCHED        {lakeId}          lakes that someone watches (the weekly sweep reads this)
  PLACE#{gh7}    V#{version}       cached place check
  JOB#{id}       META              progress of an on-demand analysis (TTL)
  AUDIT#{area}   {ts}#{n}          every allowed and denied action, with the deciding Cedar policy
  RATE#{who}#{day}  {action}       per-user / per-IP daily counters (TTL)
  STATS          GLOBAL            public counters
"""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache

from . import config as C


@lru_cache(maxsize=1)
def table():
    import boto3
    from botocore.config import Config
    return boto3.resource("dynamodb", region_name=C.REGION,
                          config=Config(retries={"max_attempts": 8, "mode": "adaptive"})).Table(C.TABLE_NAME)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def iso_days_ago(days: float) -> str:
    """An ISO timestamp `days` ago, in the same format as now_iso() (so the two compare as strings)."""
    t = datetime.now(timezone.utc) - timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def new_id(prefix: str = "") -> str:
    """Sortable, unguessable id: base36 time + random."""
    t = int(time.time() * 1000)
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    while t:
        t, r = divmod(t, 36)
        s = alphabet[r] + s
    return f"{prefix}{s}{secrets.token_hex(4)}"


def to_ddb(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return Decimal(str(round(v, 6)))
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        return {str(k): to_ddb(x) for k, x in v.items() if x is not None and to_ddb(x) is not None}
    if isinstance(v, (list, tuple)):
        return [to_ddb(x) for x in v]
    if hasattr(v, "item"):   # numpy scalar
        return to_ddb(v.item())
    return v


def plain(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    if isinstance(v, set):
        return sorted(plain(x) for x in v)
    return v


def put(item: dict, condition: str | None = None, **kw) -> None:
    args = {"Item": to_ddb(item)}
    if condition:
        args["ConditionExpression"] = condition
    args.update(kw)
    table().put_item(**args)


def get(pk: str, sk: str = "META") -> dict | None:
    r = table().get_item(Key={"PK": pk, "SK": sk})
    return plain(r.get("Item")) if r.get("Item") else None


def delete(pk: str, sk: str = "META") -> None:
    table().delete_item(Key={"PK": pk, "SK": sk})


def query(pk: str, sk_prefix: str | None = None, index: str | None = None, limit: int | None = None,
          forward: bool = True, start: dict | None = None) -> tuple[list[dict], dict | None]:
    from boto3.dynamodb.conditions import Key
    pk_name, sk_name = ("PK", "SK") if not index else (f"{index}PK", f"{index}SK")
    cond = Key(pk_name).eq(pk)
    if sk_prefix:
        cond = cond & Key(sk_name).begins_with(sk_prefix)
    args = {"KeyConditionExpression": cond, "ScanIndexForward": forward}
    if index:
        args["IndexName"] = index
    if limit:
        args["Limit"] = limit
    if start:
        args["ExclusiveStartKey"] = start
    r = table().query(**args)
    return [plain(i) for i in r.get("Items", [])], r.get("LastEvaluatedKey")


def query_all(pk: str, sk_prefix: str | None = None, index: str | None = None, cap: int = 5000) -> list[dict]:
    out, start = [], None
    while True:
        items, start = query(pk, sk_prefix, index, start=start)
        out += items
        if not start or len(out) >= cap:
            return out[:cap]


def update(pk: str, sk: str, sets: dict | None = None, adds: dict | None = None, condition: str | None = None,
           cond_values: dict | None = None, remove: list | None = None) -> dict:
    """SET / ADD / REMOVE in one call; returns the new item."""
    names, values, parts = {}, {}, []
    if sets:
        exprs = []
        for i, (k, v) in enumerate(sets.items()):
            names[f"#s{i}"] = k
            values[f":s{i}"] = to_ddb(v)
            exprs.append(f"#s{i} = :s{i}")
        parts.append("SET " + ", ".join(exprs))
    if adds:
        exprs = []
        for i, (k, v) in enumerate(adds.items()):
            names[f"#a{i}"] = k
            values[f":a{i}"] = to_ddb(v)
            exprs.append(f"#a{i} :a{i}")
        parts.append("ADD " + ", ".join(exprs))
    if remove:
        exprs = []
        for i, k in enumerate(remove):
            names[f"#r{i}"] = k
            exprs.append(f"#r{i}")
        parts.append("REMOVE " + ", ".join(exprs))
    args = {"Key": {"PK": pk, "SK": sk}, "UpdateExpression": " ".join(parts), "ReturnValues": "ALL_NEW"}
    if names:
        args["ExpressionAttributeNames"] = names
    if values:
        args["ExpressionAttributeValues"] = values
    if condition:
        args["ConditionExpression"] = condition
        if cond_values:
            args["ExpressionAttributeValues"] = {**args.get("ExpressionAttributeValues", {}), **to_ddb(cond_values)}
    return plain(table().update_item(**args).get("Attributes", {}))


def batch_put(items: list[dict]) -> None:
    with table().batch_writer(overwrite_by_pkeys=["PK", "SK"]) as bw:
        for it in items:
            bw.put_item(Item=to_ddb(it))


# ------------------------------------------------------------------------------------------ counters
def bump_stats(**counts) -> None:
    try:
        update("STATS", "GLOBAL", adds={k: v for k, v in counts.items() if v})
    except Exception:
        pass


def stats() -> dict:
    return get("STATS", "GLOBAL") or {}


class RateLimited(Exception):
    pass


def rate_limit(who: str, action: str, limit: int | None = None) -> int:
    """Count one use of `action` by `who` today; raise RateLimited past the daily limit."""
    limit = limit or C.RATE_LIMIT_PER_DAY.get(action, 50)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    try:
        r = update(f"RATE#{who}#{day}", action, adds={"n": 1}, sets={"ttl": int(time.time()) + 2 * 86400},
                   condition="attribute_not_exists(n) OR n < :lim", cond_values={":lim": limit})
        return int(r.get("n", 1))
    except Exception as ex:
        if "ConditionalCheckFailed" in str(ex):
            raise RateLimited(f"daily limit of {limit} reached for {action}")
        raise


# ------------------------------------------------------------------------------------------ audit
def audit(area: str, user: dict | None, action: str, resource: dict, decision: dict | None = None,
          extra: dict | None = None) -> None:
    item = {"PK": f"AUDIT#{area or 'global'}", "SK": f"{now_iso()}#{secrets.token_hex(3)}", "action": action,
            "user": (user or {}).get("id"), "pseudonym": (user or {}).get("pseudonym"), "role": (user or {}).get("role"),
            "resource": resource, "allowed": (decision or {}).get("allowed", True),
            "explanation": (decision or {}).get("explanation"), "policies": (decision or {}).get("policies"),
            "extra": extra, "ttl": int(time.time()) + 400 * 86400}
    try:
        put(item)
    except Exception:
        pass


def dumps(obj) -> str:
    return json.dumps(plain(obj), ensure_ascii=False, default=str)

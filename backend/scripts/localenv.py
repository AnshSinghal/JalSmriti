"""Shared setup for running JalSmriti locally: environment, the DynamoDB table (moto) and a table snapshot."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
LOCAL = Path(os.environ.get("JALSMRITI_LOCAL_DIR") or (ROOT / ".local"))


def setup_env(local_dir: Path = LOCAL) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("JALSMRITI_LOCAL_DIR", str(local_dir))
    os.environ.setdefault("JALSMRITI_LOCAL", "1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    os.environ.setdefault("AWS_REGION", "us-west-2")
    os.environ.setdefault("TABLE_NAME", "jalsmriti")
    os.environ.setdefault("SITE_URL", "http://127.0.0.1:8787")
    for p in (BACKEND / "src", BACKEND / "src" / "handlers"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


TABLE_SCHEMA = dict(
    TableName="jalsmriti",
    KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
    AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in
                          ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK")],
    GlobalSecondaryIndexes=[{"IndexName": f"GSI{i}", "KeySchema": [{"AttributeName": f"GSI{i}PK", "KeyType": "HASH"},
                                                                  {"AttributeName": f"GSI{i}SK", "KeyType": "RANGE"}],
                             "Projection": {"ProjectionType": "ALL"}} for i in (1, 2, 3)],
    BillingMode="PAY_PER_REQUEST",
)


def create_table(region: str = "us-west-2"):
    import boto3
    ddb = boto3.client("dynamodb", region_name=region)
    try:
        ddb.create_table(**TABLE_SCHEMA)
    except ddb.exceptions.ResourceInUseException:
        pass
    return boto3.resource("dynamodb", region_name=region).Table(TABLE_SCHEMA["TableName"])


def dump_table(path: Path) -> int:
    import boto3
    t = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table("jalsmriti")
    items, start = [], None
    while True:
        kw = {"ExclusiveStartKey": start} if start else {}
        r = t.scan(**kw)
        items += r["Items"]
        start = r.get("LastEvaluatedKey")
        if not start:
            break
    from jalsmriti.store import plain
    path.write_text(json.dumps([plain(i) for i in items], ensure_ascii=False))
    return len(items)


def load_table(path: Path) -> int:
    if not path.exists():
        return 0
    from jalsmriti.store import to_ddb
    import boto3
    t = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table("jalsmriti")
    items = json.loads(path.read_text())
    with t.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as bw:
        for it in items:
            bw.put_item(Item=to_ddb(it))
    return len(items)

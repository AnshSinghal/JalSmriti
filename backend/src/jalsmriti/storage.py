"""Object storage: Amazon S3 in AWS, a local folder in the local stack (JALSMRITI_LOCAL_DIR).

Two buckets: the private DATA_BUCKET (originals, intermediate rasters) and the SITE_BUCKET served by CloudFront,
where everything under pub/ is public (frames, layers, evidence derivatives, signed dossiers).
"""
from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path

from . import config as C

log = logging.getLogger(__name__)
LOCAL_DIR = os.environ.get("JALSMRITI_LOCAL_DIR", "")


@lru_cache(maxsize=1)
def _s3():
    import boto3
    from botocore.config import Config
    # regional, virtual-hosted addresses: presigned browser uploads to a brand-new bucket would otherwise go to the
    # global endpoint and could be redirected (which breaks the cross-origin POST) until DNS settles
    return boto3.client("s3", region_name=C.REGION, config=Config(retries={"max_attempts": 8, "mode": "adaptive"},
                                                                  max_pool_connections=64, signature_version="s3v4",
                                                                  s3={"addressing_style": "virtual"}))


def _local(bucket: str, key: str) -> Path:
    name = "site" if bucket == C.SITE_BUCKET or bucket == "site" else "data"
    p = Path(LOCAL_DIR) / name / key
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def put(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream",
        cache: str | None = None) -> None:
    if LOCAL_DIR:
        _local(bucket, key).write_bytes(data)
        return
    kw = {"Bucket": bucket, "Key": key, "Body": data, "ContentType": content_type}
    if cache:
        kw["CacheControl"] = cache
    _s3().put_object(**kw)


def get(bucket: str, key: str) -> bytes:
    if LOCAL_DIR:
        return _local(bucket, key).read_bytes()
    return _s3().get_object(Bucket=bucket, Key=key)["Body"].read()


def exists(bucket: str, key: str) -> bool:
    if LOCAL_DIR:
        return _local(bucket, key).exists()
    try:
        _s3().head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def list_keys(bucket: str, prefix: str) -> list[str]:
    if LOCAL_DIR:
        root = Path(LOCAL_DIR) / ("site" if bucket == C.SITE_BUCKET or bucket == "site" else "data")
        start = root / prefix if (root / prefix).is_dir() else (root / prefix).parent
        if not start.exists():
            return []
        rels = (p.relative_to(root).as_posix() for p in start.rglob("*") if p.is_file())
        return sorted(r for r in rels if r.startswith(prefix))
    keys, token = [], None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        r = _s3().list_objects_v2(**kw)
        keys += [o["Key"] for o in r.get("Contents", [])]
        if not r.get("IsTruncated"):
            return keys
        token = r["NextContinuationToken"]


def put_json(bucket: str, key: str, obj, cache: str | None = None) -> None:
    put(bucket, key, json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_default).encode("utf-8"),
        "application/json", cache)


def get_json(bucket: str, key: str):
    return json.loads(get(bucket, key))


def _default(o):
    try:
        import numpy as np
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    from decimal import Decimal
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


# ------------------------------------------------------------------------------------------ public URLs
_site_url = {"v": None, "t": 0.0}


def site_url() -> str:
    """The CloudFront address (written to SSM by deploy.py after the stack exists, to avoid a template cycle)."""
    if C.SITE_URL:
        return C.SITE_URL.rstrip("/")
    if _site_url["v"] and time.time() - _site_url["t"] < 600:
        return _site_url["v"]
    try:
        import boto3
        v = boto3.client("ssm", region_name=C.REGION).get_parameter(Name=C.SITE_URL_PARAM)["Parameter"]["Value"]
    except Exception:
        v = ""
    _site_url.update(v=v.rstrip("/"), t=time.time())
    return _site_url["v"] or ""


def public_key(path: str) -> str:
    return C.PUBLIC_PREFIX + path.lstrip("/")


def put_public(path: str, data: bytes, content_type: str, immutable: bool = False) -> str:
    """Write under SITE_BUCKET/pub/ and return the site-relative URL path (/pub/...)."""
    key = public_key(path)
    put(C.SITE_BUCKET or "site", key, data, content_type,
        "public, max-age=31536000, immutable" if immutable else "public, max-age=300")
    return "/" + key


def put_public_json(path: str, obj, max_age: int = 300) -> str:
    key = public_key(path)
    put(C.SITE_BUCKET or "site", key,
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_default).encode("utf-8"),
        "application/json", f"public, max-age={max_age}")
    return "/" + key


def get_public_json(path: str):
    return get_json(C.SITE_BUCKET or "site", public_key(path))


def put_data(path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    put(C.DATA_BUCKET or "data", path, data, content_type)


def get_data(path: str) -> bytes:
    return get(C.DATA_BUCKET or "data", path)


def put_data_json(path: str, obj) -> None:
    put_json(C.DATA_BUCKET or "data", path, obj)


def get_data_json(path: str):
    return get_json(C.DATA_BUCKET or "data", path)


def data_exists(path: str) -> bool:
    return exists(C.DATA_BUCKET or "data", path)


def presigned_post(path: str, content_type: str, max_bytes: int, expires: int = 600) -> dict:
    """A browser upload straight to the private bucket, limited in type and size."""
    if LOCAL_DIR:
        return {"url": "/local-upload", "fields": {"key": path, "Content-Type": content_type}}
    return _s3().generate_presigned_post(
        Bucket=C.DATA_BUCKET, Key=path, Fields={"Content-Type": content_type},
        Conditions=[{"Content-Type": content_type}, ["content-length-range", 1024, max_bytes]], ExpiresIn=expires)


def presigned_get(path: str, expires: int = 900) -> str:
    if LOCAL_DIR:
        return f"/local-data/{path}"
    return _s3().generate_presigned_url("get_object", Params={"Bucket": C.DATA_BUCKET, "Key": path}, ExpiresIn=expires)

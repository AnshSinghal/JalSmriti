"""Calling Amazon Nova on Amazon Bedrock (Converse API) with model fallback, for text and images."""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from . import config as C

log = logging.getLogger(__name__)

UNAVAILABLE = ("inference profile", "on-demand throughput", "model identifier is invalid", "ResourceNotFound",
               "not supported", "AccessDenied", "don't have access", "is not authorized", "ValidationException")


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config
    return boto3.client("bedrock-runtime", region_name=C.REGION,
                        config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 3, "mode": "adaptive"}))


def converse(messages: list, system: str | None = None, models: list[str] | None = None, max_tokens: int = 1200,
             temperature: float = 0.2) -> tuple[str, str]:
    """Returns (text, model_id) from the first model that answers."""
    last = None
    for mid in models or C.TEXT_MODEL_IDS:
        try:
            kw = {"modelId": mid, "messages": messages,
                  "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature}}
            if system:
                kw["system"] = [{"text": system}]
            r = _client().converse(**kw)
            parts = r["output"]["message"]["content"]
            return "".join(p.get("text", "") for p in parts), mid
        except Exception as ex:
            last = ex
            if any(s.lower() in str(ex).lower() for s in UNAVAILABLE):
                log.warning("model %s unavailable: %s", mid, str(ex)[:200])
                continue
            raise
    raise RuntimeError(f"no Bedrock model answered: {last}")


def converse_text(prompt: str, system: str | None = None, **kw) -> str:
    return converse([{"role": "user", "content": [{"text": prompt}]}], system=system, **kw)[0]


def converse_image(prompt: str, image_bytes: bytes, fmt: str = "jpeg", system: str | None = None, **kw) -> tuple[str, str]:
    msg = [{"role": "user", "content": [{"image": {"format": fmt, "source": {"bytes": image_bytes}}}, {"text": prompt}]}]
    return converse(msg, system=system, models=C.VISION_MODEL_IDS, **kw)


def parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None

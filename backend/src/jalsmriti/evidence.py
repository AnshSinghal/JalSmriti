"""Citizen photo evidence: provenance, privacy and AI triage.

For every upload:
  1. SHA-256 of the original bytes (the original stays private and unchanged),
  2. EXIF capture time, camera and GPS; the GPS is checked against the lake's historic outline,
  3. Amazon Rekognition rejects explicit content and finds faces, which are blurred in the public copy,
  4. Amazon Nova (vision) describes what the photo shows in fixed categories (dumping, sewage, construction ...),
     with Rekognition labels as an independent second signal,
  5. a public copy is published without EXIF (no phone metadata leaks), plus a thumbnail.
The AI only triages; a verifier (NGO account) confirms or rejects, and that decision is what counts.
"""
from __future__ import annotations

import io
import json
import logging
import math
from datetime import datetime
from functools import lru_cache

from PIL import ExifTags, Image, ImageFilter, ImageOps

from . import config as C

log = logging.getLogger(__name__)

BLOCK_MODERATION = ("Explicit Nudity", "Explicit", "Non-Explicit Nudity of Intimate parts and Kissing", "Violence",
                    "Graphic Violence", "Graphic Violence Or Gore", "Hate Symbols", "Drugs & Tobacco", "Rude Gestures")
LABEL_HINTS = {
    "dumping": ("Garbage", "Trash", "Litter", "Landfill", "Plastic", "Rubble", "Waste"),
    "construction": ("Construction", "Crane", "Bulldozer", "Excavator", "Construction Crane", "Building Construction",
                     "Scaffolding", "Concrete", "Machine"),
    "fencing": ("Fence", "Wall", "Barbed Wire", "Gate"),
    "weeds": ("Algae", "Water Hyacinth", "Aquatic Plant", "Plant", "Vegetation", "Moss"),
    "sewage": ("Pipe", "Sewer", "Drain", "Foam"),
    "dead_fish": ("Fish", "Dead Fish"),
    "dry_bed": ("Soil", "Dirt", "Mud", "Desert"),
}


def _ratio(v) -> float:
    try:
        return float(v[0]) / float(v[1]) if isinstance(v, tuple) else float(v)
    except Exception:
        return float("nan")


def _dms(vals, ref) -> float | None:
    try:
        d, m, s = (_ratio(x) for x in vals)
        deg = d + m / 60 + s / 3600
        return -deg if ref in ("S", "W", b"S", b"W") else deg
    except Exception:
        return None


def read_exif(data: bytes) -> dict:
    """Capture time, camera and GPS from EXIF (None where absent)."""
    out = {"capturedAt": None, "make": None, "model": None, "lat": None, "lon": None, "gpsAccuracyM": None}
    try:
        img = Image.open(io.BytesIO(data))
        ex = img.getexif()
    except Exception:
        return out
    tags = {ExifTags.TAGS.get(k, k): v for k, v in ex.items()}
    try:
        sub = ex.get_ifd(0x8769)   # Exif IFD: DateTimeOriginal lives here
        tags.update({ExifTags.TAGS.get(k, k): v for k, v in sub.items()})
    except Exception:
        pass
    dt = tags.get("DateTimeOriginal") or tags.get("DateTime")
    if dt:
        try:
            out["capturedAt"] = datetime.strptime(str(dt).strip(), "%Y:%m:%d %H:%M:%S").isoformat()
        except ValueError:
            pass
    out["make"] = str(tags.get("Make") or "").strip() or None
    out["model"] = str(tags.get("Model") or "").strip() or None
    try:
        gps = ex.get_ifd(0x8825)
        g = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps.items()}
        if "GPSLatitude" in g and "GPSLongitude" in g:
            out["lat"] = _dms(g["GPSLatitude"], g.get("GPSLatitudeRef", "N"))
            out["lon"] = _dms(g["GPSLongitude"], g.get("GPSLongitudeRef", "E"))
            if "GPSHPositioningError" in g:
                out["gpsAccuracyM"] = round(_ratio(g["GPSHPositioningError"]), 1)
    except Exception:
        pass
    if out["lat"] is not None and (not math.isfinite(out["lat"]) or abs(out["lat"]) < 1e-6):
        out["lat"] = out["lon"] = None
    return out


def distance_to_outline_m(lat: float, lon: float, geometry: dict) -> float:
    """Metres from a point to a lon/lat polygon (0 inside), on a local equirectangular projection."""
    import numpy as np
    import shapely
    from shapely.geometry import Point, shape
    k = math.cos(math.radians(lat))
    scale, origin = np.array([111_320 * k, 110_540]), np.array([lon, lat])
    g = shapely.transform(shape(geometry), lambda xy: (xy - origin) * scale)
    return float(g.distance(Point(0, 0)))


@lru_cache(maxsize=1)
def _rek():
    import boto3
    return boto3.client("rekognition", region_name=C.REGION)


def moderate(data: bytes) -> dict:
    if C.LOCAL:
        return {"blocked": False, "labels": [], "engine": "local stand-in"}
    r = _rek().detect_moderation_labels(Image={"Bytes": data}, MinConfidence=70)
    labels = [{"name": m["Name"], "parent": m.get("ParentName"), "confidence": round(m["Confidence"], 1)}
              for m in r.get("ModerationLabels", [])]
    blocked = any(l["name"] in BLOCK_MODERATION or l["parent"] in BLOCK_MODERATION for l in labels)
    return {"blocked": blocked, "labels": labels, "engine": "Amazon Rekognition"}


def faces(data: bytes) -> list[dict]:
    if C.LOCAL:
        return []
    r = _rek().detect_faces(Image={"Bytes": data}, Attributes=["DEFAULT"])
    return [f["BoundingBox"] for f in r.get("FaceDetails", []) if f.get("Confidence", 0) >= 80]


def labels(data: bytes) -> list[dict]:
    if C.LOCAL:
        return []
    r = _rek().detect_labels(Image={"Bytes": data}, MaxLabels=25, MinConfidence=65)
    return [{"name": l["Name"], "confidence": round(l["Confidence"], 1)} for l in r.get("Labels", [])]


def categories_from_labels(lbls: list[dict]) -> list[str]:
    names = {l["name"] for l in lbls}
    return [cat for cat, hints in LABEL_HINTS.items() if names.intersection(hints)]


TRIAGE_PROMPT = (
    "You are helping citizens document problems at a lake, tank or wetland in India or Nepal. Look at the photo and "
    "answer ONLY with a JSON object with keys: categories (array, choose from: dumping, sewage, construction, "
    "fencing, weeds, dead_fish, foam, dry_bed, healthy, other), summary (one plain sentence, max 30 words, "
    "describing only what is visible, no guesses about who is responsible), water_visible (true/false), "
    "confidence (0 to 1). Do not identify people.")


def triage(jpeg: bytes) -> dict:
    """AI description of the photo in fixed categories (never a verdict)."""
    if C.LOCAL:
        return {"categories": ["other"], "summary": "Local stand-in: deployed builds describe the photo with Amazon Nova.",
                "waterVisible": None, "confidence": None, "model": "local stand-in"}
    from .bedrock import converse_image, parse_json
    try:
        text, mid = converse_image(TRIAGE_PROMPT, jpeg, "jpeg", max_tokens=300, temperature=0.0)
        d = parse_json(text) or {}
    except Exception as ex:
        log.warning("vision triage failed: %s", ex)
        return {"categories": [], "summary": None, "model": None, "error": str(ex)[:200]}
    cats = [c for c in (d.get("categories") or []) if c in C.EVIDENCE_CATEGORIES][:4]
    summary = str(d.get("summary") or "")[:240] or None
    conf = d.get("confidence")
    return {"categories": cats or ["other"], "summary": summary, "waterVisible": d.get("water_visible"),
            "confidence": round(float(conf), 2) if isinstance(conf, (int, float)) else None, "model": mid}


def public_copies(data: bytes, face_boxes: list[dict]) -> tuple[bytes, bytes, tuple[int, int]]:
    """EXIF-free, upright, face-blurred JPEG (max 1600 px) and a 480 px thumbnail."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    W, H = img.size
    for b in face_boxes:
        pad = 0.25
        x0 = max(0, int((b["Left"] - pad * b["Width"]) * W))
        y0 = max(0, int((b["Top"] - pad * b["Height"]) * H))
        x1 = min(W, int((b["Left"] + (1 + pad) * b["Width"]) * W))
        y1 = min(H, int((b["Top"] + (1 + pad) * b["Height"]) * H))
        if x1 > x0 and y1 > y0:
            region = img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(radius=max(8, (x1 - x0) // 6)))
            img.paste(region, (x0, y0))
    big = img.copy()
    big.thumbnail((1600, 1600), Image.LANCZOS)
    small = img.copy()
    small.thumbnail((480, 480), Image.LANCZOS)
    out = []
    for im in (big, small):
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=84, optimize=True, progressive=True)   # no exif= argument: metadata dropped
        out.append(buf.getvalue())
    return out[0], out[1], big.size


def jpeg_for_models(data: bytes, max_side: int = 1280) -> bytes:
    """Upright JPEG under the model input limits."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()

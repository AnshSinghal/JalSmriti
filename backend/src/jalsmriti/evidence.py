"""Citizen photo evidence: provenance, privacy and AI triage.

For every upload:
  1. SHA-256 of the original bytes (the original stays private and unchanged),
  2. EXIF capture time, camera and GPS; the GPS is checked against the lake's historic outline,
  3. Amazon Rekognition rejects explicit content,
  4. is it a photo of the place at all? Three independent signals (relevance()): how many printed words Rekognition
     reads (DetectText: a screenshot, document or poster has many), Rekognition's labels (Poster, Document ... and no
     outdoor scene), and Amazon Nova's own answer to "is this a real photo taken at a lake, its banks or the land
     around it?". An upload that fails is kept private as "unrelated", with the reason, and never reaches the
     public page, the ledger or the verifiers' queue,
  5. Rekognition finds faces, which are blurred in the public copy,
  6. Amazon Nova (vision) describes what the photo shows in fixed categories (dumping, sewage, construction ...),
     with Rekognition labels as an independent second signal,
  7. a public copy is published without EXIF (no phone metadata leaks), plus a thumbnail.
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


# ------------------------------------------------------------------------------ is it a photo of the place at all?
TEXT_WORDS_LIMIT = 25          # printed words Rekognition reads: a lake's signboard has a few, a screenshot many
TEXT_MIN_CONFIDENCE = 80
UNRELATED_CONFIDENCE = 0.6     # Nova must be at least this sure that the image is not a photo of the place
LABEL_MIN_CONFIDENCE = 70
# Rekognition labels of made images (documents, screenshots, posters, drawings) ...
GRAPHIC_LABELS = frozenset((
    "Text", "Document", "Poster", "Page", "Flyer", "Brochure", "Advertisement", "Diagram", "Screenshot", "Chart",
    "Plot", "Logo", "Menu", "Webpage", "Web Page", "File", "Paper", "Letter", "Book", "Publication", "Newspaper",
    "Magazine", "Business Card", "Id Cards", "Receipt", "Invoice", "Graphics", "Drawing", "Cartoon", "Illustration",
    "Comics", "Art", "Pattern", "Number", "Symbol", "Trademark", "Emblem", "Electronics", "Computer Hardware",
    "Monitor", "Screen", "Phone", "Mobile Phone"))
# ... and of the outdoor scenes a lake photo shows (any one of them and the image is not treated as a made image)
SCENE_LABELS = frozenset((
    "Outdoors", "Nature", "Water", "Lake", "Pond", "River", "Shoreline", "Waterfront", "Wetland", "Swamp", "Marsh",
    "Puddle", "Flood", "Land", "Landscape", "Scenery", "Grass", "Vegetation", "Tree", "Plant", "Sky", "Soil", "Dirt",
    "Mud", "Sand", "Rock", "Field", "Ground", "Road", "Street", "Path", "City", "Urban", "Neighborhood",
    "Construction", "Building", "Rubble", "Garbage", "Trash", "Litter", "Bird", "Waterfowl", "Fish", "Cattle",
    "Weather", "Cloud", "Shore", "Coast", "Bank"))
# ... and of water itself: when Rekognition sees water, a "no" from Nova alone is not enough (a verifier decides)
WATER_LABELS = frozenset(("Water", "Lake", "Pond", "River", "Shoreline", "Waterfront", "Wetland", "Swamp", "Marsh",
                          "Puddle", "Flood", "Canal", "Reservoir"))
SCENES = ("lake_or_pond", "wetland_or_marsh", "dry_lake_bed", "river_or_canal", "drain_or_outlet", "street_or_buildings",
          "construction_site", "indoor", "screenshot_or_document", "poster_or_graphic", "other")
SCENE_REASONS = {"indoor": "indoor", "screenshot_or_document": "text", "poster_or_graphic": "graphic"}
UNRELATED_REASONS = ("text", "graphic", "indoor", "other")


def text_words(data: bytes) -> int | None:
    """Printed words Amazon Rekognition reads in the photo (DetectText reads at most 100); None if the check failed."""
    if C.LOCAL:
        return 0
    try:
        r = _rek().detect_text(Image={"Bytes": data},
                               Filters={"WordFilter": {"MinConfidence": TEXT_MIN_CONFIDENCE}})
    except Exception as ex:                 # the other two signals still decide
        log.warning("text detection failed: %s", ex)
        return None
    return sum(1 for t in r.get("TextDetections", [])
               if t.get("Type") == "WORD" and t.get("Confidence", 0) >= TEXT_MIN_CONFIDENCE)


def relevance(tri: dict, words: int | None, lbls: list[dict]) -> str | None:
    """Why the upload is not a photo of the lake, its banks or the land around it ("text", "graphic", "indoor" or
    "other"), or None when it may be one (then a verifier still decides).

    Rekognition's signals come first because they cannot be talked into seeing a lake: many printed words or the
    labels of a made image, with no outdoor scene at all. Nova's answer counts when it is sure, unless Rekognition
    sees water (two models disagreeing is a question for a person)."""
    names = {l.get("name") for l in lbls or [] if (l.get("confidence") or 0) >= LABEL_MIN_CONFIDENCE}
    outdoors, water = bool(names & SCENE_LABELS), bool(names & WATER_LABELS)
    site, conf, scene = tri.get("sitePhoto"), tri.get("confidence"), tri.get("scene")
    if words is not None and words >= TEXT_WORDS_LIMIT and not outdoors:
        return "text"
    if names & GRAPHIC_LABELS and not outdoors and site is not True:
        return "graphic"
    if site is False and conf is not None and conf >= UNRELATED_CONFIDENCE and not water:
        return SCENE_REASONS.get(scene, "other")
    return None


TRIAGE_PROMPT = (
    "Someone uploaded this image as evidence about a lake, tank or wetland in India or Nepal. Uploads are not always "
    "what they claim to be: some are screenshots, documents, posters, infographics, drawings, memes, indoor photos or "
    "photos of something unrelated. Describe only what is actually visible and never assume that a lake is there. "
    "Answer ONLY with a JSON object with keys: "
    "scene (one of: " + ", ".join(SCENES) + "), "
    "site_photo (true if this is a real photograph taken outdoors at or near a lake, tank, pond or wetland, its banks, "
    "its inflow or outflow channels, or the land around it, including buildings or construction on old lake land; "
    "false for a screenshot, document, poster, infographic, drawing, meme, indoor scene or a photo of something "
    "unrelated), "
    "confidence (0 to 1, how sure you are about site_photo), "
    "categories (array of what is clearly visible, chosen from: dumping, sewage, construction, fencing, weeds, "
    "dead_fish, foam, dry_bed, healthy; an empty array when site_photo is false or none of them is visible), "
    "summary (one plain sentence, max 30 words, describing only what is visible, with no guesses about who is "
    "responsible), "
    "water_visible (true or false). "
    "Never identify people or describe their faces.")


def _flag(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return {"true": True, "yes": True, "false": False, "no": False}.get(v.strip().lower())
    return None


def _share(v) -> float | None:
    """A 0-1 confidence from what the model wrote (a percentage is accepted); None if it is not a number."""
    if isinstance(v, bool):
        return None
    try:
        c = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(c) or c < 0:
        return None
    return round(min(c / 100 if 1 < c <= 100 else c, 1.0), 2)


def triage(jpeg: bytes) -> dict:
    """AI description of the photo: is it a photo of the place, what kind of scene, what is visible (never a verdict)."""
    if C.LOCAL:
        return {"categories": ["other"], "summary": "Local stand-in: deployed builds describe the photo with Amazon Nova.",
                "waterVisible": None, "confidence": None, "sitePhoto": None, "scene": None, "model": "local stand-in"}
    from .bedrock import converse_image, parse_json
    try:
        text, mid = converse_image(TRIAGE_PROMPT, jpeg, "jpeg", max_tokens=300, temperature=0.0)
        d = parse_json(text) or {}
    except Exception as ex:
        log.warning("vision triage failed: %s", ex)
        return {"categories": [], "summary": None, "sitePhoto": None, "scene": None, "model": None,
                "error": str(ex)[:200]}
    site = _flag(d.get("site_photo"))
    cats = [c for c in (d.get("categories") or []) if c in C.EVIDENCE_CATEGORIES and c != "other"][:4]
    scene = str(d.get("scene") or "").strip().lower()
    summary = " ".join(str(d.get("summary") or "").split())[:240] or None
    return {"categories": cats if site is not False else [], "summary": summary,
            "waterVisible": _flag(d.get("water_visible")), "confidence": _share(d.get("confidence")),
            "sitePhoto": site, "scene": scene if scene in SCENES else None, "model": mid}


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

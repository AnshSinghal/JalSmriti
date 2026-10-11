"""Citizen waterlogging reports: a photo of standing water during rain, checked and put on the live public map.

Upload (API) -> private bucket evidence/waterlogging/{id}.{ext} -> evidence Lambda -> process():
  1. SHA-256 of the original bytes (the original stays private and unchanged) and its EXIF,
  2. where: the photo's GPS when it lies in India or Nepal, else the phone's location; when both exist and are more
     than 2 km apart the photo wins and the report is flagged; with neither it stays private ("no-location"),
  3. when: the EXIF capture time (camera clocks are local: IST, or Nepal time for a place in Nepal) unless it is in
     the future, else the upload time; a photo taken over 48 h before its upload is marked old,
  4. Amazon Rekognition blocks explicit content and finds faces, which are blurred in the public copy (no EXIF),
  5. Amazon Nova (vision) says whether standing water is visible, how deep, in one plain sentence. A confident
     "no water", or many printed words read by Rekognition (a screenshot or document, not a street), hides the report
     until a verifier looks; every other report goes live at once.
NGO verifiers confirm or reject a report (apply_review; who may is decided by Cedar in the API). The national map
reads the last hours (recent) and a place's page counts the reports nearby (nearby).

Keys (one table, see store.py):
  WLOG#{id}          META            one report     GSI1 WLGEO#{gh4} / {seenAt}
                                                    GSI2 USER#{sub} / WLOG#{createdAt}
                                                    GSI3 QUEUE#WLOG#{areaId|other} / {status}#{createdAt}
  WLDAY#{yyyymmdd}   {seenAt}#{id}   public copy of a live, hidden or reviewed report, by the UTC day it was seen

The API Lambda imports this module too and has no numpy, shapely or rasterio: only the standard library and light
jalsmriti modules are imported here; evidence (Pillow, Rekognition) and bedrock are imported inside the functions.
"""
from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime, timedelta, timezone

from . import areas, geo, storage, store
from . import config as C

log = logging.getLogger(__name__)

DEPTHS = ("ankle", "knee", "waist", "vehicle")      # what the uploader can choose
AI_DEPTHS = ("none",) + DEPTHS                       # what Amazon Nova can answer
MISMATCH_M = 2000.0           # photo GPS and phone location further apart than this: use the photo, flag the report
OLD_PHOTO_HOURS = 48          # photo taken this long before its upload: marked old
HIDE_CONFIDENCE = 0.6         # Nova says "no water" at least this sure: hidden until a verifier looks
SUMMARY_WORDS = 30
PUBLIC_STATUSES = ("live", "verified")              # what the map and place pages show by default
DAY_STATUSES = ("live", "hidden", "verified")       # copied to the WLDAY# index by process()
REVIEWABLE = ("live", "hidden", "verified", "rejected")
RECENT_CAP = 500
RECENT_MAX_HOURS = 31 * 24    # recent() reads one partition per UTC day, so the window is bounded
NEARBY_ITEMS = 50
NEARBY_MAX_M = 15_000.0       # a 4-character geohash cell and its 8 neighbours cover >= 19.5 km around any point
NEARBY_READ_CAP = 10_000      # items read per cell before nearby() stops and says the count is capped
CELL_MARGIN_M = 100.0
IST = timezone(timedelta(hours=5, minutes=30))
NPT = timezone(timedelta(hours=5, minutes=45))

PUBLIC_FIELDS = ("reportId", "lat", "lon", "seenAt", "createdAt", "capturedAt", "depth", "ai", "status", "url",
                 "thumbUrl", "uploader", "areaId", "review", "locationSource", "oldPhoto", "locationMismatch", "note",
                 "hiddenReason")
AI_PUBLIC = ("waterVisible", "depth", "summary", "confidence", "model")
REVIEW_FIELDS = ("decision", "by", "role", "at", "note")

LOOK_PROMPT = (
    "A resident of India or Nepal took this photo to report standing water (waterlogging) on a street or other public "
    "place during or after rain. Look at the photo and answer ONLY with a JSON object with keys: "
    "water_visible (true if rain or flood water stands or flows over part of a road, street, footpath, underpass, "
    "compound or open ground; false if not; a merely wet surface, or a lake, river, canal or drain within its banks, "
    "does not count), "
    "depth (one of: none, ankle, knee, waist, vehicle; the deepest standing water you can judge from kerbs, steps, "
    "wheels, legs or walls in the photo: ankle = up to about 15 cm, knee = up to about 50 cm, waist = up to about 1 m, "
    "vehicle = deeper, with cars or other vehicles largely under water; none if no standing water is visible), "
    "summary (one plain sentence, max 30 words, describing only what is visible, with no guesses about causes or who "
    "is responsible), "
    "confidence (0 to 1, how sure you are about water_visible). "
    "Never identify people or describe their faces; refer to them only as a person or people.")

LOCAL_LOOK = {"waterVisible": None, "depth": None,
              "summary": "Local stand-in: deployed builds describe the photo with Amazon Nova.",
              "confidence": None, "model": "local stand-in"}


# ------------------------------------------------------------------------------------------ processing
def process(report_id: str, data: bytes) -> dict:
    """Check one uploaded photo and publish the report (called by the evidence Lambda with the original bytes).

    Idempotent: a report that is no longer "uploading" is returned unchanged, and the outcome is written only if no
    other delivery of the same upload wrote one first (SQS delivers at least once)."""
    item = store.get(f"WLOG#{report_id}")
    if not item:
        raise ValueError(f"unknown waterlogging report {report_id}")
    if item.get("status") != "uploading":
        return item
    from . import evidence as E

    created = item.get("createdAt") or store.now_iso()
    exif = E.read_exif(data)
    sets = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "exif": {k: v for k, v in exif.items() if k not in ("lat", "lon")}}
    if not item.get("reportId"):
        sets["reportId"] = report_id
    try:
        model_jpeg = E.jpeg_for_models(data)
    except Exception as ex:                        # not a picture Pillow can open: a retry would fail the same way
        log.warning("waterlog %s: unreadable upload: %s", report_id, ex)
        sets.update(status="unreadable", GSI3SK=f"unreadable#{created}")
        return _finish(report_id, sets)[0]

    loc = _locate(exif, item.get("device"))
    tz = NPT if loc and geo.country(loc["lat"], loc["lon"]) == "NP" else IST
    captured, seen, old = _when(exif.get("capturedAt"), created, tz)
    sets.update(capturedAt=captured, seenAt=seen, oldPhoto=old)
    if not loc:
        sets.update(status="no-location", GSI3SK=f"no-location#{created}")
        return _finish(report_id, sets)[0]

    lat, lon = round(loc["lat"], 5), round(loc["lon"], 5)
    sets.update(lat=lat, lon=lon, locationSource=loc["source"], locationMismatch=loc["mismatch"],
                locationGapM=loc["gapM"], accuracyM=loc["accuracyM"])
    area = areas.area_for(lat, lon)
    area_id, remove = (area.id if area else None), []
    if area_id != item.get("areaId"):              # the API guessed the area from the phone; the photo decides
        sets["GSI3PK"] = f"QUEUE#WLOG#{area_id or 'other'}"
        if area_id:
            sets["areaId"] = area_id
        else:
            remove.append("areaId")

    mod = E.moderate(model_jpeg)
    sets["moderation"] = mod
    if mod["blocked"]:
        sets.update(status="blocked", GSI3SK=f"blocked#{created}")
        done, won = _finish(report_id, sets, remove)
        if won:
            store.audit(area_id or "other", {"id": item.get("uploaderId"), "pseudonym": item.get("uploader")},
                        "WaterReportBlocked", {"reportId": report_id}, extra={"labels": mod["labels"][:5]})
        return done

    boxes = E.faces(model_jpeg)
    big, thumb, size = E.public_copies(data, boxes)
    url = storage.put_public(f"waterlogging/{report_id}.jpg", big, "image/jpeg", immutable=True)
    turl = storage.put_public(f"waterlogging/{report_id}_t.jpg", thumb, "image/jpeg", immutable=True)
    ai = look(model_jpeg)
    words = E.text_words(model_jpeg)
    conf = ai.get("confidence")
    hidden = ("text" if words is not None and words >= E.TEXT_WORDS_LIMIT       # a screenshot or document, not a street
              else "no-water" if ai.get("waterVisible") is False and conf is not None and conf >= HIDE_CONFIDENCE
              else None)
    status = "hidden" if hidden else "live"
    gh4 = geo.geohash(lat, lon, 4)
    sets.update(status=status, url=url, thumbUrl=turl, width=size[0], height=size[1], facesBlurred=len(boxes), ai=ai,
                textWords=words, hiddenReason=hidden, gh4=gh4, GSI1PK=f"WLGEO#{gh4}", GSI1SK=seen,
                GSI3SK=f"{status}#{created}")
    done, won = _finish(report_id, sets, remove)
    if won:                                        # else another delivery finished first and did the rest
        store.put(_day_copy(done))
        store.bump_stats(waterReports=1)
    return done


def _finish(report_id: str, sets: dict, remove: list | None = None) -> tuple[dict, bool]:
    """Write the outcome once: (stored report, True), or (what another delivery already wrote, False)."""
    sets = {**{k: v for k, v in sets.items() if v is not None}, "processedAt": store.now_iso()}
    try:
        return store.update(f"WLOG#{report_id}", "META", sets=sets, remove=remove or None,
                            condition="attribute_not_exists(processedAt)"), True
    except Exception as ex:
        if "ConditionalCheckFailed" not in str(ex):
            raise
        log.info("waterlog %s was processed by another delivery", report_id)
        return store.get(f"WLOG#{report_id}") or {}, False


def _point(lat, lon) -> tuple[float, float] | None:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return (la, lo) if math.isfinite(la) and math.isfinite(lo) else None


def _metres(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, 1) if math.isfinite(x) and x >= 0 else None


def _locate(exif: dict, device: dict | None) -> dict | None:
    """Where the water was: the photo's GPS if usable, else the phone's location (None when neither is usable)."""
    device = device if isinstance(device, dict) else {}
    photo = _point(exif.get("lat"), exif.get("lon"))
    phone = _point(device.get("lat"), device.get("lon"))
    phone = phone if phone and geo.supported(*phone) else None
    gap = geo.haversine_m(*photo, *phone) if photo and phone else None
    if photo and geo.supported(*photo):
        lat, lon, source, acc = photo[0], photo[1], "photo", _metres(exif.get("gpsAccuracyM"))
    elif phone:
        lat, lon, source, acc = phone[0], phone[1], "device", _metres(device.get("accuracyM"))
    else:
        return None
    return {"lat": lat, "lon": lon, "source": source, "mismatch": gap is not None and gap > MISMATCH_M,
            "gapM": round(gap) if gap is not None else None, "accuracyM": acc}


def _parse_iso(s, naive_tz=timezone.utc) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=naive_tz) if d.tzinfo is None else d


def _iso(d: datetime) -> str:
    """UTC, in store.now_iso()'s format, so timestamps compare as strings."""
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _when(captured_raw: str | None, created: str, tz: timezone) -> tuple[str | None, str, bool]:
    """(capturedAt in UTC, seenAt, oldPhoto) from the camera's local capture time and the upload time."""
    now = datetime.now(timezone.utc)
    created_dt = _parse_iso(created)
    if created_dt is None:
        created_dt, created = now, _iso(now)
    cap = _parse_iso(captured_raw, tz)
    captured = _iso(cap) if cap else None
    seen_dt, seen = (cap, captured) if cap and cap <= now else (created_dt, created)
    return captured, seen, created_dt - seen_dt > timedelta(hours=OLD_PHOTO_HOURS)


# ------------------------------------------------------------------------------------------ AI look
def look(jpeg: bytes) -> dict:
    """Amazon Nova's look at the photo: is standing water visible, how deep, one plain sentence (never a verdict)."""
    if C.LOCAL:
        return dict(LOCAL_LOOK)
    from .bedrock import converse_image, parse_json
    blank = {"waterVisible": None, "depth": None, "summary": None, "confidence": None}
    try:
        text, mid = converse_image(LOOK_PROMPT, jpeg, "jpeg", max_tokens=300, temperature=0.0)
    except Exception as ex:
        log.warning("waterlog vision look failed: %s", ex)
        return {**blank, "model": None, "error": str(ex)[:200]}
    d = parse_json(text)
    if d is None:
        return {**blank, "model": mid, "error": "the model did not answer with JSON"}
    return {"waterVisible": _bool(d.get("water_visible")), "depth": _depth(d.get("depth")),
            "summary": _summary(d.get("summary")), "confidence": _confidence(d.get("confidence")), "model": mid}


def _bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return {"true": True, "yes": True, "false": False, "no": False}.get(v.strip().lower())
    return None


def _depth(v) -> str | None:
    s = str(v or "").strip().lower().replace("-deep", "").replace(" deep", "").strip()
    return s if s in AI_DEPTHS else None


def _summary(v) -> str | None:
    words = str(v or "").split()
    if not words:
        return None
    s = " ".join(words[:SUMMARY_WORDS])
    if len(words) > SUMMARY_WORDS:
        s = s.rstrip(",;: ") + "…"
    return s[:240]


def _confidence(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        c = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(c) or c < 0:
        return None
    if 1 < c <= 100:                               # answered as a percentage
        c /= 100
    return round(min(c, 1.0), 2)


# ------------------------------------------------------------------------------------------ public views
def public(item: dict) -> dict:
    """What anyone may see of a report: no uploader id, phone location, hashes or EXIF; position to ~11 m."""
    out = {}
    for k in PUBLIC_FIELDS:
        v = item.get(k)
        if v is None:
            continue
        if k in ("lat", "lon"):
            v = round(float(v), 4)
        elif k == "ai":
            v = {a: v.get(a) for a in AI_PUBLIC if v.get(a) is not None} if isinstance(v, dict) else None
        elif k == "review":
            v = {r: x for r, x in v.items() if x is not None} if isinstance(v, dict) else None
        if v not in (None, "", {}):                    # False and 0 are kept
            out[k] = v
    return out


def _day_copy(item: dict) -> dict:
    seen, rid = item["seenAt"], item.get("reportId") or item["PK"].split("#", 1)[1]
    return {"PK": f"WLDAY#{seen[:10].replace('-', '')}", "SK": f"{seen}#{rid}", **public(item)}


def _statuses(statuses) -> frozenset:
    return frozenset([statuses] if isinstance(statuses, str) else (statuses or ()))


def _tidy(x: float):
    return int(x) if float(x).is_integer() else x


def _since(pk: str, since: str, index: str | None = None):
    """Items of one partition whose sort key is >= `since`, newest first, page by page."""
    from boto3.dynamodb.conditions import Key
    pk_name, sk_name = ("PK", "SK") if not index else (f"{index}PK", f"{index}SK")
    args = {"KeyConditionExpression": Key(pk_name).eq(pk) & Key(sk_name).gte(since), "ScanIndexForward": False}
    if index:
        args["IndexName"] = index
    while True:
        r = store.table().query(**args)
        for it in r.get("Items", []):
            yield store.plain(it)
        if not r.get("LastEvaluatedKey"):
            return
        args["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def recent(hours: int = 48, statuses=PUBLIC_STATUSES) -> list[dict]:
    """Reports seen in the last `hours` (at most 31 days), newest first, at most 500, from the WLDAY# partitions."""
    keep = _statuses(statuses)
    hours = min(max(float(hours), 0.0), RECENT_MAX_HOURS)
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    cutoff = _iso(start)
    out, day = [], now.date()
    while day >= start.date() and len(out) < RECENT_CAP:
        for it in _since(f"WLDAY#{day:%Y%m%d}", cutoff):
            if it.get("status") in keep and (it.get("seenAt") or "") >= cutoff:
                out.append(public(it))
                if len(out) >= RECENT_CAP:
                    break
        day -= timedelta(days=1)
    out.sort(key=lambda r: (r.get("seenAt") or "", r.get("reportId") or ""), reverse=True)
    return out


def cell_size(precision: int = 4) -> tuple[float, float]:
    """(degrees of longitude, degrees of latitude) one geohash cell of this length covers; 4 -> 0.3516 x 0.1758."""
    bits = 5 * precision
    return 360.0 / 2 ** ((bits + 1) // 2), 180.0 / 2 ** (bits // 2)


def neighbours(cell: str) -> list[str]:
    """The (up to) 8 geohash cells around `cell`: its centre re-encoded one cell width / height away."""
    lat, lon = geo.geohash_decode(cell)
    dlon, dlat = cell_size(len(cell))
    out = []
    for dy in (1, 0, -1):
        for dx in (-1, 0, 1):
            la = lat + dy * dlat
            if (dx, dy) == (0, 0) or not -90.0 < la < 90.0:
                continue
            gh = geo.geohash(la, (lon + dx * dlon + 180.0) % 360.0 - 180.0, len(cell))
            if gh != cell and gh not in out:
                out.append(gh)
    return out


def _distance_to_cell_m(lat: float, lon: float, cell: str) -> float:
    clat, clon = geo.geohash_decode(cell)
    dlon, dlat = cell_size(len(cell))
    return geo.haversine_m(lat, lon, min(max(lat, clat - dlat / 2), clat + dlat / 2),
                           min(max(lon, clon - dlon / 2), clon + dlon / 2))


def nearby(lat: float, lon: float, radius_m: float = 1000, days: int = 365, statuses=PUBLIC_STATUSES) -> dict:
    """How often people reported standing water within `radius_m` (at most 15 km) of a point in the last `days`."""
    pt = _point(lat, lon)
    if not pt:
        raise ValueError("lat and lon must be numbers")
    lat, lon = pt
    keep = _statuses(statuses)
    radius_m = min(max(float(radius_m), 0.0), NEARBY_MAX_M)
    days = min(max(float(days), 0.0), 36500.0)
    cutoff = store.iso_days_ago(days)
    centre = geo.geohash(lat, lon, 4)
    found, capped = {}, False
    for cell in [centre] + neighbours(centre):
        if cell != centre and _distance_to_cell_m(lat, lon, cell) > radius_m + CELL_MARGIN_M:
            continue                                   # no point of that cell can be within the radius
        for n, it in enumerate(_since(f"WLGEO#{cell}", cutoff, index="GSI1")):
            if n >= NEARBY_READ_CAP:
                capped = True
                break
            p = _point(it.get("lat"), it.get("lon"))
            if it.get("status") in keep and p and geo.haversine_m(lat, lon, *p) <= radius_m:
                found[it.get("reportId") or it["PK"]] = it
    items = sorted(found.values(), key=lambda i: (i.get("seenAt") or "", i.get("reportId") or ""), reverse=True)
    out = {"count": len(items), "radiusM": _tidy(radius_m), "days": _tidy(days),
           "items": [public(i) for i in items[:NEARBY_ITEMS]], "lastSeenAt": items[0].get("seenAt") if items else None}
    if capped:
        out["capped"] = True
    return out


# ------------------------------------------------------------------------------------------ review and history
def apply_review(report_id: str, review: dict) -> dict:
    """A verifier's decision ({"decision": "verified" | "rejected", "by", "role", "at", "note"}) on the report and its
    day copy. The API decides with Cedar who may review; this only records it."""
    decision = (review or {}).get("decision")
    if decision not in ("verified", "rejected"):
        raise ValueError("decision must be verified or rejected")
    item = store.get(f"WLOG#{report_id}")
    if not item:
        raise ValueError(f"unknown waterlogging report {report_id}")
    if item.get("status") not in REVIEWABLE:
        raise ValueError(f"report {report_id} is {item.get('status')}: only reports that passed the checks "
                         "can be reviewed")
    rv = {k: review.get(k) for k in REVIEW_FIELDS if review.get(k) is not None}
    rv.setdefault("at", store.now_iso())
    done = store.update(f"WLOG#{report_id}", "META",
                        sets={"status": decision, "review": rv, "GSI3SK": f"{decision}#{item.get('createdAt', '')}"})
    store.put(_day_copy(done))                         # a rejected copy stays; recent() leaves it out
    return done


def mine(user_id: str) -> list[dict]:
    """Everything one person reported, newest first, with the raw status (also no-location, blocked, unreadable)."""
    items = store.query_all(f"USER#{user_id}", "WLOG#", index="GSI2")
    items.sort(key=lambda i: (i.get("createdAt") or "", i.get("reportId") or ""), reverse=True)
    return [{**public(i), "status": i.get("status")} for i in items]

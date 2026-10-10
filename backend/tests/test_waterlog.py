"""Citizen waterlogging reports: a photo of standing water becomes a point on the live map (provenance, privacy, an
AI look), verifiers confirm or reject it, and a place's page counts the reports near it. AWS is moto (conftest)."""
import hashlib
import io
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from jalsmriti import areas, geo, storage, store
from jalsmriti import waterlog as W

IST = timezone(timedelta(hours=5, minutes=30))
NPT = timezone(timedelta(hours=5, minutes=45))
BELLANDUR = (12.9352, 77.6807)
MG_ROAD = (12.9716, 77.5946)
MYSURU = (12.2958, 76.6394)                # India, outside every pre-loaded area
KATHMANDU = (27.7172, 85.3240)
KOCHI = (9.9816, 76.2999)                  # used by one test only, so its counts are exact
DUBAI = (25.2048, 55.2708)                 # outside the area JalSmriti covers
PUB = Path(storage.LOCAL_DIR) / "site" / "pub" / "waterlogging"
VERIFIER = {"by": "NGO Kingfisher", "role": "verifier"}


def dms(v):
    d = int(v); m = int((v - d) * 60); s = round(((v - d) * 60 - m) * 60, 2)
    return (float(d), float(m), float(s))


def photo(lat=None, lon=None, taken=None) -> bytes:
    """A JPEG as a phone writes it: GPS in the GPS IFD, DateTimeOriginal (camera local time) in the Exif IFD."""
    img = Image.new("RGB", (640, 480), (70, 95, 120))
    buf = io.BytesIO()
    if lat is None and taken is None:
        img.save(buf, "JPEG", quality=85)                  # no EXIF at all
        return buf.getvalue()
    exif = Image.Exif()
    if lat is not None:
        exif[0x8825] = {1: "N", 2: dms(lat), 3: "E", 4: dms(lon)}
    if taken is not None:
        exif[0x8769] = {0x9003: taken.strftime("%Y:%m:%d %H:%M:%S")}
    img.save(buf, "JPEG", quality=85, exif=exif)
    return buf.getvalue()


def iso(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def report(sub="u-wl-citizen", device=None, depth="knee", note=None, created=None) -> str:
    """A WLOG item exactly as the API writes it when it hands out the upload URL."""
    rid = store.new_id("wl")
    now = created or store.now_iso()
    a = areas.area_for(*device) if device else None
    store.put({"PK": f"WLOG#{rid}", "SK": "META", "reportId": rid, "status": "uploading", "createdAt": now,
               "uploaderId": sub, "uploader": "Monsoon Heron 42",
               "device": {"lat": device[0], "lon": device[1], "accuracyM": 12.0} if device else None,
               "depth": depth, "note": note, "contentType": "image/jpeg", "areaId": a.id if a else None,
               "GSI2PK": f"USER#{sub}", "GSI2SK": f"WLOG#{now}",
               "GSI3PK": f"QUEUE#WLOG#{a.id if a else 'other'}", "GSI3SK": f"uploading#{now}"})
    return rid


def ids(rows) -> list:
    return [r["reportId"] for r in rows]


def day_copy(it: dict) -> dict | None:
    return store.get(f"WLDAY#{it['seenAt'][:10].replace('-', '')}", f"{it['seenAt']}#{it['reportId']}")


def counter() -> int:
    return int(store.stats().get("waterReports", 0))


def taken_ago(**delta) -> datetime:
    return datetime.now(IST).replace(microsecond=0) - timedelta(**delta)


def test_photo_with_gps_goes_live_on_the_map(aws):
    taken = taken_ago(hours=2)
    data = photo(*BELLANDUR, taken=taken)
    rid = report(note="Knee-deep near the bus stop")
    before = counter()
    it = W.process(rid, data)

    assert it["status"] == "live" and it["locationSource"] == "photo"
    assert it["locationMismatch"] is False and it["oldPhoto"] is False
    assert (it["lat"], it["lon"]) == BELLANDUR and it["areaId"] == "bengaluru"
    assert it["seenAt"] == it["capturedAt"] == iso(taken)        # camera local time read as IST, kept in UTC
    assert it["sha256"] == hashlib.sha256(data).hexdigest() and it["bytes"] == len(data)
    assert "lat" not in it["exif"] and it["processedAt"] >= it["createdAt"]
    assert it["ai"] == {"summary": W.LOCAL_LOOK["summary"], "model": "local stand-in"}
    assert it["gh4"] == geo.geohash(*BELLANDUR, 4) == "tdr1"
    assert it["GSI1PK"] == "WLGEO#tdr1" and it["GSI1SK"] == it["seenAt"]
    assert it["GSI3PK"] == "QUEUE#WLOG#bengaluru" and it["GSI3SK"] == f"live#{it['createdAt']}"
    assert it["GSI2PK"] == "USER#u-wl-citizen" and it["GSI2SK"] == f"WLOG#{it['createdAt']}"

    # public copies: JPEG, upright, no EXIF (no phone metadata leaks)
    assert it["url"] == f"/pub/waterlogging/{rid}.jpg" and it["thumbUrl"] == f"/pub/waterlogging/{rid}_t.jpg"
    for name in (f"{rid}.jpg", f"{rid}_t.jpg"):
        raw = (PUB / name).read_bytes()
        assert raw[:2] == b"\xff\xd8" and not Image.open(io.BytesIO(raw)).getexif()
    assert max(Image.open(PUB / f"{rid}_t.jpg").size) <= 480

    # the day copy for the national list holds only the public view
    copy = day_copy(it)
    assert copy["status"] == "live" and (copy["lat"], copy["lon"]) == (12.9352, 77.6807)
    assert copy["note"] == "Knee-deep near the bus stop" and copy["depth"] == "knee"
    assert not {"uploaderId", "sha256", "exif", "device", "moderation", "GSI1PK", "GSI3PK"} & set(copy)
    assert counter() == before + 1

    # the live map and the place page
    assert rid in ids(W.recent()) and rid not in ids(W.recent(hours=1))
    near = W.nearby(12.9360, 77.6815)
    assert rid in ids(near["items"]) and near["count"] >= 1 and near["lastSeenAt"] >= it["seenAt"]
    assert near["radiusM"] == 1000 and near["days"] == 365
    north = (12.9622, 77.6807)                                     # 3 km north, same geohash cell
    assert geo.haversine_m(*BELLANDUR, *north) == pytest.approx(3000, abs=50)
    assert rid not in ids(W.nearby(*north)["items"]) and rid in ids(W.nearby(*north, radius_m=5000)["items"])
    east = (12.9352, 77.7084)                                      # 3 km east, in the next cell
    assert geo.geohash(*east, 4) == "tdr3" and rid in ids(W.nearby(*east, radius_m=5000)["items"])
    assert rid not in ids(W.nearby(*east, radius_m=1000)["items"])

    # a second delivery of the same upload changes nothing
    assert W.process(rid, data) == it and counter() == before + 1 and day_copy(it) == copy


def test_a_delivery_that_raced_another_writes_nothing(aws, monkeypatch):
    data = photo(*BELLANDUR)
    rid = report()
    first = W.process(rid, data)
    before, real_get, reads = counter(), store.get, []

    def stale_get(pk, sk="META"):                                  # this delivery read the report before the
        got = real_get(pk, sk)                                     # first one wrote its outcome
        if pk == f"WLOG#{rid}" and not reads:
            reads.append(pk)
            return {**got, "status": "uploading"}
        return got

    monkeypatch.setattr(store, "get", stale_get)
    assert W.process(rid, data) == first and reads and counter() == before


def test_phone_location_when_the_photo_has_no_gps(aws):
    rid = report(device=MG_ROAD)
    it = W.process(rid, photo())                                   # no EXIF at all
    assert it["status"] == "live" and it["locationSource"] == "device" and it["accuracyM"] == 12.0
    assert (it["lat"], it["lon"]) == MG_ROAD and it["areaId"] == "bengaluru"
    assert it["seenAt"] == it["createdAt"] and "capturedAt" not in it and it["oldPhoto"] is False
    assert it["locationMismatch"] is False and "locationGapM" not in it
    assert rid in ids(W.recent()) and day_copy(it)["locationSource"] == "device"


def test_no_location_stays_private(aws):
    rid = report(sub="u-wl-nowhere")
    it = W.process(rid, photo(taken=taken_ago(minutes=20)))       # capture time, but no GPS and no phone fix
    assert it["status"] == "no-location" and it["GSI3SK"] == f"no-location#{it['createdAt']}"
    assert not {"url", "lat", "lon", "GSI1PK", "moderation", "ai"} & set(it)
    assert not (PUB / f"{rid}.jpg").exists()
    assert rid not in ids(W.recent(statuses=W.REVIEWABLE + ("no-location",)))
    assert [(m["reportId"], m["status"]) for m in W.mine("u-wl-nowhere")] == [(rid, "no-location")]
    with pytest.raises(ValueError):
        W.apply_review(rid, {"decision": "verified", **VERIFIER, "note": "Seen on site."})


def test_photo_gps_far_from_the_phone_wins_and_is_flagged(aws):
    rid = report(device=MYSURU)                                    # the API filed it under "other" ...
    it = W.process(rid, photo(*BELLANDUR))                         # ... but the photo was taken in Bengaluru
    assert it["locationSource"] == "photo" and it["locationMismatch"] is True and it["locationGapM"] > 100_000
    assert (it["lat"], it["lon"]) == BELLANDUR
    assert it["areaId"] == "bengaluru" and it["GSI3PK"] == "QUEUE#WLOG#bengaluru"

    rid = report(device=BELLANDUR)                                 # filed under Bengaluru, photo from Mysuru
    it = W.process(rid, photo(*MYSURU))
    assert it["locationMismatch"] is True and (it["lat"], it["lon"]) == MYSURU
    assert "areaId" not in it and it["GSI3PK"] == "QUEUE#WLOG#other"

    rid = report(device=(12.9400, 77.6807))                        # 530 m from the photo: the same place
    it = W.process(rid, photo(*BELLANDUR))
    assert it["locationSource"] == "photo" and it["locationMismatch"] is False and it["locationGapM"] < 2000

    rid = report(device=MG_ROAD)                                   # photo GPS outside India and Nepal (Dubai):
    it = W.process(rid, photo(*DUBAI))                             # the phone's location is used, and flagged
    assert it["locationSource"] == "device" and (it["lat"], it["lon"]) == MG_ROAD and it["locationMismatch"] is True
    assert W.process(report(), photo(*DUBAI))["status"] == "no-location"


def test_old_photo_is_flagged_and_kept_off_the_live_map(aws):
    taken = taken_ago(days=3)
    rid = report()
    it = W.process(rid, photo(*BELLANDUR, taken=taken))
    assert it["status"] == "live" and it["oldPhoto"] is True and it["seenAt"] == iso(taken)
    assert day_copy(it)["oldPhoto"] is True and it["GSI1SK"] == iso(taken)
    assert rid not in ids(W.recent()) and rid in ids(W.recent(hours=4 * 24))
    assert rid in ids(W.nearby(*BELLANDUR)["items"]) and rid not in ids(W.nearby(*BELLANDUR, days=2)["items"])


def test_capture_time_in_the_future_is_not_believed(aws):
    taken = taken_ago(days=-2)                                     # camera clock two days ahead
    it = W.process(report(), photo(*BELLANDUR, taken=taken))
    assert it["seenAt"] == it["createdAt"] and it["capturedAt"] == iso(taken) and it["oldPhoto"] is False


def test_camera_time_in_nepal_is_nepal_time(aws):
    taken = datetime.now(NPT).replace(microsecond=0) - timedelta(hours=1)
    it = W.process(report(), photo(*KATHMANDU, taken=taken))
    assert it["areaId"] == "kathmandu" and it["seenAt"] == iso(taken)


def test_neighbouring_cells():
    n = W.neighbours("tdr1")
    assert len(n) == len(set(n)) == 8 and "tdr1" not in n and {"tdr3", "tdr4"} <= set(n)
    dlon, dlat = W.cell_size(4)
    assert (round(dlon, 4), round(dlat, 4)) == (0.3516, 0.1758)
    clat, clon = geo.geohash_decode("tdr1")
    steps = {(round((la - clat) / dlat), round((lo - clon) / dlon)) for la, lo in map(geo.geohash_decode, n)}
    assert steps == {(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)} - {(0, 0)}


def test_report_just_across_a_cell_edge_is_counted(aws):
    there, here = (12.9352, 77.6990), (12.9352, 77.6920)           # 760 m apart, either side of 77.6953 E
    assert geo.geohash(*there, 4) == "tdr3" and geo.geohash(*here, 4) == "tdr1"
    rid = report()
    W.process(rid, photo(*there))
    assert rid in ids(W.nearby(*here, radius_m=1000)["items"])
    assert rid not in ids(W.nearby(*here, radius_m=500)["items"])


def test_nearby_counts_reports_newest_first(aws):
    old, new, gone = report(), report(), report()
    W.process(old, photo(*KOCHI, taken=taken_ago(days=10)))
    W.process(new, photo(KOCHI[0] + 0.002, KOCHI[1], taken=taken_ago(hours=1)))       # 220 m north
    W.process(gone, photo(KOCHI[0], KOCHI[1] + 0.002))                                 # 220 m east
    W.apply_review(gone, {"decision": "rejected", **VERIFIER, "note": "Photo of another street."})
    near = W.nearby(*KOCHI)
    assert near["count"] == 2 and ids(near["items"]) == [new, old]
    assert near["lastSeenAt"] == near["items"][0]["seenAt"]
    assert near["items"][0]["lat"] == round(KOCHI[0] + 0.002, 4)
    assert W.nearby(*KOCHI, statuses=("live", "verified", "rejected"))["count"] == 3
    assert W.nearby(*KOCHI, days=5)["count"] == 1
    assert ids(W.nearby(*KOCHI, radius_m=50)["items"]) == [old]
    assert W.nearby(*KOCHI, radius_m=10**6)["radiusM"] == W.NEARBY_MAX_M


def test_review_updates_the_report_and_its_day_copy(aws):
    rid = report()
    it = W.process(rid, photo(*BELLANDUR))
    rv = {"decision": "verified", **VERIFIER, "at": store.now_iso(), "note": "Matches our site visit."}
    done = W.apply_review(rid, rv)
    assert done["status"] == "verified" and done["review"] == rv and done["GSI3SK"] == f"verified#{it['createdAt']}"
    copy = day_copy(it)
    assert copy["status"] == "verified" and copy["review"] == rv
    assert rid in ids(W.recent()) and rid in ids(W.nearby(*BELLANDUR)["items"])

    done = W.apply_review(rid, {**rv, "decision": "rejected", "note": "Photo is from another street."})
    assert done["status"] == "rejected" and done["GSI3SK"] == f"rejected#{it['createdAt']}"
    assert day_copy(it)["status"] == "rejected"                    # the copy is kept ...
    assert rid not in ids(W.recent()) and rid not in ids(W.nearby(*BELLANDUR)["items"])   # ... but not shown
    assert rid in ids(W.recent(statuses=("rejected",)))
    with pytest.raises(ValueError):
        W.apply_review(rid, {"decision": "maybe"})


def test_confident_no_water_waits_for_a_verifier(aws, monkeypatch):
    dry = {"waterVisible": False, "depth": "none", "summary": "A dry street with parked scooters.", "model": "test"}
    monkeypatch.setattr(W, "look", lambda jpeg: {**dry, "confidence": 0.9})
    rid = report()
    it = W.process(rid, photo(*BELLANDUR))
    assert it["status"] == "hidden" and it["GSI3SK"] == f"hidden#{it['createdAt']}" and it["GSI1PK"] == "WLGEO#tdr1"
    assert day_copy(it)["status"] == "hidden" and day_copy(it)["ai"]["waterVisible"] is False
    assert rid not in ids(W.recent()) and rid in ids(W.recent(statuses=("hidden",)))
    assert rid not in ids(W.nearby(*BELLANDUR)["items"])
    W.apply_review(rid, {"decision": "verified", **VERIFIER, "note": "Water stood here at 9 am."})
    assert rid in ids(W.recent()) and rid in ids(W.nearby(*BELLANDUR)["items"])

    monkeypatch.setattr(W, "look", lambda jpeg: {**dry, "confidence": 0.4})
    assert W.process(report(), photo(*BELLANDUR))["status"] == "live"      # unsure: it goes live


def test_blocked_photo_is_audited_and_never_published(aws, monkeypatch):
    from jalsmriti import evidence as E
    label = {"name": "Graphic Violence", "parent": None, "confidence": 97.0}
    monkeypatch.setattr(E, "moderate", lambda jpeg: {"blocked": True, "labels": [label], "engine": "test"})
    before = counter()
    rid = report(sub="u-wl-blocked")
    it = W.process(rid, photo(*BELLANDUR))
    assert it["status"] == "blocked" and it["GSI3SK"] == f"blocked#{it['createdAt']}" and it["moderation"]["blocked"]
    assert not {"url", "thumbUrl", "GSI1PK", "ai"} & set(it) and not (PUB / f"{rid}.jpg").exists()
    assert rid not in ids(W.recent(statuses=W.REVIEWABLE + ("blocked",))) and counter() == before
    audit = store.query_all("AUDIT#bengaluru")
    assert any(a["action"] == "WaterReportBlocked" and a["resource"] == {"reportId": rid}
               and a["user"] == "u-wl-blocked" and [x["name"] for x in a["extra"]["labels"]] == ["Graphic Violence"]
               for a in audit)
    assert W.mine("u-wl-blocked")[0]["status"] == "blocked"


def test_unreadable_upload_gets_a_final_status(aws):
    rid = report(device=MG_ROAD)
    it = W.process(rid, b"this is not a photo " * 100)
    assert it["status"] == "unreadable" and "url" not in it and len(it["sha256"]) == 64
    assert W.process(rid, b"anything else") == it


def test_mine_lists_every_report_with_its_status(aws):
    sub, t0 = "u-wl-history", datetime.now(timezone.utc) - timedelta(minutes=10)
    first = report(sub, device=MG_ROAD, created=iso(t0))
    second = report(sub, created=iso(t0 + timedelta(minutes=1)))
    third = report(sub, created=iso(t0 + timedelta(minutes=2)))     # never uploaded
    W.process(first, photo())
    W.process(second, photo())
    rows = W.mine(sub)
    assert ids(rows) == [third, second, first]
    assert [r["status"] for r in rows] == ["uploading", "no-location", "live"]
    assert {"lat", "url"} <= set(rows[2]) and "lat" not in rows[1]
    assert not any({"uploaderId", "sha256", "device"} & set(r) for r in rows)


def test_nova_answer_is_checked_and_normalised(monkeypatch):
    from jalsmriti import bedrock
    monkeypatch.setattr(W.C, "LOCAL", False)
    calls = []

    def answer(text):
        def fake(prompt, image, fmt="jpeg", **kw):
            calls.append({"prompt": prompt, "fmt": fmt, **kw})
            return text, "us.amazon.nova-lite-v1:0"
        return fake

    words = " ".join(["water"] * 40)
    monkeypatch.setattr(bedrock, "converse_image", answer(
        '```json\n{"water_visible": "true", "depth": "Knee-deep", "summary": "%s", "confidence": 85}\n```' % words))
    ai = W.look(b"jpeg")
    assert calls[0]["prompt"] == W.LOOK_PROMPT and calls[0]["fmt"] == "jpeg" and calls[0]["temperature"] == 0.0
    assert (ai["waterVisible"], ai["depth"], ai["confidence"]) == (True, "knee", 0.85)
    assert ai["model"] == "us.amazon.nova-lite-v1:0" and "error" not in ai
    assert len(ai["summary"].split()) == W.SUMMARY_WORDS and ai["summary"].endswith("…")

    monkeypatch.setattr(bedrock, "converse_image", answer(
        '{"water_visible": false, "depth": "none", "summary": "A dry road.", "confidence": 0.7}'))
    assert W.look(b"jpeg") == {"waterVisible": False, "depth": "none", "summary": "A dry road.", "confidence": 0.7,
                               "model": "us.amazon.nova-lite-v1:0"}

    monkeypatch.setattr(bedrock, "converse_image", answer("I cannot help with that."))
    ai = W.look(b"jpeg")
    assert ai["error"] and ai["waterVisible"] is None and ai["model"] == "us.amazon.nova-lite-v1:0"

    def down(*a, **k):
        raise RuntimeError("no Bedrock model answered: throttled")
    monkeypatch.setattr(bedrock, "converse_image", down)
    assert W.look(b"jpeg") == {"waterVisible": None, "depth": None, "summary": None, "confidence": None,
                               "model": None, "error": "no Bedrock model answered: throttled"}


def test_public_view_leaves_private_fields_out():
    item = {"PK": "WLOG#wl1", "SK": "META", "reportId": "wl1", "status": "live", "lat": 12.935212, "lon": 77.680749,
            "createdAt": "2026-10-11T03:00:00.000Z", "seenAt": "2026-10-11T02:40:00.000Z", "capturedAt": None,
            "uploaderId": "sub-123", "uploader": "Monsoon Heron 42", "device": {"lat": 12.9, "lon": 77.6},
            "sha256": "ab" * 32, "exif": {"make": "Phone"}, "moderation": {"blocked": False}, "depth": "knee",
            "note": None, "oldPhoto": False, "locationMismatch": False, "locationSource": "photo", "locationGapM": 40,
            "ai": {"waterVisible": True, "depth": "knee", "summary": "Water covers the road.", "confidence": 0.9,
                   "model": "m", "error": None},
            "GSI1PK": "WLGEO#tdr1", "url": "/pub/waterlogging/wl1.jpg"}
    p = W.public(item)
    assert (p["lat"], p["lon"]) == (12.9352, 77.6807)
    assert set(p) == {"reportId", "status", "lat", "lon", "createdAt", "seenAt", "uploader", "depth", "ai", "oldPhoto",
                      "locationMismatch", "locationSource", "url"}
    assert p["ai"] == {"waterVisible": True, "depth": "knee", "summary": "Water covers the road.", "confidence": 0.9,
                       "model": "m"}
    assert p["oldPhoto"] is False and W.public(p) == p


def test_module_stays_light_for_the_api_lambda():
    """The API Lambda has no numpy, shapely or rasterio: importing waterlog must not pull them (or Pillow) in."""
    heavy = ("numpy", "shapely", "rasterio", "PIL", "boto3", "jalsmriti.evidence", "jalsmriti.bedrock")
    code = f"import sys, jalsmriti.waterlog; print(','.join(m for m in {heavy!r} if m in sys.modules))"
    src = Path(__file__).resolve().parents[1] / "src"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                       env={**os.environ, "PYTHONPATH": str(src)})
    assert r.stdout.strip() == ""

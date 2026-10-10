"""The features that turn a place check into action, through the API as API Gateway calls it: this week's steps,
the rain forecast and heads-up emails, the signed place report, listening to a report, RTI requests and standing-water
reports from people (with Cedar deciding who may review them)."""
import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from test_api import CITIZEN, OFFICER, VERIFIER, call, claims, photo

LAT, LON = 12.93520, 77.68070          # Bellandur, Bengaluru

CANNED = {"days": [{"date": "2026-10-11", "mm": 2.0, "prob": 30, "maxHourlyMm": 1.0, "level": "light"},
                   {"date": "2026-10-12", "mm": 72.4, "prob": 90, "maxHourlyMm": 24.0, "level": "heavy"},
                   {"date": "2026-10-13", "mm": 8.0, "prob": 60, "maxHourlyMm": 3.0, "level": "light"}],
          "next24hMm": 30.0, "maxHourlyMm": 24.0, "timezone": "Asia/Kolkata", "utcOffsetSeconds": 19800,
          "source": "Open-Meteo", "fetchedAt": "2026-10-11T00:30:00.00Z"}


@pytest.fixture()
def place(aws):
    """A stored place check, as the place workflow writes it (with summer heat and two radar sightings)."""
    from jalsmriti import config as C
    from jalsmriti import geo, store
    gh = geo.geohash(LAT, LON, 7)
    item = {
        "PK": f"PLACE#{gh}", "SK": f"V#{C.PLACE_CACHE_VERSION}", "lat": LAT, "lon": LON, "areaId": "bengaluru",
        "label": {"label": "Bellandur, Bengaluru"},
        "signals": {"occurrenceHere": 62.0, "everWater1000": 0.31, "lostWater1000": 0.08, "builtOverWater2000": 0.02,
                    "lostWaterHa300": 4.2, "builtOverWaterHa2000": 21.4, "historicWaterHa1000": 80.0, "nearestWaterM": 180,
                    "depressionMax300": 2.1, "handMin300": 0.4, "elevationM": 873.0, "relElevationM": 2.0,
                    "landCoverHere": "built area",
                    "radarSightings": [{"date": "2022-09-05", "haCore": 1.3, "orbit": 63}, {"date": "2024-10-12", "haCore": 0.6, "orbit": 63}]},
        "memory": {"index": 79, "tier": "strong", "ranks": {}, "radarSightings": 2},
        "findings": [{"key": "wasWater", "severity": "high", "text": "Satellites saw water on this very spot in 62% of looks between 1984 and 2020.", "vars": {"pct": 62.0}},
                     {"key": "bowl", "severity": "medium", "text": "The ground within 300 m forms a bowl up to 2.1 m deep where rain can pond.", "vars": {"m": 2.1}},
                     {"key": "radar", "severity": "high", "text": "Radar saw unusual standing water within 300 m on 2022-09-05 (1.3 ha).", "vars": {"date": "2022-09-05", "ha": 1.3}}],
        "frames": [], "radar": {"scenesChecked": 41},
        "heat": {"hereC": 43.2, "builtC": 40.4, "waterC": 31.8, "treesC": 37.4, "vsBuiltC": 2.8, "vsWaterC": 11.4, "hotter": True,
                 "years": [2024, 2025, 2026], "scale": [25, 50], "scenes": []},
        "scienceVersion": C.SCIENCE_VERSION, "checkedAt": "2026-10-10T06:41:00.00Z", "checkId": "pl-test",
    }
    store.put(item)
    return item


@pytest.fixture()
def canned_forecast(monkeypatch):
    from jalsmriti import forecast
    calls = []

    def fake_fetch(points, days=3, timeout=8.0, **kw):
        from jalsmriti import store
        calls.append(points)
        from datetime import datetime, timedelta, timezone
        today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
        fc = json.loads(json.dumps(CANNED))
        for i, d in enumerate(fc["days"]):                 # today, tomorrow and the day after, in India
            d["date"] = (today + timedelta(days=i)).isoformat()
        return [{**fc, "fetchedAt": store.now_iso()} for _ in points]
    monkeypatch.setattr(forecast, "fetch", fake_fetch)
    return calls


def test_place_check_carries_this_weeks_steps(place):
    s, r = call("POST", "/v1/places", {"lat": LAT, "lon": LON})
    assert s == 200 and r["cached"] is True
    acts = r["result"]["actions"]
    home = [a["key"] for a in acts["home"]]
    res = [a["key"] for a in acts["resident"]]
    assert home[0] == "act.home.ask" and "act.home.radar" in home and "act.home.floor" in home
    assert home[-2:] == ["act.home.report", "act.home.follow"] and len(home) <= 7
    assert "act.res.follow" in res and "act.res.before" in res and "act.res.report" in res and len(res) <= 7
    radar = next(a for a in acts["home"] if a["key"] == "act.home.radar")
    assert radar["vars"]["dates"] == ["2024-10-12", "2022-09-05"]
    assert r["result"]["heat"]["hereC"] == 43.2


def test_actions_follow_the_record():
    from jalsmriti import actions
    quiet = {"lat": 13.1, "lon": 77.6, "areaId": "bengaluru", "memory": {"tier": "little"},
             "signals": {"handMin300": 6.0, "depressionMax300": 0.2, "builtOverWaterHa2000": 0, "radarSightings": []}}
    home = [a["key"] for a in actions.for_place(quiet)["home"]]
    assert "act.home.floor" not in home and "act.home.radar" not in home and "act.home.records" not in home
    hyd = {**quiet, "lat": 17.4, "lon": 78.45, "areaId": "hyderabad", "signals": {"builtOverWaterHa2000": 5}}
    assert "act.home.hydraa" in [a["key"] for a in actions.for_place(hyd)["home"]]
    nepal = {**quiet, "lat": 27.7, "lon": 85.3, "areaId": "kathmandu"}
    keys = [a["key"] for a in actions.for_place(nepal)["resident"]]
    assert "act.res.alertsNp" in keys and "act.res.alerts" not in keys


def test_forecast_for_a_place(aws, canned_forecast):
    s, fc = call("GET", "/v1/forecast", query={"lat": LAT, "lon": LON})
    assert s == 200 and fc["days"][1]["mm"] == 72.4 and fc["source"] == "Open-Meteo"
    call("GET", "/v1/forecast", query={"lat": LAT + 0.001, "lon": LON})       # same 5 km cell: served from the cache
    assert len(canned_forecast) == 1
    assert call("GET", "/v1/forecast", query={"lat": 51.5, "lon": -0.1})[0] == 400


def test_follow_a_place_and_get_a_test_heads_up(place, canned_forecast):
    unverified = {**claims("u-unverified"), "email_verified": "false"}
    s, r = call("POST", "/v1/secure/follows", {"lat": LAT, "lon": LON}, unverified)
    assert s == 400 and "verified" in r["message"]
    who = claims("u-follower")
    s, r = call("POST", "/v1/secure/follows", {"lat": LAT, "lon": LON, "lang": "en"}, who)
    assert s == 200 and r["status"] == "active" and len(r["gh7"]) == 7
    s, again = call("POST", "/v1/secure/follows", {"lat": LAT, "lon": LON}, who)
    assert s == 200 and again["already"] is True
    s, act = call("GET", "/v1/secure/me/activity", who=who)
    assert [f["tier"] for f in act["follows"]] == ["strong"] and act["headsUp"]["status"] == "active"
    s, t = call("POST", f"/v1/secure/follows/{r['gh7']}/test", who=who)
    assert s == 200 and "Bellandur" in t["subject"] and "Open-Meteo" in t["body"]
    s, _ = call("DELETE", f"/v1/secure/follows/{r['gh7']}", who=who)
    assert s == 200 and call("GET", "/v1/secure/me/activity", who=who)[1]["follows"] == []
    assert call("POST", f"/v1/secure/follows/{r['gh7']}/test", who=who)[0] == 404


def test_daily_rain_check_emails_followers_once(place, canned_forecast):
    import alerts
    from jalsmriti import store
    store.put({"PK": "FOLLOW#u-rain", "SK": "tdr1x6u", "userId": "u-rain", "gh7": "tdr1x6u", "lat": LAT, "lon": LON,
               "label": "Bellandur, Bengaluru", "tier": "strong", "lang": "hi", "createdAt": store.now_iso(),
               "GSI3PK": "FOLLOWS", "GSI3SK": "tdr1x6u#u-rain"})
    before = len(alerts.OUTBOX)
    first = alerts.rain_check()
    mine = [m for m in alerts.OUTBOX[before:] if m[2] == "u-rain"]
    assert first["alerts"] >= 1 and len(mine) == 1
    alerts.rain_check()
    assert len([m for m in alerts.OUTBOX[before:] if m[2] == "u-rain"]) == 1      # not twice for the same rain


def test_signed_place_report_in_hindi(place):
    import jobs
    from jalsmriti import storage
    s, r = call("POST", "/v1/places/report", {"lat": LAT, "lon": LON, "lang": "hi", "persona": "home"})
    assert s == 202 and r["status"] == "rendering" and r["reportId"].startswith("rpt")
    built = jobs.build_report(r["reportId"])
    assert built["status"] == "ready" and built["pdfUrl"] == f"/pub/reports/{r['reportId']}.pdf"
    s, again = call("POST", "/v1/places/report", {"lat": LAT, "lon": LON, "lang": "hi", "persona": "home"})
    assert s == 200 and again["reportId"] == r["reportId"] and again["status"] == "ready"   # same report, not redrawn
    s, v = call("GET", f"/v1/verify/{r['reportId']}")
    assert s == 200 and v["kind"] == "report" and v["serverCheck"] is True and v["subject"] == "Bellandur, Bengaluru"
    raw = base64.b64decode(v["signature"]["raw"])
    key = serialization.load_der_public_key(base64.b64decode(v["publicKey"]["spki"]))
    key.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
               v["attestationCanonical"].encode(), ec.ECDSA(hashes.SHA256()))
    pdf = storage.get("site", v["pdfUrl"].lstrip("/"))
    assert pdf[:5] == b"%PDF-" and hashlib.sha256(pdf).hexdigest() == json.loads(v["attestationCanonical"])["pdfSha256"]
    assert built["payload"]["actions"][0] == "act.home.ask" and built["payload"]["memory"]["tier"] == "strong"
    assert call("POST", "/v1/places/report", {"lat": 13.2, "lon": 77.2})[0] == 409            # not checked yet


def test_listen_to_a_place_and_a_lake(place, lake):
    s, r = call("POST", "/v1/speech", {"kind": "place", "lat": LAT, "lon": LON, "lang": "en", "persona": "resident"})
    assert s == 200 and r["url"].startswith("/pub/speech/") and r["local"] is True
    assert "Bellandur" in r["text"] and "hectares" not in r["text"].split(".")[0]
    s, again = call("POST", "/v1/speech", {"kind": "place", "lat": LAT, "lon": LON, "lang": "en", "persona": "resident"})
    assert again["url"] == r["url"] and again["cached"] is True
    s, lk = call("POST", "/v1/speech", {"kind": "lake", "lakeId": lake["lakeId"], "lang": "hi"})
    assert s == 200 and lk["url"].endswith(".wav")
    assert call("POST", "/v1/speech", {"kind": "lake", "lakeId": lake["lakeId"], "lang": "ta"})[0] == 400


def test_record_an_rti_request(lake):
    from jalsmriti import ledger
    lid = lake["lakeId"]
    s, r = call("POST", f"/v1/secure/lakes/{lid}/rti",
                {"office": "Public Information Officer, KTCDA", "filedOn": "2026-10-01", "reference": "KTCDA/R/2026/88",
                 "channel": "online", "items": ["survey", "encroachments"]}, CITIZEN)
    assert s == 200 and r["dueBy"] == "2026-10-31"
    assert ledger.entries(lid)[-1]["kind"] == "rti" and ledger.verify(lid)["ok"]
    s, lst = call("GET", f"/v1/lakes/{lid}/rti")
    assert s == 200 and lst["requests"][0]["office"].startswith("Public Information Officer")
    assert call("POST", f"/v1/secure/lakes/{lid}/rti", {"office": "x"}, CITIZEN)[0] == 400
    assert call("POST", f"/v1/secure/lakes/{lid}/rti", {"office": "Somewhere", "filedOn": "2020-01-01"}, CITIZEN)[0] == 400


def test_standing_water_report_from_upload_to_review(aws):
    import evidence_ingest
    s, up = call("POST", "/v1/secure/waterlogging/upload",
                 {"contentType": "image/jpeg", "size": 40_000, "lat": LAT, "lon": LON, "accuracyM": 12, "depth": "knee",
                  "note": "Water across the service road"}, CITIZEN)
    assert s == 200 and up["reportId"].startswith("wl") and up["upload"]["url"] == "/local-upload"
    item = evidence_ingest.process(up["reportId"], photo(LAT, LON))
    assert item["status"] == "live" and item["locationSource"] == "photo"
    s, live = call("GET", "/v1/waterlogging", query={"hours": 168})
    assert s == 200 and any(x["reportId"] == up["reportId"] for x in live["reports"])
    s, near = call("GET", "/v1/waterlogging/near", query={"lat": LAT, "lon": LON, "radius": 1000, "days": 30})
    assert s == 200 and near["count"] >= 1
    s, mine = call("GET", f"/v1/secure/waterlogging/{up['reportId']}", who=CITIZEN)
    assert s == 200 and mine["status"] == "live" and mine["depth"] == "knee"
    assert call("GET", f"/v1/secure/waterlogging/{up['reportId']}", who=claims("u-stranger"))[0] == 404
    # Cedar: the reporter cannot review their own report, an officer cannot review, a verifier of the area can
    s, d = call("POST", f"/v1/secure/waterlogging/{up['reportId']}/review", {"decision": "verified", "note": "Seen on the ground too."}, CITIZEN)
    assert s == 403
    s, d = call("POST", f"/v1/secure/waterlogging/{up['reportId']}/review", {"decision": "verified", "note": "Seen on the ground too."}, OFFICER)
    assert s == 403
    s, q = call("GET", "/v1/secure/console/queue", who=VERIFIER, query={"area": "bengaluru", "type": "waterlogging"})
    assert s == 200 and any(i["reportId"] == up["reportId"] for i in q["items"])
    s, d = call("POST", f"/v1/secure/waterlogging/{up['reportId']}/review", {"decision": "verified", "note": "Seen on the ground too."}, VERIFIER)
    assert s == 200 and d["status"] == "verified"
    s, act = call("GET", "/v1/secure/me/activity", who=CITIZEN)
    assert any(w["reportId"] == up["reportId"] for w in act["waterReports"])
    assert call("POST", "/v1/secure/waterlogging/upload", {"contentType": "image/gif"}, CITIZEN)[0] == 400

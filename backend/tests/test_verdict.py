"""Our read for someone about to rent or buy: a clear verdict with why, pros and cons and what to do if they still like
the place, changed by four quick answers; through the API and in the signed PDF."""
import pytest

from jalsmriti import verdict as V
from test_api import call
from test_features import LAT, LON, place  # noqa: F401  (the stored place fixture)


def stored(tier="some", index=58, occ=0.0, lost300=0.0, built2k=0.0, hand=2.0, bowl=0.4, radar=(), hereC=None,
           vsBuilt=None, area="bengaluru", lat=12.95, lon=77.70):
    return {"lat": lat, "lon": lon, "areaId": area, "memory": {"tier": tier, "index": index},
            "signals": {"occurrenceHere": occ, "lostWaterHa300": lost300, "builtOverWaterHa2000": built2k,
                        "handMin300": hand, "depressionMax300": bowl, "nearestWaterM": 800,
                        "radarSightings": [{"date": d, "haCore": 1.0} for d in radar]},
            "radar": {"scenesChecked": 40}, "heat": {"hereC": hereC, "vsBuiltC": vsBuilt} if hereC else None}


def keys(items):
    return [x["key"] for x in items]


def test_an_old_lake_bed_is_a_clear_no_for_a_ground_floor_buyer():
    p = stored("strong", 79, occ=62, lost300=4.2, built2k=21.4, hand=0.4, bowl=2.1, radar=("2022-09-05", "2024-10-12"))
    v = V.build(p, {"mode": "buy", "floor": "ground", "parking": "1", "vulnerable": "yes"})
    assert v["level"] == "avoid" and v["placePoints"] == 4 + 4 + 2 + 1 + 2 and v["points"] == 13 + 2 + 1 + 1
    assert v["headline"] == {"key": "verdict.head.avoid.buy", "vars": {"home": {"key": "verdict.home.ground"}}}
    assert V.text(v["headline"]) == "Do not buy a ground-floor flat here: the records point to water trouble."
    assert keys(v["why"]) == ["verdict.why.strong", "verdict.con.wasWater", "verdict.con.radar"]
    assert "verdict.con.legal" in keys(v["cons"]) and "verdict.con.basement" in keys(v["cons"])
    assert not set(keys(v["why"])) & set(keys(v["cons"]))                       # nothing said twice
    tips = keys(v["ifStill"])
    assert tips[:3] == ["verdict.if.floor", "verdict.if.parking", "verdict.if.radar"]
    assert "verdict.if.records" in tips and tips[-1] == "verdict.if.follow" and len(tips) <= V.MAX_TIPS
    radar = next(x for x in v["ifStill"] if x["key"] == "verdict.if.radar")
    assert V.text(radar) == "Ask about 12 Oct 2024, 5 Sep 2022 in particular, when radar saw water nearby."


def test_the_floor_changes_the_read_but_never_to_good_to_go():
    p = stored("strong", 79, occ=62, lost300=4.2, built2k=21.4, hand=0.4, bowl=2.1, radar=("2022-09-05",))
    levels = {f: V.build(p, {"floor": f})["level"] for f in V.FLOORS}
    assert levels == {"ground": "avoid", "low": "avoid", "high": "think", "house": "avoid"}   # high: stranded, not flooded
    mild = stored("some", 58, built2k=6.0, hand=0.8)          # scores 3 + 1 + 1 = 5
    assert {f: V.build(mild, {"floor": f})["level"] for f in V.FLOORS} == \
        {"ground": "think", "low": "checks", "high": "checks", "house": "think"}       # exposed: at least checks
    up = V.build(mild, {"floor": "high"})
    assert "verdict.pro.upper" in keys(up["why"] + up["pros"]) and "verdict.if.floor" not in keys(up["ifStill"])


def test_a_dry_high_spot_is_good_to_go():
    p = stored("little", 22, hand=6.5, bowl=0.2, hereC=36.0, vsBuilt=-2.4)
    v = V.build(p, {"mode": "buy", "floor": "ground", "parking": True})
    assert v["level"] == "fine" and v["points"] == 0
    assert V.text(v["headline"]) == "Good to buy a ground-floor flat here: no sign of flood trouble in the records."
    assert keys(v["why"]) == ["verdict.why.little", "verdict.pro.dry", "verdict.pro.high"]
    assert "verdict.con.basement" not in keys(v["cons"])                 # a car downstairs only matters where water goes
    assert keys(v["ifStill"]) == ["verdict.if.follow"]
    assert V.text(v["why"][2]) == "The ground sits 6.5 m above the nearest drainage line."


def test_renting_is_lighter_than_buying_on_an_old_bed():
    p = stored("some", 60, occ=8.0, hand=1.5, bowl=0.6)       # 3 + 3 = 6
    rent, buy = V.build(p, {"mode": "rent"}), V.build(p, {"mode": "buy"})
    assert (rent["points"], buy["points"]) == (6, 7) and rent["level"] == buy["level"] == "think"
    assert "verdict.pro.rent" in keys(rent["pros"] + rent["why"]) and "verdict.con.legal" in keys(buy["cons"] + buy["why"])
    np_ = V.build(stored("some", 60, occ=8.0, area="kathmandu", lat=27.7, lon=85.3), {"mode": "buy"})
    assert "verdict.con.legalNp" in keys(np_["cons"] + np_["why"]) and "verdict.if.recordsNp" in keys(np_["ifStill"])


def test_people_reports_and_the_flood_to_ask_about():
    p = stored("some", 55, hand=1.5, bowl=0.3, area="chennai", lat=12.98, lon=80.22)
    v = V.build(p, {}, reports=4)
    assert v["placePoints"] == 3 + 2 and "verdict.con.reports" in keys(v["why"] + v["cons"])
    ask = next(x for x in v["ifStill"] if x["key"] == "verdict.if.ask")
    assert ask["vars"]["dates"] == ["2023-12-04"]                          # Chennai remembers Michaung
    assert V.text(ask) == "Ask the owner and two neighbours whether water came in during the floods of 4 Dec 2023."


def test_bad_answers_fall_back_to_safe_defaults():
    assert V.answers({"mode": "lease", "floor": "attic", "parking": "maybe", "vulnerable": None}) == \
        {"mode": "rent", "floor": "ground", "parking": False, "vulnerable": False}


def test_verdict_route(place):  # noqa: F811
    s, v = call("GET", "/v1/places/verdict", query={"lat": LAT, "lon": LON, "mode": "buy", "floor": "low",
                                                    "parking": "1", "vulnerable": "0"})
    assert s == 200 and v["answers"] == {"mode": "buy", "floor": "low", "parking": True, "vulnerable": False}
    assert v["level"] == "avoid" and v["why"][0]["key"] == "verdict.why.strong"
    assert call("GET", "/v1/places/verdict", query={"lat": 13.3, "lon": 77.3})[0] == 409     # not checked yet
    assert call("GET", "/v1/places/verdict", query={"lat": 51.5, "lon": -0.1})[0] == 400


def test_signed_report_carries_our_read(place):  # noqa: F811
    import jobs
    from jalsmriti import storage
    ans = {"mode": "buy", "floor": "ground", "parking": True, "vulnerable": False}
    s, r = call("POST", "/v1/places/report", {"lat": LAT, "lon": LON, "lang": "en", "persona": "home", "answers": ans})
    s2, plain = call("POST", "/v1/places/report", {"lat": LAT, "lon": LON, "lang": "en", "persona": "home"})
    assert s == 202 and plain["reportId"] != r["reportId"]                 # the answers make it a different report
    built = jobs.build_report(r["reportId"])
    assert built["payload"]["answers"] == ans and built["payload"]["verdict"]["level"] == "avoid"
    pdf = storage.get("site", built["pdfUrl"].lstrip("/"))
    assert pdf[:5] == b"%PDF-" and 1 <= pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages") <= 3
    from jalsmriti import placereport, store
    block = placereport.verdict_block(store.get(f"RPT#{r['reportId']}"), place, 0, "en")
    assert block["title"] == "Our read" and block["levelLabel"] == "Look elsewhere"
    assert block["headline"].startswith("Do not buy a ground-floor flat here")
    assert block["why"][0].startswith("Strong water memory (79 of 100)") and block["cons"] and block["note"]
    assert placereport.verdict_block({**store.get(f"RPT#{plain['reportId']}")}, place, 0, "en") is None


def test_english_words_match_the_website():
    """The PDF's English fallbacks are the website's English strings (en.ts), word for word."""
    import json
    import re
    from pathlib import Path
    en = Path(__file__).resolve().parents[2] / "web" / "src" / "i18n" / "en.ts"
    found = {m.group(1): json.loads(f'"{m.group(2)}"')
             for m in re.finditer(r'^\s*"(verdict\.[^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$', en.read_text(), re.M)}
    assert {k: found.get(k) for k in V.VERDICT_EN} == V.VERDICT_EN

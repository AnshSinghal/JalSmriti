"""The numbers people see: grades, rain-matched retention, storage and the water-memory index."""
from jalsmriti import metrics


def test_grade_bands_and_parts():
    healthy = metrics.lake_grade(retention_ratio=1.0, built_pct=0, weed_pct=0, lost_pct=0)
    assert healthy["grade"] == "A" and healthy["score"] == 100
    assert {p["key"] for p in healthy["parts"]} == {"water", "bed", "surface", "history"}

    lost = metrics.lake_grade(retention_ratio=0.1, built_pct=30, weed_pct=60, lost_pct=50)
    assert lost["grade"] == "E" and lost["score"] < 35

    # a missing part is left out and the rest rescaled, not counted as zero
    partial = metrics.lake_grade(retention_ratio=None, built_pct=0, weed_pct=None, lost_pct=0)
    assert partial["grade"] == "A" and len(partial["parts"]) == 2
    assert metrics.lake_grade(None, None, None, None)["grade"] is None


def test_grade_thresholds():
    # built over 15 % of the bed = half of the 25 bed points
    g = metrics.lake_grade(retention_ratio=None, built_pct=15, weed_pct=None, lost_pct=None)
    assert g["parts"][0]["points"] == 12.5 and g["score"] == 50 and g["grade"] == "C"


def test_retention_compares_seasons_of_similar_rain():
    series = {y: {"waterHa": 100.0} for y in range(1990, 2011)}
    series.update({2019: {"waterHa": 50.0}, 2020: {"waterHa": 55.0}, 2021: {"waterHa": 45.0}, 2022: {"waterHa": 50.0}})
    rain = {y: 800.0 for y in range(1990, 2011)}
    rain.update({1995: 400.0, 2000: 420.0, 2005: 410.0})        # three dry years
    rain.update({2019: 410.0, 2020: 800.0, 2021: 800.0, 2022: 800.0})
    r = metrics.retention(series, rain, hist_ha=120.0)
    assert 0.45 <= r["ratio"] <= 0.6
    dry = next(p for p in r["pairs"] if p["season"] == 2019)
    assert dry["comparableRain"] and set(dry["comparedWith"]) == {1995, 2000, 2005}


def test_retention_needs_history():
    assert metrics.retention({2020: {"waterHa": 5.0}}, {}, 10.0)["ratio"] is None


def test_storage_range():
    s = metrics.storage_lost(10.0)       # 10 ha x 1-2 m = 100-200 million litres
    assert (s["millionLitresLow"], s["millionLitresHigh"]) == (100, 200)
    assert s["olympicPoolsLow"] == 40


def test_water_memory_index_is_bounded_and_ordered():
    wet = {"depressionMax300": 6.0, "builtOverWater2000": 0.08, "lostWater1000": 0.3, "everWater1000": 0.6, "handMin300": 0.0}
    dry = {"depressionMax300": 0.0, "builtOverWater2000": 0.0, "lostWater1000": 0.0, "everWater1000": 0.0, "handMin300": 25.0}
    hi, lo = metrics.water_memory_index(wet), metrics.water_memory_index(dry)
    assert 0 <= lo["index"] < hi["index"] <= 100
    assert hi["tier"] == "strong" and lo["tier"] == "little"
    # a radar sighting lifts a place with little memory by one tier
    lifted = metrics.water_memory_index({**dry, "radarSightings": [{"date": "2022-09-05"}]})
    assert lifted["tier"] == "some"
    assert metrics.water_memory_index({})["index"] is None


def test_lake_findings_carry_numbers_for_translation():
    summ = {"lostHa": 12.5, "lostPct": 31.2, "replacedBy": {"built": 6.0, "crops": 3.0, "water": 1.0}, "builtHa": 2.5,
            "builtPct": 6.2, "retention": {"ratio": 0.55}, "quality": {"weedPct": 41.0, "date": "2026-10-04"},
            "storageLost": {"millionLitresLow": 125, "millionLitresHigh": 250, "olympicPoolsLow": 50, "olympicPoolsHigh": 100}}
    fs = {f["key"]: f for f in metrics.lake_findings(summ)}
    assert set(fs) >= {"lost", "built", "retention", "weeds", "storage"}
    assert fs["lost"]["vars"]["now"] == {"built": 6.0, "crops": 3.0} and fs["lost"]["vars"]["again"] == 1.0
    assert fs["retention"]["vars"] == {"pct": 55}
    assert all(f["text"] and f["severity"] in ("high", "medium", "low", "info") for f in fs.values())

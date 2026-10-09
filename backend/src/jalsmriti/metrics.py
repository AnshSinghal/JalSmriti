"""Turning measurements into the numbers and words people see: lake health and a place's water memory.

Everything here is a pure function of measurements, so it is unit-tested without any network access and the
rules can change without re-reading imagery.
"""
from __future__ import annotations

import json
import math
import statistics
from functools import lru_cache
from pathlib import Path

from . import config as C

OLYMPIC_POOL_ML = 2.5          # million litres
DEPTH_RANGE_M = (1.0, 2.0)     # assumed average depth of a lost water spread (tanks and urban lakes)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


# ------------------------------------------------------------------------------------------ water series
def season_series(looks: list[dict], px_ha: float) -> dict[int, dict]:
    """Per season: the largest water spread among usable looks (a lake is fullest after the monsoon).

    looks: [{season, date, source, total, valid, clear, water, cloudNear}] for one lake.
    """
    out: dict[int, dict] = {}
    for lk in looks:
        tot = lk["total"]
        if tot <= 0:
            continue
        usable = (lk["valid"] >= C.LOOK_MIN_VALID_FRAC * tot and lk["clear"] >= C.LOOK_MIN_CLEAR_FRAC * tot
                  and not lk.get("cloudNear"))
        if not usable:
            continue
        s = int(lk["season"])
        w = lk["water"] * px_ha
        cur = out.get(s)
        if cur is None or w > cur["waterHa"]:
            out[s] = {"season": s, "waterHa": round(w, 2), "date": lk["date"], "source": lk["source"],
                      "looks": (cur["looks"] + 1) if cur else 1}
        else:
            cur["looks"] += 1
    return dict(sorted(out.items()))


def retention(series: dict[int, dict], rain: dict[int, float], hist_ha: float,
              recent_n: int = 4, historic_until: int = 2010, tol: float = 0.25) -> dict:
    """How much water the lake holds now compared with itself in past years of similar monsoon rain."""
    seasons = sorted(series)
    if not seasons:
        return {"ratio": None, "why": "no clear satellite looks"}
    recent = [s for s in seasons if s > historic_until][-recent_n:]
    historic = [s for s in seasons if s <= historic_until]
    if not recent or len(historic) < 2:
        return {"ratio": None, "recent": recent, "why": "not enough clear looks before 2011 to compare"}
    hist_w = {s: series[s]["waterHa"] for s in historic}
    ratios, pairs = [], []
    for r in recent:
        wr = series[r]["waterHa"]
        rr = rain.get(r)
        comps = [h for h in historic if rr and rain.get(h) and abs(rain[h] / rr - 1) <= tol]
        base_seasons = comps if len(comps) >= 2 else historic
        base = statistics.median(hist_w[h] for h in base_seasons)
        if base <= max(0.3, 0.02 * hist_ha):
            continue   # the lake was nearly dry in those years too: no basis for a ratio
        ratios.append(wr / base)
        pairs.append({"season": r, "waterHa": round(wr, 1), "rainMm": rr, "comparedWith": base_seasons[:8],
                      "comparableRain": len(comps) >= 2, "thenWaterHa": round(base, 1)})
    if not ratios:
        return {"ratio": None, "recent": recent, "why": "the lake held little water in the past years compared"}
    return {"ratio": round(statistics.median(ratios), 3), "pairs": pairs}


# ------------------------------------------------------------------------------------------ lake grade
def lake_grade(retention_ratio: float | None, built_pct: float | None, weed_pct: float | None,
               lost_pct: float | None) -> dict:
    """A-E grade from four parts, each worth 25 points; unknown parts are left out and the rest rescaled."""
    parts = []
    if retention_ratio is not None:
        parts.append(("water", 25 * _clamp(retention_ratio), "Water held now vs. past years of similar rain"))
    if built_pct is not None:
        parts.append(("bed", 25 * (1 - _clamp(built_pct / 30.0)), "Old lake bed still open (not built over)"))
    if weed_pct is not None:
        parts.append(("surface", 25 * (1 - _clamp(weed_pct / 60.0)), "Open water surface (not choked by weeds)"))
    if lost_pct is not None:
        parts.append(("history", 25 * (1 - _clamp(lost_pct / 50.0)), "Water spread kept since 1984"))
    if not parts:
        return {"grade": None, "score": None, "parts": []}
    score = 100 * sum(p[1] for p in parts) / (25 * len(parts))
    grade = next(g for lim, g in C.GRADE_BANDS if score >= lim)
    return {"grade": grade, "score": round(score), "parts": [{"key": k, "points": round(v, 1), "label": lab}
                                                              for k, v, lab in parts]}


def storage_lost(lost_ha: float) -> dict:
    lo, hi = (lost_ha * d * 10.0 for d in DEPTH_RANGE_M)   # 1 ha x 1 m = 10 million litres
    return {"millionLitresLow": round(lo), "millionLitresHigh": round(hi),
            "olympicPoolsLow": round(lo / OLYMPIC_POOL_ML), "olympicPoolsHigh": round(hi / OLYMPIC_POOL_ML),
            "assumedDepthM": list(DEPTH_RANGE_M)}


def lake_summary(body: dict, jrc_stats: dict, land: dict, series: dict[int, dict], rain: dict[int, float],
                 latest: dict | None) -> dict:
    """Everything the lake page shows, from per-lake statistics.

    jrc_stats: {histPx, permanentPx, seasonalPx, lostPx, newPx, meanOcc, typicalPx}
    land: {pxHa, builtPxByYear: {year: px}, lostNow: {class: px}, worldcoverBuiltPx}
    latest: {date, openWaterPx, weedPx, typicalPx, ndci, turbidity, pxHa} or None
    """
    pxha = land["pxHa"]
    hist_ha = jrc_stats["histPx"] * pxha
    lost_ha = jrc_stats["lostPx"] * pxha
    lost_pct = 100 * lost_ha / hist_ha if hist_ha else None
    built_by_year = {int(y): round(px * pxha, 2) for y, px in land.get("builtPxByYear", {}).items()}
    last_year = max(built_by_year) if built_by_year else None
    built_ha = land.get("builtPersistentPx", 0) * pxha if "builtPersistentPx" in land else \
        (built_by_year.get(last_year) if last_year else None)
    built_pct = 100 * built_ha / hist_ha if (hist_ha and built_ha is not None) else None
    replaced = {k: round(v * pxha, 2) for k, v in land.get("lostNow", {}).items()}
    ret = retention(series, rain, hist_ha)
    weed_pct = None
    quality = None
    if latest and latest.get("typicalPx"):
        lp = latest["pxHa"]
        open_ha = latest["openWaterPx"] * lp
        weed_ha = latest["weedPx"] * lp
        denom = open_ha + weed_ha
        weed_pct = 100 * weed_ha / denom if denom > 0.2 else None
        quality = {"date": latest["date"], "openWaterHa": round(open_ha, 1), "weedHa": round(weed_ha, 1),
                   "weedPct": _r(weed_pct), "ndci": _r(latest.get("ndci"), 3), "turbidity": _r(latest.get("turbidity"), 3),
                   "algaeSign": (latest.get("ndci") or -1) > 0.1, "dryNow": open_ha + weed_ha < 0.05 * hist_ha}
    waters = [v["waterHa"] for v in series.values()]
    peak = sorted(waters)[int(0.9 * (len(waters) - 1))] if waters else None
    recent = [series[s]["waterHa"] for s in sorted(series)[-3:]] if series else []
    grade = lake_grade(ret.get("ratio"), built_pct, weed_pct, lost_pct)
    return {
        "historicHa": round(hist_ha, 1), "typicalHa": round(jrc_stats.get("typicalPx", 0) * pxha, 1),
        "permanentHa": round(jrc_stats.get("permanentPx", 0) * pxha, 1),
        "seasonalHa": round(jrc_stats.get("seasonalPx", 0) * pxha, 1),
        "lostHa": round(lost_ha, 1), "lostPct": _r(lost_pct), "newHa": round(jrc_stats.get("newPx", 0) * pxha, 1),
        "meanOccurrence": _r(jrc_stats.get("meanOcc")),
        "builtByYear": built_by_year, "builtHa": _r(built_ha), "builtPct": _r(built_pct),
        "builtChangeHa": _r(built_by_year[last_year] - built_by_year[min(built_by_year)]) if len(built_by_year) > 1 else None,
        "worldcoverBuiltHa": _r(land.get("worldcoverBuiltPx", 0) * pxha) if "worldcoverBuiltPx" in land else None,
        "replacedBy": replaced, "storageLost": storage_lost(lost_ha),
        "series": [{**v, "rainMm": rain.get(s)} for s, v in series.items()],
        "peakWaterHa": _r(peak), "recentWaterHa": _r(statistics.median(recent)) if recent else None,
        "retention": ret, "quality": quality, "grade": grade,
    }


def lake_findings(lake: dict) -> list[dict]:
    """Findings, most important first: a key and numbers for the UI's translated templates, plus English text."""
    out = []
    m = lake
    if m.get("lostHa") and m["lostHa"] >= 0.5:
        rb = dict(m.get("replacedBy") or {})
        again = rb.pop("water", 0) or 0
        top = [(k, v) for k, v in sorted(rb.items(), key=lambda kv: -kv[1]) if v >= 0.3][:3]
        what = ", ".join(f"{k} {v:g} ha" for k, v in top)
        text = (f"{m['lostHa']:g} ha of water seen in 1984-2020 had gone by 2020 ({m.get('lostPct'):g}% of its historic spread)"
                + (f"; that ground is now {what}" if what else ""))
        if again >= 0.3:
            text += f"; {again:g} ha of it held water again in 2023"
        out.append({"key": "lost", "severity": "high" if (m.get("lostPct") or 0) >= 25 else "medium", "text": text + ".",
                    "vars": {"lostHa": m["lostHa"], "lostPct": m.get("lostPct"), "now": dict(top), "again": round(again, 1)}})
    if m.get("builtHa") and m["builtHa"] >= 0.3:
        out.append({"key": "built", "severity": "high" if (m.get("builtPct") or 0) >= 10 else "medium",
                    "text": f"{m['builtHa']:g} ha of the old lake bed is built over ({m.get('builtPct'):g}%).",
                    "vars": {"builtHa": m["builtHa"], "builtPct": m.get("builtPct")}})
    r = (m.get("retention") or {}).get("ratio")
    if r is not None:
        sev = "high" if r < 0.5 else "medium" if r < 0.8 else "low"
        out.append({"key": "retention", "severity": sev,
                    "text": f"In recent seasons it held {round(100 * r)}% of the water it held in past years of similar rain.",
                    "vars": {"pct": round(100 * r)}})
    q = m.get("quality") or {}
    if q.get("weedPct") is not None and q["weedPct"] >= 20:
        out.append({"key": "weeds", "severity": "high" if q["weedPct"] >= 50 else "medium",
                    "text": f"{q['weedPct']:g}% of the water surface was covered by floating weeds on {q['date']}.",
                    "vars": {"pct": q["weedPct"], "date": q["date"]}})
    if q.get("algaeSign"):
        out.append({"key": "algae", "severity": "medium",
                    "text": f"The water's colour on {q['date']} suggests an algal bloom (often a sign of sewage).",
                    "vars": {"date": q["date"]}})
    sl = m.get("storageLost") or {}
    if sl.get("millionLitresHigh"):
        out.append({"key": "storage", "severity": "info",
                    "text": f"Lost storage is roughly {sl['millionLitresLow']:,}-{sl['millionLitresHigh']:,} million litres "
                            f"(about {sl['olympicPoolsLow']:,}-{sl['olympicPoolsHigh']:,} Olympic pools) if it was 1-2 m deep.",
                    "vars": {"low": sl["millionLitresLow"], "high": sl["millionLitresHigh"], "poolsLow": sl["olympicPoolsLow"],
                             "poolsHigh": sl["olympicPoolsHigh"]}})
    return out


# ------------------------------------------------------------------------------------------ place
@lru_cache(maxsize=1)
def _reference() -> dict:
    p = Path(__file__).resolve().parent / "data" / "place_reference.json"
    return json.loads(p.read_text())


def _pct_rank(value: float, sorted_ref: list[float]) -> float:
    if not sorted_ref:
        return 0.5
    lo = sum(1 for v in sorted_ref if v < value)
    eq = sum(1 for v in sorted_ref if v == value)
    return (lo + 0.5 * eq) / len(sorted_ref)


PLACE_SIGNALS = (  # key, higher-is-more-memory
    ("depressionMax300", True), ("builtOverWater2000", True), ("lostWater1000", True), ("everWater1000", True),
    ("handMin300", False),
)


def water_memory_index(sig: dict) -> dict:
    """0-100: the mean percentile of five signals against ordinary built-up places in four Indian cities.

    Equal weights, not fitted. In validation (docs/validation.md) flooded localities scored higher than random
    built-up places in 68% of pairs (AUC 0.68). It describes history and terrain; it is not a flood forecast.
    """
    ref = _reference()["builtUpRandom"]
    ranks = {}
    for key, higher in PLACE_SIGNALS:
        v = sig.get(key)
        if v is None:
            continue
        pr = _pct_rank(float(v), ref[key])
        ranks[key] = pr if higher else 1 - pr
    if not ranks:
        return {"index": None, "tier": "unknown", "ranks": {}}
    idx = 100 * sum(ranks.values()) / len(ranks)
    sightings = len(sig.get("radarSightings") or [])
    tier = "strong" if idx >= 70 else "some" if idx >= 45 else "little"
    if sightings and tier == "little":
        tier = "some"
    elif sightings >= 2 and tier == "some":
        tier = "strong"
    return {"index": round(idx), "tier": tier, "ranks": {k: round(v, 3) for k, v in ranks.items()},
            "radarSightings": sightings}


def place_findings(sig: dict) -> list[dict]:
    out = []

    def add(key, severity, text, **vars):
        out.append({"key": key, "severity": severity, "text": text, "vars": vars})

    if sig.get("occurrenceHere", 0) >= C.JRC_OCCURRENCE_MIN:
        add("wasWater", "high", f"Satellites saw water on this very spot in {sig['occurrenceHere']:g}% of looks between 1984 and 2020.",
            pct=sig["occurrenceHere"])
    if sig.get("lostWaterHa300", 0) >= 0.3:
        add("lostNear", "high", f"{sig['lostWaterHa300']:g} ha of water that existed within 300 m has disappeared since 1984.",
            ha=sig["lostWaterHa300"])
    if sig.get("builtOverWaterHa2000", 0) >= 1:
        add("builtOver", "medium", f"Within 2 km, {sig['builtOverWaterHa2000']:g} ha of old water-body beds are now built over.",
            ha=sig["builtOverWaterHa2000"])
    if sig.get("depressionMax300", 0) >= 1.0:
        add("bowl", "medium", f"The ground within 300 m forms a bowl up to {sig['depressionMax300']:.1f} m deep where rain can pond.",
            m=round(sig["depressionMax300"], 1))
    if sig.get("handMin300") is not None and sig["handMin300"] <= 1.0:
        add("lowDrain", "medium", "Part of this place sits less than 1 m above the nearest natural drainage line.")
    for s in (sig.get("radarSightings") or [])[:6]:
        add("radar", "high", f"Radar saw unusual standing water within 300 m on {s['date']} ({s['haCore']:g} ha).",
            date=s["date"], ha=s["haCore"])
    if sig.get("nearestWaterM") is not None and sig["nearestWaterM"] <= 500 and not out:
        add("nearWater", "info", f"The nearest historic water body is {round(sig['nearestWaterM'])} m away.", m=round(sig["nearestWaterM"]))
    if not out:
        add("quiet", "low", "No strong water history was found here in 37 years of satellite records.")
    return out

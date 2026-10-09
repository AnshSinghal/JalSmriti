"""What to do this week: concrete steps for one place, from what its records show.

Two lists, because the same street asks different things of different people:
  home      someone about to rent or buy here
  resident  someone who already lives here
Each step is {"key": "act....", "vars": {...}}; the website, the signed report, the narration and the rain email
turn the key into words in the reader's language (strings.action_text), so the advice is written once.
The rules use only the stored place check, so the page, the PDF and the voice always give the same steps.
"""
from __future__ import annotations

from . import areas as A
from . import geo

MAX_STEPS = 7
HOT_GROUND_C = 42.0       # late-morning summer ground temperature from which heat advice is added


def _facts(result: dict) -> dict:
    sig = result.get("signals") or {}
    tier = (result.get("memory") or {}).get("tier") or "unknown"
    sightings = sorted((sig.get("radarSightings") or []), key=lambda s: s.get("date", ""), reverse=True)
    lat, lon = result.get("lat"), result.get("lon")
    area = A.AREAS.get(result.get("areaId") or "")
    country = area.country if area else (geo.country(float(lat), float(lon)) if lat is not None and lon is not None else "IN")
    heat = result.get("heat") or {}
    here = heat.get("hereC")
    return {
        "tier": tier,
        "dates": [s["date"] for s in sightings[:3] if s.get("date")],
        "low": sig.get("handMin300") is not None and float(sig["handMin300"]) <= 1.0,
        "bowl": float(sig.get("depressionMax300") or 0) >= 1.0,
        "oldBeds": float(sig.get("builtOverWaterHa2000") or 0) >= 1 or float(sig.get("lostWaterHa300") or 0) >= 0.3
                   or float(sig.get("occurrenceHere") or 0) >= 5,
        "nearWater": sig.get("nearestWaterM") is not None and float(sig["nearestWaterM"]) <= 1000,
        "country": country,
        "area": area.id if area else None,
        "hot": here is not None and (float(here) >= HOT_GROUND_C or bool(heat.get("hotter"))),
        "hereC": round(float(here)) if here is not None else None,
    }


def _home(f: dict) -> list[dict]:
    out = []
    add = lambda key, **vars: out.append({"key": key, "vars": vars})
    wet = f["tier"] in ("strong", "some")
    add("act.home.ask")
    if f["dates"]:
        add("act.home.radar", dates=f["dates"])
    if f["tier"] == "strong" or f["low"] or f["bowl"]:
        add("act.home.floor")
    if wet:
        add("act.home.plinth")
    if f["oldBeds"]:
        add("act.home.recordsNp" if f["country"] == "NP" else "act.home.records")
        if f["area"] == "hyderabad":
            add("act.home.hydraa")
    if f["hot"]:
        add("act.home.heat", temp=f["hereC"])
    add("act.home.insuranceNp" if f["country"] == "NP" else "act.home.insurance")
    add("act.home.report")
    add("act.home.follow")
    return out


def _resident(f: dict) -> list[dict]:
    out = []
    add = lambda key, **vars: out.append({"key": key, "vars": vars})
    wet = f["tier"] in ("strong", "some")
    add("act.res.follow")
    if wet:
        add("act.res.before")
    if f["dates"]:
        add("act.res.radar", dates=f["dates"])
    add("act.res.drain")
    if f["tier"] == "strong":
        add("act.res.route")
    add("act.res.report")
    if f["hot"]:
        add("act.res.heat", temp=f["hereC"])
    if f["oldBeds"] or f["nearWater"]:
        add("act.res.lake")
    add("act.res.alertsNp" if f["country"] == "NP" else "act.res.alerts")
    return out


def _cap(steps: list[dict], keep_last: tuple[str, ...]) -> list[dict]:
    """At most MAX_STEPS, dropping from the middle so the steps that close the list (report, follow) stay."""
    if len(steps) <= MAX_STEPS:
        return steps
    tail = [s for s in steps if s["key"] in keep_last]
    head = [s for s in steps if s["key"] not in keep_last][:MAX_STEPS - len(tail)]
    return head + tail


def for_place(result: dict) -> dict:
    """{"home": [...], "resident": [...]} for a stored place check."""
    f = _facts(result)
    return {"home": _cap(_home(f), ("act.home.report", "act.home.follow")),
            "resident": _cap(_resident(f), ("act.res.report",))}

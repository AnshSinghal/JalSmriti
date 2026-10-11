"""Why a lake is in the state it is in, what that costs, and what would help: read from its satellite record.

causes(): each likely cause with the numbers that point to it, most serious first:
  encroachment  buildings and roads on the old lake bed (Impact Observatory land cover and ESA WorldCover built-up
                over the JRC water history)
  drying        water spread that turned into bare ground: filled with debris or silt, or drying out
  overgrown     water spread that now shows as plants from space: scrub, fields, or water hidden under weed mats
                (land-cover maps often call a thick mat of water hyacinth "crops" or "rangeland", so the page says so)
  inflow        it holds much less water now than in past years of similar monsoon rain (Landsat/Sentinel-2 series)
  sewage        floating weeds or an algal colour on the latest Sentinel-2 image: nutrients, usually sewage
  holding       none of these: the lake is holding up
actions(): what residents can do here (each tied to something on the page) and what to ask the authorities for.
benefit(): what protecting or restoring it brings back, in numbers.

These are readings of satellite data, not findings of fact about anyone: the page says what each one rests on, and a
site visit or the official records (the RTI request) settle it. Keys and numbers go to the website, which words them
in the reader's language; `text` is the English wording for the PDF and for anyone reading the API.
"""
from __future__ import annotations

SEVERITY = {"high": 0, "medium": 1, "low": 2}
RESIDENT_ACTIONS = ("photo", "rti", "watch", "dossier", "home", "inflow", "sewage", "group")
AUTHORITY_ACTIONS = ("survey", "remove", "channels", "debris", "stp", "weeds", "bed", "monitor")


def _n(v, nd: int = 1):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _first_built_year(by_year: dict | None, min_ha: float = 0.3) -> int | None:
    years = sorted((int(y), float(v)) for y, v in (by_year or {}).items() if v is not None)
    return next((y for y, v in years if v >= min_ha), None)


def causes(m: dict) -> list[dict]:
    """Likely causes for a lake's metrics (lake["metrics"]), most serious first."""
    m = m or {}
    rb = m.get("replacedBy") or {}
    built_bed = max(float(m.get("builtHa") or 0), float(rb.get("built") or 0))
    built_pct = float(m.get("builtPct") or 0)
    lost, lost_pct = float(m.get("lostHa") or 0), float(m.get("lostPct") or 0)
    bare, veg, crops = float(rb.get("bare") or 0), float(rb.get("vegetation") or 0), float(rb.get("crops") or 0)
    ret = m.get("retention") or {}
    ratio = ret.get("ratio")
    q = m.get("quality") or {}
    weed, algae = q.get("weedPct"), bool(q.get("algaeSign"))
    out = []
    if built_bed >= 0.3:
        since = _first_built_year(m.get("builtByYear"))
        out.append({"key": "encroachment", "severity": "high" if built_pct >= 10 or built_bed >= 5 else "medium",
                    "vars": {"ha": _n(built_bed), "pct": _n(built_pct), "since": since,
                             "change": _n(m.get("builtChangeHa"))},
                    "text": f"Buildings and roads cover {built_bed:.1f} ha of the old lake bed ({built_pct:.1f}%)"
                            + (f", first seen around {since}" if since else "") + ". Built-up ground cannot hold "
                            "monsoon water, which then floods the streets around it."})
    big = lost_pct >= 25
    if lost >= 0.5 and bare >= 0.5:
        out.append({"key": "drying", "severity": "high" if big and bare >= 0.3 * lost else "medium",
                    "vars": {"ha": _n(bare), "lostPct": _n(lost_pct)},
                    "text": f"{bare:.1f} ha where water used to be is now bare ground: the bed is being filled with "
                            "debris or silt, or the lake is drying out because its inflow channels are cut or blocked."})
    if lost >= 0.5 and veg + crops >= 0.5:
        weedy = weed is not None and weed >= 40
        out.append({"key": "overgrown", "severity": "high" if big else "medium",
                    "vars": {"ha": _n(veg + crops), "crops": _n(crops), "veg": _n(veg), "weedy": weedy,
                             "lostPct": _n(lost_pct)},
                    "text": f"{veg + crops:.1f} ha of its old water spread now shows as plants from space: scrub, "
                            "fields, or water hidden under a mat of weeds"
                            + (" (likely here: the open water is choked with weeds too)" if weedy else "") + "."})
    if ratio is not None and ratio < 0.8:
        pairs = ret.get("pairs") or []
        last = pairs[-1] if pairs else {}
        out.append({"key": "inflow", "severity": "high" if ratio < 0.5 else "medium",
                    "vars": {"pct": round(100 * ratio), "season": last.get("season"), "now": _n(last.get("waterHa")),
                             "then": _n(last.get("thenWaterHa")), "rainMm": _n(last.get("rainMm"), 0),
                             "sameRain": bool(last.get("comparableRain"))},
                    "text": f"In recent monsoons it held only {round(100 * ratio)}% of the water it held in past years "
                            "of similar rain: less water is reaching it, or it is being drained."})
    if (weed is not None and weed >= 20) or algae:
        out.append({"key": "sewage", "severity": "high" if (weed or 0) >= 50 else "medium",
                    "vars": {"weedPct": _n(weed), "algae": algae, "date": q.get("date")},
                    "text": (f"Floating weeds covered {weed:.0f}% of the water on {q.get('date')}" if weed and weed >= 20
                             else f"The water's colour on {q.get('date')} suggests an algal bloom")
                            + ": weeds and algae feed on nutrients, usually untreated sewage."})
    if not out:
        out.append({"key": "holding", "severity": "low",
                    "vars": {"lostPct": _n(lost_pct), "grade": (m.get("grade") or {}).get("grade")},
                    "text": "None of the usual signs of harm shows in the satellite record: the lake is holding up. "
                            "Keeping it that way means protecting its edges and inflow channels."})
    out.sort(key=lambda c: SEVERITY[c["severity"]])
    return out


def actions(found: list[dict]) -> dict:
    """{"residents": [...], "authorities": [...]}: action keys for what was found, in order of use."""
    keys = {c["key"] for c in found}
    residents = ["photo", "rti", "watch", "dossier"]
    if keys & {"encroachment", "drying"}:
        residents.append("home")
    if keys & {"drying", "overgrown", "inflow"}:
        residents.append("inflow")
    if "sewage" in keys:
        residents.append("sewage")
    residents.append("group")
    authorities = []
    if keys & {"encroachment", "drying", "overgrown"}:
        authorities.append("survey")
    if "encroachment" in keys:
        authorities.append("remove")
    if keys & {"drying", "overgrown", "inflow"}:
        authorities.append("channels")
    if "drying" in keys:
        authorities.append("debris")
    if "sewage" in keys:
        authorities += ["stp", "weeds"]
    if "overgrown" in keys and "sewage" not in keys:
        authorities.append("bed")
    authorities.append("monitor")
    return {"residents": residents, "authorities": authorities}


def benefit(m: dict) -> dict | None:
    """What restoring the lost water spread would bring back: storage for monsoon water (1-2 m deep)."""
    sl = (m or {}).get("storageLost") or {}
    if not sl.get("millionLitresHigh") or float((m or {}).get("lostHa") or 0) < 0.5:
        return None
    return {"lostHa": _n(m.get("lostHa")), "millionLitresLow": sl.get("millionLitresLow"),
            "millionLitresHigh": sl.get("millionLitresHigh"), "poolsLow": sl.get("olympicPoolsLow"),
            "poolsHigh": sl.get("olympicPoolsHigh")}


def lake_insights(lake: dict) -> dict:
    found = causes(lake.get("metrics") or {})
    return {"causes": found, "actions": actions(found), "benefit": benefit(lake.get("metrics") or {})}

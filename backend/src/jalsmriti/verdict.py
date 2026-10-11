"""Our read for someone about to rent or buy a home: a clear verdict, why, pros and cons, and what to do if they still
like the place, personalised by four quick answers.

  mode        rent | buy
  floor       ground | low (1st-2nd) | high (3rd or above) | house (independent house)
  parking     a car in basement parking (true / false)
  vulnerable  elderly people or small children at home (true / false)

The verdict rests on the stored place check (water memory, terrain, radar, summer heat), the standing water people
reported within 1 km in the last year, and the area's flood history; the answers change how much each fact matters
for this family. Points:

  water memory      strong 4, some 3, little 0, unknown 1
  this very spot    was water in >= 5% of satellite looks 1984-2020: +3 (>= 20%: +4)
  terrain           low ground (<= 1 m above the nearest drainage line) or a hollow >= 1 m deep within 300 m: +1,
                    both: +2, and a hollow >= 3 m deep: +1 more
  old lakes         >= 5 ha built over within 2 km: +1
  radar             unusual standing water seen nearby: +2 (3 or more passes: +3)
  people            standing water reported within 1 km in the last year: +1 (3 or more: +2)
  floor             ground 0, low -2, high -3, independent house +1 (never below 0)
  basement parking  +2 and elderly or small children +1, once the place scores 3 or more
  buying            +1 where an old lake bed is at or near the spot (legal risk, and a long commitment)

  avoid >= 8      think twice 5-7      fine with checks 2-4      good to go <= 1

A place that scores 3 or more on its own is never "good to go", whatever the floor: the street, the basement, the
power and the water supply still go under. A flat on the third floor or above is never "look elsewhere": the family
can be stranded, not flooded, so it is "think twice" at most.

Every line is {"key": "verdict....", "vars": {...}} so the website, the signed PDF and the narration word it in the
reader's language from one rule set. It is a reading of open data, not a survey, a legal opinion or financial advice,
and it says so.
"""
from __future__ import annotations

from . import areas as A
from . import geo

MODES = ("rent", "buy")
FLOORS = ("ground", "low", "high", "house")
LEVELS = (("avoid", 8), ("think", 5), ("checks", 2), ("fine", -99))
TIER_POINTS = {"strong": 4, "some": 3, "little": 0}
FLOOR_POINTS = {"ground": 0, "low": -2, "high": -3, "house": 1}
EXPOSED = 3              # from this score, how the family lives there starts to matter
MAX_TIPS = 6
# the flood residents of an area remember best, when it is not the area's latest mapped event
FLOOD_ASK = {"chennai": "2023-12-04", "hyderabad": "2020-10-13"}

VERDICT_EN = {
    "verdict.title": "Our read",
    "verdict.level.avoid": "Look elsewhere",
    "verdict.level.think": "Think twice",
    "verdict.level.checks": "Fine, with checks",
    "verdict.level.fine": "Good to go",
    "verdict.home.ground": "a ground-floor flat",
    "verdict.home.low": "a flat on the first or second floor",
    "verdict.home.high": "a flat on the third floor or above",
    "verdict.home.house": "an independent house",
    "verdict.head.avoid.rent": "Look for another place to rent: {home} here is likely to take water.",
    "verdict.head.avoid.buy": "Do not buy {home} here: the records point to water trouble.",
    "verdict.head.think.rent": "Think twice before renting {home} here.",
    "verdict.head.think.buy": "Think twice before buying {home} here.",
    "verdict.head.checks.rent": "Fine to rent {home} here, after a few checks.",
    "verdict.head.checks.buy": "Fine to buy {home} here, after a few checks.",
    "verdict.head.fine.rent": "Good to rent {home} here: no sign of flood trouble in the records.",
    "verdict.head.fine.buy": "Good to buy {home} here: no sign of flood trouble in the records.",
    "verdict.why": "Why",
    "verdict.why.strong": "Strong water memory ({n} of 100): only about 1 in 6 built-up places in the cities we tested score this high.",
    "verdict.why.some": "Some water memory ({n} of 100): 85% of the flooded localities we tested scored at least this, against 58% of random built-up places.",
    "verdict.why.little": "Little water memory ({n} of 100): only 15% of the flooded localities we tested scored this low.",
    "verdict.why.unknown": "The water memory of this spot could not be read.",
    "verdict.pros": "In its favour",
    "verdict.cons": "Against it",
    "verdict.ifStill": "If you still like it",
    "verdict.con.wasWater": "This very spot was water in {pct}% of satellite looks from 1984 to 2020.",
    "verdict.con.lostNear": "{ha} ha of water within 300 m has disappeared since 1984.",
    "verdict.con.builtOver": "{ha} ha of old lakes and tanks within 2 km are now built over, and rain still flows to where they were.",
    "verdict.con.bowl": "It sits in a hollow up to {m} m deep, so rain runs towards it.",
    "verdict.con.low": "The ground is less than 1 m above the nearest drainage line.",
    "verdict.con.radar": "Radar saw unusual standing water nearby on {dates}.",
    "verdict.con.reports": "People reported standing water within 1 km {n} times in the last year.",
    "verdict.con.reportsOne": "People reported standing water within 1 km once in the last year.",
    "verdict.con.hot": "Summer mornings reach {c} °C at ground level here.",
    "verdict.con.ground": "Water gets into ground-floor homes first.",
    "verdict.con.basement": "Basements flood first in a downpour, and cars parked there are the most common loss.",
    "verdict.con.vulnerable": "Elderly people and small children are the hardest to move if water rises at night.",
    "verdict.con.legal": "Buying on or next to an old lake bed carries legal risk: homes inside a lake's full tank level or buffer, or over storm-water drains, have been demolished in Indian cities (Hyderabad 2024-25, Bengaluru 2022).",
    "verdict.con.legalNp": "Buying on or next to an old lake bed or river bank carries legal risk: such land can be public land, and buildings on it can be removed.",
    "verdict.pro.dry": "This spot was never water in 40 years of satellite images.",
    "verdict.pro.high": "The ground sits {m} m above the nearest drainage line.",
    "verdict.pro.flat": "There is no hollow around it for rain to collect in.",
    "verdict.pro.upper": "Upstairs, floodwater rarely gets into the home itself.",
    "verdict.pro.cool": "Summer mornings here are {c} °C cooler than the built-up ground around it.",
    "verdict.pro.rent": "Renting keeps you free to move if a monsoon goes badly.",
    "verdict.pro.fewSigns": "Only {n} of the usual warning signs shows here.",
    "verdict.if.floor": "Take the first floor or above.",
    "verdict.if.parking": "Avoid basement parking, or move the car to higher ground when heavy rain is forecast.",
    "verdict.if.ask": "Ask the owner and two neighbours whether water came in during the floods of {dates}.",
    "verdict.if.askMonsoons": "Ask the owner and two neighbours whether water came in during the last three monsoons.",
    "verdict.if.radar": "Ask about {dates} in particular, when radar saw water nearby.",
    "verdict.if.plinth": "Check that the entrance and the plinth are well above the road: at least three steps.",
    "verdict.if.records": "Before paying anything, check the land's survey number against the lake's full tank level and buffer in the revenue records.",
    "verdict.if.recordsNp": "Before paying anything, check the land's ownership and its distance from rivers and ponds with the municipality.",
    "verdict.if.insurance": "Get home insurance that covers floods, and keep documents and electronics off the floor.",
    "verdict.if.vulnerable": "Plan how you would move elderly people or children upstairs or out at night.",
    "verdict.if.visit": "Visit once after heavy rain and look at the street and the basement.",
    "verdict.if.follow": "Follow this place to get a heads-up before heavy rain.",
    "verdict.note": "Our read of open satellite records and your answers: not a survey, a legal opinion or financial advice. Visit after heavy rain, ask neighbours and check the records before you sign.",
}


def answers(raw: dict | None) -> dict:
    """The four answers, with safe defaults (renting a ground-floor flat, no basement car, no one vulnerable)."""
    raw = raw or {}

    def flag(v) -> bool:
        return v is True or str(v).strip().lower() in ("1", "true", "yes", "y", "on")
    return {"mode": raw.get("mode") if raw.get("mode") in MODES else "rent",
            "floor": raw.get("floor") if raw.get("floor") in FLOORS else "ground",
            "parking": flag(raw.get("parking")), "vulnerable": flag(raw.get("vulnerable"))}


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def facts(place: dict, reports: int = 0) -> dict:
    """What the verdict reads from a stored place check."""
    sig = place.get("signals") or {}
    memory = place.get("memory") or {}
    sightings = sorted(sig.get("radarSightings") or [], key=lambda s: s.get("date", ""), reverse=True)
    lat, lon = _f(place.get("lat")), _f(place.get("lon"))
    area = A.AREAS.get(place.get("areaId") or "")
    country = area.country if area else (geo.country(lat, lon) if lat is not None and lon is not None else "IN")
    events = sorted((area.events if area else []) or [], key=lambda e: e.get("date", ""), reverse=True)
    heat = place.get("heat") or {}
    return {
        "tier": memory.get("tier") or "unknown", "index": memory.get("index"),
        "occ": _f(sig.get("occurrenceHere")) or 0.0, "lost300": _f(sig.get("lostWaterHa300")) or 0.0,
        "built2k": _f(sig.get("builtOverWaterHa2000")) or 0.0, "hand": _f(sig.get("handMin300")),
        "bowl": _f(sig.get("depressionMax300")) or 0.0, "nearWaterM": _f(sig.get("nearestWaterM")),
        "radar": [s["date"] for s in sightings if s.get("date")],
        "scenes": int((place.get("radar") or {}).get("scenesChecked") or 0),
        "reports": int(reports or 0), "country": country,
        "event": FLOOD_ASK.get(area.id if area else "") or (events[0]["date"] if events else None),
        "hereC": _f(heat.get("hereC")), "vsBuiltC": _f(heat.get("vsBuiltC")), "hotter": bool(heat.get("hotter")),
    }


def score(f: dict) -> int:
    """Points from the place alone (before the family's answers)."""
    s = TIER_POINTS.get(f["tier"], 1)
    s += 4 if f["occ"] >= 20 else 3 if f["occ"] >= 5 else 0
    low, hollow = f["hand"] is not None and f["hand"] <= 1.0, f["bowl"] >= 1
    s += 2 if (low and hollow) else 1 if (low or hollow) else 0
    s += 1 if f["bowl"] >= 3 else 0
    s += 1 if f["built2k"] >= 5 else 0
    s += 3 if len(f["radar"]) >= 3 else 2 if f["radar"] else 0
    s += 2 if f["reports"] >= 3 else 1 if f["reports"] else 0
    return s


def old_bed(f: dict) -> bool:
    return f["occ"] >= 5 or f["lost300"] >= 0.3 or f["built2k"] >= 5


def level_for(points: int) -> str:
    return next(name for name, low in LEVELS if points >= low)


def build(place: dict, raw_answers: dict | None, reports: int = 0) -> dict:
    """The verdict for one stored place check and one family's answers."""
    a = answers(raw_answers)
    f = facts(place, reports)
    base = score(f)
    pts = max(0, base + FLOOR_POINTS[a["floor"]])
    exposed = base >= EXPOSED
    if exposed and a["parking"]:
        pts += 2
    if exposed and a["vulnerable"]:
        pts += 1
    if a["mode"] == "buy" and old_bed(f):
        pts += 1
    level = level_for(pts)
    if a["floor"] == "high" and level == "avoid":
        level = "think"
    if exposed and level == "fine":
        level = "checks"
    ground = a["floor"] in ("ground", "house")
    home = {"key": f"verdict.home.{a['floor']}"}

    cons: list[tuple[int, dict]] = []
    pros: list[tuple[int, dict]] = []

    def con(w, key, **vars):
        cons.append((w, {"key": key, "vars": vars}))

    def pro(w, key, **vars):
        pros.append((w, {"key": key, "vars": vars}))

    if f["occ"] >= 5:
        con(6 if f["occ"] >= 20 else 5, "verdict.con.wasWater", pct=round(f["occ"]))
    if f["radar"]:
        con(5, "verdict.con.radar", dates=f["radar"][:3])
    if f["hand"] is not None and f["hand"] <= 1.0:
        con(4, "verdict.con.low")
    if f["lost300"] >= 0.3:
        con(3, "verdict.con.lostNear", ha=round(f["lost300"], 1))
    if f["bowl"] >= 1:
        con(3 if f["bowl"] >= 3 else 2, "verdict.con.bowl", m=round(f["bowl"], 1))
    if f["built2k"] >= 1:
        con(3 if f["built2k"] >= 10 else 2, "verdict.con.builtOver", ha=round(f["built2k"], 1))
    if f["reports"]:
        con(3 if f["reports"] >= 3 else 2, "verdict.con.reportsOne" if f["reports"] == 1 else "verdict.con.reports",
            n=f["reports"])
    if exposed and ground:
        con(3, "verdict.con.ground")
    if exposed and a["parking"]:
        con(3, "verdict.con.basement")
    if exposed and a["vulnerable"]:
        con(2, "verdict.con.vulnerable")
    if a["mode"] == "buy" and old_bed(f):
        con(4, "verdict.con.legalNp" if f["country"] == "NP" else "verdict.con.legal")
    if f["hereC"] is not None and (f["hereC"] >= 42 or f["hotter"]):
        con(1, "verdict.con.hot", c=round(f["hereC"]))

    if f["occ"] < 1 and f["lost300"] < 0.3 and f["tier"] == "little":
        pro(4, "verdict.pro.dry")
    if f["hand"] is not None and f["hand"] >= 3:
        pro(3, "verdict.pro.high", m=round(f["hand"], 1))
    if f["bowl"] < 0.5:
        pro(2, "verdict.pro.flat")
    if a["floor"] in ("low", "high"):
        pro(3 if exposed else 1, "verdict.pro.upper")
    if f["vsBuiltC"] is not None and f["vsBuiltC"] <= -1.5:
        pro(1, "verdict.pro.cool", c=round(abs(f["vsBuiltC"]), 1))
    if a["mode"] == "rent" and exposed:
        pro(2, "verdict.pro.rent")
    signs = sum([f["occ"] >= 5, bool(f["radar"]), f["hand"] is not None and f["hand"] <= 1.0, f["bowl"] >= 1,
                 f["lost300"] >= 0.3, f["built2k"] >= 1, f["reports"] > 0])
    if signs == 1 and f["tier"] != "strong":
        pro(1, "verdict.pro.fewSigns", n=1)

    cons.sort(key=lambda x: -x[0])
    pros.sort(key=lambda x: -x[0])
    if_still: list[dict] = []

    def tip(key, **vars):
        if_still.append({"key": key, "vars": vars})

    if level != "fine":
        if exposed and ground:
            tip("verdict.if.floor")
        if exposed and a["parking"]:
            tip("verdict.if.parking")
        if f["radar"]:
            tip("verdict.if.radar", dates=f["radar"][:3])
        elif f["event"]:
            tip("verdict.if.ask", dates=[f["event"]])
        else:
            tip("verdict.if.askMonsoons")
        if a["mode"] == "buy" and old_bed(f):
            tip("verdict.if.recordsNp" if f["country"] == "NP" else "verdict.if.records")
        if ground and f["tier"] in ("strong", "some"):
            tip("verdict.if.plinth")
        tip("verdict.if.visit")
        if exposed and a["vulnerable"]:
            tip("verdict.if.vulnerable")
        if exposed:
            tip("verdict.if.insurance")
    if len(if_still) > MAX_TIPS - 1:
        del if_still[MAX_TIPS - 1:]
    tip("verdict.if.follow")

    # why: what the place's water memory says, then the two facts that weigh most for this verdict; pros and cons
    # list the rest, so nothing is said twice
    memory = {"key": f"verdict.why.{f['tier'] if f['tier'] in TIER_POINTS else 'unknown'}", "vars": {"n": f["index"]}}
    lead = cons if level != "fine" else pros
    why = [memory] + [x for _, x in lead[:2]]
    used = {id(x) for x in why}
    return {"level": level, "points": pts, "placePoints": base, "answers": a,
            "headline": {"key": f"verdict.head.{level}.{a['mode']}", "vars": {"home": home}},
            "why": why, "pros": [p for _, p in pros if id(p) not in used][:5],
            "cons": [c for _, c in cons if id(c) not in used][:6], "ifStill": if_still,
            "note": {"key": "verdict.note", "vars": {}}}


def text(item: dict, lang: str | None = "en") -> str:
    """One verdict line in words (for the PDF and narration): nested {"key": ...} values are worded first, dates and
    numbers are formatted for the reader, and a key missing from the dictionaries falls back to VERDICT_EN."""
    from . import strings
    vars_ = {}
    for k, v in (item.get("vars") or {}).items():
        if isinstance(v, dict) and "key" in v:
            vars_[k] = strings.t(lang, v["key"], en=VERDICT_EN.get(v["key"]))
        elif k == "dates":
            vars_[k] = ", ".join(strings.day(d, lang) for d in v)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            vars_[k] = strings.num(v)
        else:
            vars_[k] = str(v)
    return strings.t(lang, item["key"], en=VERDICT_EN.get(item["key"]), **vars_)

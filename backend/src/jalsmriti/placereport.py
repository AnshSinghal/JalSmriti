"""The signed place report: everything report_pdf.render() draws, in the reader's language.

A family about to rent or buy (or someone who lives there) downloads it from the place page. It holds the stored place
check (water memory, findings, time-lapse, radar, summer heat), standing water people reported nearby, this week's
steps for that reader, questions to ask the owner or seller, the limits, and the signature block. Every sentence comes
from the website's dictionaries (strings.t); the English defaults below are what en.ts holds for the same keys.
"""
from __future__ import annotations

from . import actions as ACT
from . import strings
from .strings import day, num

REPORT_EN = {
    "report.docTitle": "JalSmriti water memory report",
    "report.signedNote": "Digitally signed: see the last page",
    "report.checked": "Checked on {date}",
    "report.made": "Report made {date}",
    "report.coords": "{lat} N, {lon} E",
    "report.memoryTitle": "What this place remembers",
    "report.findings": "What the records show",
    "report.timelapse": "The same spot through the years",
    "report.radar": "Monsoon radar sightings",
    "report.heat": "Summer heat",
    "report.reports": "Standing water reported by people",
    "report.reportsSome": "People reported standing water within 1 km {n} times in the last year.",
    "report.reportsOne": "People reported standing water within 1 km once in the last year.",
    "report.reportItem": "{date}: {depth}",
    "report.actions.home": "This week, if you are renting or buying here",
    "report.actions.resident": "This week, if you live here",
    "report.questions": "Questions to ask the owner or seller",
    "report.q1": "Has water ever come into the building, the basement or the parking? When, and how deep?",
    "report.q2": "Is the land's survey number in a lake, tank or storm-drain area in the revenue records or the master plan?",
    "report.q3": "Was the ground filled or raised before building, and when?",
    "report.q4": "Where does rain water from this plot drain, and has the drain outside ever overflowed?",
    "report.limits": "Read this before you rely on it",
    "report.limit1": "This is history and terrain from satellites, not a flood forecast. Floods can come from extreme rain or blocked drains anywhere.",
    "report.limit2": "Satellite pixels are 10 to 30 m, so small ponds and narrow drains can be missed. Outlines are approximate and are not a land survey.",
    "report.limit3": "Radar cannot see water between tall buildings, and water that drains within hours can fall between radar passes.",
    "report.limit4": "The water memory index was tested against 39 localities reported flooded in four cities: it is a guide, not a certainty.",
    "report.sources": "Data: JRC Global Surface Water (1984-2020); USGS Landsat and Copernicus Sentinel-1 and Sentinel-2 (Earth Search on the Registry of Open Data on AWS, and Microsoft Planetary Computer); Copernicus GLO-30 elevation; Impact Observatory land cover; NASA POWER rainfall. Names: OpenStreetMap contributors.",
    "report.verification": "Verification",
    "report.payload": "Content fingerprint (SHA-256)",
    "report.key": "Signing key fingerprint (ECDSA P-256 in AWS KMS)",
    "report.check": "Check this document",
    "report.checkHow": "Open that page and drop this PDF on it: your browser checks the KMS signature and the file's fingerprint itself. Any change to the PDF changes the fingerprint.",
    "report.footer": "JalSmriti water memory report: satellite history and terrain, not a flood forecast and not a land survey.",
    "report.page": "Page {n} of {total}",
    "report.depth.ankle": "ankle deep",
    "report.depth.knee": "knee deep",
    "report.depth.waist": "waist deep",
    "report.depth.vehicle": "deeper than a car's wheels",
    "report.depth.unknown": "depth not given",
}

HEAT_EN = {
    "heat.here": "On summer mornings (about 10:30, mid-March to May, {years}) the ground here measures about {here} °C.",
    "heat.vsBuiltWarmer": "That is {d} °C warmer than built-up ground nearby ({built} °C).",
    "heat.vsBuiltCooler": "That is {d} °C cooler than built-up ground nearby ({built} °C).",
    "heat.vsBuiltSame": "That is about as warm as built-up ground nearby ({built} °C).",
    "heat.vsWater": "Lake water nearby measures about {water} °C, so the ground here is {d} °C hotter than the water.",
    "heat.trees": "Ground under trees nearby measures about {trees} °C.",
    "heat.note": "Satellites measure the surface itself (roofs, roads, soil, water), not the air. Afternoons are hotter still.",
    "heat.none": "Summer heat could not be measured here: too few clear satellite passes in the last three summers.",
    "heat.scale": "{lo} °C to {hi} °C",
}


def T(lang: str, key: str, **vars) -> str:
    return strings.t(lang, key, en=REPORT_EN.get(key) or HEAT_EN.get(key), **vars)


def heat_lines(heat: dict | None, lang: str) -> list[str]:
    """The summer-heat sentences of a place check (also what the place page says)."""
    if not heat:
        return []
    if heat.get("hereC") is None:
        return [T(lang, "heat.none")]
    years = heat.get("years") or []
    yrs = f"{min(years)}-{max(years)}" if years else ""
    out = [T(lang, "heat.here", years=yrs, here=num(heat["hereC"]))]
    vb = heat.get("vsBuiltC")
    if vb is not None and heat.get("builtC") is not None:
        key = "heat.vsBuiltWarmer" if vb >= 0.5 else "heat.vsBuiltCooler" if vb <= -0.5 else "heat.vsBuiltSame"
        out.append(T(lang, key, d=num(abs(vb)), built=num(heat["builtC"])))
    vw = heat.get("vsWaterC")
    if vw is not None and heat.get("waterC") is not None and vw > 0:
        out.append(T(lang, "heat.vsWater", water=num(heat["waterC"]), d=num(vw)))
    if heat.get("treesC") is not None:
        out.append(T(lang, "heat.trees", trees=num(heat["treesC"])))
    out.append(T(lang, "heat.note"))
    return out


def labels(lang: str, report: dict, place: dict) -> dict:
    lat, lon = float(report["lat"]), float(report["lon"])
    return {
        "docTitle": T(lang, "report.docTitle"), "signedNote": T(lang, "report.signedNote"),
        "checked": T(lang, "report.checked", date=day(place.get("checkedAt"), lang)),
        "made": T(lang, "report.made", date=day(report.get("createdAt"), lang)),
        "coords": T(lang, "report.coords", lat=f"{lat:.5f}", lon=f"{lon:.5f}"),
        "memoryTitle": T(lang, "report.memoryTitle"), "findings": T(lang, "report.findings"),
        "timelapse": T(lang, "report.timelapse"), "radar": T(lang, "report.radar"), "heat": T(lang, "report.heat"),
        "reports": T(lang, "report.reports"), "actions": T(lang, f"report.actions.{report.get('persona', 'home')}"),
        "questions": T(lang, "report.questions"), "limits": T(lang, "report.limits"),
        "verification": T(lang, "report.verification"), "payload": T(lang, "report.payload"), "key": T(lang, "report.key"),
        "check": T(lang, "report.check"), "checkHow": T(lang, "report.checkHow"), "footer": T(lang, "report.footer"),
        "page": T(lang, "report.page"),
    }


def assemble(report: dict, place: dict, *, frames: list[tuple[str, bytes]], heat_image: bytes | None,
             nearby: dict | None, payload_sha256: str, key_fingerprint: str, verify_url: str, qr_png: bytes | None) -> dict:
    """The input of report_pdf.render() for one stored place check, in report["lang"], for report["persona"]."""
    lang = strings.lang_or_en(report.get("lang"))
    persona = report.get("persona") if report.get("persona") in ("home", "resident") else "home"
    memory = place.get("memory") or {}
    tier = memory.get("tier") or "unknown"
    sig = place.get("signals") or {}
    sightings = sorted(sig.get("radarSightings") or [], key=lambda s: s.get("date", ""))
    scenes = (place.get("radar") or {}).get("scenesChecked") or 0
    radar = None
    if (place.get("radar") or {}).get("scenesChecked") is not None or sightings:
        radar = {"sentence": strings.t(lang, "place.radar.some", n=len(sightings), scenes=scenes) if sightings
                 else strings.t(lang, "place.radar.none", n=scenes),
                 "dates": [f"{day(s['date'], lang)}, {num(s.get('haCore'))} ha" for s in sightings[-6:]]}
    heat = place.get("heat")
    heat_block = None
    if heat:
        lo, hi = (heat.get("scale") or [25, 50])[:2]
        heat_block = {"lines": heat_lines(heat, lang), "image": heat_image, "lo": lo, "hi": hi,
                      "scaleLabel": T(lang, "heat.scale", lo=lo, hi=hi)}
    reports = None
    if nearby and nearby.get("count"):
        reports = {"sentence": T(lang, "report.reportsOne" if nearby["count"] == 1 else "report.reportsSome", n=nearby["count"]),
                   "items": [T(lang, "report.reportItem", date=day(r.get("seenAt"), lang),
                               depth=T(lang, f"report.depth.{r.get('depth') or 'unknown'}"))
                             for r in (nearby.get("items") or [])[:6]]}
    steps = ACT.for_place(place)[persona]
    label = report.get("label") or (place.get("label") or {}).get("label") or \
        T(lang, "report.coords", lat=f"{float(report['lat']):.4f}", lon=f"{float(report['lon']):.4f}")
    return {
        "lang": lang, "reportId": report["reportId"], "title": label, "lat": float(report["lat"]), "lon": float(report["lon"]),
        "labels": labels(lang, report, place),
        "tier": tier, "tierLabel": strings.tier_label(tier, lang), "index": memory.get("index"),
        "indexLabel": strings.t(lang, "place.memory.index", n=memory.get("index")) if memory.get("index") is not None else "",
        "explain": strings.t(lang, "place.memory.explain"), "validation": strings.t(lang, "place.memory.validation"),
        "findings": [{"text": strings.finding_text(f, lang), "severity": f.get("severity", "info")}
                     for f in (place.get("findings") or [])],
        "frames": [{"label": lbl, "image": img} for lbl, img in frames],
        "radar": radar, "heat": heat_block, "reports": reports,
        "actions": {"title": T(lang, f"report.actions.{persona}"), "items": [strings.action_text(a, lang) for a in steps]},
        "questions": [T(lang, f"report.q{i}") for i in (1, 2, 3, 4)] if persona == "home" else None,
        "limits": [T(lang, f"report.limit{i}") for i in (1, 2, 3, 4)], "sources": T(lang, "report.sources"),
        "payloadSha256": payload_sha256, "keyFingerprint": key_fingerprint, "verifyUrl": verify_url, "qrPng": qr_png,
    }


def payload(report: dict, place: dict) -> dict:
    """What the signature vouches for: the stored check and the advice given, independent of layout and language."""
    persona = report.get("persona") if report.get("persona") in ("home", "resident") else "home"
    keep_heat = ("hereC", "builtC", "waterC", "treesC", "vsBuiltC", "vsWaterC", "years")
    return {
        "reportId": report["reportId"], "place": {"lat": report["lat"], "lon": report["lon"], "gh7": report.get("gh7"),
                                                  "label": report.get("label")},
        "checkedAt": place.get("checkedAt"), "checkId": place.get("checkId"), "scienceVersion": place.get("scienceVersion"),
        "memory": {k: (place.get("memory") or {}).get(k) for k in ("index", "tier")},
        "findings": [{"key": f.get("key"), "vars": f.get("vars")} for f in (place.get("findings") or [])],
        "radar": [{"date": s.get("date"), "haCore": s.get("haCore")}
                  for s in ((place.get("signals") or {}).get("radarSightings") or [])],
        "heat": {k: (place.get("heat") or {}).get(k) for k in keep_heat} if place.get("heat") else None,
        "frames": [f.get("season") for f in (place.get("frames") or [])],
        "actions": [a["key"] for a in ACT.for_place(place)[persona]],
        "lang": report.get("lang"), "persona": persona,
    }

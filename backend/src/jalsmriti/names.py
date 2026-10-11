"""Names for water bodies and places.

OpenStreetMap names come from the public Photon geocoder (komoot), asked politely: one request at a time,
a descriptive User-Agent and a cache. GeoNames (CC BY 4.0, bundled for India and Nepal) is the fallback.
When neither knows the water body, it is named after what is near it (fallback_name), never just "unnamed":
  1. the nearest named lake within 2 km: "Water body near Bellandur Lake" or "Water body 1.6 km east of ...",
  2. the locality the geocoder gave for its own position: "Water body near Mahadevapura",
  3. the nearest named lake within 6 km,
  4. the locality of the nearest named neighbour within 3 km: "Water body in Varthur",
  5. the area: "Water body in Bengaluru".
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

from . import config as C
from .geo import haversine_m

log = logging.getLogger(__name__)

WATER_WORDS = re.compile(
    r"\b(lake|kere|kerey|tank|cheruvu|cheruv|kunta|eri|ery|talab|talav|taal|tal|jheel|jhil|sagar|sarovar|pokhari|"
    r"pokhri|pokhara|pond|kulam|kund|kunda|beel|bil|pukur|pukuri|reservoir|dam|marsh|wetland|lagoon|chira|johad|"
    r"bund|jalashay|jalasaya|samudra|kayal|kaayal)\b", re.I)
_lock = threading.Lock()
_last = [0.0]


def _photon(path: str, params: dict, timeout: int = 15) -> dict | None:
    with _lock:   # at most ~1 request per second from one process
        wait = 1.05 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    url = f"{C.PHOTON}/{path}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": C.USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as ex:
        log.info("photon %s failed: %s", path, ex)
        return None


@lru_cache(maxsize=1)
def _geonames() -> list:
    p = Path(__file__).resolve().parent / "data" / "geonames_water.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def geonames_near(lat: float, lon: float, max_m: float) -> str | None:
    best, best_d = None, max_m
    for la, lo, name, _code in _geonames():
        if abs(la - lat) > 0.05 or abs(lo - lon) > 0.05:
            continue
        d = haversine_m(lat, lon, la, lo)
        if d < best_d:
            best, best_d = name, d
    return best


def _admin(props: dict) -> dict:
    return {"locality": props.get("district") or props.get("locality") or props.get("city") or props.get("county"),
            "city": props.get("city"), "county": props.get("county"), "state": props.get("state"),
            "country": props.get("country"), "countryCode": props.get("countrycode"), "postcode": props.get("postcode")}


def reverse(lat: float, lon: float, radius_km: float = 0.6, limit: int = 10) -> list[dict]:
    j = _photon("reverse", {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "limit": limit, "radius": radius_km, "lang": "en"})
    out = []
    for f in (j or {}).get("features", []):
        p = f.get("properties", {})
        lo, la = f["geometry"]["coordinates"]
        out.append({"name": p.get("name"), "key": p.get("osm_key"), "value": p.get("osm_value"), "lat": la, "lon": lo,
                    "distM": haversine_m(lat, lon, la, lo), **_admin(p)})
    return out


def water_body_name(lat: float, lon: float, area_ha: float) -> dict:
    """{'name', 'source', 'locality', 'state', ...} for a water body whose representative point is given."""
    reach_m = max(250.0, min(1500.0, 60.0 * math.sqrt(max(area_ha, 1.0))))
    feats = reverse(lat, lon, radius_km=reach_m / 1000.0)
    admin = next((f for f in feats if f.get("state")), {}) if feats else {}
    for f in sorted(feats, key=lambda x: x["distM"]):
        nm = f.get("name") or ""
        is_water_tag = f.get("value") in ("water", "lake", "reservoir", "pond", "basin", "wetland", "lagoon") or \
            f.get("key") in ("water", "natural") and f.get("value") in ("water", "wetland")
        if nm and (is_water_tag or WATER_WORDS.search(nm)) and f["distM"] <= reach_m:
            return {"name": nm, "source": "OpenStreetMap", **_strip(admin)}
    gn = geonames_near(lat, lon, reach_m)
    if gn:
        return {"name": gn, "source": "GeoNames", **_strip(admin)}
    loc = admin.get("locality") or admin.get("city") or admin.get("county")
    return {"name": f"Water body near {loc}" if loc else "Unnamed water body", "source": "generated", **_strip(admin)}


def place_label(lat: float, lon: float) -> dict:
    feats = reverse(lat, lon, radius_km=1.0, limit=5)
    if not feats:
        return {}
    f = feats[0]
    return {"label": ", ".join([x for x in (f.get("locality"), f.get("city") or f.get("county"), f.get("state")) if x]),
            **_strip(f)}


def search(q: str, limit: int = 6, bias: tuple[float, float] | None = None) -> list[dict]:
    params = {"q": q, "limit": limit, "lang": "en"}
    if bias:
        params.update({"lat": bias[0], "lon": bias[1]})
    j = _photon("api", params)
    out = []
    for f in (j or {}).get("features", []):
        p = f.get("properties", {})
        if p.get("countrycode") not in ("IN", "NP"):
            continue
        lo, la = f["geometry"]["coordinates"]
        out.append({"label": ", ".join([x for x in (p.get("name"), p.get("district") or p.get("city"), p.get("state")) if x]),
                    "lat": la, "lon": lo, "kind": p.get("osm_value"), "source": "OpenStreetMap (Photon)"})
    return out


def _strip(d: dict) -> dict:
    return {k: d.get(k) for k in ("locality", "city", "county", "state", "country", "countryCode") if d.get(k)}


# ------------------------------------------------------------------------------------------ named after what is near
REAL_SOURCES = ("OpenStreetMap", "GeoNames")
COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
NEAR_M = 1000.0            # within this: "Water body near Bellandur Lake"
PREFER_LAKE_M = 2000.0     # a named lake this close beats the locality
LAKE_MAX_M = 6000.0        # further than this, a lake does not describe where a water body is
PLACE_MAX_M = 3000.0
_DEG = 0.06                # a quick box test before measuring (about 6.6 km)


def direction(lat: float, lon: float, from_lat: float, from_lon: float) -> str:
    """Where (lat, lon) lies seen from (from_lat, from_lon), to 8 compass points."""
    dy = lat - from_lat
    dx = (lon - from_lon) * math.cos(math.radians((lat + from_lat) / 2))
    ang = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0          # 0 = north, 90 = east
    return COMPASS[int((ang + 22.5) // 45) % 8]


def nearest(lat: float, lon: float, anchors, max_m: float):
    """(distance in m, anchor) for the nearest of `anchors` [(lat, lon, label), ...] within max_m, else None."""
    best = None
    for a in anchors:
        if abs(a[0] - lat) > _DEG or abs(a[1] - lon) > _DEG:
            continue
        d = haversine_m(lat, lon, a[0], a[1])
        if d <= max_m and (best is None or d < best[0]):
            best = (d, a)
    return best


def near_label(lat: float, lon: float, anchor, dist_m: float, noun: str = "Water body") -> str:
    if dist_m <= NEAR_M:
        return f"{noun} near {anchor[2]}"
    return f"{noun} {dist_m / 1000:.1f} km {direction(lat, lon, anchor[0], anchor[1])} of {anchor[2]}"


def geonames_anchors(bbox, pad: float = _DEG) -> list[tuple[float, float, str]]:
    """Named water bodies from GeoNames inside [west, south, east, north] widened by `pad` degrees."""
    w, s, e, n = bbox
    return [(la, lo, name) for la, lo, name, _code in _geonames()
            if s - pad <= la <= n + pad and w - pad <= lo <= e + pad]


def fallback_name(lat: float, lon: float, kind: str, lakes, places, generated: dict | None, area_name: str | None
                  ) -> dict:
    """{"name", "source", "lake"} for a water body that has no name of its own.

    lakes:  named water bodies nearby, [(lat, lon, name), ...] (OpenStreetMap and GeoNames names only),
    places: localities the geocoder gave for named neighbours, [(lat, lon, locality), ...],
    generated: what water_body_name() made from the geocoder's locality for this body ("Water body near X"), if any.
    source is "nearby-lake", "nearby-place", "area" or "none"; "lake" is (distance, anchor) of the nearest named lake
    within 6 km or None (distinct() uses it to tell apart water bodies that got the same name)."""
    noun = "River stretch" if kind == "river" else "Water body"
    lake = nearest(lat, lon, lakes, LAKE_MAX_M)
    out = {"lat": lat, "lon": lon, "noun": noun, "lake": lake}
    loc = (generated or {}).get("locality") or (generated or {}).get("city")
    place = None if lake or loc else nearest(lat, lon, places, PLACE_MAX_M)
    if lake and lake[0] <= PREFER_LAKE_M:
        name, source = near_label(lat, lon, lake[1], lake[0], noun), "nearby-lake"
    elif loc:
        name, source = f"{noun} near {loc}", "nearby-place"
    elif lake:
        name, source = near_label(lat, lon, lake[1], lake[0], noun), "nearby-lake"
    elif place:
        name, source = f"{noun} in {place[1][2]}", "nearby-place"
    elif area_name:
        name, source = f"{noun} in {area_name}", "area"
    else:
        name, source = f"Unnamed {noun.lower()}", "none"
    return {**out, "name": name, "source": source}


def distinct(named: list[dict]) -> None:
    """Tell apart water bodies that got the same name (in place), using the nearest named lake: "Water body near
    Bellandur Lake" twice becomes "Water body north of Bellandur Lake" and "Water body south-east of ..."; a repeated
    locality name becomes "Water body 3.4 km south of Varthur Lake". Names that are still the same stay so.

    named: fallback_name() results."""
    seen: dict[str, int] = {}
    for n in named:
        seen[n["name"]] = seen.get(n["name"], 0) + 1
    for n in named:
        lake = n.get("lake")
        if seen[n["name"]] < 2 or not lake:
            continue
        d, a = lake
        side = direction(n["lat"], n["lon"], a[0], a[1])
        if d <= NEAR_M:
            n["name"], n["source"] = f"{n['noun']} {side} of {a[2]}", "nearby-lake"
        else:
            n["name"], n["source"] = f"{n['noun']} {d / 1000:.1f} km {side} of {a[2]}", "nearby-lake"

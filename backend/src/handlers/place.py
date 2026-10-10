"""Place check (Step Functions): what 37 years of satellite records remember about one spot.

  Parallel[ Static (water history, land cover, terrain) | Optical (time-lapse frames) | Radar (monsoon sightings)
            | Heat (summer ground temperature) ]
  -> Score

Steps write their part into the job record (JOB#{id}) as soon as they finish, so the page fills in live.
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from jalsmriti import areas as A
from jalsmriti import catalog, frames, geo, heat, landcover, metrics, names, placecheck, radar, storage, store, terrain, water
from jalsmriti import config as C
from jalsmriti.raster import MERCATOR, Grid

log = logging.getLogger()
log.setLevel(logging.INFO)


_disk = placecheck.disk


def _save(job_id: str, part: str, value: dict) -> None:
    store.update(f"JOB#{job_id}", "META", sets={part: value, f"{part}At": store.now_iso()})


# ------------------------------------------------------------------------------------------ static
def static(event, context=None):
    lat, lon, job = float(event["lat"]), float(event["lon"]), event["jobId"]
    sig = placecheck.signals(lat, lon)
    area = A.area_for(lat, lon)
    label = {}
    try:
        label = names.place_label(lat, lon)
    except Exception:
        pass
    _save(job, "static", {"signals": sig, "areaId": area.id if area else None, "label": label})
    return {"ok": True}


# ------------------------------------------------------------------------------------------ optical frames
def _best_for(lat: float, lon: float, season: int, half: float) -> tuple[str, list[dict]] | None:
    src = "S2" if season >= C.S2_FIRST_SEASON else "LS"
    bbox = geo.bbox_around(lat, lon, half)
    area = A.area_for(lat, lon)
    window = area.look if area else ("10-15", "02-28")
    cands = catalog.pick_season_scenes(src, bbox, season, window, n=4, max_cloud=40)
    best, best_score = None, -1.0
    for it in cands:
        passes = catalog.same_pass_items(src, bbox, it)
        sc = water.area_clear_score(src, passes, bbox, res=60.0)
        if sc > best_score:
            best, best_score = (src, passes), sc
        if sc > 0.97:
            break
    return best if best and best_score > 0.6 else None


def optical(event, context=None):
    lat, lon, job = float(event["lat"]), float(event["lon"]), event["jobId"]
    gh = geo.geohash(lat, lon, 7)
    half = C.PLACE_CHIP_HALF_M
    out = []

    def one(target):
        try:
            got = _best_for(lat, lon, target, half)
            if not got:
                return None
            src, passes = got
            res = 10.0 if src == "S2" else 30.0
            g = Grid.around(lon, lat, half / math.cos(math.radians(lat)), res, crs=MERCATOR)
            fr = frames.frame(src, passes, g)
            det = water.detect(src, passes, Grid.around(lon, lat, 350, res))
            core = _disk(Grid.around(lon, lat, 350, res), 300)
            wfrac = float((det["water"] & core).sum()) / max(1, float((det["valid"] & core).sum()))
            url = storage.put_public(f"places/{gh}/frames/{target}.webp", frames.to_webp(fr["rgb"], fr["valid"], 82, 480),
                                     "image/webp")
            return {"season": target, "date": catalog.item_date(passes[0]).isoformat(), "source": src,
                    "platform": passes[0]["properties"].get("platform"), "url": url, "waterShare300": round(wfrac, 3)}
        except Exception as ex:
            log.warning("place frame %s failed: %s", target, ex)
            return None

    with ThreadPoolExecutor(5) as ex:
        for r in ex.map(one, list(C.FRAME_SEASONS)):
            if r:
                out.append(r)
    out.sort(key=lambda r: r["season"])
    _save(job, "optical", {"frames": out, "geohash": gh})
    return {"ok": True, "frames": len(out)}


# ------------------------------------------------------------------------------------------ radar
def radar_step(event, context=None):
    lat, lon, job = float(event["lat"]), float(event["lon"]), event["jobId"]
    g = Grid.around(lon, lat, 1000, 20.0)
    core = _disk(g, C.PLACE_RADIUS_M)
    try:
        r = radar.sightings(g, core)
    except Exception as ex:
        log.warning("radar failed: %s", ex)
        r = {"sightings": [], "scenesChecked": 0, "error": str(ex)[:200]}
    _save(job, "radar", r)
    return {"ok": True, "sightings": len(r.get("sightings", []))}


# ------------------------------------------------------------------------------------------ summer heat
def heat_step(event, context=None):
    """Summer ground temperature around the place (Landsat 8/9 surface temperature), next to built-up ground and water."""
    lat, lon, job = float(event["lat"]), float(event["lon"]), event["jobId"]
    try:
        stats, img, corners = heat.summer_heat(lat, lon)
    except Exception as ex:
        log.warning("heat failed: %s", ex)
        stats, img, corners = {"hereC": None, "error": str(ex)[:200]}, None, None
    if img:
        gh = geo.geohash(lat, lon, 7)
        stats["imageUrl"] = storage.put_public(f"places/{gh}/heat.webp", img, "image/webp")
        stats["corners"] = corners
    _save(job, "heat", stats)
    return {"ok": True, "hereC": stats.get("hereC")}


# ------------------------------------------------------------------------------------------ score
def score(event, context=None):
    job_id = event["jobId"]
    j = store.get(f"JOB#{job_id}") or {}
    sig = dict((j.get("static") or {}).get("signals") or {})
    sig["radarSightings"] = (j.get("radar") or {}).get("sightings", [])
    idx = metrics.water_memory_index(sig)
    findings = metrics.place_findings(sig)
    result = {"lat": j.get("lat"), "lon": j.get("lon"), "label": (j.get("static") or {}).get("label") or {},
              "areaId": (j.get("static") or {}).get("areaId"), "signals": sig, "memory": idx, "findings": findings,
              "frames": (j.get("optical") or {}).get("frames", []),
              "radar": {k: v for k, v in (j.get("radar") or {}).items() if k != "sightings"},
              "heat": j.get("heat"),
              "scienceVersion": C.SCIENCE_VERSION, "checkedAt": store.now_iso(), "checkId": job_id}
    gh = geo.geohash(float(j["lat"]), float(j["lon"]), 7)
    store.put({"PK": f"PLACE#{gh}", "SK": f"V#{C.PLACE_CACHE_VERSION}", **result, "ttl": int(__import__("time").time()) + 90 * 86400})
    store.update(f"JOB#{job_id}", "META", sets={"status": "done", "result": result, "finishedAt": store.now_iso()})
    store.bump_stats(places=1)
    return {"ok": True, "index": idx.get("index")}


def failed(event, context=None):
    job_id = (event or {}).get("jobId")
    if job_id:
        err = (event or {}).get("error") or {}
        store.update(f"JOB#{job_id}", "META", sets={"status": "failed", "error": str(err.get("Cause", err))[:400]})
    return {"ok": False}

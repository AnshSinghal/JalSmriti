"""Area pipeline (Step Functions): every water body of a pre-loaded area, 1987 to now.

  Prepare -> Parallel[ Map(ProcessScene) | StaticLayers | LatestQuality | RadarEvents | NameLakes ] -> Aggregate

Each step reads what it needs from the private data bucket and writes its own results there, so steps can be
retried independently and the state machine only passes small references around.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from jalsmriti import areas as A
from jalsmriti import catalog, frames, lakes, landcover, metrics, names, radar, rain, storage, store, terrain, water
from jalsmriti import config as C
from jalsmriti.raster import MERCATOR, Grid, near, rasterize_labels, reproject_geom, zonal_count

log = logging.getLogger()
log.setLevel(logging.INFO)

_cache: dict = {}


# ------------------------------------------------------------------------------------------ helpers
def _base(area_id: str) -> dict:
    """Grid, labels, JRC layers and bodies for an area (cached in the warm Lambda)."""
    if area_id in _cache:
        return _cache[area_id]
    from shapely import wkt
    from jalsmriti.raster import load_npz
    meta = storage.get_data_json(f"areas/{area_id}/base.json")
    arr = load_npz(storage.get_data(f"areas/{area_id}/base.npz"))
    grid = Grid.from_dict(meta["grid"])
    bodies = meta["bodies"]
    for b in bodies:
        b["geomUtm"] = wkt.loads(b["wkt"])
    out = {"grid": grid, "labels": arr["labels"], "occ": arr["occ"].astype(np.float32), "ext": arr["ext"],
           "trn": arr["trn"], "bodies": bodies, "meta": meta}
    _cache.clear()
    _cache[area_id] = out
    return out


def _area(area_id: str) -> A.Area:
    if area_id not in A.AREAS:
        raise ValueError(f"unknown area {area_id}")
    return A.AREAS[area_id]


def _frame_grid(area: A.Area, source: str, fine: bool = False) -> Grid:
    res = C.FRAME_RES_S2_M if source == "S2" else C.FRAME_RES_LANDSAT_M
    if source == "S2" and not fine:
        res = 20.0
    return frames.mercator_grid(area.bbox, res)


# ------------------------------------------------------------------------------------------ 1. prepare
def prepare(event, context=None):
    area = _area(event["areaId"])
    t0 = time.time()
    store.update(f"AREA#{area.id}", "META", sets={"status": "running", "startedAt": store.now_iso(), "id": area.id,
                                                   "stage": "finding water bodies"})
    grid = Grid.for_bbox(area.bbox, C.AREA_RES_M)
    j = landcover.jrc(grid)
    z = terrain.dem(grid)
    bodies, labels = lakes.discover(grid, j, area.id, dem=z, min_ha=area.min_ha)
    from jalsmriti.raster import save_npz
    storage.put_data(f"areas/{area.id}/base.npz", save_npz({
        "labels": labels.astype(np.int32), "occ": np.clip(j["occurrence"], 0, 100).astype(np.uint8),
        "ext": j["extent"], "trn": j["transitions"]}))
    storage.put_data_json(f"areas/{area.id}/base.json", {
        "grid": grid.to_dict(), "areaId": area.id, "createdAt": store.now_iso(),
        "bodies": [{k: v for k, v in b.items() if k != "geomUtm"} | {"wkt": b["geomUtm"].wkt} for b in bodies]})

    # scenes: one or two clearest post-monsoon passes per season, Landsat before Sentinel-2
    jobs, frame_seasons = [], {}
    seasons = list(range(C.FIRST_SEASON, C.CURRENT_SEASON))

    def pick(season):
        src = "S2" if season >= C.S2_FIRST_SEASON else "LS"
        try:
            return season, src, catalog.pick_season_scenes(src, area.bbox, season, area.look)
        except Exception as ex:
            log.warning("scene search failed %s %s: %s", area.id, season, ex)
            return season, src, []

    with ThreadPoolExecutor(6) as ex:
        picks = list(ex.map(pick, seasons))
    available = {s: (src, its) for s, src, its in picks if its}
    # time-machine frames: among passes within 2 seasons of each target, the one clearest over THIS area
    frame_items: dict[int, str] = {}

    def best_frame(target):
        cands = [(s, src, it) for s, (src, its) in available.items() if abs(s - target) <= 2 for it in its]
        scored = []
        for s, src, it in cands:
            try:
                passes = catalog.same_pass_items(src, area.bbox, it)
            except Exception:
                passes = [it]
            score = water.area_clear_score(src, passes, area.bbox)
            scored.append((score - 0.02 * abs(s - target), s, it["id"]))
        return target, max(scored) if scored else None

    with ThreadPoolExecutor(4) as ex:
        for target, best in ex.map(best_frame, C.FRAME_SEASONS):
            if best and best[0] > 0.55 and best[1] not in frame_seasons.values():
                frame_seasons[target] = best[1]
                frame_items[best[1]] = best[2]
    for s, (src, its) in sorted(available.items()):
        for it in its:
            jobs.append({"areaId": area.id, "source": src, "season": s, "itemId": it["id"],
                         "date": catalog.item_date(it).isoformat(), "platform": it["properties"].get("platform"),
                         "cloud": it["properties"].get("eo:cloud_cover"), "frame": frame_items.get(s) == it["id"]})
    storage.put_data_json(f"areas/{area.id}/scenes.json", jobs)
    store.update(f"AREA#{area.id}", "META", sets={"stage": "reading satellite archive", "scenes": len(jobs),
                                                   "lakes": sum(1 for b in bodies if b["kind"] == "lake")})
    log.info("prepared %s: %d bodies, %d scenes in %.0fs", area.id, len(bodies), len(jobs), time.time() - t0)
    return {"areaId": area.id, "bucket": C.DATA_BUCKET, "manifestKey": f"areas/{area.id}/scenes.json",
            "scenes": len(jobs), "bodies": len(bodies)}


# ------------------------------------------------------------------------------------------ 2. one scene
def _item(source: str, item_id: str) -> dict:
    api, coll = (C.EARTH_SEARCH, C.S2_COLLECTION) if source == "S2" else (C.PLANETARY_COMPUTER, "landsat-c2-l2")
    return catalog.item_by_id(api, coll, item_id)


def process_scene(event, context=None):
    job = event.get("job") or event
    area = _area(job["areaId"])
    b = _base(area.id)
    grid, labels, bodies = b["grid"], b["labels"], b["bodies"]
    n = len(bodies)
    it = _item(job["source"], job["itemId"])
    items = catalog.same_pass_items(job["source"], area.bbox, it)
    det = water.detect(job["source"], items, grid)
    total = zonal_count(labels, n)
    valid = zonal_count(labels, n, det["valid"])
    clear = zonal_count(labels, n, det["clear"])
    wat = zonal_count(labels, n, det["water"])
    cloud_near = zonal_count(labels, n, near(det["cloud"], C.LOOK_CLOUD_BUFFER_M, grid.res))
    rows = {}
    for i in range(n):
        if total[i] > 0 and valid[i] > 0:
            rows[bodies[i]["lakeId"]] = [int(total[i]), int(valid[i]), int(clear[i]), int(wat[i]), int(cloud_near[i] > 0)]
    out = {"season": job["season"], "date": job["date"], "source": job["source"], "platform": job.get("platform"),
           "sceneIds": [x["id"] for x in items], "lakes": rows}
    storage.put_data_json(f"areas/{area.id}/looks/{job['season']}-{job['source']}-{job['date']}.json", out)
    if job.get("frame"):
        _frames_for_scene(area, b, job, items)
    return {"ok": True, "lakes": len(rows)}


def _frames_for_scene(area: A.Area, b: dict, job: dict, items: list[dict]) -> None:
    fine = _frame_grid(area, job["source"], fine=True)
    fr = frames.frame(job["source"], items, fine)
    season = job["season"]
    # area frame for the map (20 m for Sentinel-2, 30 m for Landsat)
    step = 2 if job["source"] == "S2" else 1
    area_rgb = fr["rgb"][::step, ::step]
    area_valid = fr["valid"][::step, ::step]
    coarse = Grid(fine.crs, fine.transform * fine.transform.scale(step, step), area_rgb.shape[1], area_rgb.shape[0])
    url = storage.put_public(f"areas/{area.id}/frames/{season}.webp", frames.to_webp(area_rgb, area_valid, 74),
                             "image/webp", immutable=False)
    storage.put_data_json(f"areas/{area.id}/frames/{season}.json", {
        "season": season, "date": job["date"], "source": job["source"], "platform": job.get("platform"),
        "url": url, "corners": frames.corners_lonlat(coarse), "resM": fine.res * step})
    # crops for every lake
    def crop(body):
        g = reproject_geom(body["geomUtm"], b["grid"].crs, MERCATOR)
        box = frames.crop_box(fine, g)
        if not box:
            return
        data = frames.cut(fr, box, 360, outline=frames.rings_px(fine, g))
        storage.put_public(f"lakes/{body['lakeId']}/frames/{season}.webp", data, "image/webp")

    with ThreadPoolExecutor(16) as ex:
        list(ex.map(crop, [x for x in b["bodies"] if x["kind"] == "lake"]))


# ------------------------------------------------------------------------------------------ 3. land cover, rain, layers
def static_layers(event, context=None):
    area = _area(event["areaId"])
    b = _base(area.id)
    grid, labels, bodies = b["grid"], b["labels"], b["bodies"]
    n = len(bodies)
    occ, ext, trn = b["occ"], b["ext"], b["trn"]
    hist = (ext == 1) & (occ >= C.JRC_OCCURRENCE_MIN)
    lulc = landcover.io_lulc(grid)
    wc = landcover.worldcover(grid)
    persistent = landcover.built_persistent(lulc)
    last = lulc[max(lulc)]
    lost = np.isin(trn, C.JRC_LOST) & hist
    groups = {"built": [C.IO_BUILT], "vegetation": [C.IO_TREES, C.IO_FLOODED_VEG, C.IO_RANGE], "crops": [C.IO_CROPS],
              "bare": [C.IO_BARE], "water": [C.IO_WATER]}
    stats = {}
    zc = lambda m: zonal_count(labels, n, m)
    hist_px, perm_px = zc(hist), zc(np.isin(trn, C.JRC_PERMANENT) & hist)
    seas_px, new_px = zc(np.isin(trn, C.JRC_SEASONAL) & hist), zc(np.isin(trn, C.JRC_NEW) & hist)
    lost_px, typ_px = zc(lost), zc(hist & (occ >= 50))
    occ_sum = zonal_count(labels, n, np.where(hist, occ, 0))
    built_year = {y: zc((a == C.IO_BUILT) & hist) for y, a in lulc.items()}
    persist_px = zc(persistent & hist)
    wc_px = zc((wc == 50) & hist)
    lost_now = {k: zc(lost & np.isin(last, v)) for k, v in groups.items()}
    for i, body in enumerate(bodies):
        stats[body["lakeId"]] = {
            "jrc": {"histPx": int(hist_px[i]), "permanentPx": int(perm_px[i]), "seasonalPx": int(seas_px[i]),
                    "lostPx": int(lost_px[i]), "newPx": int(new_px[i]), "typicalPx": int(typ_px[i]),
                    "meanOcc": float(occ_sum[i] / hist_px[i]) if hist_px[i] else None},
            "land": {"pxHa": grid.px_area_m2 / 1e4, "builtPxByYear": {str(y): int(v[i]) for y, v in built_year.items()},
                     "builtPersistentPx": int(persist_px[i]), "worldcoverBuiltPx": int(wc_px[i]),
                     "lostNow": {k: int(v[i]) for k, v in lost_now.items()}}}
    storage.put_data_json(f"areas/{area.id}/landcover.json", stats)

    # rain per lake per season (NASA POWER; lakes in the same ~50 km cell share one request)
    seasons = list(range(C.FIRST_SEASON, C.CURRENT_SEASON + 1))
    lake_rain, complete_all = {}, {}
    for bd in bodies:
        try:
            tot, comp = rain.seasonal(bd["lat"], bd["lon"], seasons, area.rain)
        except Exception as ex:
            log.warning("rain failed for %s: %s", bd["lakeId"], ex)
            tot, comp = {}, {}
        lake_rain[bd["lakeId"]] = {str(k): v for k, v in tot.items()}
        complete_all.update({str(k): v for k, v in comp.items()})
    try:
        area_tot, area_comp = rain.seasonal(area.center[1], area.center[0], seasons, area.rain)
    except Exception:
        area_tot, area_comp = {}, {}
    storage.put_data_json(f"areas/{area.id}/rain.json", {
        "source": "NASA POWER PRECTOTCORR (MERRA-2, monthly)", "months": list(area.rain),
        "complete": complete_all or {str(k): v for k, v in area_comp.items()}, "lakes": lake_rain,
        "area": {str(k): v for k, v in area_tot.items()}})

    # the water-memory layer: historic water coloured by what it is now
    mg = frames.mercator_grid(area.bbox, 30.0)
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    def to_merc(a, rs=Resampling.nearest):
        out = np.zeros(mg.shape, dtype=a.dtype)
        reproject(a, out, src_transform=grid.transform, src_crs=grid.crs, dst_transform=mg.transform,
                  dst_crs=mg.crs, resampling=rs)
        return out

    m_hist = to_merc(hist.astype(np.uint8)) > 0
    m_lost = to_merc(lost.astype(np.uint8)) > 0
    m_built = to_merc((hist & (last == C.IO_BUILT)).astype(np.uint8)) > 0
    m_occ = to_merc(occ.astype(np.uint8))
    rgba = np.zeros(mg.shape + (4,), dtype=np.uint8)
    blue = m_hist & ~m_lost & ~m_built
    rgba[blue] = (52, 132, 238, 0)
    rgba[..., 3][blue] = (90 + np.clip(m_occ[blue], 0, 100) * 1.4).astype(np.uint8)
    rgba[m_lost & ~m_built] = (245, 165, 36, 215)
    rgba[m_built] = (229, 72, 77, 235)
    import io as _io
    from PIL import Image
    buf = _io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="WEBP", lossless=True, method=4)
    url = storage.put_public(f"areas/{area.id}/layers/memory.webp", buf.getvalue(), "image/webp")
    px_ha = grid.px_area_m2 / 1e4
    layer = {"url": url, "corners": frames.corners_lonlat(mg),
             "legend": {"water": "Water body (darker = water more often, 1984-2020)",
                        "lost": "Water lost since 1984", "built": "Old water-body bed now built over"},
             "historicHa": round(float(hist.sum()) * px_ha), "lostHa": round(float(lost.sum()) * px_ha),
             "builtOverHa": round(float((hist & (last == C.IO_BUILT)).sum()) * px_ha),
             "builtOverPersistentHa": round(float((hist & persistent).sum()) * px_ha)}
    storage.put_data_json(f"areas/{area.id}/layers.json", {"memory": layer})
    return {"ok": True}


# ------------------------------------------------------------------------------------------ 4. latest look
def latest_quality(event, context=None):
    area = _area(event["areaId"])
    b = _base(area.id)
    bodies = b["bodies"]
    import datetime as _dt
    today = _dt.date.today()
    since = catalog.shift(today, -120).isoformat()
    items = catalog.search(C.EARTH_SEARCH, C.S2_COLLECTION, area.bbox, f"{since}/{today.isoformat()}",
                           {"eo:cloud_cover": {"lt": 35}}, limit=200)
    if not items:
        storage.put_data_json(f"areas/{area.id}/latest.json", {"date": None, "lakes": {}})
        return {"ok": True, "date": None}
    items.sort(key=lambda it: (-catalog.item_date(it).toordinal() // 10, it["properties"]["eo:cloud_cover"]))
    it = items[0]
    passes = catalog.same_pass_items("S2", area.bbox, it)
    g20 = Grid.for_bbox(area.bbox, 20.0)
    det = water.detect("S2", passes, g20, bands=("red", "rededge1"))
    labels = rasterize_labels([x["geomUtm"] for x in bodies], g20)
    n = len(bodies)
    occ20 = landcover.jrc(g20, layers=("occurrence",))["occurrence"]
    refl = det["refl"]
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = (refl["nir"] - refl["red"]) / (refl["nir"] + refl["red"])
        ndci = (refl["rededge1"] - refl["red"]) / (refl["rededge1"] + refl["red"])
    typical = occ20 >= 50
    weed = det["clear"] & typical & (ndvi > C.FLOATING_VEG_NDVI) & ~det["water"]
    openw = det["water"]
    tot, clr = zonal_count(labels, n), zonal_count(labels, n, det["clear"])
    ow, wd, ty = zonal_count(labels, n, openw), zonal_count(labels, n, weed), zonal_count(labels, n, typical)
    ndci_sum = zonal_count(labels, n, np.where(openw, np.nan_to_num(ndci), 0))
    red_sum = zonal_count(labels, n, np.where(openw, np.nan_to_num(refl["red"]), 0))
    out = {}
    for i, bd in enumerate(bodies):
        if tot[i] == 0 or clr[i] < 0.8 * tot[i]:
            continue
        out[bd["lakeId"]] = {"openWaterPx": int(ow[i]), "weedPx": int(wd[i]), "typicalPx": int(ty[i]),
                             "ndci": float(ndci_sum[i] / ow[i]) if ow[i] >= 5 else None,
                             "turbidity": float(red_sum[i] / ow[i]) if ow[i] >= 5 else None}
    date = catalog.item_date(it).isoformat()
    storage.put_data_json(f"areas/{area.id}/latest.json", {"date": date, "sceneIds": [p["id"] for p in passes],
                                                            "pxHa": g20.px_area_m2 / 1e4, "lakes": out})
    # latest frame and lake crops
    fine = frames.mercator_grid(area.bbox, 10.0)
    fr = frames.frame("S2", passes, fine)
    url = storage.put_public(f"areas/{area.id}/frames/latest.webp",
                             frames.to_webp(fr["rgb"][::2, ::2], fr["valid"][::2, ::2], 74), "image/webp")
    coarse = Grid(fine.crs, fine.transform * fine.transform.scale(2, 2), fr["rgb"][::2, ::2].shape[1],
                  fr["rgb"][::2, ::2].shape[0])
    storage.put_data_json(f"areas/{area.id}/frames/latest.json", {
        "season": "latest", "date": date, "source": "S2", "url": url, "corners": frames.corners_lonlat(coarse), "resM": 20})

    def crop(body):
        g = reproject_geom(body["geomUtm"], b["grid"].crs, MERCATOR)
        box = frames.crop_box(fine, g)
        if box:
            storage.put_public(f"lakes/{body['lakeId']}/frames/latest.webp",
                               frames.cut(fr, box, 360, outline=frames.rings_px(fine, g)), "image/webp")

    with ThreadPoolExecutor(16) as ex:
        list(ex.map(crop, [x for x in bodies if x["kind"] == "lake"]))
    return {"ok": True, "date": date}


# ------------------------------------------------------------------------------------------ 5. radar flood events
def radar_events(event, context=None):
    area = _area(event["areaId"])
    out = []
    g = frames.mercator_grid(area.bbox, 20.0)
    for ev in area.events:
        try:
            m = radar.event_map(g, ev["date"])
        except Exception as ex:
            log.warning("radar event %s %s failed: %s", area.id, ev["date"], ex)
            m = None
        if not m:
            continue
        rgba = np.zeros(g.shape + (4,), dtype=np.uint8)
        rgba[m["usual"] & m["valid"]] = (37, 99, 235, 150)
        rgba[m["unusual"]] = (255, 77, 46, 230)
        import io as _io
        from PIL import Image
        buf = _io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(buf, format="WEBP", lossless=True, method=4)
        url = storage.put_public(f"areas/{area.id}/events/{m['date']}.webp", buf.getvalue(), "image/webp")
        out.append({**ev, "sceneDate": m["date"], "sceneId": m["sceneId"], "url": url, "corners": frames.corners_lonlat(g),
                    "unusualHa": m["unusualHa"], "baselineScenes": m["baselineScenes"]})
    storage.put_data_json(f"areas/{area.id}/events.json", out)
    return {"ok": True, "events": len(out)}


# ------------------------------------------------------------------------------------------ 6. names
def name_lakes(event, context=None):
    area = _area(event["areaId"])
    b = _base(area.id)
    deadline = time.time() + float(event.get("budgetSeconds", 780))
    try:
        got = storage.get_data_json(f"areas/{area.id}/names.json")
    except Exception:
        got = {}
    todo = sorted([x for x in b["bodies"] if x["kind"] == "lake" and x["lakeId"] not in got], key=lambda x: -x["areaHa"])
    for body in todo:
        if time.time() > deadline:
            break
        try:
            got[body["lakeId"]] = names.water_body_name(body["lat"], body["lon"], body["areaHa"])
        except Exception as ex:
            log.info("naming failed %s: %s", body["lakeId"], ex)
    storage.put_data_json(f"areas/{area.id}/names.json", got)
    return {"ok": True, "named": len(got), "remaining": max(0, len(todo) - len(got))}


# ------------------------------------------------------------------------------------------ 7. aggregate
def _load_looks(area_id: str) -> dict[str, list[dict]]:
    by_lake: dict[str, list[dict]] = {}
    keys = storage.list_keys(C.DATA_BUCKET or "data", f"areas/{area_id}/looks/")

    def load(k):
        try:
            return storage.get_data_json(k)
        except Exception:
            return None

    with ThreadPoolExecutor(16) as ex:
        docs = [d for d in ex.map(load, keys) if d]
    for d in docs:
        for lake_id, (tot, val, clr, wat, cn) in d["lakes"].items():
            by_lake.setdefault(lake_id, []).append({"season": d["season"], "date": d["date"], "source": d["source"],
                                                    "total": tot, "valid": val, "clear": clr, "water": wat, "cloudNear": bool(cn)})
    return by_lake


def _opt(path: str, default):
    try:
        return storage.get_data_json(path)
    except Exception:
        return default


def aggregate(event, context=None):
    area = _area(event["areaId"])
    b = _base(area.id)
    grid, bodies = b["grid"], b["bodies"]
    land = _opt(f"areas/{area.id}/landcover.json", {})
    rn = _opt(f"areas/{area.id}/rain.json", {"lakes": {}, "area": {}})
    latest = _opt(f"areas/{area.id}/latest.json", {"lakes": {}})
    nm = _opt(f"areas/{area.id}/names.json", {})
    layers = _opt(f"areas/{area.id}/layers.json", {})
    events = _opt(f"areas/{area.id}/events.json", [])
    by_date = {e["date"]: e for e in area.events}            # titles and notes follow the current area definition
    events = [{**e, **{k: by_date[e["date"]][k] for k in ("title", "detail")}} if e.get("date") in by_date else e
              for e in events]
    looks = _load_looks(area.id)
    frame_meta = []
    for k in storage.list_keys(C.DATA_BUCKET or "data", f"areas/{area.id}/frames/"):
        fm = _opt(k, None)
        if fm:
            frame_meta.append(fm)
    frame_meta.sort(key=lambda f: (f["season"] == "latest", f["season"] if f["season"] != "latest" else 9999))
    frame_seasons = [f["season"] for f in frame_meta]
    px_ha = grid.px_area_m2 / 1e4
    summaries, details, features = [], [], []
    grades: dict[str, int] = {}
    tot_hist = tot_lost = tot_built = 0.0
    for body in bodies:
        lid = body["lakeId"]
        name = (nm.get(lid) or {}).get("name") or names.geonames_near(body["lat"], body["lon"], 400) or \
            ("River stretch" if body["kind"] == "river" else "Unnamed water body")
        admin = {k: v for k, v in (nm.get(lid) or {}).items() if k not in ("name", "source")}
        st = land.get(lid) or {"jrc": {"histPx": 0, "lostPx": 0}, "land": {"pxHa": px_ha}}
        series = metrics.season_series(looks.get(lid, []), px_ha)
        complete = rn.get("complete", {})
        lake_rain = {int(k): v for k, v in (rn.get("lakes", {}).get(lid) or {}).items() if complete.get(str(k), False)}
        lt = latest.get("lakes", {}).get(lid)
        lt = {**lt, "date": latest.get("date"), "pxHa": latest.get("pxHa", 0.04)} if lt else None
        summ = metrics.lake_summary(body, st["jrc"], st["land"], series, lake_rain, lt) if body["kind"] == "lake" else None
        geo_feat = lakes.lonlat_feature(body, grid.crs)
        grade = (summ or {}).get("grade", {}).get("grade")
        if grade:
            grades[grade] = grades.get(grade, 0) + 1
        if summ:
            tot_hist += summ["historicHa"]
            tot_lost += summ["lostHa"]
            tot_built += summ.get("builtHa") or 0
        row = {"PK": f"AREA#{area.id}", "SK": f"LAKE#{lid}", "lakeId": lid, "areaId": area.id, "name": name,
               "kind": body["kind"], "areaHa": body["areaHa"], "lon": body["lon"], "lat": body["lat"],
               "grade": grade, "score": (summ or {}).get("grade", {}).get("score"),
               "lostPct": (summ or {}).get("lostPct"), "lostHa": (summ or {}).get("lostHa"),
               "builtPct": (summ or {}).get("builtPct"), "builtHa": (summ or {}).get("builtHa"),
               "retention": ((summ or {}).get("retention") or {}).get("ratio"),
               "weedPct": ((summ or {}).get("quality") or {}).get("weedPct")}
        summaries.append(row)
        if summ:
            details.append({"PK": f"LAKE#{lid}", "SK": "META", "lakeId": lid, "areaId": area.id, "name": name,
                            "nameSource": (nm.get(lid) or {}).get("source", "GeoNames/generated"), "admin": admin,
                            "kind": body["kind"], "areaHa": body["areaHa"], "lon": body["lon"], "lat": body["lat"],
                            "geometry": geo_feat["geometry"], "metrics": summ, "findings": metrics.lake_findings(summ),
                            "frames": frame_seasons, "latestDate": latest.get("date"),
                            "scienceVersion": C.SCIENCE_VERSION, "updatedAt": store.now_iso(),
                            "GSI1PK": f"AREA#{area.id}", "GSI1SK": f"{grade or 'Z'}#{lid}"})
        geo_feat["properties"].update({"name": name, "grade": grade, "lostPct": row["lostPct"], "builtPct": row["builtPct"],
                                       "score": row["score"]})
        features.append(geo_feat)
    store.batch_put(summaries + details)
    storage.put_public_json(f"areas/{area.id}/lakes.geojson", {"type": "FeatureCollection", "features": features}, 300)
    st = {"lakes": sum(1 for x in bodies if x["kind"] == "lake"), "rivers": sum(1 for x in bodies if x["kind"] == "river"),
          "historicHa": round(tot_hist), "lostHa": round(tot_lost), "builtOverHa": round(tot_built), "grades": grades,
          "rain": rn.get("area", {}), "latestDate": latest.get("date")}
    manifest = {"id": area.id, **area.public(), "stats": st, "frames": frame_meta, "layers": layers, "radarEvents": events,
                "lakesUrl": f"/{C.PUBLIC_PREFIX}areas/{area.id}/lakes.geojson", "updatedAt": store.now_iso(),
                "scienceVersion": C.SCIENCE_VERSION}
    storage.put_public_json(f"areas/{area.id}/area.json", manifest, 300)
    store.update(f"AREA#{area.id}", "META", sets={"status": "ready", "stage": "done", "finishedAt": store.now_iso(),
                                                   "stats": st, "manifest": f"/{C.PUBLIC_PREFIX}areas/{area.id}/area.json"})
    store.bump_stats(lakesAnalyzed=st["lakes"])
    return {"ok": True, **st}


def failed(event, context=None):
    """Catch-all: mark the area failed so the UI can say so."""
    area_id = (event or {}).get("areaId") or (event or {}).get("input", {}).get("areaId")
    if area_id:
        err = event.get("error") or {}
        store.update(f"AREA#{area_id}", "META", sets={"status": "failed", "stage": "failed",
                                                       "error": str(err.get("Cause", err))[:500]})
    return {"ok": False}

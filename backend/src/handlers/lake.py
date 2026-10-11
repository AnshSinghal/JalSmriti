"""Any water body in India or Nepal, analysed on demand (Step Functions).

  Find -> Parallel[ Looks (1987-now water history + frames) | Static (land cover, rain) | Latest (quality) ] -> Aggregate

Pre-loaded areas answer instantly from their area run; elsewhere the user clicks on the map and this pipeline
builds the same lake page in one to three minutes.
"""
from __future__ import annotations

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from jalsmriti import areas as A
from jalsmriti import catalog, frames, geo, lakes, landcover, metrics, names, rain, storage, store, water
from jalsmriti import config as C
from jalsmriti.raster import MERCATOR, Grid, near, rasterize_labels, reproject_geom, to_lonlat_geom, zonal_count

log = logging.getLogger()
log.setLevel(logging.INFO)


def _body(lake_id: str) -> tuple[dict, Grid]:
    from shapely import wkt
    d = storage.get_data_json(f"lakes/{lake_id}/body.json")
    d["geomUtm"] = wkt.loads(d["wkt"])
    return d, Grid.from_dict(d["grid"])


def _set(job_id: str, **kw):
    store.update(f"JOB#{job_id}", "META", sets=kw)


def _step_done(event: dict, step: str) -> None:
    """Parallel branches each flag their own attribute, so progress updates never overwrite each other."""
    if event.get("jobId"):
        try:
            _set(event["jobId"], **{f"step_{step}": True})
        except Exception:
            pass


# ------------------------------------------------------------------------------------------ find
def find(event, context=None):
    lat, lon, job = float(event["lat"]), float(event["lon"]), event["jobId"]
    area = A.area_for(lat, lon)
    # 1. a pre-loaded area already knows its water bodies
    if area and storage.data_exists(f"areas/{area.id}/base.json"):
        from jalsmriti.raster import load_npz
        meta = storage.get_data_json(f"areas/{area.id}/base.json")
        g = Grid.from_dict(meta["grid"])
        labels = load_npz(storage.get_data(f"areas/{area.id}/base.npz"))["labels"]
        r, c = g.lonlat_to_rowcol(lon, lat)
        win = labels[max(r - 3, 0):r + 4, max(c - 3, 0):c + 4]
        vals = [v for v in np.unique(win) if v > 0]
        if vals:
            body = meta["bodies"][int(vals[0]) - 1]
            if store.get(f"LAKE#{body['lakeId']}"):
                _set(job, status="done", lakeId=body["lakeId"], result={"lakeId": body["lakeId"], "existing": True})
                return {"done": True, "lakeId": body["lakeId"]}
    # 2. find the water body at the point from the JRC record
    g = Grid.around(lon, lat, 3000, C.AREA_RES_M)
    j = landcover.jrc(g)
    poly = lakes.body_at(g, j, lon, lat)
    if poly is None:
        _set(job, status="done", result={"lakeId": None, "why": "No water body seen here in 1984-2020 (JRC Global Surface Water)."})
        return {"done": True, "lakeId": None}
    # if the body runs off this window, widen once
    l, b, r_, t = g.bounds
    pl, pb, pr, pt = poly.bounds
    if pl <= l + 60 or pb <= b + 60 or pr >= r_ - 60 or pt >= t - 60:
        g = Grid.around(lon, lat, 9000, C.AREA_RES_M)
        j = landcover.jrc(g)
        poly = lakes.body_at(g, j, lon, lat) or poly
    kind, compact, length = lakes.classify_shape(poly)
    rp = to_lonlat_geom(poly.representative_point(), g.crs)
    lake_id = f"x-{geo.geohash(rp.y, rp.x, 8)}"
    existing = store.get(f"LAKE#{lake_id}")
    if existing and existing.get("scienceVersion") == C.SCIENCE_VERSION:
        _set(job, status="done", lakeId=lake_id, result={"lakeId": lake_id, "existing": True})
        return {"done": True, "lakeId": lake_id}
    # analysis grid: the lake plus a margin
    minx, miny, maxx, maxy = poly.bounds
    pad = max(400.0, 0.3 * max(maxx - minx, maxy - miny))
    bbox_utm = (minx - pad, miny - pad, maxx + pad, maxy + pad)
    from affine import Affine
    res = C.AREA_RES_M
    x0, y1 = math.floor(bbox_utm[0] / res) * res, math.ceil(bbox_utm[3] / res) * res
    w = int(math.ceil((bbox_utm[2] - x0) / res))
    h = int(math.ceil((y1 - bbox_utm[1]) / res))
    lg = Grid(g.crs, Affine(res, 0, x0, 0, -res, y1), w, h)
    simple = poly.simplify(res * 0.5, preserve_topology=True)
    body = {"lakeId": lake_id, "kind": kind, "areaHa": round(poly.area / 1e4, 2), "compactness": round(compact, 3),
            "lengthM": round(length), "lon": round(rp.x, 6), "lat": round(rp.y, 6), "wkt": simple.wkt,
            "grid": lg.to_dict(), "areaId": area.id if area else None, "bbox": lg.bbox_lonlat()}
    storage.put_data_json(f"lakes/{lake_id}/body.json", body)
    _set(job, lakeId=lake_id, stage="reading 40 years of satellite images")
    return {"done": False, "lakeId": lake_id}


# ------------------------------------------------------------------------------------------ looks + frames
def looks(event, context=None):
    lake_id = event["lakeId"]
    body, g = _body(lake_id)
    labels = rasterize_labels([body["geomUtm"]], g)
    bbox = body["bbox"]
    area = A.AREAS.get(body.get("areaId") or "")
    window = area.look if area else ("10-15", "02-28")
    targets = {min(range(C.FIRST_SEASON, C.CURRENT_SEASON), key=lambda s: abs(s - t)) for t in C.FRAME_SEASONS}

    def season(s):
        src = "S2" if s >= C.S2_FIRST_SEASON else "LS"
        out = []
        try:
            its = catalog.pick_season_scenes(src, bbox, s, window, n=2, max_cloud=40)
        except Exception as ex:
            log.info("search failed %s: %s", s, ex)
            return out, None
        frame = None
        for it in its:
            try:
                passes = catalog.same_pass_items(src, bbox, it)
                det = water.detect(src, passes, g)
                tot = int(zonal_count(labels, 1)[0])
                cloud_near = int(zonal_count(labels, 1, near(det["cloud"], C.LOOK_CLOUD_BUFFER_M, g.res))[0]) > 0
                lk = {"season": s, "date": catalog.item_date(it).isoformat(), "source": src, "total": tot,
                      "valid": int(zonal_count(labels, 1, det["valid"])[0]), "clear": int(zonal_count(labels, 1, det["clear"])[0]),
                      "water": int(zonal_count(labels, 1, det["water"])[0]), "cloudNear": cloud_near}
                out.append(lk)
                usable = lk["valid"] >= C.LOOK_MIN_VALID_FRAC * tot and lk["clear"] >= C.LOOK_MIN_CLEAR_FRAC * tot and not cloud_near
                if s in targets and frame is None and usable:
                    fg_res = 10.0 if src == "S2" else 30.0
                    merc = reproject_geom(body["geomUtm"], g.crs, MERCATOR)
                    mb = Grid.for_bbox(bbox, fg_res, crs=MERCATOR)
                    fr = frames.frame(src, passes, mb)
                    box = frames.crop_box(mb, merc)
                    if box:
                        storage.put_public(f"lakes/{lake_id}/frames/{s}.webp",
                                           frames.cut(fr, box, 360, outline=frames.rings_px(mb, merc)), "image/webp")
                        frame = s
            except Exception as ex:
                log.info("look failed %s %s: %s", s, it["id"], ex)
        return out, frame

    all_looks, frame_list = [], []
    with ThreadPoolExecutor(8) as ex:
        for lks, fr in ex.map(season, range(C.FIRST_SEASON, C.CURRENT_SEASON)):
            all_looks += lks
            if fr:
                frame_list.append(fr)
    storage.put_data_json(f"lakes/{lake_id}/looks.json", {"looks": all_looks, "frames": sorted(frame_list)})
    _step_done(event, "looks")
    return {"ok": True, "looks": len(all_looks)}


# ------------------------------------------------------------------------------------------ land cover + rain
def static(event, context=None):
    lake_id = event["lakeId"]
    body, g = _body(lake_id)
    labels = rasterize_labels([body["geomUtm"]], g)
    j = landcover.jrc(g)
    occ, ext, trn = j["occurrence"], j["extent"], j["transitions"]
    hist = (ext == 1) & (occ >= C.JRC_OCCURRENCE_MIN)
    lulc = landcover.io_lulc(g)
    wc = landcover.worldcover(g)
    last = lulc[max(lulc)]
    lost = np.isin(trn, C.JRC_LOST) & hist
    z = lambda m: int(zonal_count(labels, 1, m)[0])
    groups = {"built": [C.IO_BUILT], "vegetation": [C.IO_TREES, C.IO_FLOODED_VEG, C.IO_RANGE], "crops": [C.IO_CROPS],
              "bare": [C.IO_BARE], "water": [C.IO_WATER]}
    hp = z(hist)
    stats = {"jrc": {"histPx": hp, "permanentPx": z(np.isin(trn, C.JRC_PERMANENT) & hist),
                     "seasonalPx": z(np.isin(trn, C.JRC_SEASONAL) & hist), "lostPx": z(lost),
                     "newPx": z(np.isin(trn, C.JRC_NEW) & hist), "typicalPx": z(hist & (occ >= 50)),
                     "meanOcc": float(zonal_count(labels, 1, np.where(hist, occ, 0))[0] / hp) if hp else None},
             "land": {"pxHa": g.px_area_m2 / 1e4,
                      "builtPxByYear": {str(y): z((a == C.IO_BUILT) & hist) for y, a in lulc.items()},
                      "builtPersistentPx": z(landcover.built_persistent(lulc) & hist), "worldcoverBuiltPx": z((wc == 50) & hist),
                      "lostNow": {k: z(lost & np.isin(last, v)) for k, v in groups.items()}}}
    area = A.AREAS.get(body.get("areaId") or "")
    months = area.rain if area else (6, 7, 8, 9)
    try:
        tot, comp = rain.seasonal(body["lat"], body["lon"], list(range(C.FIRST_SEASON, C.CURRENT_SEASON + 1)), months)
        rn = {str(k): v for k, v in tot.items() if comp.get(k)}
    except Exception as ex:
        log.warning("rain failed: %s", ex)
        rn = {}
    storage.put_data_json(f"lakes/{lake_id}/static.json", {"stats": stats, "rain": rn})
    _step_done(event, "static")
    return {"ok": True}


# ------------------------------------------------------------------------------------------ latest look
def latest(event, context=None):
    import datetime as _dt
    lake_id = event["lakeId"]
    body, g30 = _body(lake_id)
    bbox = body["bbox"]
    today = _dt.date.today()
    items = catalog.search(C.EARTH_SEARCH, C.S2_COLLECTION, bbox, f"{(today - _dt.timedelta(days=120)).isoformat()}/{today.isoformat()}",
                           {"eo:cloud_cover": {"lt": 50}}, limit=100)
    items.sort(key=lambda it: catalog.item_date(it), reverse=True)
    out = None
    for it in items[:8]:
        passes = catalog.same_pass_items("S2", bbox, it)
        g = Grid(g30.crs, g30.transform * g30.transform.scale(1 / 1.5, 1 / 1.5), int(g30.width * 1.5), int(g30.height * 1.5))
        labels = rasterize_labels([body["geomUtm"]], g)
        det = water.detect("S2", passes, g, bands=("red", "rededge1"))
        tot = int(zonal_count(labels, 1)[0])
        clr = int(zonal_count(labels, 1, det["clear"])[0])
        if tot == 0 or clr < 0.8 * tot:
            continue
        occ = landcover.jrc(g, layers=("occurrence",))["occurrence"]
        refl = det["refl"]
        with np.errstate(invalid="ignore", divide="ignore"):
            ndvi = (refl["nir"] - refl["red"]) / (refl["nir"] + refl["red"])
            ndci = (refl["rededge1"] - refl["red"]) / (refl["rededge1"] + refl["red"])
        typical = occ >= 50
        weed = det["clear"] & typical & (ndvi > C.FLOATING_VEG_NDVI) & ~det["water"]
        ow = int(zonal_count(labels, 1, det["water"])[0])
        out = {"date": catalog.item_date(it).isoformat(), "pxHa": g.px_area_m2 / 1e4, "openWaterPx": ow,
               "weedPx": int(zonal_count(labels, 1, weed)[0]), "typicalPx": int(zonal_count(labels, 1, typical)[0]),
               "ndci": float(zonal_count(labels, 1, np.where(det["water"], np.nan_to_num(ndci), 0))[0] / ow) if ow >= 5 else None,
               "turbidity": float(zonal_count(labels, 1, np.where(det["water"], np.nan_to_num(refl["red"]), 0))[0] / ow) if ow >= 5 else None}
        merc = reproject_geom(body["geomUtm"], g30.crs, MERCATOR)
        mb = Grid.for_bbox(bbox, 10.0, crs=MERCATOR)
        fr = frames.frame("S2", passes, mb)
        box = frames.crop_box(mb, merc)
        if box:
            storage.put_public(f"lakes/{lake_id}/frames/latest.webp", frames.cut(fr, box, 360, outline=frames.rings_px(mb, merc)),
                               "image/webp")
        break
    storage.put_data_json(f"lakes/{lake_id}/latest.json", out or {})
    _step_done(event, "latest")
    return {"ok": True, "date": (out or {}).get("date")}


# ------------------------------------------------------------------------------------------ aggregate
def aggregate(event, context=None):
    lake_id, job = event["lakeId"], event.get("jobId")
    body, g = _body(lake_id)
    lk = storage.get_data_json(f"lakes/{lake_id}/looks.json")
    st = storage.get_data_json(f"lakes/{lake_id}/static.json")
    lt = storage.get_data_json(f"lakes/{lake_id}/latest.json") if storage.data_exists(f"lakes/{lake_id}/latest.json") else {}
    series = metrics.season_series([{**x} for x in lk["looks"]], g.px_area_m2 / 1e4)
    rn = {int(k): v for k, v in st.get("rain", {}).items()}
    summ = metrics.lake_summary(body, st["stats"]["jrc"], st["stats"]["land"], series, rn, lt or None)
    try:
        nm = names.water_body_name(body["lat"], body["lon"], body["areaHa"])
    except Exception:
        nm = {}
    if nm.get("source") not in names.REAL_SOURCES:      # no name of its own: GeoNames close by, else what is near
        gn = names.geonames_near(body["lat"], body["lon"], 500)
        if gn:
            nm = {**nm, "name": gn, "source": "GeoNames"}
        else:
            area = A.AREAS.get(body.get("areaId") or "")
            near = names.geonames_anchors([body["lon"], body["lat"], body["lon"], body["lat"]])
            f = names.fallback_name(body["lat"], body["lon"], body["kind"], near, [],
                                    nm if nm.get("source") == "generated" else None,
                                    (area.names or {}).get("en") if area else None)
            nm = {**nm, "name": f["name"], "source": f["source"]}
    feat = lakes.lonlat_feature({"lakeId": lake_id, "kind": body["kind"], "areaHa": body["areaHa"], "geomUtm": body["geomUtm"]}, g.crs)
    frames_list = lk.get("frames", []) + (["latest"] if lt else [])
    item = {"PK": f"LAKE#{lake_id}", "SK": "META", "lakeId": lake_id, "areaId": body.get("areaId") or "other",
            "name": nm.get("name"), "nameSource": nm.get("source"), "admin": {k: v for k, v in nm.items() if k not in ("name", "source")},
            "kind": body["kind"], "areaHa": body["areaHa"], "lon": body["lon"], "lat": body["lat"], "geometry": feat["geometry"],
            "metrics": summ, "findings": metrics.lake_findings(summ), "frames": frames_list, "latestDate": (lt or {}).get("date"),
            "onDemand": True, "scienceVersion": C.SCIENCE_VERSION, "updatedAt": store.now_iso(),
            "GSI1PK": f"AREA#{body.get('areaId') or 'other'}", "GSI1SK": f"{(summ.get('grade') or {}).get('grade') or 'Z'}#{lake_id}"}
    store.put(item)
    store.bump_stats(lakesAnalyzed=1)
    if job:
        _set(job, status="done", result={"lakeId": lake_id, "existing": False}, finishedAt=store.now_iso())
    return {"ok": True, "lakeId": lake_id}


def failed(event, context=None):
    job = (event or {}).get("jobId")
    if job:
        err = (event or {}).get("error") or {}
        _set(job, status="failed", error=str(err.get("Cause", err))[:400])
    return {"ok": False}

"""Monsoon water seen by radar (Sentinel-1 RTC, 10 m, sees through cloud).

Calm open water is dark to C-band radar. A "sighting" is water that is NOT usually there at that time of year:
VV backscatter (5x5 mean) below -18 dB AND at least 3 dB darker than the median of the same orbit in other
years within +-20 days of the same date. Comparing with the same season (not the dry season) stops flooded
paddy fields and seasonal tanks from being counted as floods.

Limits: radar cannot see water between tall buildings (it bounces off walls) and misses water under crops or
trees; a sighting means water was seen, absence means nothing.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
from rasterio.enums import Resampling

from . import catalog
from . import config as C
from .raster import Grid, box_mean, read

log = logging.getLogger(__name__)


def vv_db(item: dict, grid: Grid) -> np.ndarray:
    a = read(item["assets"]["vv"]["href"], grid, dtype="float32", resampling=Resampling.average, src_nodata=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        db = 10 * np.log10(np.where(a > 0, a, np.nan))
    return box_mean(db, 2 if grid.res <= 12 else 1)


def _season_items(bbox: list[float], first_year: int, last_year: int, months=(6, 7, 8, 9, 10, 11, 12)) -> list[dict]:
    import calendar
    items = []
    for y in range(first_year, last_year + 1):
        last_day = calendar.monthrange(y, months[-1])[1]
        items += catalog.s1_items(bbox, f"{y}-{months[0]:02d}-01", f"{y}-{months[-1]:02d}-{last_day:02d}")
    # one item per (date, orbit): adjacent slices of the same pass duplicate coverage
    seen, out = set(), []
    for it in items:
        k = (catalog.item_date(it), it["properties"].get("sat:relative_orbit"))
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def sightings(grid: Grid, core: np.ndarray, first_year: int = C.S1_FIRST_YEAR, last_year: int | None = None,
              months=(6, 7, 8, 9, 10, 11, 12), workers: int = 24, max_items: int = 420) -> dict:
    """Dates when radar saw unusual water inside `core` (boolean mask on grid).

    Returns {"sightings": [{date, orbit, haCore, haGrid}], "scenesChecked": n, "years": [..], "usualWaterHa": x}.
    """
    last_year = last_year or C.CURRENT_SEASON
    items = _season_items(grid.bbox_lonlat(), first_year, last_year, months)
    if len(items) > max_items:   # keep it bounded: thin the oldest years first
        items.sort(key=catalog.item_date, reverse=True)
        items = items[:max_items]
    by_id = {}

    def load(it):
        try:
            return it["id"], vv_db(it, grid)
        except Exception as ex:   # one bad scene must not sink the check
            log.warning("s1 read failed %s: %s", it["id"], ex)
            return it["id"], None

    with ThreadPoolExecutor(workers) as ex:
        for iid, arr in ex.map(load, items):
            if arr is not None:
                by_id[iid] = arr
    items = [it for it in items if it["id"] in by_id]
    by_orbit = defaultdict(list)
    for it in items:
        by_orbit[it["properties"].get("sat:relative_orbit")].append(it)
    px_ha = grid.px_area_m2 / 1e4
    out, usual = [], []
    for orbit, its in by_orbit.items():
        for it in its:
            d = catalog.item_date(it)
            refs = [by_id[o["id"]] for o in its if catalog.item_date(o).year != d.year
                    and catalog.doy_distance(catalog.item_date(o), d) <= C.S1_BASELINE_DAYS]
            if len(refs) < 2:
                continue
            base = np.nanmedian(np.stack(refs), axis=0)
            now = by_id[it["id"]]
            usual_w = base < C.S1_WATER_DB
            unusual = (now < C.S1_WATER_DB) & ~usual_w & ((base - now) > C.S1_DROP_DB)
            usual.append(float((usual_w & core).sum()) * px_ha)
            n_core = int((unusual & core).sum())
            if n_core >= C.S1_MIN_SIGHTING_PX:
                out.append({"date": d.isoformat(), "orbit": orbit, "haCore": round(n_core * px_ha, 2),
                            "haGrid": round(float(unusual.sum()) * px_ha, 1)})
    out.sort(key=lambda s: s["date"])
    return {"sightings": out, "scenesChecked": len(items), "years": sorted({catalog.item_date(i).year for i in items}),
            "usualWaterHa": round(float(np.median(usual)), 2) if usual else 0.0}


def event_map(grid: Grid, event_date: str, search_days: int = 1) -> dict | None:
    """Unusual water on one flood date over a whole area (for the area's flood-event layer)."""
    d = date.fromisoformat(event_date)
    bbox = grid.bbox_lonlat()
    flood = catalog.s1_items(bbox, catalog.iso(catalog.shift(d, -search_days)), catalog.iso(catalog.shift(d, search_days)))
    if not flood:
        return None
    flood.sort(key=lambda it: catalog.days_between(catalog.item_date(it), d))
    fi = flood[0]
    orbit = fi["properties"].get("sat:relative_orbit")
    refs = []
    years = [y for y in range(2015, C.CURRENT_SEASON + 1) if y != d.year]
    years.sort(key=lambda y: abs(y - d.year))           # nearest years first: land use changes slowly
    for y in years:
        if len(refs) >= 8:
            break
        try:
            same_day = d.replace(year=y)
        except ValueError:          # 29 February
            same_day = d.replace(year=y, day=28)
        refs += catalog.s1_items(bbox, catalog.iso(catalog.shift(same_day, -C.S1_BASELINE_DAYS)),
                                 catalog.iso(catalog.shift(same_day, C.S1_BASELINE_DAYS)), orbit=orbit, limit=10)
    if len(refs) < 2:
        return None
    refs = refs[:8]
    with ThreadPoolExecutor(8) as ex:
        ref_arrs = [a for a in ex.map(lambda it: vv_db(it, grid), refs)]
    base = np.nanmedian(np.stack(ref_arrs), axis=0)
    now = vv_db(fi, grid)
    usual_w = base < C.S1_WATER_DB
    unusual = (now < C.S1_WATER_DB) & ~usual_w & ((base - now) > C.S1_DROP_DB)
    return {"date": catalog.item_date(fi).isoformat(), "sceneId": fi["id"], "orbit": orbit, "unusual": unusual,
            "usual": usual_w, "valid": np.isfinite(now), "baselineScenes": len(refs),
            "unusualHa": round(float(unusual.sum()) * grid.px_area_m2 / 1e4, 1)}

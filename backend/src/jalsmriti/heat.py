"""Summer heat: how hot the ground gets around a place before the monsoon, next to built-up ground and lake water.

Landsat 8 and 9 measure the temperature of the surface itself (roofs, roads, soil, tree canopy, water), not of the
air: Collection 2 Level-2 band ST_B10, from the TIRS thermal sensor (100 m pixels, delivered by USGS on a 30 m grid),
read from Microsoft Planetary Computer. Landsat crosses India and Nepal at about 10:30-11:00 local time, so this is
mid-morning heat; the same surfaces get hotter still in the afternoon.

How it is measured
  * Summers: 15 March - 31 May of the last three years whose summer is over (summer Y counts from 1 June of Y).
  * Passes: Landsat 8/9 scenes with less than 30 % cloud. The rows one satellite records on one day are one pass and
    are mosaicked. The 10 passes with the least scene cloud are read; the 8 with the largest usable share of the
    window are kept, and a pass with less than 40 % of the window usable is dropped. At least 2 passes are needed.
    Equally clear passes are taken from the summers in turn, nearest the middle of the window first, so in clear-sky
    places the sample spans the three summers and is centred on the season.
  * Usable pixels: QA_PIXEL not fill and none of dilated cloud, cirrus, cloud or cloud shadow (the same test as
    water.landsat_pass), and a temperature between 5 and 75 deg C (anything else is a missed cloud or a bad pixel).
  * Composite: per pixel, the median of its usable observations; a pixel needs at least 2.
  * Here: the median within 300 m of the point (at least 10 pixels), compared with the median over built-up ground and
    over trees (Impact Observatory land cover 2023) and over lasting water (JRC Global Surface Water: water in at
    least half of the 1984-2020 observations) anywhere in the window. Small ponds read warm: the thermal pixels are
    100 m across, so a pond narrower than that mixes with the ground around it.

One grid
  Everything is read once onto one Web Mercator grid centred on the point, covering 6 km x 6 km on the ground at 30 m
  ground resolution (200 x 200 pixels). Mercator stretches lengths by 1/cos(latitude), so in Mercator metres the
  half-width is 3000 / cos(lat) and a pixel is 30 / cos(lat) wide. The statistics and the map image come from the same
  array, and the map lays the image over its Mercator basemap without resampling. Distances are counted in ground
  metres: the 300 m disk is 10 pixels. Across 6 km the stretch varies by less than 0.1 % anywhere in India and Nepal,
  so the disk and the window are true to size.
"""
from __future__ import annotations

import io
import logging
import math
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
from PIL import Image
from rasterio.enums import Resampling

from . import catalog, frames, landcover
from . import config as C
from .raster import MERCATOR, Grid, read_mosaic

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------- summers and passes
WINDOW = ("03-15", "05-31")          # the pre-monsoon summer (month-day), every year
SUMMER_OVER = (6, 1)                 # summer Y counts once 1 June of Y has come
N_SUMMERS = 3
PLATFORMS = ("landsat-8", "landsat-9")
MAX_SCENE_CLOUD = 30.0               # % scene cloud cover for a scene to be considered at all
MAX_PASSES_READ = 10                 # passes read, least scene cloud first (in CLOUD_STEP % steps) ...
MAX_PASSES_KEPT = 8                  # ... of which those with the most of the window usable are kept (CLEAR_STEP steps)
MIN_CLEAR_FRAC = 0.4                 # ... when at least this share of the window is usable
CLOUD_STEP = 5.0                     # % (as catalog.pick_season_scenes ranks scenes)
CLEAR_STEP = 0.1
MIN_PASSES = 2
MIN_OBS = 2                          # usable observations a pixel needs in the composite
OVERPASS = "10:30-11:00"             # local time when Landsat 8/9 cross India and Nepal

# ---------------------------------------------------------------------------------- grid and place
RADIUS_M = 300.0                     # "here": the place check's radius
CONTEXT_M = 3000.0                   # half-width of the window: 6 km x 6 km on the ground
RES_M = 30.0                         # ground resolution of the grid (Landsat's)

# ---------------------------------------------------------------------------------- surface temperature
ST_SCALE, ST_OFFSET = 0.00341802, 149.0   # Collection 2 ST_B10: kelvin = DN x scale + offset; DN 0 is no data
KELVIN = 273.15
MIN_C, MAX_C = 5.0, 75.0             # surface temperatures outside this range are errors, not weather
QA_FILL = 1 << 0
QA_CLOUDY = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)   # dilated cloud, cirrus, cloud, cloud shadow

# ---------------------------------------------------------------------------------- comparisons
LULC_YEAR = 2023                     # Impact Observatory land cover year for built-up ground and trees
JRC_PERSISTENT = 50.0                # % of 1984-2020 observations with water: water at least half the time
MIN_HERE_PX = 10                     # usable pixels needed for each median ...
MIN_BUILT_PX = 50
MIN_WATER_PX = 20
MIN_TREES_PX = 50
HOTTER_BY_C = 2.0                    # "hotter than built-up ground nearby" from this difference

# ---------------------------------------------------------------------------------- image
SCALE_C = (25, 50)                   # default colour scale, deg C ...
SCALE_STEP_C = 5                     # ... widened in 5-degree steps to cover the window's 2nd-98th percentile
PALETTE = ("#313695", "#74add1", "#fee090", "#f46d43", "#a50026")   # cool to hot: ColorBrewer RdYlBu, colour-blind safe
RING_PX, RING_OUTLINE_PX = 2.0, 1.0  # the 300 m ring: 2 px white with a 1 px dark outline on each side
RING_RGB, RING_OUTLINE_RGB = (255, 255, 255), (24, 24, 24)
IMAGE_PX = 480                       # longest side of the image
WEBP_QUALITY = 82
WORKERS = 4

_STOPS = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in PALETTE], dtype=np.float64)


# ------------------------------------------------------------------------------------------ summers and passes
def summer_years(today: date, n: int = N_SUMMERS) -> list[int]:
    """The last n summers that are over: on 11 Oct 2026 [2024, 2025, 2026]; on 31 May 2026 [2023, 2024, 2025]."""
    last = today.year if today >= date(today.year, *SUMMER_OVER) else today.year - 1
    return list(range(last - n + 1, last + 1))


def _cloud(it: dict) -> float:
    cc = it["properties"].get("eo:cloud_cover")
    return 100.0 if cc is None else float(cc)


def _steps(x: float, step: float) -> int:
    """x in whole steps (half up): small differences in cloud or clear share mean nothing for the composite."""
    return math.floor(x / step + 0.5)


def _days_from_mid(d: date) -> int:
    a, b = (date.fromisoformat(f"{d.year}-{md}") for md in WINDOW)
    return abs((d - (a + (b - a) / 2)).days)


def group_passes(items: list[dict]) -> list[dict]:
    """Landsat 8/9 items grouped into passes (one satellite, one day: all its rows over the window), in reading order.

    Order: scene cloud in steps of CLOUD_STEP % (clearest first). Among equally clear passes the summers take turns,
    and within a summer the pass nearest the middle of the window comes first, so in clear-sky places (where dozens
    of passes have no cloud at all) the passes read are spread over the summers and centred on the season rather than
    all taken from the latest or the hottest weeks. A pass's cloud is that of its clearest row. Items without a
    surface temperature band (USGS sometimes ships reflectance only) are left out.
    """
    rows: dict[tuple[date, str], dict[str, dict]] = {}
    for it in items:
        plat = it["properties"].get("platform")
        if plat in PLATFORMS and {"lwir11", "qa_pixel"} <= set(it.get("assets") or {}):
            rows.setdefault((catalog.item_date(it), plat), {})[it["id"]] = it
    passes = [{"date": d, "platform": plat, "rows": [its[k] for k in sorted(its)],
               "cloud": min(_cloud(it) for it in its.values())} for (d, plat), its in rows.items()]

    def within_summer(p: dict) -> tuple:
        return _steps(p["cloud"], CLOUD_STEP), _days_from_mid(p["date"]), -p["date"].toordinal()

    passes.sort(key=within_summer)
    turns: dict[int, int] = {}
    for p in passes:                                  # each pass's turn within its own summer
        p["turn"] = turns.get(p["date"].year, 0)
        turns[p["date"].year] = p["turn"] + 1
    passes.sort(key=lambda p: (_steps(p["cloud"], CLOUD_STEP), p["turn"], within_summer(p)))
    return passes


def pick_passes(reads: list[dict | None], keep: int = MAX_PASSES_KEPT, min_clear: float = MIN_CLEAR_FRAC) -> list[dict]:
    """The passes to composite: at most `keep` of those read, each with at least `min_clear` of the window usable,
    the largest usable share first in steps of CLEAR_STEP (equal shares keep their reading order, so the summers stay
    balanced). Reads that failed (None) or were skipped as too cloudy are left out."""
    ok = [r for r in reads if r and r.get("usable") is not None and r["clearFrac"] >= min_clear]
    ok.sort(key=lambda r: -_steps(r["clearFrac"], CLEAR_STEP))        # a stable sort
    return ok[:keep]


# ------------------------------------------------------------------------------------------ temperature
def celsius(dn: np.ndarray) -> np.ndarray:
    """ST_B10 digital numbers -> surface temperature in deg C (NaN where there is no data: DN 0 or NaN)."""
    dn = np.asarray(dn, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(dn) & (dn > 0)
    return np.where(ok, dn * ST_SCALE + ST_OFFSET - KELVIN, np.nan).astype(np.float32)


def clear_mask(qa: np.ndarray) -> np.ndarray:
    """QA_PIXEL -> clear pixels: has data (not 0, not fill) and none of dilated cloud, cirrus, cloud, cloud shadow."""
    qa = np.asarray(qa).astype(np.uint16)
    return (qa != 0) & ((qa & QA_FILL) == 0) & ((qa & QA_CLOUDY) == 0)


def plausible(temp: np.ndarray) -> np.ndarray:
    """Temperatures a real surface can have in an Indian or Nepali summer."""
    with np.errstate(invalid="ignore"):
        return np.isfinite(temp) & (temp >= MIN_C) & (temp <= MAX_C)


def composite(stack: np.ndarray, clear_stack: np.ndarray, min_obs: int = MIN_OBS) -> np.ndarray:
    """Per-pixel median of the usable observations (passes along axis 0); NaN where a pixel has fewer than min_obs."""
    vals = np.where(np.asarray(clear_stack, dtype=bool) & np.isfinite(stack), stack, np.nan)
    n = np.isfinite(vals).sum(axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # "All-NaN slice": those pixels are set to NaN below
        med = np.nanmedian(vals, axis=0)
    return np.where(n >= min_obs, med, np.nan).astype(np.float32)


# ------------------------------------------------------------------------------------------ statistics
def disk_mask(shape: tuple[int, int], radius_px: float) -> np.ndarray:
    """Pixels whose centre lies within radius_px of the grid centre (where the point is)."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    return np.hypot(yy - (h - 1) / 2, xx - (w - 1) / 2) <= radius_px


def _median(comp: np.ndarray, mask: np.ndarray | None, min_px: int) -> float | None:
    if mask is None:
        return None
    v = comp[mask & np.isfinite(comp)]
    return round(float(np.median(v)), 1) if v.size >= min_px else None


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(a - b, 1)


def stats_from(comp: np.ndarray, here_mask: np.ndarray, built_mask: np.ndarray | None,
               water_mask: np.ndarray | None, trees_mask: np.ndarray | None) -> dict:
    """The numbers people see, from the composite and boolean masks on the same grid (a missing mask gives None).

    Differences are taken from the rounded medians, so the numbers on the page add up.
    """
    here = _median(comp, here_mask, MIN_HERE_PX)
    built = _median(comp, built_mask, MIN_BUILT_PX)
    water = _median(comp, water_mask, MIN_WATER_PX)
    vs_built = _diff(here, built)
    return {"hereC": here, "builtC": built, "waterC": water, "treesC": _median(comp, trees_mask, MIN_TREES_PX),
            "vsBuiltC": vs_built, "vsWaterC": _diff(here, water),
            "hotter": None if vs_built is None else bool(vs_built >= HOTTER_BY_C)}


# ------------------------------------------------------------------------------------------ image
def scale_for(comp: np.ndarray) -> tuple[int, int]:
    """Colour scale in deg C: 25-50, widened in 5-degree steps when the window's 2nd-98th percentile falls outside."""
    lo, hi = SCALE_C
    v = comp[np.isfinite(comp)]
    if v.size:
        p2, p98 = np.percentile(v, [2, 98])
        lo = min(lo, int(math.floor(p2 / SCALE_STEP_C)) * SCALE_STEP_C)
        hi = max(hi, int(math.ceil(p98 / SCALE_STEP_C)) * SCALE_STEP_C)
    return lo, hi


def colourise(comp: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Temperatures -> RGBA uint8 on the cool-to-hot ramp from lo to hi (clipped at both ends); NaN is transparent."""
    valid = np.isfinite(comp)
    t = np.clip((np.where(valid, comp, lo) - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    pos = t * (len(_STOPS) - 1)
    i = np.minimum(pos.astype(int), len(_STOPS) - 2)
    f = (pos - i)[..., None]
    out = np.zeros(comp.shape + (4,), dtype=np.uint8)
    out[..., :3] = np.round(_STOPS[i] * (1 - f) + _STOPS[i + 1] * f)
    out[..., 3] = np.where(valid, 255, 0)
    return out


def upsample(comp: np.ndarray, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear resize of temperatures that ignores NaN pixels: (temperatures, data coverage 0-1) at the new shape."""
    def resize(a: np.ndarray) -> np.ndarray:
        img = Image.fromarray(a.astype(np.float32), "F").resize((shape[1], shape[0]), Image.BILINEAR)
        return np.asarray(img, dtype=np.float64)
    valid = np.isfinite(comp)
    cover = resize(valid.astype(np.float32))
    total = resize(np.where(valid, comp, 0.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cover > 1e-6, total / cover, np.nan), np.clip(cover, 0.0, 1.0)


def ring_mask(shape: tuple[int, int], radius_px: float, width_px: float = RING_PX) -> np.ndarray:
    """How much of each pixel (0-1) a ring of this radius and width around the centre covers: an anti-aliased mask."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(yy - (h - 1) / 2, xx - (w - 1) / 2)
    return np.clip(width_px / 2 + 0.5 - np.abs(d - radius_px), 0.0, 1.0)


def _paint(rgba: np.ndarray, cover: np.ndarray, rgb: tuple[int, int, int]) -> np.ndarray:
    """Lay a colour over an RGBA image with per-pixel coverage (alpha compositing, so it also works on transparency)."""
    a_s = cover[..., None]
    a_d = rgba[..., 3:4].astype(np.float64) / 255
    a_o = a_s + a_d * (1 - a_s)
    rgb_o = (np.asarray(rgb, dtype=np.float64) * a_s + rgba[..., :3] * a_d * (1 - a_s)) / np.maximum(a_o, 1e-9)
    return np.concatenate([np.round(rgb_o), np.round(a_o * 255)], axis=2).clip(0, 255).astype(np.uint8)


def draw_ring(rgba: np.ndarray, radius_px: float) -> np.ndarray:
    """A thin white ring with a dark outline at radius_px around the image centre: the 300 m "here"."""
    shape = rgba.shape[:2]
    out = _paint(rgba, ring_mask(shape, radius_px, RING_PX + 2 * RING_OUTLINE_PX), RING_OUTLINE_RGB)
    return _paint(out, ring_mask(shape, radius_px, RING_PX), RING_RGB)


def heat_rgba(comp: np.ndarray, lo: float, hi: float, radius_px: float, out_px: int = IMAGE_PX) -> np.ndarray:
    """The map image as RGBA: the composite smoothly enlarged to out_px on its longest side (temperatures are resized
    before colouring, so every colour is on the ramp), no data transparent, and the ring at radius_px grid pixels."""
    h, w = comp.shape
    s = out_px / max(h, w)
    temps, cover = upsample(comp, (max(1, round(h * s)), max(1, round(w * s))))
    return draw_ring(colourise(np.where(cover >= 0.5, temps, np.nan), lo, hi), radius_px * s)


def to_webp(rgba: np.ndarray, quality: int = WEBP_QUALITY) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="WEBP", quality=quality, method=4)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------ reading
def heat_grid(lat: float, lon: float) -> Grid:
    """The one grid everything is read onto: Web Mercator, centred on the point, 2 x CONTEXT_M wide on the ground at
    RES_M ground resolution (Mercator metres are ground metres / cos(lat); see the module notes)."""
    k = 1.0 / math.cos(math.radians(lat))           # Mercator metres per ground metre at this latitude
    return Grid.around(lon, lat, CONTEXT_M * k, RES_M * k, crs=MERCATOR)


def _search(bbox: list[float], year: int) -> list[dict] | None:
    """Landsat Collection 2 Level-2 scenes over the window in one summer (None if the catalogue did not answer)."""
    a, b = WINDOW
    try:
        return catalog.search(C.PLANETARY_COMPUTER, "landsat-c2-l2", bbox, f"{year}-{a}/{year}-{b}",
                              {"eo:cloud_cover": {"lt": MAX_SCENE_CLOUD}})
    except (RuntimeError, OSError) as ex:         # network or catalogue trouble; programming errors still raise
        log.warning("summer heat: Landsat search for %s failed: %s", year, ex)
        return None


def _read_pass(p: dict, grid: Grid) -> dict | None:
    """Temperature and usable pixels of one pass on the grid (None if it could not be read).

    The QA band is read first; a pass too cloudy to be kept is not read further (temp/usable are None).
    """
    hrefs = {key: [it["assets"][key]["href"] for it in p["rows"]] for key in ("qa_pixel", "lwir11")}
    try:
        qa = read_mosaic(hrefs["qa_pixel"], grid, dtype="uint16", resampling=Resampling.nearest, src_nodata=1,
                         use_overviews=False)
        clear = clear_mask(qa)
        if (frac := float(clear.mean())) < MIN_CLEAR_FRAC:
            return {**p, "temp": None, "usable": None, "clearFrac": frac}
        dn = read_mosaic(hrefs["lwir11"], grid, dtype="float32", resampling=Resampling.nearest, src_nodata=0,
                         use_overviews=False)
    except (RuntimeError, OSError) as ex:         # one unreadable scene must not sink the check
        log.warning("summer heat: pass %s %s unreadable: %s", p["date"], p["platform"], ex)
        return None
    temp = celsius(dn)
    usable = clear & plausible(temp)
    return {**p, "temp": temp, "usable": usable, "clearFrac": float(usable.mean())}


def _land(grid: Grid) -> dict | None:
    """Built-up, tree and persistent-water masks on the grid (None if the layers could not be read).

    io_lulc gives the Impact Observatory class as uint8 (0 = no data, so no data is neither built nor trees); jrc gives
    occurrence as float32 percent with no data already set to 0 (never water).
    """
    try:
        lulc = landcover.io_lulc(grid, years=(LULC_YEAR,))[LULC_YEAR]
        occ = landcover.jrc(grid, layers=("occurrence",))["occurrence"]
    except (RuntimeError, OSError) as ex:
        log.warning("summer heat: land cover unavailable: %s", ex)
        return None
    return {"built": lulc == C.IO_BUILT, "trees": lulc == C.IO_TREES, "water": occ >= JRC_PERSISTENT}


def _blank(years: list[int], scenes: list[dict]) -> dict:
    """The stats with every measurement still unknown (same keys, same order as a full answer)."""
    return {"hereC": None, "builtC": None, "waterC": None, "treesC": None, "vsBuiltC": None, "vsWaterC": None,
            "hotter": None, "scenes": scenes, "years": years, "window": list(WINDOW), "radiusM": int(RADIUS_M),
            "contextM": int(CONTEXT_M), "resM": int(RES_M), "scale": None, "overpass": OVERPASS}


def _no_passes_reason(years: list[int], found: list[list[dict] | None], cands: list[dict],
                      reads: list[dict | None], kept: list[dict]) -> str:
    """Why there is no answer, in plain words (found holds each summer's search result, None where it failed)."""
    if all(f is None for f in found):
        return "The Landsat catalogue (Microsoft Planetary Computer) did not answer; please try again later."
    span = f"{years[0]}-{years[-1]}"
    unsearched = [str(y) for y, f in zip(years, found) if f is None]
    unread = sum(r is None for r in reads)
    notes = ([f"the catalogue did not answer for {', '.join(unsearched)}"] if unsearched else []) + \
            ([f"{unread} could not be read"] if unread else [])
    note = f" ({'; '.join(notes)})" if notes else ""
    if not cands:
        return (f"Landsat 8 and 9 saw this spot on no summer day with less than {MAX_SCENE_CLOUD:.0f} % cloud in "
                f"{span}{note}.")
    return (f"Only {len(kept)} of the {len(cands)} summer Landsat passes checked in {span} were clear enough over this "
            f"spot{note}; at least {MIN_PASSES} are needed.")


# ------------------------------------------------------------------------------------------ the measurement
def summer_heat(lat: float, lon: float, today: date | None = None) -> tuple[dict, bytes | None, list | None]:
    """returns (stats, webp_image_bytes_or_None, corners_lonlat_or_None)

    stats (JSON-ready; temperatures in deg C to 0.1): hereC (median within 300 m), builtC, waterC, treesC (medians over
    built-up ground, persistent water and trees in the 6 km window), vsBuiltC = hereC - builtC, vsWaterC = hereC -
    waterC, hotter (vsBuiltC >= 2), scenes (passes used, newest first), years (the summers searched), window, radiusM,
    contextM, resM, scale (the image's colour scale) and overpass. A comparison is None when there are too few pixels
    of that kind. The image is WebP (longest side 480 px) on the Mercator grid; corners are top-left, top-right,
    bottom-right, bottom-left [lon, lat] for a MapLibre image source.

    With fewer than 2 usable passes, image and corners are None and stats carry "error" (a plain reason). "error" is
    also set, with the image kept, when too few clear pixels lie within 300 m for hereC. A scene or land-cover layer
    that cannot be read is logged and skipped; programming errors raise.
    """
    if not (-85.0 < lat < 85.0 and -180.0 <= lon <= 180.0):
        raise ValueError(f"not a point on the map: lat {lat}, lon {lon}")
    t0 = time.time()
    years = summer_years(today or date.today())
    grid = heat_grid(lat, lon)
    bbox = grid.bbox_lonlat()
    with ThreadPoolExecutor(WORKERS) as ex:
        land = ex.submit(_land, grid)                # land cover is read while the passes are found and read
        found = list(ex.map(lambda y: _search(bbox, y), years))
        cands = group_passes([it for items in found if items for it in items])[:MAX_PASSES_READ]
        reads = list(ex.map(lambda p: _read_pass(p, grid), cands))
        masks = land.result()
    kept = pick_passes(reads)
    scenes = [{"date": p["date"].isoformat(), "platform": p["platform"]}
              for p in sorted(kept, key=lambda p: p["date"], reverse=True)]
    if len(kept) < MIN_PASSES:
        log.info("summer heat %.5f,%.5f: %d usable passes of %d read, %.1fs", lat, lon, len(kept), len(cands),
                 time.time() - t0)
        return {**_blank(years, scenes), "error": _no_passes_reason(years, found, cands, reads, kept)}, None, None

    comp = composite(np.stack([p["temp"] for p in kept]), np.stack([p["usable"] for p in kept]))
    radius_px = RADIUS_M / RES_M                     # the grid is RES_M on the ground, whatever the latitude
    built, water, trees = (masks["built"], masks["water"], masks["trees"]) if masks else (None, None, None)
    lo, hi = scale_for(comp)
    stats = {**_blank(years, scenes), **stats_from(comp, disk_mask(grid.shape, radius_px), built, water, trees),
             "scale": [lo, hi]}
    if stats["hereC"] is None:
        stats["error"] = (f"Too few clear summer pixels within {RADIUS_M:.0f} m of this spot to give its temperature "
                          f"(at least {MIN_HERE_PX} are needed).")
    image = to_webp(heat_rgba(comp, lo, hi, radius_px))
    log.info("summer heat %.5f,%.5f: %d passes (%d read), here %s C, built %s C, %.1fs", lat, lon, len(kept),
             len(cands), stats["hereC"], stats["builtC"], time.time() - t0)
    return stats, image, frames.corners_lonlat(grid)

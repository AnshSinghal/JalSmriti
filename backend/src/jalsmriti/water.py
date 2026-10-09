"""Open-water detection for one satellite pass, on any grid.

Sentinel-2 L2A (2016 onwards): a pixel is water when it is clear (scene classes 4/5/6) and either MNDWI > 0 with
SWIR1 < 0.10, or the scene classifier calls it water and NDWI > -0.20 with SWIR1 < 0.12.

Landsat 4/5/7/8/9 Collection 2 surface reflectance (1984 onwards): the same spectral rule (MNDWI > 0 with
SWIR1 < 0.10) on pixels the QA band marks free of cloud, cirrus and shadow. Landsat 7 after May 2003 has
scan-line gaps; they are simply "no data" and the look only counts for a lake when >= 90 % of it has data.
"""
from __future__ import annotations

import numpy as np
from rasterio.enums import Resampling

from . import config as C
from .raster import Grid, opening, read, read_mosaic


def _s2_reflectance(item: dict, key: str, arr: np.ndarray) -> np.ndarray:
    a = item["assets"][key]
    rb = (a.get("raster:bands") or [{}])[0]
    scale = float(rb.get("scale", 0.0001) or 0.0001)
    if item["properties"].get("earthsearch:boa_offset_applied"):
        offset = 0.0
    else:
        try:
            pb = float(item["properties"].get("s2:processing_baseline", "0") or 0)
        except ValueError:
            pb = 0.0
        offset = -0.1 if pb >= 4.0 else 0.0
    out = arr * scale + offset
    out[~np.isfinite(arr) | (arr <= 0)] = np.nan
    return np.clip(out, 1e-4, None)


def _ls_reflectance(arr: np.ndarray) -> np.ndarray:
    out = arr * 0.0000275 - 0.2
    out[~np.isfinite(arr) | (arr <= 0)] = np.nan
    return np.clip(out, 1e-4, None)


def s2_pass(items: list[dict], grid: Grid, bands: tuple[str, ...] = ()) -> dict:
    """Water / clear / cloud masks for one Sentinel-2 pass (all tiles of that pass over the grid)."""
    scl = read_mosaic([it["assets"]["scl"]["href"] for it in items], grid, dtype="uint8",
                      resampling=Resampling.nearest)
    refl = {}
    need = set(("green", "nir", "swir16") + tuple(bands))
    for key in need:
        parts = []
        for it in items:
            raw = read(it["assets"][key]["href"], grid, dtype="float32", resampling=Resampling.average, src_nodata=0)
            parts.append(_s2_reflectance(it, key, raw))
        out = parts[0]
        for p in parts[1:]:
            out = np.where(np.isfinite(out), out, p)
        refl[key] = out
    g, nir, sw = refl["green"], refl["nir"], refl["swir16"]
    with np.errstate(invalid="ignore", divide="ignore"):
        mndwi = (g - sw) / (g + sw)
        ndwi = (g - nir) / (g + nir)
    valid = (scl > 0) & np.isfinite(g) & np.isfinite(sw)
    clear = valid & np.isin(scl, C.S2_CLEAR_CLASSES)
    water = clear & (((mndwi > C.S2_MNDWI_MIN) & (sw < C.S2_SWIR1_MAX)) |
                     ((scl == 6) & (ndwi > C.S2_SCL_WATER_NDWI_MIN) & (sw < C.S2_SCL_WATER_SWIR1_MAX)))
    cloud = opening(np.isin(scl, C.S2_CLOUD_CLASSES), 1)
    return {"water": water, "valid": valid, "clear": clear, "cloud": cloud, "refl": refl, "source": "S2"}


def landsat_pass(items: list[dict], grid: Grid, bands: tuple[str, ...] = ()) -> dict:
    """Water / clear / cloud masks for one Landsat pass (all rows of that pass over the grid)."""
    qa = read_mosaic([it["assets"]["qa_pixel"]["href"] for it in items], grid, dtype="uint16",
                     resampling=Resampling.nearest, src_nodata=1)
    refl = {}
    for key in set(("green", "swir16") + tuple(bands)):
        parts = [_ls_reflectance(read(it["assets"][key]["href"], grid, dtype="float32",
                                      resampling=Resampling.nearest, src_nodata=0)) for it in items]
        out = parts[0]
        for p in parts[1:]:
            out = np.where(np.isfinite(out), out, p)
        refl[key] = out
    g, sw = refl["green"], refl["swir16"]
    fill = (qa & 1).astype(bool) | (qa == 0)
    cloudish = (((qa >> 1) & 1) | ((qa >> 2) & 1) | ((qa >> 3) & 1) | ((qa >> 4) & 1)).astype(bool)
    valid = ~fill & np.isfinite(g) & np.isfinite(sw)
    clear = valid & ~cloudish
    with np.errstate(invalid="ignore", divide="ignore"):
        mndwi = (g - sw) / (g + sw)
    water = clear & (mndwi > C.LS_MNDWI_MIN) & (sw < C.LS_SWIR1_MAX)
    return {"water": water, "valid": valid, "clear": clear, "cloud": cloudish & valid, "refl": refl, "source": "LS"}


def area_clear_score(source: str, items: list[dict], bbox: list[float], res: float = 300.0) -> float:
    """Share of the area that is covered by data and free of cloud, from the QA/SCL band read coarsely."""
    g = Grid.for_bbox(bbox, res)
    try:
        if source == "S2":
            scl = read_mosaic([it["assets"]["scl"]["href"] for it in items], g, dtype="uint8")
            valid = scl > 0
            clear = np.isin(scl, C.S2_CLEAR_CLASSES)
        else:
            qa = read_mosaic([it["assets"]["qa_pixel"]["href"] for it in items], g, dtype="uint16", src_nodata=1)
            valid = (qa != 0) & ~(qa & 1).astype(bool)
            cloudish = (((qa >> 1) & 1) | ((qa >> 2) & 1) | ((qa >> 3) & 1) | ((qa >> 4) & 1)).astype(bool)
            clear = valid & ~cloudish
    except Exception:
        return 0.0
    return float(clear.sum()) / max(1, valid.size)


def detect(source: str, items: list[dict], grid: Grid, bands: tuple[str, ...] = ()) -> dict:
    return s2_pass(items, grid, bands) if source == "S2" else landsat_pass(items, grid, bands)


def rgb_bands(source: str) -> tuple[str, str, str]:
    return ("red", "green", "blue")

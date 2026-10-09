"""Long-term water history and land cover, read onto a grid.

* JRC Global Surface Water v1.3 (1984-2020, 30 m): occurrence (% of valid months with water), maximum extent,
  and transitions (permanent / seasonal / lost / new water) - the 37-year memory of where water was.
* Impact Observatory annual land cover v2 (2017-2023, 10 m, from Sentinel-2): what is there now
  (water, trees, flooded vegetation, crops, built area, bare ground, rangeland).
* ESA WorldCover 2021 (10 m): an independent second opinion on built-up and water.
All three are served as cloud-optimised GeoTIFFs by Microsoft Planetary Computer.
"""
from __future__ import annotations

import numpy as np
from rasterio.enums import Resampling

from . import catalog
from . import config as C
from .raster import Grid, read_mosaic


def _items(collection: str, bbox: list[float], dt: str | None = None) -> list[dict]:
    return catalog.search(C.PLANETARY_COMPUTER, collection, bbox, dt, limit=50)


def jrc(grid: Grid, layers=("occurrence", "extent", "transitions")) -> dict:
    """JRC GSW layers on the grid. occurrence: float % (NaN = no data); extent/transitions: uint8."""
    bbox = grid.bbox_lonlat()
    items = _items("jrc-gsw", bbox)
    out = {}
    for layer in layers:
        hrefs = [it["assets"][layer]["href"] for it in items if layer in it["assets"]]
        if layer == "occurrence":
            a = read_mosaic(hrefs, grid, dtype="float32", resampling=Resampling.average, src_nodata=255)
            out[layer] = np.where(np.isfinite(a), a, 0.0).astype(np.float32)
        else:
            out[layer] = read_mosaic(hrefs, grid, dtype="uint8", resampling=Resampling.nearest, src_nodata=255)
    return out


def io_lulc(grid: Grid, years=C.IO_LULC_YEARS) -> dict[int, np.ndarray]:
    """Impact Observatory class per year (uint8; 0 = no data). Mode resampling keeps classes crisp."""
    bbox = grid.bbox_lonlat()
    out = {}
    rs = Resampling.mode if grid.res > 12 else Resampling.nearest
    for y in years:
        items = _items("io-lulc-annual-v02", bbox, f"{y}-01-01/{y}-12-31")
        out[y] = read_mosaic([it["assets"]["data"]["href"] for it in items], grid, dtype="uint8", resampling=rs,
                             src_nodata=0)
    return out


def worldcover(grid: Grid) -> np.ndarray:
    """ESA WorldCover 2021 class (10 tree, 20 shrub, 30 grass, 40 crop, 50 built, 60 bare, 80 water, 90 wetland)."""
    bbox = grid.bbox_lonlat()
    items = [it for it in _items("esa-worldcover", bbox) if "2021" in it["id"]] or _items("esa-worldcover", bbox)
    rs = Resampling.mode if grid.res > 12 else Resampling.nearest
    return read_mosaic([it["assets"]["map"]["href"] for it in items], grid, dtype="uint8", resampling=rs, src_nodata=0)


def built_persistent(lulc: dict[int, np.ndarray], years=(2021, 2022, 2023), min_years: int = 2) -> np.ndarray:
    """Built in at least min_years of the given years: removes single-year classification flicker."""
    have = [lulc[y] for y in years if y in lulc]
    if not have:
        return np.zeros(next(iter(lulc.values())).shape, dtype=bool)
    return sum((a == C.IO_BUILT).astype(np.int8) for a in have) >= min(min_years, len(have))


def historic_water(j: dict) -> np.ndarray:
    """Pixels that were water often enough in 1984-2020 to count as part of a water body."""
    return (j["extent"] == 1) & (j["occurrence"] >= C.JRC_OCCURRENCE_MIN)


IO_CLASS_NAMES = {1: "water", 2: "trees", 4: "flooded vegetation", 5: "crops", 7: "built area", 8: "bare ground",
                  9: "snow", 10: "clouds", 11: "rangeland"}

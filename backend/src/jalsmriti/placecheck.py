"""The water-memory signals of one place (pure computation; used by the place pipeline and the validation)."""
from __future__ import annotations

import numpy as np

from . import config as C
from . import landcover, terrain
from .raster import Grid


def disk(grid: Grid, r_m: float) -> np.ndarray:
    h, w = grid.shape
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2, (w - 1) / 2
    return np.hypot(yy - cy, xx - cx) * grid.res <= r_m


def signals(lat: float, lon: float) -> dict:
    """Water history (JRC 1984-2020), what is there now (land cover 2023) and terrain around a point."""
    g = Grid.around(lon, lat, C.PLACE_CONTEXT_M + 300, C.AREA_RES_M)
    j = landcover.jrc(g)
    io = landcover.io_lulc(g, years=(2023,))[2023]
    hist = (j["extent"] == 1) & (j["occurrence"] >= C.JRC_OCCURRENCE_MIN)
    ever = j["extent"] == 1
    lost = np.isin(j["transitions"], C.JRC_LOST)
    px_ha = g.px_area_m2 / 1e4
    d300, d1000, d2000 = disk(g, 300), disk(g, 1000), disk(g, 2000)
    cy, cx = g.height // 2, g.width // 2
    occ_here = float(j["occurrence"][cy - 1:cy + 2, cx - 1:cx + 2].max())
    built_over = ever & (io == C.IO_BUILT)
    if hist.any():
        yy, xx = np.nonzero(hist)
        nearest = float(np.min(np.hypot(yy - cy, xx - cx)) * g.res)
    else:
        nearest = None
    tg = Grid.around(lon, lat, 5000, C.AREA_RES_M)    # wide window so drainage areas are not cut short
    z = terrain.dem(tg)
    t = terrain.analyse(z, tg.res, stream_km2=1.0)
    t300 = disk(tg, 300)
    tcy, tcx = tg.height // 2, tg.width // 2
    ring = z[disk(tg, 2000)]
    here = float(np.nanmean(z[tcy - 1:tcy + 2, tcx - 1:tcx + 2]))
    return {
        "occurrenceHere": round(occ_here, 1),
        "everWater1000": round(float(ever[d1000].mean()), 4), "lostWater1000": round(float(lost[d1000].mean()), 4),
        "builtOverWater2000": round(float(built_over[d2000].mean()), 4),
        "lostWaterHa300": round(float((lost & d300).sum()) * px_ha, 2),
        "builtOverWaterHa2000": round(float((built_over & d2000).sum()) * px_ha, 1),
        "historicWaterHa1000": round(float((hist & d1000).sum()) * px_ha, 1),
        "nearestWaterM": round(nearest) if nearest is not None else None,
        "depressionMax300": round(float(np.nanmax(t["depression"][t300])), 2),
        "handMin300": round(float(np.nanmin(t["hand"][t300])), 2),
        "elevationM": round(here, 1),
        "relElevationM": round(here - float(np.nanpercentile(ring, 10)), 1),
        "landCoverHere": landcover.IO_CLASS_NAMES.get(int(io[cy, cx]), "unknown"),
    }

"""Finding the water bodies of an area from 37 years of satellite water history.

A pixel belongs to a water body if JRC Global Surface Water saw water there in at least 5 % of valid months
between 1984 and 2020. Connected patches of at least 2 ha (after a 3x3 opening that splits lakes joined by a
one-pixel channel) are water bodies. Long thin patches are river stretches, kept for the map but not graded.
Because the history reaches back to 1984, lakes that have since dried, filled or been built over are found too.
"""
from __future__ import annotations

import math

import numpy as np

from . import config as C
from . import geo
from .landcover import historic_water
from .raster import Grid, opening, polygonize, rasterize_labels, to_lonlat_geom


def classify_shape(poly) -> tuple[str, float, float]:
    """('lake' | 'river', compactness, length_m)."""
    area, perim = poly.area, poly.length
    compact = 4 * math.pi * area / (perim * perim) if perim > 0 else 1.0
    mrr = poly.minimum_rotated_rectangle
    xs, ys = mrr.exterior.coords.xy
    sides = sorted(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(4))
    length, width = sides[-1], max(sides[0], 1.0)
    river = (compact < C.RIVER_MAX_COMPACTNESS and length > C.RIVER_MIN_LENGTH_M) or \
            (length / width > 6 and length > 2 * C.RIVER_MIN_LENGTH_M and compact < 0.15)
    return ("river" if river else "lake"), compact, length


def sea_mask(grid: Grid, jrc: dict, dem: np.ndarray | None) -> np.ndarray:
    """Open sea and sea-connected lagoons: frequent water at elevation ~0 m that touches the edge of the grid.

    The Copernicus elevation model is flattened to 0 m over the sea, so frequent water at <= 0.5 m that is
    connected to the grid edge is coastal water, not a lake (it is left out of the lake list).
    """
    if dem is None:
        return np.zeros(grid.shape, dtype=bool)
    cand = (np.nan_to_num(dem, nan=0.0) <= 0.5) & (jrc["occurrence"] >= 50)
    if not cand.any():
        return cand
    l, b, r, t = grid.bounds
    edge = []
    for p in polygonize(cand, grid, min_area_m2=0.0):
        pl, pb, pr, pt = p.bounds
        if pl <= l + grid.res or pb <= b + grid.res or pr >= r - grid.res or pt >= t - grid.res:
            edge.append(p)
    if not edge:
        return np.zeros(grid.shape, dtype=bool)
    return rasterize_labels(edge, grid) > 0


def discover(grid: Grid, jrc: dict, area_id: str, dem: np.ndarray | None = None,
             min_ha: float = C.LAKE_MIN_HA) -> tuple[list[dict], np.ndarray]:
    """Water bodies on the grid. Returns (bodies, label raster with value = index + 1)."""
    hist = historic_water(jrc) & ~sea_mask(grid, jrc, dem)
    hist = opening(hist, C.OPEN_RADIUS_PX)
    polys = polygonize(hist, grid, min_area_m2=min_ha * 1e4)
    polys.sort(key=lambda p: -p.area)
    bodies, used = [], set()
    for p in polys:
        kind, compact, length = classify_shape(p)
        rp = p.representative_point()
        ll = to_lonlat_geom(rp, grid.crs)
        gh = geo.geohash(ll.y, ll.x, 7)
        lake_id = f"{area_id[:3]}-{gh}"
        n = 2
        while lake_id in used:
            lake_id = f"{area_id[:3]}-{gh}{n}"
            n += 1
        used.add(lake_id)
        simple = p.simplify(grid.res * 0.5, preserve_topology=True)
        bodies.append({"lakeId": lake_id, "kind": kind, "areaHa": round(p.area / 1e4, 2),
                       "compactness": round(compact, 3), "lengthM": round(length), "lon": round(ll.x, 6),
                       "lat": round(ll.y, 6), "geomUtm": simple})
    labels = rasterize_labels([b["geomUtm"] for b in bodies], grid)
    return bodies, labels


def lonlat_feature(body: dict, crs, props: dict | None = None) -> dict:
    from shapely.geometry import mapping
    g = to_lonlat_geom(body["geomUtm"], crs)
    return {"type": "Feature", "id": body["lakeId"], "geometry": mapping(g),
            "properties": {"lakeId": body["lakeId"], "kind": body["kind"], "areaHa": body["areaHa"], **(props or {})}}


def body_at(grid: Grid, jrc: dict, lon: float, lat: float, max_dist_m: float = 120.0):
    """The water body (as a UTM polygon) containing or nearest to a point, from a local JRC window."""
    from shapely.geometry import Point
    hist = opening(historic_water(jrc), C.OPEN_RADIUS_PX)
    polys = polygonize(hist, grid, min_area_m2=0.5e4)
    if not polys:
        return None
    from rasterio.warp import transform as wt
    xs, ys = wt("EPSG:4326", grid.crs, [lon], [lat])
    pt = Point(xs[0], ys[0])
    best = min(polys, key=lambda p: p.distance(pt))
    if best.distance(pt) > max_dist_m:
        return None
    return best

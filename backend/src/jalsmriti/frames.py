"""True-colour frames for the time machine: whole areas (map overlays), lakes and places (time-lapse strips).

Frames are made on a Web Mercator grid so the map can lay them over its basemap without resampling, and saved
as WebP with an alpha channel (no-data stays transparent).
"""
from __future__ import annotations

import io
import math

import numpy as np
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import transform as warp_transform

from . import config as C
from .raster import MERCATOR, Grid, read, stretch_rgb
from .water import _ls_reflectance, _s2_reflectance


def mercator_grid(bbox: list[float], res: float) -> Grid:
    return Grid.for_bbox(bbox, res, crs=MERCATOR)


def rgb_reflectance(source: str, items: list[dict], grid: Grid) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bands = []
    for key in ("red", "green", "blue"):
        out = None
        for it in items:
            raw = read(it["assets"][key]["href"], grid, dtype="float32",
                       resampling=Resampling.bilinear if source == "S2" else Resampling.nearest, src_nodata=0)
            refl = _s2_reflectance(it, key, raw) if source == "S2" else _ls_reflectance(raw)
            out = refl if out is None else np.where(np.isfinite(out), out, refl)
        bands.append(out)
    return bands[0], bands[1], bands[2]


def to_webp(rgb: np.ndarray, valid: np.ndarray, quality: int = 78, max_side: int | None = None) -> bytes:
    img = Image.fromarray(np.dstack([rgb, (valid * 255).astype(np.uint8)]), "RGBA")
    if max_side and max(img.size) > max_side:
        s = max_side / max(img.size)
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=4)
    return buf.getvalue()


def frame(source: str, items: list[dict], grid: Grid) -> dict:
    """RGB uint8 + validity for a pass on the grid, with a robust stretch shared by the three bands."""
    r, g, b = rgb_reflectance(source, items, grid)
    valid = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)
    rgb = stretch_rgb(r, g, b, lo_pct=1.5, hi_pct=98.5, gamma=1.3)
    return {"rgb": rgb, "valid": valid}


def corners_lonlat(grid: Grid) -> list[list[float]]:
    """Top-left, top-right, bottom-right, bottom-left corners (MapLibre image source order)."""
    l, b, r, t = grid.bounds
    xs, ys = warp_transform(grid.crs, "EPSG:4326", [l, r, r, l], [t, t, b, b])
    return [[round(x, 6), round(y, 6)] for x, y in zip(xs, ys)]


def crop_box(grid: Grid, geom_merc, margin: float = 0.45, min_side_m: float = 900.0) -> tuple[int, int, int, int] | None:
    """Pixel window (row0, col0, h, w) of a square crop around a geometry in the grid's (Mercator) CRS."""
    minx, miny, maxx, maxy = geom_merc.bounds
    side = max(maxx - minx, maxy - miny)
    side = max(side * (1 + 2 * margin), min_side_m * _merc_scale(grid, (miny + maxy) / 2))
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    x0, y0 = cx - side / 2, cy + side / 2
    col0, row0 = ~grid.transform * (x0, y0)
    n = int(math.ceil(side / grid.res))
    row0, col0 = int(math.floor(row0)), int(math.floor(col0))
    if row0 >= grid.height or col0 >= grid.width or row0 + n <= 0 or col0 + n <= 0:
        return None
    return row0, col0, n, n


def _merc_scale(grid: Grid, y_merc: float) -> float:
    """Mercator metres per ground metre at this northing."""
    lat = math.degrees(2 * math.atan(math.exp(y_merc / 6378137.0)) - math.pi / 2)
    return 1 / max(math.cos(math.radians(lat)), 0.1)


def cut(fr: dict, box: tuple[int, int, int, int], out_px: int = 360, outline=None) -> bytes:
    """Crop a frame (padding outside with transparency), optionally drawing an outline (list of pixel rings)."""
    row0, col0, h, w = box
    H, W = fr["rgb"].shape[:2]
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    val = np.zeros((h, w), dtype=bool)
    r0, c0 = max(row0, 0), max(col0, 0)
    r1, c1 = min(row0 + h, H), min(col0 + w, W)
    if r1 > r0 and c1 > c0:
        rgb[r0 - row0:r1 - row0, c0 - col0:c1 - col0] = fr["rgb"][r0:r1, c0:c1]
        val[r0 - row0:r1 - row0, c0 - col0:c1 - col0] = fr["valid"][r0:r1, c0:c1]
    img = Image.fromarray(np.dstack([rgb, (val * 255).astype(np.uint8)]), "RGBA")
    if out_px and max(img.size) != out_px:
        img = img.resize((out_px, out_px), Image.LANCZOS if img.width > out_px else Image.BICUBIC)
    if outline:
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        s = out_px / w
        for ring in outline:
            pts = [((c - col0) * s, (r - row0) * s) for r, c in ring]
            if len(pts) > 2:
                d.line(pts + [pts[0]], fill=(255, 214, 10, 255), width=2)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=82, method=4)
    return buf.getvalue()


def rings_px(grid: Grid, geom_merc) -> list[list[tuple[float, float]]]:
    """Exterior rings of a (multi)polygon as (row, col) pixel coordinates on the grid."""
    polys = [geom_merc] if geom_merc.geom_type == "Polygon" else list(getattr(geom_merc, "geoms", []))
    inv = ~grid.transform
    out = []
    for p in polys:
        ring = []
        for x, y in p.exterior.coords:
            c, r = inv * (x, y)
            ring.append((r, c))
        out.append(ring)
    return out

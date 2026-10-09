"""Grids, reading any open raster onto a grid, and the small image operations the science needs.

Everything is computed on a local grid (UTM metres for analysis, Web Mercator for map frames) so areas and
distances are honest. Reading uses GDAL warping straight from cloud-optimised GeoTIFFs: only the blocks that
cover the grid are fetched, and a coarser overview is used when the grid is coarser than the source.
"""
from __future__ import annotations

import io
import logging
import math
import os
import time
from dataclasses import dataclass

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF,.tiff,.cog,.TIFF")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MULTIPLEX", "YES")
os.environ.setdefault("GDAL_HTTP_VERSION", "2")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("VSI_CACHE_SIZE", "50000000")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("GDAL_CACHEMAX", "256")
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_HTTP_USERAGENT", "jalsmriti/1.0")
try:  # GDAL's curl needs a CA bundle; in Lambda use certifi's (shipped with rasterio) unless one is set already
    import certifi as _certifi
    os.environ.setdefault("CURL_CA_BUNDLE", _certifi.where())
except Exception:
    pass

import numpy as np
import rasterio
from affine import Affine
from rasterio import features
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform as warp_transform
from rasterio.warp import transform_bounds

from . import catalog

log = logging.getLogger(__name__)

WGS84 = CRS.from_epsg(4326)
MERCATOR = CRS.from_epsg(3857)


def utm_crs(lon: float, lat: float) -> CRS:
    zone = int((lon + 180) // 6) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


@dataclass(frozen=True)
class Grid:
    crs: CRS
    transform: Affine
    width: int
    height: int

    @property
    def res(self) -> float:
        return abs(self.transform.a)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    @property
    def px_area_m2(self) -> float:
        return abs(self.transform.a * self.transform.e)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        l, t = self.transform.c, self.transform.f
        return (l, t - self.height * self.res, l + self.width * self.res, t)

    def bbox_lonlat(self) -> list[float]:
        return list(transform_bounds(self.crs, WGS84, *self.bounds, densify_pts=21))

    def to_dict(self) -> dict:
        return {"crs": self.crs.to_string(), "transform": list(self.transform)[:6], "width": self.width,
                "height": self.height}

    @staticmethod
    def from_dict(d: dict) -> "Grid":
        return Grid(CRS.from_string(d["crs"]), Affine(*d["transform"]), int(d["width"]), int(d["height"]))

    @staticmethod
    def for_bbox(bbox: list[float], res: float, crs: CRS | None = None) -> "Grid":
        w, s, e, n = bbox
        crs = crs or utm_crs((w + e) / 2, (s + n) / 2)
        l, b, r, t = transform_bounds(WGS84, crs, w, s, e, n, densify_pts=21)
        l, b = math.floor(l / res) * res, math.floor(b / res) * res
        r, t = math.ceil(r / res) * res, math.ceil(t / res) * res
        return Grid(crs, Affine(res, 0, l, 0, -res, t), int(round((r - l) / res)), int(round((t - b) / res)))

    @staticmethod
    def around(lon: float, lat: float, half_m: float, res: float, crs: CRS | None = None) -> "Grid":
        crs = crs or utm_crs(lon, lat)
        xs, ys = warp_transform(WGS84, crs, [lon], [lat])
        x, y = xs[0], ys[0]
        n = int(math.ceil(2 * half_m / res))
        return Grid(crs, Affine(res, 0, x - n * res / 2, 0, -res, y + n * res / 2), n, n)

    def lonlat_to_rowcol(self, lon: float, lat: float) -> tuple[int, int]:
        xs, ys = warp_transform(WGS84, self.crs, [lon], [lat])
        col, row = ~self.transform * (xs[0], ys[0])
        return int(math.floor(row)), int(math.floor(col))

    def rowcol_to_lonlat(self, row: float, col: float) -> tuple[float, float]:
        x, y = self.transform * (col + 0.5, row + 0.5)
        lon, lat = warp_transform(self.crs, WGS84, [x], [y])
        return lon[0], lat[0]

    def subgrid(self, row0: int, col0: int, h: int, w: int) -> "Grid":
        return Grid(self.crs, self.transform * Affine.translation(col0, row0), w, h)


# ------------------------------------------------------------------------------------------- reading
def _overview_level(src, target_res: float) -> int | None:
    """Index of the coarsest overview that is still at least as fine as the target resolution."""
    try:
        factors = src.overviews(1)
    except Exception:
        return None
    if not factors:
        return None
    src_res = abs(src.transform.a)
    if src.crs and src.crs.is_geographic:
        src_res *= 111_320.0
    best = None
    for i, f in enumerate(factors):
        if src_res * f <= target_res * 1.01:
            best = i
    return best


def read(href: str, grid: Grid, band: int = 1, resampling: Resampling = Resampling.nearest,
         dtype: str = "float32", src_nodata=None, tries: int = 3, use_overviews: bool = True) -> np.ndarray:
    """Read one band of any raster onto the grid. Float output uses NaN for no data; integers use 0."""
    path = catalog.readable(href)
    fill = np.nan if np.dtype(dtype).kind == "f" else 0
    last = None
    for attempt in range(tries):
        try:
            with rasterio.open(path) as src0:
                lvl = _overview_level(src0, grid.res) if use_overviews else None
                nod = src_nodata if src_nodata is not None else src0.nodata
            kwargs = {"overview_level": lvl} if lvl is not None else {}
            with rasterio.open(path, **kwargs) as src:
                with WarpedVRT(src, crs=grid.crs, transform=grid.transform, width=grid.width, height=grid.height,
                               resampling=resampling, src_nodata=nod, nodata=fill if np.dtype(dtype).kind == "f" else 0,
                               dtype=dtype) as vrt:
                    return vrt.read(band, out_dtype=dtype)
        except Exception as ex:  # transient HTTP errors on public COG hosts: retry; expired PC token: re-sign
            last = ex
            if "403" in str(ex) or "AuthenticationFailed" in str(ex):
                catalog._tokens.clear()
                path = catalog.readable(href)
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"could not read {href.split('?')[0]}: {last}")


def read_mosaic(hrefs: list[str], grid: Grid, **kw) -> np.ndarray:
    """First valid value wins, in the order given."""
    out = None
    for h in hrefs:
        a = read(h, grid, **kw)
        if out is None:
            out = a
        else:
            empty = np.isnan(out) if out.dtype.kind == "f" else (out == 0)
            out = np.where(empty, a, out)
    if out is None:
        dtype = kw.get("dtype", "float32")
        out = np.full(grid.shape, np.nan if np.dtype(dtype).kind == "f" else 0, dtype=dtype)
    return out


# ------------------------------------------------------------------------------------------- filters
def box_sum(a: np.ndarray, r: int) -> np.ndarray:
    """Sum over a (2r+1)x(2r+1) window, zero padded, via summed-area tables."""
    a = np.asarray(a, dtype=np.float64)
    if r <= 0:
        return a.copy()
    p = np.pad(a, ((r + 1, r), (r + 1, r)))
    c = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def box_mean(a: np.ndarray, r: int) -> np.ndarray:
    """NaN-aware mean over a (2r+1)x(2r+1) window."""
    v = np.isfinite(a)
    s = box_sum(np.where(v, a, 0.0), r)
    n = box_sum(v.astype(np.float64), r)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, s / np.maximum(n, 1), np.nan)


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    return box_sum(mask.astype(np.float64), r) > 0.5 if r > 0 else mask.copy()


def erode(mask: np.ndarray, r: int) -> np.ndarray:
    k = (2 * r + 1) ** 2
    return box_sum(mask.astype(np.float64), r) > k - 0.5 if r > 0 else mask.copy()


def opening(mask: np.ndarray, r: int) -> np.ndarray:
    return dilate(erode(mask, r), r)


def near(mask: np.ndarray, dist_m: float, res: float) -> np.ndarray:
    """Pixels within ~dist_m of any True pixel (square neighbourhood, cheap and conservative)."""
    return dilate(mask, int(math.ceil(dist_m / res)))


# ------------------------------------------------------------------------------------------- vectors
def polygonize(mask: np.ndarray, grid: Grid, min_area_m2: float = 0.0):
    """Connected regions (8-connectivity) of a boolean mask as shapely polygons in the grid CRS."""
    from shapely.geometry import shape
    m = mask.astype(np.uint8)
    out = []
    for geom, val in features.shapes(m, mask=m.astype(bool), transform=grid.transform, connectivity=8):
        g = shape(geom)
        if g.area >= min_area_m2:
            out.append(g)
    return out


def rasterize_labels(geoms, grid: Grid, all_touched: bool = False) -> np.ndarray:
    """Label raster: pixel value i+1 for geometry i, 0 elsewhere."""
    if not geoms:
        return np.zeros(grid.shape, dtype=np.int32)
    return features.rasterize([(g, i + 1) for i, g in enumerate(geoms)], out_shape=grid.shape,
                              transform=grid.transform, fill=0, dtype="int32", all_touched=all_touched)


def zonal_count(labels: np.ndarray, n: int, mask: np.ndarray | None = None) -> np.ndarray:
    w = None if mask is None else mask.ravel().astype(np.float64)
    return np.bincount(labels.ravel(), weights=w, minlength=n + 1)[1:n + 1]


def to_lonlat_geom(geom, crs: CRS):
    from shapely.geometry import mapping, shape
    from rasterio.warp import transform_geom
    return shape(transform_geom(crs, WGS84, mapping(geom), precision=6))


def reproject_geom(geom, src: CRS, dst: CRS):
    from shapely.geometry import mapping, shape
    from rasterio.warp import transform_geom
    return shape(transform_geom(src, dst, mapping(geom)))


def from_lonlat_geom(geom, crs: CRS):
    from shapely.geometry import mapping, shape
    from rasterio.warp import transform_geom
    return shape(transform_geom(WGS84, crs, mapping(geom)))


# ------------------------------------------------------------------------------------------- images
def stretch_rgb(r: np.ndarray, g: np.ndarray, b: np.ndarray, lo_pct: float = 2, hi_pct: float = 98,
                gamma: float = 1.25, ref: tuple[float, float] | None = None) -> np.ndarray:
    """Surface reflectance bands -> 8-bit RGB with a robust common stretch (keeps colours natural)."""
    stack = np.dstack([r, g, b]).astype(np.float32)
    valid = np.isfinite(stack).all(axis=2) & (stack.max(axis=2) > 0)
    if ref is None:
        if valid.sum() < 50:
            return np.zeros(stack.shape, dtype=np.uint8)
        vals = stack[valid]
        lo = float(np.percentile(vals, lo_pct))
        hi = float(np.percentile(vals, hi_pct))
    else:
        lo, hi = ref
    hi = max(hi, lo + 0.02)
    out = np.clip((stack - lo) / (hi - lo), 0, 1) ** (1 / gamma)
    out[~valid] = 0
    return (out * 255 + 0.5).astype(np.uint8)


def encode_image(rgb: np.ndarray, fmt: str = "JPEG", quality: int = 82, alpha: np.ndarray | None = None) -> bytes:
    from PIL import Image
    if alpha is not None:
        img = Image.fromarray(np.dstack([rgb, alpha.astype(np.uint8)]), "RGBA")
        fmt = "PNG" if fmt.upper() == "JPEG" else fmt
    else:
        img = Image.fromarray(rgb)
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    elif fmt.upper() == "WEBP":
        img.save(buf, format="WEBP", quality=quality, method=4)
    else:
        img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def save_npz(arrays: dict) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def load_npz(data: bytes) -> dict:
    with np.load(io.BytesIO(data), allow_pickle=False) as z:
        return {k: z[k] for k in z.files}

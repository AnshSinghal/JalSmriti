"""Terrain from the Copernicus GLO-30 elevation model (30 m, on AWS Open Data).

For a place we want to know whether water would collect there:
  * depression depth: how much the ground would have to fill before water could drain away (priority-flood),
  * height above the nearest drainage line (HAND) along the D8 flow path,
  * elevation relative to the surrounding 2 km.
GLO-30 is a surface model (it includes buildings and trees), so in dense cities these are indicative only.
"""
from __future__ import annotations

import heapq

import numpy as np
from rasterio.enums import Resampling

from . import catalog
from . import config as C
from .raster import Grid, read_mosaic

NB = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def dem(grid: Grid) -> np.ndarray:
    items = catalog.search(C.EARTH_SEARCH, C.DEM_COLLECTION, grid.bbox_lonlat(), limit=20)
    hrefs = [it["assets"]["data"]["href"] for it in items]
    return read_mosaic(hrefs, grid, dtype="float32", resampling=Resampling.bilinear)


def priority_flood(z: np.ndarray, eps: float = 1e-3) -> np.ndarray:
    """Fill depressions so every cell drains to the edge (Barnes et al. priority-flood, epsilon variant)."""
    z = np.where(np.isfinite(z), z, np.nanmedian(z) if np.isfinite(z).any() else 0.0).astype(np.float64)
    H, W = z.shape
    filled = z.copy()
    done = np.zeros((H, W), dtype=bool)
    pq: list = []
    for r in range(H):
        for c in (0, W - 1):
            if not done[r, c]:
                done[r, c] = True
                heapq.heappush(pq, (filled[r, c], r, c))
    for c in range(1, W - 1):
        for r in (0, H - 1):
            if not done[r, c]:
                done[r, c] = True
                heapq.heappush(pq, (filled[r, c], r, c))
    while pq:
        e, r, c = heapq.heappop(pq)
        for dr, dc in NB:
            rr, cc = r + dr, c + dc
            if 0 <= rr < H and 0 <= cc < W and not done[rr, cc]:
                done[rr, cc] = True
                if filled[rr, cc] <= e:
                    filled[rr, cc] = e + eps
                heapq.heappush(pq, (filled[rr, cc], rr, cc))
    return filled


def d8(filled: np.ndarray) -> np.ndarray:
    """Index (0-7 into NB) of the steepest downhill neighbour, -1 where none (edges, flats)."""
    H, W = filled.shape
    pad = np.pad(filled, 1, constant_values=np.inf)
    best = np.full((H, W), -1, dtype=np.int8)
    bestdrop = np.zeros((H, W))
    for k, (dr, dc) in enumerate(NB):
        nb = pad[1 + dr:1 + dr + H, 1 + dc:1 + dc + W]
        drop = (filled - nb) / (1.41421356 if dr and dc else 1.0)
        m = drop > bestdrop
        best[m] = k
        bestdrop[m] = drop[m]
    return best


def accumulation(filled: np.ndarray, fdir: np.ndarray) -> np.ndarray:
    H, W = filled.shape
    acc = np.ones(H * W)
    order = np.argsort(-filled, axis=None)
    fd = fdir.ravel()
    drs = [n[0] for n in NB]
    dcs = [n[1] for n in NB]
    for idx in order:
        k = fd[idx]
        if k < 0:
            continue
        r, c = divmod(int(idx), W)
        rr, cc = r + drs[k], c + dcs[k]
        if 0 <= rr < H and 0 <= cc < W:
            acc[rr * W + cc] += acc[idx]
    return acc.reshape(H, W)


def hand(filled: np.ndarray, fdir: np.ndarray, stream: np.ndarray) -> np.ndarray:
    """Height above the nearest drainage cell reached by following the flow path."""
    H, W = filled.shape
    base = np.full(H * W, np.nan)
    order = np.argsort(filled, axis=None)
    fd, st, fl = fdir.ravel(), stream.ravel(), filled.ravel()
    drs = [n[0] for n in NB]
    dcs = [n[1] for n in NB]
    for idx in order:
        if st[idx]:
            base[idx] = fl[idx]
            continue
        k = fd[idx]
        if k < 0:
            base[idx] = fl[idx]
            continue
        r, c = divmod(int(idx), W)
        rr, cc = r + drs[k], c + dcs[k]
        b = base[rr * W + cc] if (0 <= rr < H and 0 <= cc < W) else np.nan
        base[idx] = b if np.isfinite(b) else fl[idx]
    return filled - base.reshape(H, W)


def analyse(z: np.ndarray, res: float, stream_km2: float = 1.0) -> dict:
    """Depression depth, flow accumulation (km2), drainage lines and HAND for an elevation grid."""
    filled = priority_flood(z)
    fdir = d8(filled)
    acc = accumulation(filled, fdir)
    cells = stream_km2 * 1e6 / (res * res)
    stream = acc >= cells
    h = hand(filled, fdir, stream)
    zf = np.where(np.isfinite(z), z, filled)
    return {"filled": filled, "depression": np.maximum(filled - zf, 0.0), "acc_km2": acc * res * res / 1e6,
            "stream": stream, "hand": h}

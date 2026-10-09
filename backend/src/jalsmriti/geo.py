"""Small geographic helpers with no heavy dependencies (used by the API as well as the pipelines)."""
from __future__ import annotations

import math

_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lon: float, precision: int = 7) -> str:
    lat_r, lon_r = [-90.0, 90.0], [-180.0, 180.0]
    bits, ch, even, out = 0, 0, True, []
    while len(out) < precision:
        rng, val = (lon_r, lon) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch |= 1 << (4 - bits)
            rng[0] = mid
        else:
            rng[1] = mid
        even = not even
        bits += 1
        if bits == 5:
            out.append(_B32[ch])
            bits, ch = 0, 0
    return "".join(out)


def geohash_decode(gh: str) -> tuple[float, float]:
    lat_r, lon_r = [-90.0, 90.0], [-180.0, 180.0]
    even = True
    for c in gh:
        cd = _B32.index(c)
        for mask in (16, 8, 4, 2, 1):
            rng = lon_r if even else lat_r
            mid = (rng[0] + rng[1]) / 2
            if cd & mask:
                rng[0] = mid
            else:
                rng[1] = mid
            even = not even
    return (lat_r[0] + lat_r[1]) / 2, (lon_r[0] + lon_r[1]) / 2


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# India and Nepal (with a margin). The tool is built and validated for South Asia's monsoon water bodies.
SUPPORTED_BBOXES = {"IN": (68.0, 6.0, 97.6, 37.2), "NP": (80.0, 26.3, 88.3, 30.5)}


def supported(lat: float, lon: float) -> bool:
    return any(w <= lon <= e and s <= lat <= n for (w, s, e, n) in SUPPORTED_BBOXES.values())


def bbox_around(lat: float, lon: float, half_m: float) -> list[float]:
    dlat = half_m / 111_320.0
    dlon = half_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.1))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


# A simplified outline of Nepal (lon, lat), good to ~10 km: enough to choose Nepali or Indian authorities.
NEPAL = [(80.06, 28.84), (80.37, 29.75), (81.04, 30.20), (81.48, 30.42), (82.17, 30.06), (82.73, 29.69),
         (83.35, 29.46), (83.95, 29.21), (84.23, 28.84), (85.01, 28.64), (85.82, 28.20), (86.10, 27.97),
         (86.77, 28.11), (87.24, 27.83), (88.12, 27.88), (88.20, 26.74), (87.23, 26.40), (86.03, 26.63),
         (85.25, 26.73), (84.68, 27.23), (83.90, 27.36), (83.30, 27.36), (82.70, 27.43), (81.90, 27.85),
         (81.10, 28.36), (80.59, 28.68)]


def _inside(lon: float, lat: float, poly) -> bool:
    inside, n = False, len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def country(lat: float, lon: float) -> str:
    return "NP" if _inside(lon, lat, NEPAL) else "IN"

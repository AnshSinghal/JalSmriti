"""Monsoon rainfall per season, to compare a water body with itself in years of similar rain.

Source: NASA POWER (MERRA-2 bias-corrected precipitation, PRECTOTCORR, monthly, 1981-present, ~50 km). One HTTP
request returns forty years for a point, which keeps on-demand checks fast and reliable. Rain is used only to pick
"comparable" past seasons (within +-25 % of a season's monsoon total), for which a coarse but consistent record is
enough; a dry lake after a good monsoon stands out, and a drought year is not mistaken for a lost lake.
"""
from __future__ import annotations

import calendar
import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from . import config as C

log = logging.getLogger(__name__)
POWER = "https://power.larc.nasa.gov/api/temporal/monthly/point"
_cache: dict[tuple, dict] = {}
_lock = threading.Lock()


def _cell(lat: float, lon: float) -> tuple[float, float]:
    """MERRA-2 grid cell centre (0.5 x 0.625 degrees): points in the same cell share one request."""
    return round(round(lat / 0.5) * 0.5, 3), round(round(lon / 0.625) * 0.625, 3)


def monthly(lat: float, lon: float, first_year: int, last_year: int, tries: int = 4) -> dict[tuple[int, int], float]:
    """{(year, month): rainfall mm} for every month with data (missing months are absent)."""
    clat, clon = _cell(lat, lon)
    key = (clat, clon, first_year, last_year)
    with _lock:
        if key in _cache:
            return _cache[key]
    params = {"parameters": "PRECTOTCORR", "community": "AG", "longitude": clon, "latitude": clat,
              "start": first_year, "end": last_year, "format": "JSON"}
    url = f"{POWER}?{urllib.parse.urlencode(params)}"
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": C.USER_AGENT})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read())
            series = data["properties"]["parameter"]["PRECTOTCORR"]
            out = {}
            for k, v in series.items():
                y, m = int(k[:4]), int(k[4:])
                if m > 12 or v is None or v < 0:      # month 13 is the annual mean; -999 is missing
                    continue
                out[(y, m)] = round(float(v) * calendar.monthrange(y, m)[1], 1)   # mm/day -> mm
            with _lock:
                _cache[key] = out
            return out
        except Exception as ex:
            last = ex
            time.sleep(2 * 2 ** attempt)
    raise RuntimeError(f"NASA POWER request failed: {last}")


def season_months(season: int, months: tuple[int, ...]) -> list[tuple[int, int]]:
    """Months of a season; a month smaller than the one before it belongs to the next year."""
    out, year, prev = [], season, months[0]
    for m in months:
        if m < prev:
            year += 1
        out.append((year, m))
        prev = m
    return out


def seasonal(lat: float, lon: float, seasons: list[int], months: tuple[int, ...]) -> tuple[dict, dict]:
    """({season: mm}, {season: complete}) at a point."""
    last_year = max(y for s in seasons for (y, _m) in season_months(s, months))
    mon = monthly(lat, lon, min(seasons), min(last_year, C.CURRENT_SEASON + 1))
    totals, complete = {}, {}
    for s in seasons:
        ms = season_months(s, months)
        got = [mon[k] for k in ms if k in mon]
        if got:
            totals[s] = round(sum(got), 1)
            complete[s] = len(got) == len(ms)
    return totals, complete

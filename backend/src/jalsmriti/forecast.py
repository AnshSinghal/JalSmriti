"""Rain forecast for the places people follow (rain heads-up emails and the place page).

Source: Open-Meteo (https://open-meteo.com), free and keyless, which blends national weather models (ECMWF, NCEP GFS,
DWD ICON and others) at roughly 10-25 km. One request carries up to 50 points; it then answers with a JSON list, one
entry per point in the order asked (a single point gets a plain object). Times are the point's local time
(timezone=auto). Hourly precipitation is the sum of the preceding hour, as Open-Meteo defines it. Data licence:
CC BY 4.0, so every email that uses it says "Weather data by Open-Meteo.com".

Forecasts are cached per 5-character geohash cell (about 5 x 5 km, finer than the models) for an hour, and always
fetched at the cell's centre, so every place in a cell sees the same forecast whoever asked first.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config as C
from . import geo, store

log = logging.getLogger(__name__)

API = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo"
BATCH = 50                 # points per request
CACHE_SECONDS = 3600       # a cached forecast is reused for an hour
CELL_PRECISION = 5         # geohash characters per forecast cell (about 4.9 x 4.9 km)
RETRY_DELAY_S = 1.0        # a failed request is tried once more after this pause

# ---------------------------------------------------------------------------------------- thresholds
# India Meteorological Department (IMD) categories for rain in 24 hours, in mm (IMD reports to 0.1 mm, so amounts
# are rounded to 0.1 mm before they are compared): no rain < 2.5, light 2.5-15.5, moderate 15.6-64.4,
# heavy 64.5-115.5, very heavy 115.6-204.4, extremely heavy >= 204.5.
LEVELS = ((204.5, "extreme"), (115.6, "veryHeavy"), (64.5, "heavy"), (15.6, "moderate"), (2.5, "light"))

# When a place gets a heads-up. IMD "heavy rain" (64.5 mm in a day) is enough everywhere. Places with a water memory
# flood with less: old lake beds, hollows and land just above a drain line collect the water from around them, so
# they get a heads-up from the upper part of IMD's "moderate" band. Short intense bursts above ~15-20 mm in an hour
# are what flood Indian city streets (they arrive faster than street drains can carry them away), so a heavy hour
# counts even when the day's total is modest. Working thresholds, not fitted to flood records: change them here.
HEAVY_MM = 64.5            # IMD heavy rain: every place
STRONG_DAY_MM = 35.0       # strong water memory: a day's total ...
STRONG_HOUR_MM = 15.0      # ... or one hour
SOME_DAY_MM = 50.0         # some water memory: a day's total ...
SOME_HOUR_MM = 20.0        # ... or one hour
TIER_RULES = {"strong": (STRONG_DAY_MM, STRONG_HOUR_MM), "some": (SOME_DAY_MM, SOME_HOUR_MM)}


def _mm(v) -> float:
    try:
        return round(float(v or 0.0), 1)
    except (TypeError, ValueError):
        return 0.0


def level(mm24: float) -> str:
    """IMD category of a 24-hour rain amount: none, light, moderate, heavy, veryHeavy or extreme."""
    mm = _mm(mm24)
    for limit, name in LEVELS:
        if mm >= limit:
            return name
    return "none"


def thresholds(tier: str | None) -> tuple[float, float | None]:
    """(day mm, hour mm or None) from which a place with this water memory gets a heads-up."""
    day_mm, hour_mm = TIER_RULES.get(tier or "", (HEAVY_MM, None))
    return day_mm, hour_mm


def should_alert(day: dict, tier: str) -> bool:
    """Does this forecast day call for a heads-up at a place with this water-memory tier?"""
    mm, hour = _mm(day.get("mm")), _mm(day.get("maxHourlyMm"))
    if mm >= HEAVY_MM:
        return True
    rule = TIER_RULES.get(tier or "")
    return bool(rule) and (mm >= rule[0] or hour >= rule[1])


# ---------------------------------------------------------------------------------------- fetching
def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)


def _get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": C.USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _request(batch: list[tuple[float, float]], days: int, timeout: float):
    """The raw answer for one batch (a list, or an object for one point); None if it failed twice."""
    params = {"latitude": ",".join(f"{la:.4f}" for la, _ in batch),
              "longitude": ",".join(f"{lo:.4f}" for _, lo in batch),
              "hourly": "precipitation", "daily": "precipitation_sum,precipitation_probability_max",
              "forecast_days": days, "timezone": "auto"}
    url = f"{API}?{urllib.parse.urlencode(params, safe=',')}"
    last = None
    for attempt in range(2):
        try:
            data = _get_json(url, timeout)
            if isinstance(data, dict) and data.get("error"):
                raise ValueError(str(data.get("reason") or "error"))
            if not isinstance(data, (dict, list)):
                raise ValueError("unexpected answer")
            return data
        except Exception as ex:          # timeouts, HTTP errors, bad JSON: try once more
            last = ex
            if attempt == 0:
                time.sleep(RETRY_DELAY_S)
    log.warning("Open-Meteo request for %d point(s) failed twice: %s", len(batch), last)
    return None


def _parse(entry: dict, now: datetime, fetched_at: str) -> dict | None:
    """One point's answer -> days (local dates), the next 24 hours and the heaviest hour."""
    try:
        offset = int(entry.get("utc_offset_seconds") or 0)
        daily = entry["daily"]
        hourly = entry.get("hourly") or {}
        hours = [(str(t), float(v) if v is not None else 0.0)
                 for t, v in zip(hourly.get("time") or [], hourly.get("precipitation") or [])]
        local_now = (now + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M")
        # a value labelled 07:00 is the rain of 06:00-07:00, so "from now" starts at the first label after now
        next24 = [v for t, v in hours if t > local_now][:24]
        sums = daily.get("precipitation_sum") or []
        probs = daily.get("precipitation_probability_max") or []
        days = []
        for i, d in enumerate(daily.get("time") or []):
            in_day = [v for t, v in hours if t.startswith(str(d))]
            total = sums[i] if i < len(sums) and sums[i] is not None else sum(in_day)
            prob = probs[i] if i < len(probs) else None
            days.append({"date": str(d), "mm": _mm(total), "prob": int(round(float(prob))) if prob is not None else None,
                         "maxHourlyMm": _mm(max(in_day)) if in_day else 0.0})
        if not days:
            raise ValueError("no days")
        return {"days": days, "next24hMm": _mm(sum(next24)),
                "maxHourlyMm": _mm(max(v for _, v in hours)) if hours else max(d["maxHourlyMm"] for d in days),
                "timezone": entry.get("timezone") or "GMT", "utcOffsetSeconds": offset,
                "source": SOURCE, "fetchedAt": fetched_at}
    except (KeyError, TypeError, ValueError, AttributeError) as ex:
        log.warning("unreadable Open-Meteo entry: %s", ex)
        return None


def fetch(points: list[tuple[float, float]], days: int = 3, timeout: float = 8.0, *,
          now: datetime | None = None) -> list[dict | None]:
    """The forecast for each (lat, lon), in order; None for a point whose request failed (after one retry).

    Each forecast: {"days": [{"date", "mm", "prob", "maxHourlyMm"}], "next24hMm", "maxHourlyMm", "timezone",
    "utcOffsetSeconds", "source", "fetchedAt"}. Dates are the point's local dates, today first.
    `now` (UTC) sets where "the next 24 hours" start; tests pass it, the default is the current time.
    """
    pts = [(float(la), float(lo)) for la, lo in points]
    now = _utc(now)
    days = max(1, min(16, int(days)))
    out: list[dict | None] = []
    for start in range(0, len(pts), BATCH):
        batch = pts[start:start + BATCH]
        data = _request(batch, days, timeout)
        got: list[dict | None] = [None] * len(batch)
        if data is not None:
            entries = data if isinstance(data, list) else [data]
            fetched_at = store.now_iso()
            for j, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                k = entry.get("location_id", j)          # Open-Meteo numbers the points after the first
                k = k if isinstance(k, int) and 0 <= k < len(batch) else j
                if k < len(batch):
                    got[k] = _parse(entry, now, fetched_at)
        out += got
    return out


# ---------------------------------------------------------------------------------------- cached, per place
def cell(lat: float, lon: float) -> str:
    """The forecast cell (5-character geohash) of a place."""
    return geo.geohash(lat, lon, CELL_PRECISION)


def with_levels(fc: dict) -> dict:
    """The forecast with each day's IMD category added as "level"."""
    return {**fc, "days": [{**d, "level": level(d.get("mm"))} for d in fc.get("days") or []]}


def remember(cell_id: str, fc: dict) -> None:
    """Cache a cell's forecast for an hour (the daily rain check shares its forecasts with the website this way)."""
    store.put({"PK": f"FCST#{cell_id}", "SK": "META", "payload": fc, "fetchedAt": fc.get("fetchedAt") or store.now_iso(),
               "ttl": int(time.time()) + CACHE_SECONDS})


def for_place(lat: float, lon: float) -> dict | None:
    """The forecast for a place, with "level" per day: from the cache when under an hour old, else fetched at the
    centre of its cell and cached. None when Open-Meteo cannot be reached and nothing fresh is cached."""
    cid = cell(lat, lon)
    try:
        cached = store.get(f"FCST#{cid}", "META")
    except Exception as ex:
        log.warning("forecast cache read failed: %s", ex)
        cached = None
    if cached and cached.get("payload") and (cached.get("fetchedAt") or "") >= store.iso_days_ago(CACHE_SECONDS / 86400):
        return with_levels(cached["payload"])
    clat, clon = geo.geohash_decode(cid)
    fc = fetch([(clat, clon)])[0]
    if fc is None:
        return None
    fc = with_levels(fc)
    try:
        remember(cid, fc)
    except Exception as ex:
        log.warning("forecast cache write failed: %s", ex)
    return fc

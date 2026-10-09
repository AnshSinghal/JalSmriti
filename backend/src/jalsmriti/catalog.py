"""Finding satellite scenes and turning their asset links into paths GDAL can read.

Two open catalogues are used:
  * Earth Search on AWS (Element 84): Sentinel-2 L2A COGs (s3://sentinel-cogs, us-west-2) and Copernicus DEM.
  * Microsoft Planetary Computer: Landsat 4-9 Collection 2, Sentinel-1 RTC, JRC Global Surface Water,
    Impact Observatory annual land cover and ESA WorldCover. Its blobs need a free, anonymous SAS token, which
    we request per storage account and container (the per-collection token endpoint is unreliable for some sets).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from . import config as C

log = logging.getLogger(__name__)

_tok_lock = threading.Lock()
_tokens: dict[tuple[str, str], tuple[str, float]] = {}


def _http_json(url: str, body: dict | None = None, timeout: int = 60, tries: int = 4) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    last: Exception | None = None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"User-Agent": C.USER_AGENT, "Accept": "application/json",
                                              **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as ex:
            last = ex
            if ex.code in (400, 401, 403, 404):
                raise
        except Exception as ex:  # network hiccups and 5xx are common on public catalogues; retry with backoff
            last = ex
        time.sleep(1.5 * 2 ** attempt)
    raise RuntimeError(f"catalogue request failed: {url}: {last}")


def pc_token(account: str, container: str) -> str:
    key = (account, container)
    with _tok_lock:
        tok = _tokens.get(key)
        if tok and tok[1] > time.time() + 300:
            return tok[0]
    j = _http_json(f"{C.PC_SAS}/{account}/{container}", timeout=30)
    with _tok_lock:
        _tokens[key] = (j["token"], time.time() + 40 * 60)
    return j["token"]


_BLOB = re.compile(r"^https://([a-z0-9]+)\.blob\.core\.windows\.net/([^/?]+)/")


def readable(href: str) -> str:
    """A path rasterio/GDAL can open: signs Planetary Computer blobs, maps public s3:// to https."""
    m = _BLOB.match(href)
    if m:
        return href.split("?")[0] + "?" + pc_token(m.group(1), m.group(2))
    if href.startswith("s3://"):
        bucket, _, key = href[5:].partition("/")
        if bucket == "copernicus-dem-30m":
            return f"https://copernicus-dem-30m.s3.amazonaws.com/{key}"
        return f"/vsis3/{bucket}/{key}"
    return href


def search(api: str, collection: str, bbox: list[float], dt: str | None = None, query: dict | None = None,
           limit: int = 500, sortby: list | None = None) -> list[dict]:
    """STAC item search with pagination. dt is 'YYYY-MM-DD/YYYY-MM-DD' (dates are expanded to full days)."""
    body: dict = {"collections": [collection], "bbox": [round(v, 6) for v in bbox], "limit": min(limit, 250)}
    if dt:
        a, _, b = dt.partition("/")
        body["datetime"] = f"{a}T00:00:00Z/{(b or a)}T23:59:59Z" if "T" not in dt else dt
    if query:
        body["query"] = query
    if sortby:
        body["sortby"] = sortby
    url, out = f"{api}/search", []
    while True:
        j = _http_json(url, body)
        out.extend(j.get("features", []))
        nxt = [lk for lk in j.get("links", []) if lk.get("rel") == "next"]
        if not nxt or len(out) >= limit:
            break
        n = nxt[0]
        if n.get("method", "GET").upper() == "POST":
            url, body = n["href"], (n.get("body") or body)
        else:
            url, body = n["href"], None
            j = _http_json(url)
            out.extend(j.get("features", []))
            break
    return out[:limit]


def item_by_id(api: str, collection: str, item_id: str) -> dict:
    return _http_json(f"{api}/collections/{collection}/items/{item_id}")


# ------------------------------------------------------------------------------------------ scene picking
def item_date(it: dict) -> date:
    return datetime.fromisoformat(it["properties"]["datetime"].replace("Z", "+00:00")).date()


def season_window(season: int, window: tuple[str, str]) -> tuple[str, str]:
    """('10-15','02-28') for season 2019 -> ('2019-10-15', '2020-02-28')."""
    a, b = window
    end_year = season + 1 if b < a else season
    end = b
    if b == "02-29":
        end = "02-28"
    return f"{season}-{a}", f"{end_year}-{end}"


def _footprint_covers(it: dict, bbox: list[float], frac: float = 0.9) -> bool:
    """Rough check that the item footprint covers most of the bbox (uses the item bbox)."""
    ib = it.get("bbox")
    if not ib:
        return True
    w, s, e, n = bbox
    iw, is_, ie, in_ = ib[0], ib[1], ib[-2] if len(ib) == 6 else ib[2], ib[-1] if len(ib) == 6 else ib[3]
    ix = max(0.0, min(e, ie) - max(w, iw))
    iy = max(0.0, min(n, in_) - max(s, is_))
    area = (e - w) * (n - s)
    return area <= 0 or ix * iy / area >= frac


def landsat_platform_ok(it: dict, season: int) -> bool:
    """Prefer full-swath sensors: Landsat 7 has SLC-off gaps after 31 May 2003 (still usable, ranked lower)."""
    return it["properties"].get("platform") in ("landsat-4", "landsat-5", "landsat-7", "landsat-8", "landsat-9")


def pick_season_scenes(source: str, bbox: list[float], season: int, window: tuple[str, str],
                       n: int = C.SCENES_PER_SEASON, max_cloud: float = C.MAX_SCENE_CLOUD) -> list[dict]:
    """The n clearest scenes for one post-monsoon season over the bbox.

    source 'LS' searches Landsat Collection 2 L2 (Planetary Computer); 'S2' Sentinel-2 L2A (Earth Search).
    Landsat 7 after the 2003 scan-line failure is ranked after full-swath sensors at similar cloud cover.
    """
    a, b = season_window(season, window)
    if source == "S2":
        items = search(C.EARTH_SEARCH, C.S2_COLLECTION, bbox, f"{a}/{b}", {"eo:cloud_cover": {"lt": max_cloud}}, limit=400)
    else:
        items = search(C.PLANETARY_COMPUTER, "landsat-c2-l2", bbox, f"{a}/{b}", {"eo:cloud_cover": {"lt": max_cloud}}, limit=400)
        items = [it for it in items if landsat_platform_ok(it, season)]

    def rank(it):
        cc = float(it["properties"].get("eo:cloud_cover") or 100)
        slc_off = it["properties"].get("platform") == "landsat-7" and item_date(it) > date(2003, 5, 31)
        covers = _footprint_covers(it, bbox, 0.6)
        return (not covers, slc_off, round(cc / 5), cc)

    items.sort(key=rank)
    # one scene per acquisition day (adjacent tiles of the same pass are kept together by the reader)
    picked, days = [], set()
    for it in items:
        d = (item_date(it), it["properties"].get("platform"))
        if d in days:
            continue
        days.add(d)
        picked.append(it)
        if len(picked) >= n:
            break
    return picked


def same_pass_items(source: str, bbox: list[float], it: dict) -> list[dict]:
    """All tiles of the same satellite pass over the bbox (Sentinel-2 tiles / Landsat rows), for mosaicking."""
    d = item_date(it)
    plat = it["properties"].get("platform")
    if source == "S2":
        items = search(C.EARTH_SEARCH, C.S2_COLLECTION, bbox, f"{d}/{d}", limit=20)
    else:
        items = search(C.PLANETARY_COMPUTER, "landsat-c2-l2", bbox, f"{d}/{d}", limit=20)
    items = [x for x in items if x["properties"].get("platform") == plat]
    items.sort(key=lambda x: x["id"] != it["id"])
    return items or [it]


def s1_items(bbox: list[float], start: str, end: str, orbit: int | None = None, limit: int = 500) -> list[dict]:
    q = {"sat:relative_orbit": {"eq": orbit}} if orbit is not None else None
    return search(C.PLANETARY_COMPUTER, "sentinel-1-rtc", bbox, f"{start}/{end}", q, limit=limit)


def days_between(a: date, b: date) -> int:
    return abs((a - b).days)


def doy_distance(a: date, b: date) -> int:
    """Distance between two dates ignoring the year (e.g. 3 Aug 2019 vs 10 Aug 2026 -> 7)."""
    da = a.timetuple().tm_yday
    db = b.timetuple().tm_yday
    d = abs(da - db)
    return min(d, 365 - d)


def iso(d: date) -> str:
    return d.isoformat()


def shift(d: date, days: int) -> date:
    return d + timedelta(days=days)

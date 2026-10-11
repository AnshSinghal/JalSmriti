"""Recent news about a lake or a locality: headlines about floods, encroachment, pollution or restoration.

Two open sources, asked in this order:
  1. Google News search (its public RSS feed, for India in English): fast and good on local papers (The Hindu,
     Deccan Herald, Bangalore Mirror ...), searched over the past year.
  2. The GDELT Project's open index of world news (DOC 2.0 API), when Google News does not answer. GDELT searches only
     the last three months, can take 10 seconds or more, and asks for at most one request every five seconds, so its
     calls are spaced site-wide through one DynamoDB item.
Every answer is cached for 12 hours per query, and when both sources fail the last answer is served (marked stale).

Only headlines, outlets, dates and links are shown; each article stays on its publisher's site. A headline is kept
only when it is about the water: simple keywords tag it as flooding, encroachment, pollution or restoration, and
untagged headlines (a crime story that happens to name the lake) are left out.

The API Lambda imports this module: only the standard library and light jalsmriti modules.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import config as C
from . import store

log = logging.getLogger(__name__)

GOOGLE = "https://news.google.com/rss/search"
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
WINDOW = "1year"
WINDOW_DAYS = 365
GDELT_WINDOW = "3months"      # the longest window the GDELT DOC 2.0 API searches
CACHE_HOURS = 12
SPACING_S = 5.5               # GDELT: at most one request every 5 seconds
MAX_ITEMS = 12
TIMEOUT_S = 8
CITY_TERMS = {
    "bengaluru": ("Bengaluru", "Bangalore"), "chennai": ("Chennai", "Madras"),
    "hyderabad": ("Hyderabad", "Secunderabad"),
    "delhi-ncr": ("Delhi", "Gurugram", "Gurgaon", "Noida", "Ghaziabad", "Faridabad"),
    "kochi": ("Kochi", "Ernakulam", "Cochin"), "sivasagar": ("Sivasagar", "Assam"), "bhadrak": ("Bhadrak", "Odisha"),
    "kathmandu": ("Kathmandu", "Lalitpur", "Bhaktapur"), "butwal": ("Butwal", "Rupandehi"),
}
FLOOD_WORDS = ("flood", "flooded", "flooding", "floods", "waterlogging", "waterlogged", "inundated", "submerged")
TAGS = {
    "flood": re.compile(r"flood|inundat|waterlog|submerg|deluge|cloudburst|downpour|heavy rain|rain fury|overflow|"
                        r"breach", re.I),
    # Only words that say land or water is being taken: a company building a flyover near a lake is not an
    # encroachment story, and the tag must not suggest one.
    "encroachment": re.compile(r"encroach|land[- ]?grab|illegal(?:ly)? (?:construct|buil|structure|layout|occup|fill)|"
                               r"unauthori[sz]ed (?:construct|buil|structure|layout)|demoli|bulldoz|razed|evict|"
                               r"squatter|buffer zone|notices? to (?:the |a )?(?:developer|builder)|"
                               r"built (?:up )?on (?:the |a |an )?(?:old )?(?:lake|tank)", re.I),
    "pollution": re.compile(r"sewage|sewer|foam|froth|dead fish|fish kill|fish death|pollut|hyacinth|weed|toxic|"
                            r"effluent|garbage|dumping|debris|\bfire\b|\bblaze\b|stink|contaminat|algae|algal", re.I),
    "restoration": re.compile(r"rejuvenat|restor|desilt|revival|revive|clean[- ]?up|cleaning|conserv|wetland|"
                              r"makeover|inflow|treatment plant|\bSTP\b|plantation|\bbund (?:repair|strengthen|work)|"
                              r"beautif", re.I),
}
SAFE = re.compile(r"[^\w .,'()&-]", re.UNICODE)


def lake_query(name: str | None, area_id: str | None) -> str | None:
    """The search for a lake with a name of its own: the name as a phrase, with its city's names."""
    name = SAFE.sub("", str(name or "")).strip()
    if len(name) < 4:
        return None
    cities = CITY_TERMS.get(area_id or "")
    return f'"{name}"' + (f" ({' OR '.join(cities)})" if cities else "")


def place_query(locality: str | None) -> str | None:
    """The search for floods at a locality: the locality as a phrase, with words for flooding."""
    loc = SAFE.sub("", str(locality or "")).strip()
    if len(loc) < 4:
        return None
    return f'"{loc}" ({" OR ".join(FLOOD_WORDS)})'


def tags(title: str) -> list[str]:
    return [k for k, rx in TAGS.items() if rx.search(title or "")]


def _keep(items: list[dict], title_has: str | None = None) -> list[dict]:
    """One per headline, about the water (tagged), within the window, newest first, at most MAX_ITEMS; with
    `title_has`, only headlines that name it (a locality's flood news must be about that locality)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).date().isoformat()
    must = (title_has or "").strip().lower()
    out, seen = [], set()
    for a in sorted(items, key=lambda a: a.get("date") or "", reverse=True):
        key = re.sub(r"\W+", "", a["title"].lower())[:80]
        if key in seen or not a["tags"] or (a.get("date") and a["date"] < cutoff) or (must and must not in a["title"].lower()):
            continue
        seen.add(key)
        out.append(a)
        if len(out) >= MAX_ITEMS:
            break
    return out


# ------------------------------------------------------------------------------------------ Google News (RSS)
def parse_google(payload: bytes | str, title_has: str | None = None) -> list[dict] | None:
    """Articles from a Google News RSS answer; None when it is not RSS."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None
    if root.tag != "rss":
        return None
    out = []
    for it in root.iter("item"):
        title = " ".join((it.findtext("title") or "").split())
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = " ".join((src_el.text or "").split()) if src_el is not None else ""
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].rstrip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        try:
            date = parsedate_to_datetime(it.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            date = None
        domain = urllib.parse.urlparse(src_el.get("url") or "").netloc.removeprefix("www.") if src_el is not None else ""
        out.append({"title": title[:220], "url": link[:600], "domain": source[:80] or domain[:80], "date": date,
                    "language": "English", "country": None, "tags": tags(title), "via": "Google News"})
    return _keep(out, title_has)


def _google(query: str, title_has: str | None = None) -> list[dict] | None:
    params = {"q": f"{query} when:{WINDOW_DAYS}d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    req = urllib.request.Request(f"{GOOGLE}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": C.USER_AGENT, "Accept": "application/rss+xml"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return parse_google(r.read(), title_has)
    except Exception as ex:
        log.warning("google news failed: %s", ex)
        return None


# ------------------------------------------------------------------------------------------ GDELT (fallback)
def _date(seen: str | None) -> str | None:
    """GDELT's seendate (20261003T081500Z) as an ISO date."""
    try:
        return datetime.strptime(str(seen), "%Y%m%dT%H%M%SZ").date().isoformat()
    except (TypeError, ValueError):
        return None


def parse(payload: str, title_has: str | None = None) -> list[dict] | None:
    """Articles from GDELT's ArtList JSON; None when it is not JSON (GDELT answers busy or error messages as text)."""
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    out = []
    for a in (data or {}).get("articles", []) or []:
        title = " ".join(str(a.get("title") or "").split())
        url = str(a.get("url") or "")
        if not title or not url.startswith(("http://", "https://")):
            continue
        out.append({"title": title[:220], "url": url[:600], "domain": str(a.get("domain") or "")[:80],
                    "date": _date(a.get("seendate")), "language": a.get("language"),
                    "country": a.get("sourcecountry"), "tags": tags(title), "via": "GDELT"})
    return _keep(out, title_has)


def _take_turn() -> bool:
    """One GDELT request every SPACING_S seconds across all Lambdas (a conditional write on one item)."""
    now = time.time()
    try:
        store.update("NEWS", "THROTTLE", sets={"lastCall": now}, condition="attribute_not_exists(lastCall) OR lastCall < :cut",
                     cond_values={":cut": now - SPACING_S})
        return True
    except Exception as ex:
        if "ConditionalCheckFailed" not in str(ex):
            log.warning("news throttle: %s", ex)
        return False


def _fetch(query: str, title_has: str | None = None) -> list[dict] | None:
    params = {"query": query, "mode": "artlist", "maxrecords": "50", "format": "json", "sort": "datedesc",
              "timespan": GDELT_WINDOW}
    req = urllib.request.Request(f"{GDELT}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": C.USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            got = parse(r.read().decode("utf-8", "replace"), title_has)
    except Exception as ex:
        log.warning("gdelt failed: %s", ex)
        return None
    if got is None:
        log.warning("gdelt answered without JSON (busy)")
    return got


def _gdelt(query: str, wait_s: float, title_has: str | None = None) -> list[dict] | None:
    deadline = time.time() + wait_s
    while True:
        if _take_turn():
            return _fetch(query, title_has)
        if time.time() + 1.0 > deadline:
            return None
        time.sleep(1.0)


# ------------------------------------------------------------------------------------------ search
def search(query: str | None, kind: str, wait_s: float = 3.0, title_has: str | None = None) -> dict:
    """{"status", "query", "articles", "fetchedAt", "window", "sources"} for one query, from the cache when fresh.

    status: "ok" (articles may be empty), "stale" (both sources failed: the last answer), "unavailable" (both
    failed, nothing cached) or "none" (nothing to search for)."""
    base = {"window": WINDOW, "kind": kind, "source": "Google News, GDELT Project"}
    if not query:
        return {**base, "status": "none", "query": None, "articles": []}
    key = f"{kind}#{query.lower()}"[:900]
    cached = store.get("NEWS", key)
    fresh_after = (datetime.now(timezone.utc) - timedelta(hours=CACHE_HOURS)).isoformat()
    if cached and (cached.get("fetchedAt") or "") >= fresh_after:
        return {**base, "status": "ok", "query": query, "articles": cached.get("articles") or [],
                "fetchedAt": cached.get("fetchedAt"), "cached": True}
    if C.LOCAL:
        return {**base, "status": "ok", "query": query, "articles": [], "fetchedAt": None, "local": True}
    got = _google(query, title_has)
    if got is None:
        got = _gdelt(query, wait_s, title_has)
    if got is None:
        if cached:
            return {**base, "status": "stale", "query": query, "articles": cached.get("articles") or [],
                    "fetchedAt": cached.get("fetchedAt")}
        return {**base, "status": "unavailable", "query": query, "articles": []}
    now = datetime.now(timezone.utc).isoformat()
    store.put({"PK": "NEWS", "SK": key, "query": query, "articles": got, "fetchedAt": now,
               "ttl": int(time.time()) + 14 * 86400})
    return {**base, "status": "ok", "query": query, "articles": got, "fetchedAt": now}


def summary(articles: list[dict]) -> dict:
    """How many headlines carry each tag."""
    out: dict[str, int] = {}
    for a in articles or []:
        for t in a.get("tags") or []:
            out[t] = out.get(t, 0) + 1
    return out

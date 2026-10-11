"""A lake's likely causes of harm, read from its satellite record, with what residents and authorities can do; and
recent news naming it (GDELT), cached and spaced as GDELT asks."""
import json

import pytest

from jalsmriti import insights as I
from jalsmriti import news as N
from jalsmriti import store
from test_api import call

BELLANDUR_LIKE = {
    "historicHa": 380.0, "lostHa": 120.0, "lostPct": 31.6, "builtHa": 41.0, "builtPct": 10.8,
    "builtByYear": {"2017": 0.2, "2018": 12.0, "2023": 41.0}, "builtChangeHa": 40.8,
    "replacedBy": {"built": 38.0, "bare": 9.0, "vegetation": 21.0, "crops": 0.0, "water": 3.0},
    "retention": {"ratio": 0.42, "pairs": [{"season": 2025, "waterHa": 110.0, "thenWaterHa": 262.0, "rainMm": 980,
                                            "comparableRain": True}]},
    "quality": {"date": "2026-10-04", "weedPct": 89.4, "algaeSign": True},
    "storageLost": {"millionLitresLow": 1200, "millionLitresHigh": 2400, "olympicPoolsLow": 480, "olympicPoolsHigh": 960},
    "grade": {"grade": "D", "score": 42},
}


def test_a_lake_under_every_pressure():
    found = I.causes(BELLANDUR_LIKE)
    by = {c["key"]: c for c in found}
    assert [c["key"] for c in found] == ["encroachment", "overgrown", "inflow", "sewage", "drying"]
    assert {k: c["severity"] for k, c in by.items()} == {"encroachment": "high", "overgrown": "high", "inflow": "high",
                                                       "sewage": "high", "drying": "medium"}
    assert by["encroachment"]["vars"] == {"ha": 41.0, "pct": 10.8, "since": 2018, "change": 40.8}
    assert "first seen around 2018" in by["encroachment"]["text"]
    assert by["overgrown"]["vars"]["ha"] == 21.0 and by["overgrown"]["vars"]["weedy"] is True
    assert "choked with weeds" in by["overgrown"]["text"]
    assert by["drying"]["vars"]["ha"] == 9.0
    assert by["inflow"]["vars"]["pct"] == 42 and by["inflow"]["vars"]["sameRain"] is True
    assert by["sewage"]["vars"] == {"weedPct": 89.4, "algae": True, "date": "2026-10-04"}
    acts = I.actions(found)
    assert acts["residents"] == ["photo", "rti", "watch", "dossier", "home", "inflow", "sewage", "group"]
    assert acts["authorities"] == ["survey", "remove", "channels", "debris", "stp", "weeds", "monitor"]
    assert I.benefit(BELLANDUR_LIKE) == {"lostHa": 120.0, "millionLitresLow": 1200, "millionLitresHigh": 2400,
                                         "poolsLow": 480, "poolsHigh": 960}


def test_a_healthy_lake_is_holding_up():
    m = {"historicHa": 12.0, "lostHa": 0.2, "lostPct": 1.7, "builtHa": 0.0, "builtPct": 0.0, "replacedBy": {},
         "retention": {"ratio": 0.97}, "quality": {"date": "2026-10-04", "weedPct": 4.0, "algaeSign": False},
         "storageLost": {"millionLitresLow": 2, "millionLitresHigh": 4}, "grade": {"grade": "A"}}
    found = I.causes(m)
    assert [c["key"] for c in found] == ["holding"] and found[0]["severity"] == "low"
    assert I.actions(found) == {"residents": ["photo", "rti", "watch", "dossier", "group"], "authorities": ["monitor"]}
    assert I.benefit(m) is None                          # nothing lost worth counting


def test_overgrown_bed_and_medium_signs():
    m = {"lostHa": 3.0, "lostPct": 12.0, "builtHa": 0.4, "builtPct": 2.0, "replacedBy": {"crops": 2.2},
         "retention": {"ratio": 0.7, "pairs": []}, "quality": {"weedPct": 5.0, "date": "2026-09-01"}}
    found = I.causes(m)
    assert {c["key"]: c["severity"] for c in found} == {"encroachment": "medium", "overgrown": "medium",
                                                         "inflow": "medium"}
    assert found[1]["vars"]["weedy"] is False and "choked" not in found[1]["text"]
    assert "bed" in I.actions(found)["authorities"]          # no weeds on the water: clear the bed, stop farming it


def test_lake_page_carries_the_insights(aws, lake):
    s, lk = call("GET", f"/v1/lakes/{lake['lakeId']}")
    assert s == 200 and lk["insights"]["causes"][0]["key"] in ("encroachment", "drying", "inflow", "sewage")
    assert lk["insights"]["actions"]["residents"][0] == "photo"
    assert lk["insights"]["benefit"]["millionLitresHigh"] == 250


GDELT_ANSWER = json.dumps({"articles": [
    {"url": "https://www.deccanherald.com/a", "title": "Bellandur lake  froths again after heavy rain",
     "seendate": "20261003T081500Z", "domain": "deccanherald.com", "language": "English", "sourcecountry": "India"},
    {"url": "https://www.thehindu.com/b", "title": "Bellandur lake froths again after heavy rain",
     "seendate": "20261003T091500Z", "domain": "thehindu.com", "language": "English", "sourcecountry": "India"},
    {"url": "https://example.com/c", "title": "BBMP to clear encroachments on Bellandur lake buffer",
     "seendate": "20260921T060000Z", "domain": "example.com", "language": "English", "sourcecountry": "India"},
    {"url": "javascript:alert(1)", "title": "bad link", "seendate": "20260920T060000Z"},
]})


def test_gdelt_answers_are_parsed_deduplicated_and_tagged():
    arts = N.parse(GDELT_ANSWER)
    assert [a["domain"] for a in arts] == ["deccanherald.com", "example.com"]          # one per headline, safe links
    assert arts[0]["title"] == "Bellandur lake froths again after heavy rain" and arts[0]["date"] == "2026-10-03"
    assert arts[0]["tags"] == ["flood", "pollution"] and arts[1]["tags"] == ["encroachment"]
    assert N.parse("Please limit requests to one every 5 seconds") is None              # busy: plain text
    assert N.summary(arts) == {"flood": 1, "pollution": 1, "encroachment": 1}


def test_tags_do_not_accuse():
    """Headlines from real Google News answers (Oct 2026): building near a lake is not tagged as encroachment."""
    assert N.tags("Builder completes construction of flyover near Bellandur Lake") == []
    assert N.tags("Bund roads inside lake area: BDA issues notices to developer") == ["encroachment"]
    assert N.tags("Velachery residents urge removal of encroachments along six-vent culvert") == ["encroachment"]
    assert N.tags("Illegal sewage discharge into Varthur lake continues") == ["pollution"]
    assert N.tags("Man fired at near lake park") == [] and N.tags("Bellandur lake caught fire again") == ["pollution"]
    assert N.tags("Bengaluru: 5 years on, Bellandur Lake to receive rainwater inflow this monsoon") == ["restoration"]


def test_queries():
    assert N.lake_query("Bellandur Lake", "bengaluru") == '"Bellandur Lake" (Bengaluru OR Bangalore)'
    assert N.lake_query('Ulsoor "Lake"; drop', None) == '"Ulsoor Lake drop"'
    assert N.lake_query("Kr", "bengaluru") is None
    assert N.place_query("Velachery").startswith('"Velachery" (flood OR flooded')


GOOGLE_RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>x</title>
<item><title>BDA needs six more months to desilt Bellandur Lake - Deccan Herald</title>
 <link>https://news.google.com/rss/articles/abc</link><pubDate>Thu, 03 Sep 2026 07:00:00 GMT</pubDate>
 <source url="https://www.deccanherald.com">Deccan Herald</source></item>
<item><title>Teen found murdered near Bellandur lake - The Hindu</title>
 <link>https://news.google.com/rss/articles/def</link><pubDate>Fri, 07 Aug 2026 07:00:00 GMT</pubDate>
 <source url="https://www.thehindu.com">The Hindu</source></item>
<item><title>Foam gone, but Bellandur lake revival misses its core - Citizen Matters</title>
 <link>https://news.google.com/rss/articles/ghi</link><pubDate>Mon, 29 Jun 2026 07:00:00 GMT</pubDate>
 <source url="https://citizenmatters.in">Citizen Matters</source></item>
<item><title>Bellandur lake caught fire in 2017 - Old News</title>
 <link>https://news.google.com/rss/articles/old</link><pubDate>Fri, 20 Jan 2017 07:00:00 GMT</pubDate>
 <source url="https://example.com">Old News</source></item>
</channel></rss>"""


def test_google_news_answers_are_parsed_and_kept_to_the_water():
    arts = N.parse_google(GOOGLE_RSS)
    assert [a["title"] for a in arts] == ["BDA needs six more months to desilt Bellandur Lake",
                                          "Foam gone, but Bellandur lake revival misses its core"]   # crime and old news out
    assert arts[0]["domain"] == "Deccan Herald" and arts[0]["date"] == "2026-09-03" and arts[0]["tags"] == ["restoration"]
    assert arts[1]["tags"] == ["pollution", "restoration"] and arts[0]["via"] == "Google News"
    assert N.parse_google("<html>not rss</html>") is None and N.parse_google("garbage <<") is None
    assert N.parse_google(GOOGLE_RSS, title_has="Velachery") == []          # a locality's news must name it


def test_search_uses_google_news_then_gdelt_and_serves_stale(aws, monkeypatch):
    monkeypatch.setattr(N.C, "LOCAL", False)
    calls = []
    monkeypatch.setattr(N, "_google", lambda q, t=None: calls.append(("google", q)) or N.parse_google(GOOGLE_RSS))
    monkeypatch.setattr(N, "_fetch", lambda q, t=None: calls.append(("gdelt", q)) or N.parse(GDELT_ANSWER))
    q = N.lake_query("Bellandur Lake", "bengaluru")
    first = N.search(q, "lake")
    assert first["status"] == "ok" and len(first["articles"]) == 2 and calls == [("google", q)]
    again = N.search(q, "lake")
    assert again["cached"] and len(calls) == 1                         # served from the 12-hour cache
    key = f"lake#{q.lower()}"
    store.update("NEWS", key, sets={"fetchedAt": "2020-01-01T00:00:00+00:00"})       # make it old
    monkeypatch.setattr(N, "_google", lambda q, t=None: calls.append(("google", q)) or None)   # Google down
    fallback = N.search(q, "lake", wait_s=0)
    assert fallback["status"] == "ok" and calls[-1] == ("gdelt", q) and fallback["articles"][0]["via"] == "GDELT"
    store.update("NEWS", key, sets={"fetchedAt": "2020-01-01T00:00:00+00:00"})
    monkeypatch.setattr(N, "_fetch", lambda q, t=None: None)              # GDELT busy too
    stale = N.search(q, "lake", wait_s=0)
    assert stale["status"] == "stale" and len(stale["articles"]) == 2
    assert N.search(None, "lake")["status"] == "none"


def test_news_routes(aws, lake):
    s, r = call("GET", f"/v1/lakes/{lake['lakeId']}/news")
    assert s == 200 and r["status"] == "none" and r["reason"] == "no name of its own"   # the fixture has no source
    store.update(f"LAKE#{lake['lakeId']}", "META", sets={"nameSource": "OpenStreetMap"})
    s, r = call("GET", f"/v1/lakes/{lake['lakeId']}/news")
    assert s == 200 and r["status"] == "ok" and r["query"] == '"Test Kere" (Bengaluru OR Bangalore)'
    s, r = call("GET", "/v1/news/floods", query={"locality": "Velachery"})
    assert s == 200 and r["locality"] == "Velachery" and r["kind"] == "floods"
    assert call("GET", "/v1/news/floods", query={"locality": "ab"})[0] == 400

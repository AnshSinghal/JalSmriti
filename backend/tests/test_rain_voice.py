"""Rain heads-up and Listen: IMD levels and alert thresholds, Open-Meteo parsing (one point and many), the forecast
cache, the daily rain check end to end (emails kept in alerts.OUTBOX, or published through mocked SNS), test emails,
the spoken text of places and lakes, and speech (the local WAV stand-in, and Polly through a stub).
Open-Meteo is replaced by canned answers shaped like the real API; nothing here touches the network."""
import io
import json
import urllib.error
import urllib.parse
import uuid
import wave
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

IST = timedelta(hours=5, minutes=30)
BENGALURU = (12.9352, 77.6807)     # Bellandur
CHENNAI = (12.9815, 80.2180)       # Velachery


# ------------------------------------------------------------------------------------------ a fake Open-Meteo
def om_entry(start: date, daily, peaks=None, probs=None, hourly=None, lat=12.95, lon=77.70,
             tz="Asia/Kolkata", offset=19800) -> dict:
    """One point as Open-Meteo answers it (timezone=auto: local times, hourly rain = sum of the preceding hour).
    Unless `hourly` ({"YYYY-MM-DDTHH:00": mm}) is given, each day's heaviest hour (`peaks`) falls at 15:00."""
    n = len(daily)
    peaks = peaks or [0.0] * n
    times, rain = [], []
    for i in range(n):
        d = (start + timedelta(days=i)).isoformat()
        for h in range(24):
            t = f"{d}T{h:02d}:00"
            times.append(t)
            rain.append(hourly.get(t, 0.0) if hourly is not None else (peaks[i] if h == 15 else 0.0))
    return {"latitude": lat, "longitude": lon, "generationtime_ms": 0.08, "utc_offset_seconds": offset, "timezone": tz,
            "timezone_abbreviation": "GMT+5:30", "elevation": 870.0,
            "hourly_units": {"time": "iso8601", "precipitation": "mm"},
            "hourly": {"time": times, "precipitation": rain},
            "daily_units": {"time": "iso8601", "precipitation_sum": "mm", "precipitation_probability_max": "%"},
            "daily": {"time": [(start + timedelta(days=i)).isoformat() for i in range(n)],
                      "precipitation_sum": list(daily), "precipitation_probability_max": list(probs or [50] * n)}}


class FakeOpenMeteo:
    """Stands in for urllib.request.urlopen: answers like the real API (a list for several points, an object for
    one, with location_id on every point after the first) from make(lat, lon) -> entry."""

    def __init__(self, make, fail_first: int = 0, fail_if=None):
        self.make, self.fail_first, self.fail_if, self.urls = make, fail_first, fail_if, []

    def __call__(self, req, timeout=None):
        url = getattr(req, "full_url", req)
        self.urls.append(url)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        lats = [float(x) for x in q["latitude"][0].split(",")]
        lons = [float(x) for x in q["longitude"][0].split(",")]
        if self.fail_first > 0:
            self.fail_first -= 1
            raise urllib.error.URLError("timed out")
        if self.fail_if and self.fail_if(lats):
            raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)
        entries = [self.make(la, lo) for la, lo in zip(lats, lons)]
        entries = [e if i == 0 else {**e, "location_id": i} for i, e in enumerate(entries)]
        return io.BytesIO(json.dumps(entries[0] if len(entries) == 1 else entries).encode())

    def points(self, i: int = -1):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.urls[i]).query)
        return list(zip(q["latitude"][0].split(","), q["longitude"][0].split(",")))


@pytest.fixture()
def openmeteo(monkeypatch):
    """install(make, **kw) puts a FakeOpenMeteo in place of the network and returns it."""
    from jalsmriti import forecast
    monkeypatch.setattr(forecast, "RETRY_DELAY_S", 0)

    def install(make, **kw):
        fake = FakeOpenMeteo(make, **kw)
        monkeypatch.setattr(forecast.urllib.request, "urlopen", fake)
        return fake
    return install


def ist_today(now: datetime) -> date:
    return (now + IST).date()


def put_follow(user_id: str, lat: float, lon: float, label: str, tier: str, lang: str = "en", **extra) -> dict:
    from jalsmriti import geo, store
    gh7 = geo.geohash(lat, lon, 7)
    item = {"PK": f"FOLLOW#{user_id}", "SK": gh7, "userId": user_id, "gh7": gh7, "lat": lat, "lon": lon, "label": label,
            "tier": tier, "lang": lang, "createdAt": store.now_iso(), "GSI2PK": f"USER#{user_id}", "GSI2SK": f"FOLLOW#{gh7}",
            "GSI3PK": "FOLLOWS", "GSI3SK": f"{gh7}#{user_id}", **extra}
    store.put(item)
    return item


def mine(outbox, *users):
    return [m for m in outbox if m[2] in users]


# ------------------------------------------------------------------------------------------ levels and thresholds
@pytest.mark.parametrize("mm,want", [
    (None, "none"), (-1, "none"), (0, "none"), (2.4, "none"), (2.5, "light"), (15.5, "light"), (15.6, "moderate"),
    (64.4, "moderate"), (64.5, "heavy"), (115.5, "heavy"), (115.6, "veryHeavy"), (204.4, "veryHeavy"),
    (204.5, "extreme"), (350.0, "extreme"),
    (sum([0.1] * 156), "moderate"),      # 15.599999999999994 in floating point: amounts count to 0.1 mm, like IMD's
])
def test_level_follows_imd_categories(mm, want):
    from jalsmriti import forecast
    assert forecast.level(mm) == want


def test_should_alert_by_water_memory():
    from jalsmriti import forecast as F
    for tier in ("strong", "some", "little", "unknown", ""):
        assert F.should_alert({"mm": 64.5, "maxHourlyMm": 0}, tier)            # IMD heavy rain: everyone
    assert not F.should_alert({"mm": 64.4, "maxHourlyMm": 0}, "little")
    assert not F.should_alert({"mm": 40, "maxHourlyMm": 30}, "little")         # little memory: only heavy days
    assert F.should_alert({"mm": 35, "maxHourlyMm": 0}, "strong")
    assert F.should_alert({"mm": 5, "maxHourlyMm": 15}, "strong")              # one intense hour is enough
    assert not F.should_alert({"mm": 34.9, "maxHourlyMm": 14.9}, "strong")
    assert F.should_alert({"mm": 50, "maxHourlyMm": 0}, "some")
    assert F.should_alert({"mm": 10, "maxHourlyMm": 20}, "some")
    assert not F.should_alert({"mm": 49.9, "maxHourlyMm": 19.9}, "some")
    assert not F.should_alert({"mm": 40, "maxHourlyMm": 0}, "some")
    assert not F.should_alert({}, "strong")
    assert F.thresholds("strong") == (35.0, 15.0) and F.thresholds("some") == (50.0, 20.0)
    assert F.thresholds("little") == (64.5, None) and F.thresholds(None) == (64.5, None)


# ------------------------------------------------------------------------------------------ fetching
def test_fetch_one_point_reads_the_object_answer(openmeteo):
    from jalsmriti import forecast
    now = datetime(2026, 10, 11, 0, 45, tzinfo=timezone.utc)                 # 06:15 in India
    hourly = {"2026-10-11T03:00": 2.0,                                       # before now: not in the next 24 h
              "2026-10-11T07:00": 1.5, "2026-10-11T15:00": 5.0,
              "2026-10-12T05:00": 3.0, "2026-10-12T06:00": 4.0,              # the 24th hour after now
              "2026-10-12T07:00": 6.0}                                       # the 25th: outside
    fake = openmeteo(lambda la, lo: om_entry(date(2026, 10, 11), [8.5, 13.0, 0.0], probs=[40, 70, None], hourly=hourly))
    [fc] = forecast.fetch([BENGALURU], now=now)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(fake.urls[0]).query)
    assert fake.urls[0].startswith(forecast.API)
    assert q["latitude"] == ["12.9352"] and q["longitude"] == ["77.6807"] and q["hourly"] == ["precipitation"]
    assert q["daily"] == ["precipitation_sum,precipitation_probability_max"]
    assert q["forecast_days"] == ["3"] and q["timezone"] == ["auto"]
    assert fc["days"] == [{"date": "2026-10-11", "mm": 8.5, "prob": 40, "maxHourlyMm": 5.0},
                          {"date": "2026-10-12", "mm": 13.0, "prob": 70, "maxHourlyMm": 6.0},
                          {"date": "2026-10-13", "mm": 0.0, "prob": None, "maxHourlyMm": 0.0}]
    assert fc["next24hMm"] == 13.5 and fc["maxHourlyMm"] == 6.0
    assert fc["timezone"] == "Asia/Kolkata" and fc["utcOffsetSeconds"] == 19800
    assert fc["source"] == "Open-Meteo" and fc["fetchedAt"].endswith("Z")


def test_fetch_several_points_in_order_and_in_batches_of_50(openmeteo):
    from jalsmriti import forecast
    start = ist_today(datetime.now(timezone.utc))
    fake = openmeteo(lambda la, lo: om_entry(start, [round(la, 1), 0.0, 0.0], peaks=[1.0, 0, 0], lat=la, lon=lo))
    pts = [(10.0 + i / 10, 77.0) for i in range(3)]
    out = forecast.fetch(pts)
    assert len(fake.urls) == 1 and len(fake.points()) == 3
    assert [fc["days"][0]["mm"] for fc in out] == [10.0, 10.1, 10.2]          # each point gets its own forecast

    many = [(8.0 + i / 10, 76.0) for i in range(60)]
    fake = openmeteo(lambda la, lo: om_entry(start, [round(la, 1), 0, 0], lat=la, lon=lo),
                     fail_if=lambda lats: len(lats) == 10)                    # the second request always fails
    out = forecast.fetch(many)
    assert [len(fake.points(i)) for i in range(len(fake.urls))] == [50, 10, 10]   # 50 + 10, the 10 tried twice
    assert all(fc and fc["days"][0]["mm"] == round(many[i][0], 1) for i, fc in enumerate(out[:50]))
    assert out[50:] == [None] * 10


def test_fetch_tries_once_more_then_gives_none(openmeteo):
    from jalsmriti import forecast
    start = ist_today(datetime.now(timezone.utc))
    fake = openmeteo(lambda la, lo: om_entry(start, [1.0, 2.0, 3.0]), fail_first=1)
    assert forecast.fetch([BENGALURU])[0]["days"][2]["mm"] == 3.0 and len(fake.urls) == 2
    fake = openmeteo(lambda la, lo: om_entry(start, [1.0, 2.0, 3.0]), fail_first=2)
    assert forecast.fetch([BENGALURU]) == [None] and len(fake.urls) == 2
    assert forecast.fetch([]) == []


def test_for_place_caches_per_cell_for_an_hour(aws, openmeteo):
    from jalsmriti import forecast, geo, store
    pune = (18.5204, 73.8567)
    cell = geo.geohash(*pune, 5)
    store.delete(f"FCST#{cell}")
    start = ist_today(datetime.now(timezone.utc))
    fake = openmeteo(lambda la, lo: om_entry(start, [0.0, 70.0, 20.0], peaks=[0, 12.0, 4.0]))
    fc = forecast.for_place(*pune)
    assert len(fake.urls) == 1
    clat, clon = geo.geohash_decode(cell)
    assert fake.points() == [(f"{clat:.4f}", f"{clon:.4f}")]                  # asked at the cell's centre
    assert [d["level"] for d in fc["days"]] == ["none", "heavy", "moderate"]
    again = forecast.for_place(pune[0] + 0.004, pune[1] + 0.004)              # same cell, no request
    assert len(fake.urls) == 1 and again["days"] == fc["days"]
    item = store.get(f"FCST#{cell}")
    assert item["payload"]["days"][1]["mm"] == 70 and item["ttl"] > datetime.now(timezone.utc).timestamp() + 3000
    store.update(f"FCST#{cell}", "META", sets={"fetchedAt": store.iso_days_ago(2 / 24)})   # two hours old
    forecast.for_place(*pune)
    assert len(fake.urls) == 2


# ------------------------------------------------------------------------------------------ the daily rain check
def test_rain_check_end_to_end(aws, openmeteo):
    import alerts
    from jalsmriti import forecast, geo, store, strings
    alerts.OUTBOX.clear()
    now = datetime.now(timezone.utc)
    plan = {"daily": [0.0, 40.0, 2.0], "peaks": [0.0, 8.0, 1.0], "now": now}          # 40 mm tomorrow, no heavy hour
    openmeteo(lambda la, lo: om_entry(ist_today(plan["now"]), plan["daily"], peaks=plan["peaks"], probs=[10, 80, 20]))
    strong, little = f"u-strong-{uuid.uuid4().hex[:8]}", f"u-little-{uuid.uuid4().hex[:8]}"
    fs = put_follow(strong, *BENGALURU, "Bellandur, Bengaluru", "strong")
    fl = put_follow(little, *CHENNAI, "Velachery, Chennai", "little", lang="hi")
    stats0 = int(store.stats().get("rainAlerts", 0))
    try:
        r = alerts.rain_check(now)
        assert r["follows"] >= 2 and r["cells"] >= 2 and r["failedForecasts"] == 0 and r["alerts"] >= 1
        sent = mine(alerts.OUTBOX, strong, little)
        assert [m[2] for m in sent] == [strong]                       # strong memory: 40 mm is enough; little: no
        subject, body, _ = sent[0]
        tomorrow = ist_today(now) + timedelta(days=1)
        assert subject == "Rain heads-up for Bellandur, Bengaluru: about 40 mm tomorrow"
        for part in ("Bellandur, Bengaluru: Strong water memory", f"tomorrow, {strings.day(tomorrow.isoformat())}",
                     "40 mm", "(moderate rain)", "Chance of rain: 80%", "35 mm or more", "basements",
                     "1 m above the floor", "elderly neighbours", "phones charged",
                     "https://example.test/place?lat=12.93520&lon=77.68070&label=Bellandur%2C%20Bengaluru",
                     "https://example.test/waterlogging", "India Meteorological Department (IMD)", "(NDMA)",
                     "because you follow this place", "unsubscribe link below", "Open-Meteo"):
            assert part in body, part
        assert "!" not in body
        item = store.get(fs["PK"], fs["SK"])
        assert item["lastAlertFor"] == tomorrow.isoformat() and item["lastAlertAt"][:10] == now.strftime("%Y-%m-%d")
        assert "lastAlertFor" not in store.get(fl["PK"], fl["SK"])
        assert int(store.stats().get("rainAlerts", 0)) >= stats0 + 1
        audit, _ = store.query("AUDIT#bengaluru", forward=False, limit=100)
        assert any(a["action"] == "RainHeadsUp" and a["resource"] == {"place": fs["gh7"]} and a.get("user") is None
                   for a in audit)
        assert store.get(f"FCST#{geo.geohash(*BENGALURU, 5)}")["payload"]["days"][1]["level"] == "moderate"

        alerts.rain_check(now)                                        # a second run the same day sends nothing
        assert len(mine(alerts.OUTBOX, strong, little)) == 1

        plan.update(now=now + timedelta(days=1), daily=[40.0, 0.0, 0.0], peaks=[8.0, 0, 0])
        alerts.rain_check(plan["now"])                                # next day: the same rainy day is not told twice
        assert len(mine(alerts.OUTBOX, strong, little)) == 1
        plan.update(daily=[40.0, 120.0, 0.0], peaks=[8.0, 25.0, 0])
        alerts.rain_check(plan["now"])                                # ... but a new one is, to both
        sent = mine(alerts.OUTBOX, strong, little)
        assert sorted(m[2] for m in sent[1:]) == sorted([strong, little]) and all("120" in m[0] for m in sent[1:])
        subject, body, _ = next(m for m in sent[1:] if m[2] == strong)
        assert subject.endswith("about 120 mm tomorrow") and "(very heavy rain)" in body
    finally:
        store.delete(fs["PK"], fs["SK"])
        store.delete(fl["PK"], fl["SK"])


def test_one_heads_up_a_day_when_today_and_tomorrow_are_both_wet(aws, openmeteo):
    import alerts
    from jalsmriti import store
    alerts.OUTBOX.clear()
    now = datetime(2026, 10, 11, 0, 45, tzinfo=timezone.utc)          # 06:15 in India, when the job runs
    plan = {"now": now}
    openmeteo(lambda la, lo: om_entry(ist_today(plan["now"]), [55.0, 70.0, 0.0], peaks=[9.0, 12.0, 0]))
    uid = f"u-some-{uuid.uuid4().hex[:8]}"
    f = put_follow(uid, 17.4065, 78.4772, "Hussain Sagar, Hyderabad", "some")
    try:
        alerts.rain_check(now)
        alerts.rain_check(now + timedelta(hours=3))                   # a retry or a manual run later that day
        sent = mine(alerts.OUTBOX, uid)
        assert len(sent) == 1 and sent[0][0].endswith("about 55 mm today")
        assert store.get(f["PK"], f["SK"])["lastAlertFor"] == ist_today(now).isoformat()
        plan["now"] = now + timedelta(days=1)                         # next morning: the 70 mm day is now today
        alerts.rain_check(plan["now"])
        assert len(mine(alerts.OUTBOX, uid)) == 2
    finally:
        store.delete(f["PK"], f["SK"])


def test_rain_check_counts_failed_forecasts(aws, openmeteo):
    import alerts
    from jalsmriti import store
    openmeteo(lambda la, lo: om_entry(date.today(), [0, 0, 0]), fail_if=lambda lats: True)
    uid = f"u-fail-{uuid.uuid4().hex[:8]}"
    f = put_follow(uid, 26.9176, 94.7348, "Nazira, Sivasagar", "strong")
    try:
        r = alerts.rain_check()
        assert r["failedForecasts"] == r["cells"] >= 1 and r["alerts"] == 0
    finally:
        store.delete(f["PK"], f["SK"])


def test_send_test_uses_the_wettest_coming_day(aws, openmeteo):
    import alerts
    from jalsmriti import forecast, geo, strings, store
    alerts.OUTBOX.clear()
    lat, lon = 17.3272, 78.4715
    store.delete(f"FCST#{geo.geohash(lat, lon, 5)}")
    now = datetime.now(timezone.utc)
    openmeteo(lambda la, lo: om_entry(ist_today(now), [1.0, 5.0, 12.0], peaks=[0.5, 2.0, 4.0]))
    follow = {"userId": "u-test-1", "gh7": geo.geohash(lat, lon, 7), "lat": lat, "lon": lon,
              "label": "Al Jubail Colony, Hyderabad", "tier": "some", "lang": "en"}
    r = alerts.send_test(follow)
    third = (ist_today(now) + timedelta(days=2)).isoformat()
    assert r["sent"] is True and alerts.OUTBOX[-1] == (r["subject"], r["body"], "u-test-1")
    assert r["subject"] == f"Test: Rain heads-up for Al Jubail Colony, Hyderabad: about 12 mm on {strings.day(third)}"
    assert r["body"].startswith("This is a test email.") and "using today's forecast" in r["body"]
    assert "About 12 mm of rain is forecast for " + strings.day(third) in r["body"]
    assert "50 mm or more is forecast for a day, or 20 mm in one hour" in r["body"]


def test_send_test_without_a_forecast(aws, openmeteo):
    import alerts
    from jalsmriti import geo, store
    lat, lon = 28.662, 77.2394
    store.delete(f"FCST#{geo.geohash(lat, lon, 5)}")
    openmeteo(lambda la, lo: om_entry(date.today(), [0, 0, 0]), fail_if=lambda lats: True)
    with pytest.raises(alerts.ForecastUnavailable):
        alerts.send_test({"userId": "u-x", "lat": lat, "lon": lon, "label": "Yamuna Bazar, Delhi", "tier": "strong"})


def test_message_for_nepal_names_nepal_authorities():
    import alerts
    now = datetime.now(timezone.utc)
    today = ist_today(now).isoformat()
    fc = {"days": [{"date": today, "mm": 0.0, "maxHourlyMm": 0.0}], "utcOffsetSeconds": 20700}
    follow = {"userId": "u", "lat": 27.7149, "lon": 85.3123, "label": "", "tier": "unknown", "lang": "en"}
    subject, body = alerts.message(follow, fc["days"][0], fc, test=True, now=now)
    assert subject.startswith("Test: Rain heads-up for 27.7149 N, 85.3123 E: no rain forecast")
    assert "Department of Hydrology and Meteorology (DHM)" in body and "IMD" not in body
    assert "No rain is forecast" in body and "64.5 mm or more" in body and "&label=" not in body


def test_notify_publishes_to_the_followers_topic(aws, monkeypatch):
    import boto3
    import alerts
    from jalsmriti import config as C
    monkeypatch.setattr(C, "LOCAL", False)
    alerts._sns.cache_clear()
    uid = f"u-sns-{uuid.uuid4().hex[:8]}"
    sns, sqs = boto3.client("sns", region_name=C.REGION), boto3.client("sqs", region_name=C.REGION)
    topic = sns.create_topic(Name=C.user_topic_name(uid))["TopicArn"]                # as the API does on follow
    queue = sqs.create_queue(QueueName=f"inbox-{uid}")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=queue, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=arn)
    long_subject = "Rain heads-up for " + "a very long place name, " * 6 + "\nsecond line"
    alerts.notify({"userId": uid}, long_subject, "the body")
    alerts.notify({"userId": uid}, "Rain heads-up for a second place", "another body")    # the topic ARN is reused
    msgs = sqs.receive_message(QueueUrl=queue, MaxNumberOfMessages=10, WaitTimeSeconds=1).get("Messages", [])
    notes = sorted((json.loads(m["Body"]) for m in msgs), key=lambda n: n["Message"])
    assert [n["Message"] for n in notes] == ["another body", "the body"] and {n["TopicArn"] for n in notes} == {topic}
    subject = notes[1]["Subject"]
    assert len(subject) == 99 and "\n" not in subject and subject.startswith("Rain heads-up for")
    alerts._sns.cache_clear()


# ------------------------------------------------------------------------------------------ narration
PLACE = {
    "lat": 12.9352, "lon": 77.6807, "label": {"label": "Bellandur, Bengaluru, Karnataka", "city": "Bengaluru"},
    "memory": {"index": 82, "tier": "strong"},
    "findings": [
        {"key": "wasWater", "severity": "high", "vars": {"pct": 64},
         "text": "Satellites saw water on this very spot in 64% of looks between 1984 and 2020."},
        {"key": "radar", "severity": "high", "vars": {"date": "2022-09-05", "ha": 1.2},
         "text": "Radar saw unusual standing water within 300 m on 2022-09-05 (1.2 ha)."},
        {"key": "lostNear", "severity": "high", "vars": {"ha": 3.2},
         "text": "3.2 ha of water that existed within 300 m has disappeared since 1984."},
        {"key": "builtOver", "severity": "medium", "vars": {"ha": 45},
         "text": "Within 2 km, 45 ha of old water-body beds are now built over."},
        {"key": "bowl", "severity": "medium", "vars": {"m": 2.1},
         "text": "The ground within 300 m forms a bowl up to 2.1 m deep where rain can pond."},
        {"key": "lowDrain", "severity": "medium", "vars": {},
         "text": "Part of this place sits less than 1 m above the nearest natural drainage line."},
    ],
    "signals": {"radarSightings": [{"date": "2022-09-05", "haCore": 1.2}, {"date": "2024-10-16", "haCore": 0.6}]},
    "radar": {"scenesChecked": 48},
    "heat": {"hereC": 41.3, "builtC": 43.1, "waterC": 31.9, "vsBuiltC": -1.8, "vsWaterC": 9.4},
}


def test_place_text_reads_like_a_report():
    from jalsmriti import narration, strings
    acts = ["Keep drains clear before the monsoon.", "Join or start a group for the nearest lake",
            "Ask for the revenue record before buying.", "A fourth action that is not read."]
    s = narration.place_text(PLACE, "en", acts)
    assert s.startswith("Water memory report for Bellandur, Bengaluru, Karnataka.")
    assert "Strong water memory: 82 of 100." in s
    assert "64 percent of looks" in s and "3.2 hectares" in s and "45 hectares" in s
    assert "The ground within 300 m forms a bowl" in s
    assert "less than 1 m above" not in s                                    # four findings at most
    assert "Radar saw unusual standing water within 300 m on" not in s       # radar is told once, below
    assert "2 times in 48 passes, most recently on 16 October 2024." in s      # full month names for the voice
    assert ("about 41 degrees Celsius, 2 degrees Celsius cooler than nearby built-up ground, and "
            "9 degrees Celsius warmer than nearby water.") in s
    assert "What to do this week: Keep drains clear before the monsoon. Join or start a group for the nearest lake." in s
    assert "fourth action" not in s
    assert s.endswith("It is not a flood forecast.")
    assert "%" not in s and "°" not in s and " ha " not in s
    assert "नाले साफ़ रखें।" in narration.place_text(PLACE, "hi", ["नाले साफ़ रखें"])   # Hindi ends with a danda


def test_place_text_with_little_known():
    from jalsmriti import narration
    s = narration.place_text({"lat": 26.9176, "lon": 94.7348, "label": {}, "memory": {"index": None, "tier": "unknown"},
                              "findings": [], "signals": {}, "radar": {"scenesChecked": 0, "error": "timeout"}}, "en")
    assert s.startswith("Water memory report for the place at 26.918 north, 94.735 east.")
    assert "not enough satellite data" in s and "could not be checked" in s and "Celsius" not in s
    s = narration.place_text({"label": {"label": "Nazira"}, "memory": {"index": 30, "tier": "little"},
                              "findings": [{"key": "quiet", "severity": "low", "vars": {},
                                            "text": "No strong water history was found here in 37 years of satellite records."}],
                              "signals": {"radarSightings": []}, "radar": {"scenesChecked": 40},
                              "heat": {"hereC": 36.0, "vsBuiltC": 0.2}}, "en")
    assert "Little water memory: 30 of 100." in s and "No strong water history" in s
    assert "In 40 monsoon radar passes since 2017, no unusual standing water was seen within 300 metres." in s
    assert "about 36 degrees Celsius, about as warm as nearby built-up ground." in s


def test_lake_text():
    from jalsmriti import narration, strings
    lake = {"name": "Test Kere", "metrics": {"grade": {"grade": "C", "score": 55, "parts": []}}, "findings": [
        {"key": "lost", "severity": "high", "vars": {"lostHa": 12.5, "lostPct": 31.2, "now": {"built": 2.5}, "again": 0},
         "text": "12.5 ha of water seen in 1984-2020 had gone by 2020 (31.2% of its historic spread); that ground is now built 2.5 ha."},
        {"key": "weeds", "severity": "medium", "vars": {"pct": 41, "date": "2026-10-04"},
         "text": "41% of the water surface was covered by floating weeds on 2026-10-04."}]}
    s = narration.lake_text(lake, "en")
    assert s.startswith("Health report for Test Kere. Health grade C: Damaged, 55 of 100.")
    assert "12.5 hectares of water seen in 1984 to 2020" in s and "41 percent of the water surface" in s
    assert "4 October 2026" in s and "2026-10-04" not in s
    assert s.endswith("add your photos on JalSmriti and prepare a signed complaint to the authorities who can protect it.")
    s = narration.lake_text({"name": "", "metrics": {"grade": {"grade": None}}, "findings": []}, "en")
    assert s.startswith("Health report for this water body.") and "no health grade" in s


def test_speakable():
    from jalsmriti import narration
    sp = lambda t: narration.speakable(t, "en")
    assert sp("12.5 ha of water, 3ha more.") == "12.5 hectares of water, 3 hectares more."
    assert sp("40% of looks (31 %)") == "40 percent of looks (31 percent)"
    assert sp("41°C, 41 °C and 41℃") == "41 degrees Celsius, 41 degrees Celsius and 41 degrees Celsius"
    assert sp("seen 1984-2020 and 1990–2015") == "seen 1984 to 2020 and 1990 to 2015"
    for same in ("a hall of 3 hats", "1-2 m deep, within 2 km", "since 1984", "1,250-2,500 million litres", "ha ha"):
        assert sp(same) == same


# ------------------------------------------------------------------------------------------ speech
def test_synthesize_locally_writes_a_short_wav_once():
    from jalsmriti import speech, storage
    text = f"Bellandur remembers water. Report {uuid.uuid4().hex[:6]}. It is not a forecast."
    r = speech.synthesize(text, "en")
    assert r["local"] is True and r["cached"] is False and r["voice"] == "Kajal" and r["engine"] == "neural"
    assert r["url"] == f"/pub/speech/{speech.cache_key(text, 'en')}.wav" and r["chars"] == len(text)
    path = Path(storage.LOCAL_DIR) / "site" / r["url"].lstrip("/")
    with wave.open(str(path), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert 0.9 <= w.getnframes() / 16000 <= 1.1
        pcm = w.readframes(w.getnframes())
    assert max(abs(int.from_bytes(pcm[i:i + 2], "little", signed=True)) for i in range(0, len(pcm), 2)) > 3000
    again = speech.synthesize(text, "en")
    assert again["cached"] is True and again["url"] == r["url"]
    assert speech.synthesize(text, "hi")["url"] != r["url"]                  # the language is part of the key
    with pytest.raises(ValueError):
        speech.synthesize(text, "ta")
    with pytest.raises(ValueError):
        speech.synthesize("   ", "en")


def test_trim_cuts_at_a_sentence():
    from jalsmriti import speech
    text = " ".join(f"Sentence number {i} says something about water." for i in range(120))   # ~5,500 characters
    t = speech.trim(text)
    assert len(t) <= speech.MAX_CHARS and t.endswith("water.") and text.startswith(t)
    hindi = "पानी की गहरी याद। " * 400
    t = speech.trim(hindi)
    assert len(t) <= speech.MAX_CHARS and t.endswith("।")
    assert speech.trim("  short   text\n") == "short text"
    assert len(speech.trim("x" * 5000)) == speech.MAX_CHARS                  # no sentence, no space: a hard cut


def test_synthesize_with_polly(monkeypatch):
    from jalsmriti import config as C
    from jalsmriti import speech, storage
    calls = []

    class FakePolly:
        def synthesize_speech(self, **kw):
            calls.append(kw)
            return {"AudioStream": io.BytesIO(b"ID3 not really an mp3")}

    monkeypatch.setattr(C, "LOCAL", False)
    monkeypatch.setattr(speech, "_polly", lambda: FakePolly())
    text = f"बेलंदूर की जल स्मृति रिपोर्ट। {uuid.uuid4().hex[:6]}। यह बाढ़ का पूर्वानुमान नहीं है।"
    r = speech.synthesize(text, "hi")
    key = speech.cache_key(text, "hi")
    assert r == {"url": f"/pub/speech/{key}.mp3", "voice": "Kajal", "engine": "neural", "chars": len(text),
                 "cached": False, "local": False}
    assert calls == [{"Text": text, "TextType": "text", "VoiceId": "Kajal", "Engine": "neural", "LanguageCode": "hi-IN",
                      "OutputFormat": "mp3"}]
    assert (Path(storage.LOCAL_DIR) / "site" / "pub" / "speech" / f"{key}.mp3").read_bytes() == b"ID3 not really an mp3"
    assert speech.synthesize(text, "hi")["cached"] is True and len(calls) == 1


def test_aditi_reads_where_kajal_is_not_offered(monkeypatch):
    from botocore.exceptions import ClientError
    from jalsmriti import config as C
    from jalsmriti import speech
    calls = []

    class NoKajal:
        def synthesize_speech(self, **kw):
            calls.append(kw["VoiceId"])
            if kw["VoiceId"] == "Kajal":
                raise ClientError({"Error": {"Code": "EngineNotSupportedException", "Message": "neural not here"}},
                                  "SynthesizeSpeech")
            return {"AudioStream": io.BytesIO(b"ID3 aditi")}

    monkeypatch.setattr(C, "LOCAL", False)
    monkeypatch.setattr(speech, "_polly", lambda: NoKajal())
    r = speech.synthesize(f"Bellandur water memory report {uuid.uuid4().hex[:6]}.", "en")
    assert (r["voice"], r["engine"], r["cached"]) == ("Aditi", "standard", False) and calls == ["Kajal", "Aditi"]

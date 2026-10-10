"""Rain heads-up (EventBridge Scheduler runs handler() every day at 06:15 IST).

People follow places. The API writes one item per followed place and subscribes the person's verified email, once,
to their own SNS topic (C.user_topic_name):
  FOLLOW#<userId>  <gh7>   userId, gh7, lat, lon, label, tier, lang, createdAt   GSI2 USER#<userId>  GSI3 FOLLOWS
                           lastAlertFor (YYYY-MM-DD), lastAlertAt (ISO time): written here
Every morning all follows are read, the forecast is fetched once per 5 km cell (forecast.fetch, 50 cells a request)
and a heads-up is emailed when today or tomorrow crosses the place's threshold: IMD heavy rain everywhere, less where
the place has a water memory (forecast.should_alert). A rainy day is announced only once (lastAlertFor), and a place
gets at most one heads-up a day, so a re-run or a retry of this job sends nothing new.
Words come from the website's dictionaries (strings.t, keys "rain.*"); RAIN_EN holds the English defaults.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from jalsmriti import areas as A
from jalsmriti import forecast, geo, storage, store, strings
from jalsmriti import config as C

log = logging.getLogger()
log.setLevel(logging.INFO)

OUTBOX: list[tuple[str, str, str]] = []     # local stack and tests: (subject, body, userId) of every email "sent"
IST_OFFSET_S = 19800                        # used only if a forecast lacks its UTC offset
FOLLOWS_CAP = 50_000

RAIN_EN = {
    "rain.subject": "Rain heads-up for {place}: about {mm} mm {when}",
    "rain.subjectDry": "Rain heads-up for {place}: no rain forecast {when}",
    "rain.testPrefix": "Test:",
    "rain.when.today": "today",
    "rain.when.tomorrow": "tomorrow",
    "rain.when.on": "on {date}",
    "rain.day.today": "today, {date}",
    "rain.day.tomorrow": "tomorrow, {date}",
    "rain.testIntro": "This is a test email. It shows what a rain heads-up for this place looks like, using today's "
                      "forecast. Real heads-ups are sent only when the forecast reaches the amounts given below.",
    "rain.place": "{place}: {tier}",
    "rain.amount": "About {mm} mm of rain is forecast for {day} ({level}).",
    "rain.noRain": "No rain is forecast for {day}.",
    "rain.peak": "The heaviest hour may bring about {mm} mm.",
    "rain.chance": "Chance of rain: {prob}%.",
    "rain.level.none": "little or no rain",
    "rain.level.light": "light rain",
    "rain.level.moderate": "moderate rain",
    "rain.level.heavy": "heavy rain",
    "rain.level.veryHeavy": "very heavy rain",
    "rain.level.extreme": "extremely heavy rain",
    "rain.tier.strong": "Old water bodies, low ground or past flooding nearby mean that streets and ground floors here "
                        "can flood with less rain than elsewhere.",
    "rain.tier.some": "Low ground or old water bodies nearby mean that water can collect here in heavy rain.",
    "rain.tier.little": "Satellite records show little water history here, but heavy rain can flood streets and "
                        "underpasses anywhere.",
    "rain.tier.unknown": "Heavy rain can flood streets and underpasses anywhere.",
    "rain.rule": "For this place, JalSmriti sends a heads-up when {dayMm} mm or more is forecast for a day, or "
                 "{hourMm} mm in one hour.",
    "rain.ruleHeavy": "For this place, JalSmriti sends a heads-up when {dayMm} mm or more is forecast for a day.",
    "rain.before": "Before the rain:",
    "rain.act.vehicles": "Move cars and two-wheelers out of basements and low streets.",
    "rain.act.valuables": "Keep documents, medicines and electronics at least 1 m above the floor.",
    "rain.act.neighbours": "Check on elderly neighbours and anyone who lives alone.",
    "rain.act.phone": "Keep phones charged and a torch at hand.",
    "rain.placeLink": "What this place remembers: {url}",
    "rain.reportLink": "Report standing water in your street: {url}",
    "rain.official": "Forecasts can be wrong, and rain can be heavier or lighter in your street. Official warnings "
                     "from the India Meteorological Department (IMD) and the National Disaster Management Authority "
                     "(NDMA) come first: follow them and your local authorities.",
    "rain.officialNp": "Forecasts can be wrong, and rain can be heavier or lighter in your street. Official warnings "
                       "from the Department of Hydrology and Meteorology (DHM) and the National Disaster Risk "
                       "Reduction and Management Authority (NDRRMA) come first: follow them and your local authorities.",
    "rain.why": "You get this email because you follow this place on JalSmriti. To stop these emails, use the "
                "unsubscribe link below.",
    "rain.source": "Weather data by Open-Meteo.com.",
    "rain.coords": "{lat} N, {lon} E",
}
ACTIONS = ("rain.act.vehicles", "rain.act.valuables", "rain.act.neighbours", "rain.act.phone")
TIER_EN = {"strong": "Strong water memory", "some": "Some water memory", "little": "Little water memory"}


class ForecastUnavailable(RuntimeError):
    """Open-Meteo could not be reached, so no test heads-up could be written."""


def _t(lang: str, key: str, **vars) -> str:
    return strings.t(lang, key, en=RAIN_EN[key], **vars)


def _tier_label(tier: str, lang: str) -> str:
    s = strings.tier_label(tier, lang)
    return TIER_EN.get(tier, s) if s == f"place.memory.{tier}" else s


def _about(mm: float) -> str:
    """A forecast amount as people read it: whole mm from 10 mm, one decimal below."""
    return strings.num(mm, 0 if mm >= 10 else None)


# ------------------------------------------------------------------------------------------ dates
def _utc(t: datetime | None) -> datetime:
    t = t or datetime.now(timezone.utc)
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def _iso(t: datetime) -> str:
    """Same format as store.now_iso(), for a given time."""
    t = _utc(t)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _offset(fc: dict) -> int:
    try:
        return int(fc.get("utcOffsetSeconds", IST_OFFSET_S))
    except (TypeError, ValueError):
        return IST_OFFSET_S


def _local_date(t: datetime, offset_s: int) -> date:
    return (_utc(t) + timedelta(seconds=offset_s)).date()


def _relative(day_iso: str | None, fc: dict, now: datetime | None) -> str | None:
    """Whether a forecast date is today or tomorrow at the place ("today" / "tomorrow"; None for later days)."""
    today = _local_date(_utc(now), _offset(fc))
    return {today.isoformat(): "today", (today + timedelta(days=1)).isoformat(): "tomorrow"}.get(day_iso or "")


# ------------------------------------------------------------------------------------------ the email
def message(follow: dict, day: dict, fc: dict, test: bool = False, *, now: datetime | None = None) -> tuple[str, str]:
    """(subject, plain-text body) of a heads-up for one followed place and one forecast day, in the follower's
    language. `test` marks it as a test that shows what a heads-up looks like."""
    lang = strings.lang_or_en(follow.get("lang"))
    lat, lon = float(follow["lat"]), float(follow["lon"])
    label = str(follow.get("label") or "").strip()
    place = label or _t(lang, "rain.coords", lat=f"{lat:.4f}", lon=f"{lon:.4f}")
    tier = follow.get("tier") or "unknown"
    mm = round(float(day.get("mm") or 0), 1)
    hour = round(float(day.get("maxHourlyMm") or 0), 1)
    date_text = strings.day(day.get("date"), lang)
    rel = _relative(day.get("date"), fc, now)

    when = _t(lang, f"rain.when.{rel}") if rel else _t(lang, "rain.when.on", date=date_text)
    subject = (_t(lang, "rain.subject", place=place, mm=_about(mm), when=when) if mm >= 0.1
               else _t(lang, "rain.subjectDry", place=place, when=when))
    if test:
        subject = f"{_t(lang, 'rain.testPrefix')} {subject}"

    day_text = _t(lang, f"rain.day.{rel}", date=date_text) if rel else date_text
    lvl = day.get("level") if f"rain.level.{day.get('level')}" in RAIN_EN else forecast.level(mm)
    amount = [_t(lang, "rain.amount", mm=_about(mm), day=day_text, level=_t(lang, f"rain.level.{lvl}"))
              if mm >= 0.1 else _t(lang, "rain.noRain", day=day_text)]
    if hour >= 0.1:
        amount.append(_t(lang, "rain.peak", mm=_about(hour)))
    if day.get("prob") is not None:
        amount.append(_t(lang, "rain.chance", prob=int(day["prob"])))

    day_mm, hour_mm = forecast.thresholds(tier)
    rule = (_t(lang, "rain.rule", dayMm=strings.num(day_mm), hourMm=strings.num(hour_mm)) if hour_mm
            else _t(lang, "rain.ruleHeavy", dayMm=strings.num(day_mm)))
    tier_key = f"rain.tier.{tier}" if f"rain.tier.{tier}" in RAIN_EN else "rain.tier.unknown"

    site = storage.site_url()
    query = f"lat={lat:.5f}&lon={lon:.5f}" + (f"&label={urllib.parse.quote(label, safe='')}" if label else "")
    nepal = geo.country(lat, lon) == "NP"

    paragraphs = [
        _t(lang, "rain.testIntro") if test else "",
        _t(lang, "rain.place", place=place, tier=_tier_label(tier, lang)) if tier in TIER_EN else place,
        " ".join(amount),
        f"{_t(lang, tier_key)} {rule}",
        "\n".join([_t(lang, "rain.before")] + [f"- {_t(lang, k)}" for k in ACTIONS]),
        "\n".join([_t(lang, "rain.placeLink", url=f"{site}/place?{query}"),
                   _t(lang, "rain.reportLink", url=f"{site}/waterlogging")]),
        _t(lang, "rain.officialNp" if nepal else "rain.official"),
        "\n".join([_t(lang, "rain.why"), _t(lang, "rain.source")]),
    ]
    return subject, "\n\n".join(p for p in paragraphs if p)


@lru_cache(maxsize=1)
def _sns():
    import boto3
    from botocore.config import Config
    # CreateTopic is throttled far below Publish: on a wet morning many heads-ups go out at once, so back off and retry
    return boto3.client("sns", region_name=C.REGION, config=Config(retries={"max_attempts": 8, "mode": "adaptive"}))


_topics: dict[str, str] = {}      # userId -> topic ARN, for one run (a person may follow several places)


def _subject_line(subject: str) -> str:
    """SNS subjects: UTF-8, no line breaks or control characters, under 100 characters."""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", subject).strip()[:99]


def notify(follow: dict, subject: str, body: str) -> None:
    """Email the follower through their own SNS topic (in the local stack: log it and keep it in OUTBOX)."""
    user_id = follow["userId"]
    if C.LOCAL:
        log.info("rain heads-up (local, not sent) for %s: %s", user_id, subject)
        OUTBOX.append((subject, body, user_id))
        return
    sns = _sns()
    if user_id not in _topics:
        _topics[user_id] = sns.create_topic(Name=C.user_topic_name(user_id))["TopicArn"]   # idempotent: the ARN
    sns.publish(TopicArn=_topics[user_id], Subject=_subject_line(subject), Message=body)


# ------------------------------------------------------------------------------------------ the daily check
def due_day(follow: dict, fc: dict, now: datetime | None = None) -> dict | None:
    """The forecast day (today or tomorrow, the place's local dates) to announce to this follower, or None."""
    now = _utc(now)
    offset = _offset(fc)
    today = _local_date(now, offset)
    last_at = follow.get("lastAlertAt")
    if last_at:
        try:
            if _local_date(datetime.fromisoformat(str(last_at).replace("Z", "+00:00")), offset) == today:
                return None                      # one heads-up a day per place, so a re-run sends nothing new
        except ValueError:
            pass
    window = (today.isoformat(), (today + timedelta(days=1)).isoformat())
    tier = follow.get("tier") or "unknown"
    for d in sorted(fc.get("days") or [], key=lambda d: str(d.get("date") or "")):
        if d.get("date") in window and d.get("date") != follow.get("lastAlertFor") and forecast.should_alert(d, tier):
            return d
    return None


def _send(follow: dict, day: dict, fc: dict, now: datetime) -> bool:
    try:
        subject, body = message(follow, day, fc, now=now)
        notify(follow, subject, body)
    except Exception as ex:                      # not recorded, so tomorrow's run tries again
        log.warning("rain heads-up %s %s failed: %s", follow.get("PK"), follow.get("SK"), ex)
        return False
    try:
        store.update(follow["PK"], follow["SK"], sets={"lastAlertFor": day["date"], "lastAlertAt": _iso(now)},
                     condition="attribute_exists(PK)")    # never re-create a follow removed in the meantime
    except Exception as ex:
        log.warning("could not record the heads-up for %s %s: %s", follow.get("PK"), follow.get("SK"), ex)
    lat, lon = float(follow["lat"]), float(follow["lon"])
    area = A.area_for(lat, lon)
    store.audit(area.id if area else "other", None, "RainHeadsUp", {"place": follow.get("gh7") or follow.get("SK")},
                extra={"date": day.get("date"), "mm": day.get("mm"), "maxHourlyMm": day.get("maxHourlyMm"),
                       "level": day.get("level"), "tier": follow.get("tier"), "lang": follow.get("lang")})
    store.bump_stats(rainAlerts=1)
    return True


def rain_check(now: datetime | None = None) -> dict:
    """Read every follow, fetch each cell's forecast once and send the heads-ups that are due."""
    now = _utc(now)
    _topics.clear()
    follows = store.query_all("FOLLOWS", index="GSI3", cap=FOLLOWS_CAP)
    if len(follows) >= FOLLOWS_CAP:
        log.warning("more than %d follows: only the first %d were checked", FOLLOWS_CAP, FOLLOWS_CAP)
    by_cell: dict[str, list[dict]] = {}
    for f in follows:
        try:
            by_cell.setdefault(forecast.cell(float(f["lat"]), float(f["lon"])), []).append(f)
        except (KeyError, TypeError, ValueError):
            log.warning("follow %s %s has no usable location", f.get("PK"), f.get("SK"))
    cells = list(by_cell)
    forecasts = forecast.fetch([geo.geohash_decode(c) for c in cells], now=now) if cells else []
    alerts = failed = 0
    for cell_id, fc in zip(cells, forecasts):
        if fc is None:
            failed += 1
            continue
        fc = forecast.with_levels(fc)
        try:
            forecast.remember(cell_id, fc)       # the website's forecast for these places is now fresh too
        except Exception as ex:
            log.warning("forecast cache write failed: %s", ex)
        for f in by_cell[cell_id]:
            day = due_day(f, fc, now)
            if day and _send(f, day, fc, now):
                alerts += 1
    result = {"follows": len(follows), "cells": len(cells), "alerts": alerts, "failedForecasts": failed}
    log.info("rain check: %s", result)
    return result


def send_test(follow: dict) -> dict:
    """A test heads-up for one followed place, with the wettest of the coming days, sent now.
    Raises ForecastUnavailable when the forecast cannot be read."""
    _topics.pop(follow.get("userId"), None)          # the API's Lambda stays warm: ask SNS for the topic again
    fc = forecast.for_place(float(follow["lat"]), float(follow["lon"]))
    if not fc or not fc.get("days"):
        raise ForecastUnavailable("the rain forecast could not be read just now; try again in a few minutes")
    now = datetime.now(timezone.utc)
    today = _local_date(now, _offset(fc)).isoformat()
    coming = [d for d in fc["days"] if str(d.get("date") or "") >= today] or fc["days"]
    day = max(coming, key=lambda d: float(d.get("mm") or 0))         # the earliest of equally wet days
    subject, body = message(follow, day, fc, test=True, now=now)
    notify(follow, subject, body)
    return {"subject": subject, "body": body, "sent": True}


def handler(event, context=None):
    return rain_check()

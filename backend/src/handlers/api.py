"""JalSmriti HTTP API (API Gateway HTTP API -> Lambda, routed with Powertools for AWS Lambda).

/v1/...         public: areas, lakes, places (with this week's steps, rain forecast, signed report, narration),
                evidence, dossiers, standing-water reports, verification, search
/v1/secure/...  signed in (Amazon Cognito JWT checked by API Gateway); every action decided by Cedar and audited
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import date, timedelta

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, CORSConfig, Response
from aws_lambda_powertools.event_handler.exceptions import BadRequestError, NotFoundError, ServiceError, UnauthorizedError

from jalsmriti import actions as ACT
from jalsmriti import areas as A
from jalsmriti import authz, forecast, geo, insights, ledger, names, narration, news, signing, speech, storage, store, strings, verdict, waterlog
from jalsmriti import config as C

logger = Logger(service="jalsmriti-api")
app = APIGatewayHttpResolver(cors=CORSConfig(allow_origin="*", max_age=600,
                                             allow_headers=["Authorization", "Content-Type"]))
ID = re.compile(r"^[a-z0-9-]{3,40}$")


class Forbidden(ServiceError):
    def __init__(self, msg: str, decision: dict | None = None):
        super().__init__(403, json.dumps({"message": msg, "decision": decision}))


# ------------------------------------------------------------------------------------------ helpers
def body() -> dict:
    try:
        return app.current_event.json_body or {}
    except Exception:
        raise BadRequestError("body must be JSON")


def q(name: str, default=None):
    return (app.current_event.query_string_parameters or {}).get(name, default)


def client_ip() -> str:
    """The viewer's address for per-address limits. Through CloudFront (which handler() has checked), it is the last
    X-Forwarded-For entry that CloudFront appended; anything before it was written by the caller and is ignored."""
    source = app.current_event.request_context.http.source_ip or "unknown"
    if not C.ORIGIN_SECRET:
        return source
    h = {k.lower(): v for k, v in (app.current_event.headers or {}).items()}
    hops = [x.strip() for x in (h.get("x-forwarded-for") or "").split(",") if x.strip() and x.strip() != source]
    return hops[-1] if hops else source


def user() -> dict:
    rc = app.current_event.raw_event.get("requestContext", {})
    claims = (rc.get("authorizer") or {}).get("jwt", {}).get("claims") or (rc.get("authorizer") or {}).get("claims")
    if not claims:
        raise UnauthorizedError("sign in first")
    return authz.user_from_claims(claims)


def check_id(v: str, what: str = "id") -> str:
    if not v or not ID.match(v):
        raise BadRequestError(f"bad {what}")
    return v


def rate(who: str, action: str):
    try:
        store.rate_limit(who, action)
    except store.RateLimited as ex:
        raise ServiceError(429, str(ex))


def decide(u: dict, action: str, resource: dict, area: str, context: dict | None = None, extra=None,
           audit_resource: dict | None = None) -> dict:
    d = authz.decision(u, action, resource, context, extra)
    store.audit(area, u, action, audit_resource or {"type": resource["uid"]["type"].split("::")[-1], "id": resource["uid"]["id"]}, d)
    if not d["allowed"]:
        raise Forbidden(d["rule"], d)
    return d


def lake_or_404(lake_id: str) -> dict:
    lk = store.get(f"LAKE#{check_id(lake_id, 'lake id')}")
    if not lk:
        raise NotFoundError("no such lake")
    return lk


def public_evidence(e: dict) -> dict:
    keep = ("evidenceId", "lakeId", "areaId", "lakeName", "status", "createdAt", "capturedAt", "url", "thumbUrl",
            "categories", "gpsCheck", "gpsDistanceM", "sha256", "uploader", "note", "review", "facesBlurred", "width",
            "height", "ledgerSeq")
    out = {k: e.get(k) for k in keep if e.get(k) is not None}
    if e.get("ai"):
        out["ai"] = {k: e["ai"].get(k) for k in ("summary", "categories", "confidence", "model")}
    if e.get("exif"):
        out["camera"] = " ".join(x for x in (e["exif"].get("make"), e["exif"].get("model")) if x) or None
    return out


def public_dossier(d: dict, full: bool = True) -> dict:
    keep = ["dossierId", "lakeId", "areaId", "lakeName", "status", "createdAt", "readyAt", "creator", "recipient",
            "language", "pdfUrl", "payloadSha256", "pdfSha256", "timeline", "ledgerSeq", "submission", "error"]
    if full:
        keep += ["letter", "translation", "facts"]
    return {k: d.get(k) for k in keep if d.get(k) is not None}


def lat_lon(src: dict) -> tuple[float, float]:
    """lat/lon from a body or query, inside India or Nepal."""
    try:
        lat, lon = float(src["lat"]), float(src["lon"])
    except Exception:
        raise BadRequestError("lat and lon are required")
    if not geo.supported(lat, lon):
        raise BadRequestError("JalSmriti covers India and Nepal")
    return lat, lon


def place_cached(lat: float, lon: float) -> dict | None:
    """The stored place check for this spot (the same ~150 m geohash cell the check was made for)."""
    it = store.get(f"PLACE#{geo.geohash(lat, lon, 7)}", f"V#{C.PLACE_CACHE_VERSION}")
    return {k: v for k, v in it.items() if k not in ("PK", "SK", "ttl")} if it else None


def with_actions(result: dict) -> dict:
    """A place check plus this week's steps for someone renting or buying and for someone living there."""
    try:
        country = geo.country(float(result["lat"]), float(result["lon"]))
        return {**result, "actions": ACT.for_place(result), "country": country}
    except Exception as ex:      # advice must never break the report itself
        logger.warning("actions failed: %s", ex)
        return result


def start_execution(arn: str, name: str, payload: dict) -> None:
    if C.LOCAL or not arn:
        logger.info("local: would start %s %s", arn, payload)
        return
    import boto3
    boto3.client("stepfunctions", region_name=C.REGION).start_execution(stateMachineArn=arn, name=name,
                                                                         input=json.dumps(payload))


def send_job(msg: dict) -> None:
    if C.LOCAL or not C.JOBS_QUEUE_URL:
        logger.info("local: job %s", msg)
        return
    import boto3
    boto3.client("sqs", region_name=C.REGION).send_message(QueueUrl=C.JOBS_QUEUE_URL, MessageBody=json.dumps(msg))


# ------------------------------------------------------------------------------------------ public: basics
@app.get("/v1/health")
def health():
    return {"ok": True, "service": "jalsmriti", "scienceVersion": C.SCIENCE_VERSION, "time": store.now_iso()}


@app.get("/v1/stats")
def stats():
    s = store.stats()
    areas = []
    for a in A.AREAS.values():
        m = store.get(f"AREA#{a.id}") or {}
        areas.append({"id": a.id, "status": m.get("status", "pending"), "stats": m.get("stats")})
    tot = {"historicHa": 0, "lostHa": 0, "builtOverHa": 0, "lakes": 0}
    for a in areas:
        for k in tot:
            tot[k] += int(((a.get("stats") or {}).get(k)) or 0)
    return {"counters": s, "areas": areas, "totals": tot}


@app.get("/v1/policies")
def policies():
    return {"cedar": authz.policy_text(), "rules": authz.RULES}


@app.get("/v1/keys")
def keys():
    k = signing.public_key()
    return {k2: k[k2] for k2 in ("keyId", "spki", "pem", "alg", "fingerprint", "local")}


# ------------------------------------------------------------------------------------------ areas and lakes
@app.get("/v1/areas")
def list_areas():
    out = []
    for a in A.AREAS.values():
        m = store.get(f"AREA#{a.id}") or {}
        out.append({**a.public(), "status": m.get("status", "pending"), "stage": m.get("stage"), "stats": m.get("stats"),
                    "manifest": m.get("manifest")})
    return {"areas": out, "uiLanguages": list(A.UI_LANGUAGES)}


@app.get("/v1/areas/<area_id>")
def get_area(area_id: str):
    a = A.AREAS.get(area_id)
    if not a:
        raise NotFoundError("no such area")
    m = store.get(f"AREA#{a.id}") or {}
    return {**a.public(), "status": m.get("status", "pending"), "stage": m.get("stage"), "stats": m.get("stats"),
            "manifest": m.get("manifest"), "authorities": a.authorities}


@app.get("/v1/areas/<area_id>/lakes")
def area_lakes(area_id: str):
    if area_id not in A.AREAS:
        raise NotFoundError("no such area")
    rows = store.query_all(f"AREA#{area_id}", "LAKE#")
    keep = ("lakeId", "name", "kind", "areaHa", "lon", "lat", "grade", "score", "lostPct", "lostHa", "builtPct",
            "builtHa", "retention", "weedPct")
    return {"lakes": [{k: r.get(k) for k in keep} for r in rows]}


@app.get("/v1/lakes/<lake_id>")
def get_lake(lake_id: str):
    lk = lake_or_404(lake_id)
    area = A.AREAS.get(lk.get("areaId") or "")
    watched = store.get("WATCHED", lake_id) or {}
    country = area.country if area else geo.country(lk["lat"], lk["lon"])
    out = {k: v for k, v in lk.items() if k not in ("PK", "SK", "GSI1PK", "GSI1SK")}
    out["frameUrls"] = {str(s): f"/{C.PUBLIC_PREFIX}lakes/{lake_id}/frames/{s}.webp" for s in lk.get("frames", [])}
    out["area"] = area.public() if area else None
    out["authorities"] = area.authorities if area else A.default_authorities(country)
    out["laws"] = area.laws if area else (A.LAW_NP if country == "NP" else A.LAW_IN)
    out["watchers"] = int(watched.get("count", 0))
    out["insights"] = insights.lake_insights(lk)
    return out


@app.get("/v1/lakes/<lake_id>/news")
def lake_news(lake_id: str):
    """Recent news naming the lake (Google News, then GDELT), for lakes with a name of their own."""
    lk = lake_or_404(lake_id)
    own = lk.get("nameSource") in names.REAL_SOURCES
    rate(client_ip(), "news")
    res = news.search(news.lake_query(lk.get("name"), lk.get("areaId")) if own else None, "lake")
    if not own:
        res["reason"] = "no name of its own"
    return {**res, "tags": news.summary(res["articles"])}


@app.get("/v1/news/floods")
def place_news():
    """Recent news of flooding that names a locality (Google News, then GDELT): ?locality=Velachery"""
    loc = str(q("locality") or "").strip()[:60]
    if len(loc) < 4:
        raise BadRequestError("give a locality name of at least 4 letters")
    rate(client_ip(), "news")
    res = news.search(news.place_query(loc), "floods", title_has=loc)
    return {**res, "locality": loc, "tags": news.summary(res["articles"])}


@app.get("/v1/lakes/<lake_id>/evidence")
def lake_evidence(lake_id: str):
    check_id(lake_id, "lake id")
    items = store.query_all(f"LAKE#{lake_id}", "EVID#", index="GSI1")
    items = [public_evidence(e) for e in items if e.get("status") in ("new", "verified", "rejected")]
    items.sort(key=lambda e: e.get("createdAt", ""), reverse=True)
    return {"evidence": items}


@app.get("/v1/lakes/<lake_id>/dossiers")
def lake_dossiers(lake_id: str):
    check_id(lake_id, "lake id")
    items = store.query_all(f"LAKE#{lake_id}", "DOSS#", index="GSI1")
    items.sort(key=lambda d: d.get("createdAt", ""), reverse=True)
    return {"dossiers": [public_dossier(d, full=False) for d in items]}


@app.get("/v1/lakes/<lake_id>/ledger")
def lake_ledger(lake_id: str):
    check_id(lake_id, "lake id")
    es = ledger.entries(lake_id)
    return {"entries": [{k: e.get(k) for k in ("seq", "kind", "subjectId", "payloadSha256", "actor", "at", "prevHash", "hash")}
                        for e in es], "verification": ledger.verify(lake_id)}


@app.post("/v1/lakes/find")
def find_lake():
    b = body()
    lat, lon = float(b.get("lat", 0)), float(b.get("lon", 0))
    if not geo.supported(lat, lon):
        raise BadRequestError("JalSmriti covers India and Nepal")
    rate(client_ip(), "lake")
    rate("site", "lake-all")
    job_id = store.new_id("lk")
    store.put({"PK": f"JOB#{job_id}", "SK": "META", "type": "lake", "status": "running", "lat": lat, "lon": lon,
               "createdAt": store.now_iso(), "stage": "finding the water body", "ttl": int(time.time()) + 7 * 86400})
    start_execution(C.LAKE_SFN_ARN, job_id, {"jobId": job_id, "lat": lat, "lon": lon})
    return Response(202, "application/json", json.dumps({"jobId": job_id, "status": "running"}))


# ------------------------------------------------------------------------------------------ places
@app.post("/v1/places")
def check_place():
    b = body()
    lat, lon = lat_lon(b)
    cached = place_cached(lat, lon)
    # "check again" re-reads the archive only once a day per spot; until then the stored check is the answer
    stale = bool(cached) and (cached.get("checkedAt") or "") < store.iso_days_ago(1)
    if cached and not (b.get("fresh") and stale):
        return {"status": "done", "cached": True, "result": with_actions(cached)}
    rate(client_ip(), "place")
    rate("site", "place-all")
    job_id = store.new_id("pl")
    store.put({"PK": f"JOB#{job_id}", "SK": "META", "type": "place", "status": "running", "lat": lat, "lon": lon,
               "label": b.get("label"), "createdAt": store.now_iso(), "ttl": int(time.time()) + 7 * 86400})
    start_execution(C.PLACE_SFN_ARN, job_id, {"jobId": job_id, "lat": lat, "lon": lon})
    return Response(202, "application/json", json.dumps({"jobId": job_id, "status": "running"}))


@app.get("/v1/jobs/<job_id>")
def get_job(job_id: str):
    j = store.get(f"JOB#{check_id(job_id, 'job id')}")
    if not j:
        raise NotFoundError("no such job")
    out = {k: v for k, v in j.items() if k not in ("PK", "SK", "ttl")}
    if out.get("type") == "place" and out.get("status") == "done" and out.get("result"):
        out["result"] = with_actions(out["result"])
    return out


@app.get("/v1/geocode")
def geocode():
    text = (q("q") or "").strip()
    if len(text) < 2:
        return {"results": []}
    if not C.LOCAL:
        rate(client_ip(), "geocode")
        rate("site", "geocode-all")
    results = []
    if not C.LOCAL:
        try:
            import boto3
            r = boto3.client("geo-places", region_name=C.REGION).geocode(
                QueryText=text[:200], MaxResults=6, Language="en", Filter={"IncludeCountries": ["IND", "NPL"]})
            for it in r.get("ResultItems", []):
                lon, lat = it["Position"]
                results.append({"label": it.get("Title") or it.get("Address", {}).get("Label"), "lat": lat, "lon": lon,
                                "kind": it.get("PlaceType"), "source": "Amazon Location Service"})
        except Exception as ex:
            logger.info("location service geocode failed, using Photon: %s", ex)
    if not results:
        results = names.search(text, limit=6, bias=(21.0, 79.0))
    return {"results": results}


@app.get("/v1/authorities")
def authorities():
    lat, lon = float(q("lat", 0)), float(q("lon", 0))
    a = A.area_for(lat, lon)
    if a:
        return {"areaId": a.id, "authorities": a.authorities, "laws": a.laws}
    country = geo.country(lat, lon)
    return {"areaId": None, "authorities": A.default_authorities(country), "laws": A.LAW_NP if country == "NP" else A.LAW_IN}


# ------------------------------------------------------------------------------------------ dossiers and verification
@app.get("/v1/dossiers/<dossier_id>")
def get_dossier(dossier_id: str):
    d = store.get(f"DOSS#{check_id(dossier_id, 'dossier id')}")
    if not d:
        raise NotFoundError("no such dossier")
    return public_dossier(d)


@app.get("/v1/verify/<dossier_id>")
def verify_dossier(dossier_id: str):
    check_id(dossier_id, "id")
    if dossier_id.startswith("rpt"):
        return verify_report(dossier_id)
    d = store.get(f"DOSS#{dossier_id}")
    if not d or d.get("status") in ("drafting", "failed"):
        raise NotFoundError("no signed dossier with this id")
    canon = d["attestationCanonical"].encode("utf-8")
    server_ok = signing.verify(hashlib.sha256(canon).digest(), d["signature"]["der"])
    k = signing.public_key()
    return {"kind": "dossier", "dossierId": dossier_id, "lakeId": d["lakeId"], "lakeName": d.get("lakeName"), "status": d.get("status"),
            "attestation": d["attestation"], "attestationCanonical": d["attestationCanonical"],
            "signature": {"alg": d["signature"]["alg"], "raw": d["signature"]["raw"], "der": d["signature"]["der"]},
            "publicKey": {"spki": k["spki"], "fingerprint": k["fingerprint"], "local": k["local"]},
            "serverCheck": server_ok, "pdfUrl": d.get("pdfUrl"), "payloadSha256": d.get("payloadSha256"),
            "pdfSha256": d.get("pdfSha256"), "ledger": ledger.verify(d["lakeId"]), "timeline": d.get("timeline"),
            "createdAt": d.get("createdAt"), "creator": d.get("creator")}


def public_report(r: dict) -> dict:
    keep = ("reportId", "status", "lat", "lon", "label", "lang", "persona", "checkedAt", "createdAt", "readyAt", "pdfUrl",
            "payloadSha256", "pdfSha256", "error")
    return {k: r.get(k) for k in keep if r.get(k) is not None}


def verify_report(report_id: str) -> dict:
    r = store.get(f"RPT#{report_id}")
    if not r or r.get("status") != "ready":
        raise NotFoundError("no signed report with this id")
    canon = r["attestationCanonical"].encode("utf-8")
    k = signing.public_key()
    return {"kind": "report", "reportId": report_id, "subject": r.get("label"), "lat": r.get("lat"), "lon": r.get("lon"),
            "status": r.get("status"), "attestation": r["attestation"], "attestationCanonical": r["attestationCanonical"],
            "signature": {x: r["signature"][x] for x in ("alg", "raw", "der")},
            "publicKey": {"spki": k["spki"], "fingerprint": k["fingerprint"], "local": k["local"]},
            "serverCheck": signing.verify(hashlib.sha256(canon).digest(), r["signature"]["der"]),
            "pdfUrl": r.get("pdfUrl"), "payloadSha256": r.get("payloadSha256"), "pdfSha256": r.get("pdfSha256"),
            "createdAt": r.get("createdAt"), "lang": r.get("lang")}


# ------------------------------------------------------------------------------------------ places: rain, signed report, voice
@app.get("/v1/forecast")
def place_forecast():
    lat, lon = lat_lon(app.current_event.query_string_parameters or {})
    rate(client_ip(), "forecast")
    rate("site", "forecast-all")
    fc = forecast.for_place(lat, lon)
    if not fc:
        raise ServiceError(503, "the weather forecast did not answer; try again in a minute")
    return fc


def verdict_answers(src: dict) -> dict:
    return verdict.answers({k: src.get(k) for k in ("mode", "floor", "parking", "vulnerable")})


def reports_near(lat: float, lon: float) -> int:
    try:
        return int(waterlog.nearby(lat, lon, 1000, 365)["count"])
    except Exception as ex:          # the verdict still stands on the satellite record
        logger.warning("nearby reports failed: %s", ex)
        return 0


@app.get("/v1/places/verdict")
def place_verdict():
    """Our read for someone about to rent or buy here, from the stored check and four answers:
    ?lat=&lon=&mode=rent|buy&floor=ground|low|high|house&parking=1&vulnerable=1"""
    lat, lon = lat_lon({"lat": q("lat"), "lon": q("lon")})
    cached = place_cached(lat, lon)
    if not cached:
        raise ServiceError(409, "check this place first")
    src = {k: q(k) for k in ("mode", "floor", "parking", "vulnerable")}
    return verdict.build(cached, verdict_answers(src), reports_near(lat, lon))


@app.post("/v1/places/report")
def create_report():
    """A signed PDF of the place check in the reader's language, for someone renting, buying or living there."""
    b = body()
    lat, lon = lat_lon(b)
    lang = strings.lang_or_en(b.get("lang"))
    persona = b.get("persona") if b.get("persona") in ("home", "resident") else "home"
    cached = place_cached(lat, lon)
    if not cached:
        raise ServiceError(409, "check this place first")
    gh = geo.geohash(lat, lon, 7)
    # a family about to rent or buy can add its four answers: the report then carries our read for them
    answers = verdict_answers(b["answers"]) if persona == "home" and isinstance(b.get("answers"), dict) else None
    ans_key = "|".join(str(answers[k]) for k in ("mode", "floor", "parking", "vulnerable")) if answers else ""
    # the same check, language, reader and answers always give the same report, so the id is derived and reused
    seed = f"{gh}|{C.PLACE_CACHE_VERSION}|{cached.get('checkedAt')}|{lang}|{persona}" + (f"|{ans_key}" if ans_key else "")
    rid = "rpt" + hashlib.sha256(seed.encode()).hexdigest()[:16]
    existing = store.get(f"RPT#{rid}")
    if existing and (existing.get("status") == "ready" or
                     (existing.get("status") == "rendering" and existing.get("createdAt", "") > store.iso_days_ago(10 / 1440))):
        return public_report(existing)
    rate(client_ip(), "report")
    rate("site", "report-all")
    label = str(b.get("label") or (cached.get("label") or {}).get("label") or "").strip()[:140] or None
    item = {"PK": f"RPT#{rid}", "SK": "META", "reportId": rid, "status": "rendering", "gh7": gh, "lat": round(lat, 5),
            "lon": round(lon, 5), "label": label, "lang": lang, "persona": persona, "answers": answers,
            "checkedAt": cached.get("checkedAt"),
            "createdAt": store.now_iso(), "ttl": int(time.time()) + 400 * 86400}
    store.put(item)
    send_job({"type": "report", "reportId": rid})
    return Response(202, "application/json", json.dumps(public_report(item)))


@app.get("/v1/reports/<report_id>")
def get_report(report_id: str):
    r = store.get(f"RPT#{check_id(report_id, 'report id')}")
    if not r:
        raise NotFoundError("no such report")
    return public_report(r)


@app.post("/v1/speech")
def speak():
    """The place or lake report read aloud (Amazon Polly, Hindi or English). Audio is cached by its text."""
    b = body()
    lang = b.get("lang")
    if lang not in ("hi", "en"):
        raise BadRequestError("listening is available in Hindi and English")
    kind = b.get("kind")
    if kind == "place":
        lat, lon = lat_lon(b)
        cached = place_cached(lat, lon)
        if not cached:
            raise ServiceError(409, "check this place first")
        persona = b.get("persona") if b.get("persona") in ("home", "resident") else "home"
        steps = ACT.for_place(cached)[persona][:3]
        text = narration.place_text(cached, lang, [strings.action_text(a, lang) for a in steps])
    elif kind == "lake":
        text = narration.lake_text(lake_or_404(str(b.get("lakeId") or "")), lang)
    else:
        raise BadRequestError("kind must be place or lake")
    path = storage.public_key(f"speech/{speech.cache_key(speech.trim(text), lang)}.{'wav' if C.LOCAL else 'mp3'}")
    if not storage.exists(C.SITE_BUCKET or "site", path):     # listening again to the same words costs nothing
        rate(client_ip(), "speech")
        rate("site", "speech-all")
    return {**speech.synthesize(text, lang), "text": text}


# ------------------------------------------------------------------------------------------ RTI requests about a lake
def public_rti(r: dict) -> dict:
    keep = ("rtiId", "lakeId", "lakeName", "office", "filedOn", "dueBy", "reference", "channel", "items", "by", "createdAt",
            "ledgerSeq", "country")
    return {k: r.get(k) for k in keep if r.get(k) is not None}


@app.get("/v1/lakes/<lake_id>/rti")
def lake_rti(lake_id: str):
    check_id(lake_id, "lake id")
    items = store.query_all(f"LAKE#{lake_id}", "RTI#", index="GSI1")
    items.sort(key=lambda r: r.get("filedOn", ""), reverse=True)
    return {"requests": [public_rti(r) for r in items]}


# ------------------------------------------------------------------------------------------ standing water reported by people
@app.get("/v1/waterlogging")
def water_reports():
    try:
        hours = max(1, min(int(q("hours", 48)), 168))
    except ValueError:
        raise BadRequestError("hours must be a number")
    return {"hours": hours, "reports": waterlog.recent(hours)}


@app.get("/v1/waterlogging/near")
def water_reports_near():
    lat, lon = lat_lon(app.current_event.query_string_parameters or {})
    try:
        radius = max(100.0, min(float(q("radius", 1000)), 5000.0))
        days = max(1, min(int(q("days", 365)), 730))
    except ValueError:
        raise BadRequestError("radius and days must be numbers")
    return waterlog.nearby(lat, lon, radius, days)


# ------------------------------------------------------------------------------------------ signed in
@app.get("/v1/secure/me")
def me():
    u = user()
    console_areas = [a for a in A.AREAS if u["role"] != "citizen" and ("*" in u["jurisdictions"] or a in u["jurisdictions"])]
    if u["role"] != "citizen" and "*" in u["jurisdictions"]:
        console_areas.append("other")       # standing-water reports and lakes outside the nine areas
    return {"user": {k: u[k] for k in ("id", "username", "role", "jurisdictions", "pseudonym", "email", "groups")},
            "consoleAreas": console_areas}


@app.get("/v1/secure/me/activity")
def my_activity():
    u = user()
    items = store.query_all(f"USER#{u['id']}", index="GSI2")
    ev = [public_evidence(i) for i in items if i.get("PK", "").startswith("EVID#")]
    ds = [public_dossier(i, full=False) for i in items if i.get("PK", "").startswith("DOSS#")]
    ws = []
    for i in items:
        if not i.get("PK", "").startswith("WATCH#"):
            continue
        status = i.get("status")
        if status == "pending confirmation" and str(i.get("subscriptionArn", "")).startswith("arn:") and not C.LOCAL:
            try:   # the person may have clicked the link in the email since
                import boto3
                attrs = boto3.client("sns", region_name=C.REGION).get_subscription_attributes(
                    SubscriptionArn=i["subscriptionArn"])["Attributes"]
                if attrs.get("PendingConfirmation") == "false":
                    status = "active"
                    store.update(i["PK"], i["SK"], sets={"status": status})
            except Exception as ex:
                logger.info("subscription check failed: %s", ex)
        ws.append({"lakeId": i["lakeId"], "lakeName": i.get("lakeName"), "status": status, "createdAt": i.get("createdAt")})
    follows = [{k: i.get(k) for k in ("gh7", "lat", "lon", "label", "tier", "createdAt", "lastAlertFor")}
               for i in items if i.get("PK", "").startswith("FOLLOW#")]
    sub = store.get(f"USERSUB#{u['id']}")
    rtis = [public_rti(i) for i in items if i.get("PK", "").startswith("RTI#")]
    return {"evidence": ev, "dossiers": ds, "watches": ws, "follows": follows, "rti": rtis,
            "headsUp": {"status": refresh_subscription(sub)["status"]} if sub else None,
            "waterReports": waterlog.mine(u["id"])}


# ------------------------------------------------------------------------------------------ follow a place: rain heads-up
def refresh_subscription(rec: dict) -> dict:
    """The person may have clicked the confirmation link (or unsubscribed) since we last looked."""
    if C.LOCAL or not str(rec.get("subscriptionArn", "")).startswith("arn:") or rec.get("status") == "active":
        return rec
    import boto3
    try:
        attrs = boto3.client("sns", region_name=C.REGION).get_subscription_attributes(
            SubscriptionArn=rec["subscriptionArn"])["Attributes"]
        status = "active" if attrs.get("PendingConfirmation") == "false" else "pending confirmation"
    except Exception as ex:
        logger.info("subscription check failed: %s", ex)
        status = "unsubscribed" if "NotFound" in str(ex) else rec.get("status", "pending confirmation")
    if status != rec.get("status"):
        store.update(rec["PK"], rec["SK"], sets={"status": status})
        rec = {**rec, "status": status}
    return rec


def heads_up_subscription(u: dict) -> dict:
    """One SNS topic per person; their verified email is subscribed once and gets every place's heads-up."""
    rec = store.get(f"USERSUB#{u['id']}")
    if rec and rec.get("email") == u.get("email"):
        rec = refresh_subscription(rec)
        if rec.get("status") != "unsubscribed":
            return rec
    arn = sub_arn = "local"
    if not C.LOCAL:
        import boto3
        sns = boto3.client("sns", region_name=C.REGION)
        arn = sns.create_topic(Name=C.user_topic_name(u["id"]),
                               Attributes={"DisplayName": "JalSmriti rain heads-up"})["TopicArn"]   # idempotent
        sub_arn = sns.subscribe(TopicArn=arn, Protocol="email", Endpoint=u["email"], ReturnSubscriptionArn=True)["SubscriptionArn"]
    rec = {"PK": f"USERSUB#{u['id']}", "SK": "META", "topicArn": arn, "subscriptionArn": sub_arn, "email": u["email"],
           "status": "active" if C.LOCAL else "pending confirmation", "createdAt": store.now_iso()}
    store.put(rec)
    return rec


@app.post("/v1/secure/follows")
def follow_place():
    u = user()
    b = body()
    lat, lon = lat_lon(b)
    if not u.get("email") or not u.get("emailVerified"):
        raise BadRequestError("confirm your email address first: heads-ups go only to a verified address")
    area = A.area_for(lat, lon)
    area_id = area.id if area else "other"
    decide(u, "FollowPlace", authz.area_entity(area_id), area_id)
    gh = geo.geohash(lat, lon, 7)
    if store.get(f"FOLLOW#{u['id']}", gh):
        return {"ok": True, "gh7": gh, "status": heads_up_subscription(u)["status"], "already": True}
    if len(store.query_all(f"FOLLOW#{u['id']}")) >= C.MAX_FOLLOWS:
        raise BadRequestError(f"you can follow up to {C.MAX_FOLLOWS} places: stop following one first")
    rate(u["id"], "follow")
    cached = place_cached(lat, lon) or {}
    label = str(b.get("label") or (cached.get("label") or {}).get("label") or "").strip()[:140] or None
    sub = heads_up_subscription(u)
    store.put({"PK": f"FOLLOW#{u['id']}", "SK": gh, "userId": u["id"], "gh7": gh, "lat": round(lat, 5), "lon": round(lon, 5),
               "label": label, "tier": (cached.get("memory") or {}).get("tier") or "unknown",
               "lang": strings.lang_or_en(b.get("lang")), "createdAt": store.now_iso(), "areaId": area.id if area else None,
               "GSI2PK": f"USER#{u['id']}", "GSI2SK": f"FOLLOW#{gh}", "GSI3PK": "FOLLOWS", "GSI3SK": f"{gh}#{u['id']}"})
    store.bump_stats(follows=1)
    return {"ok": True, "gh7": gh, "status": sub["status"]}


@app.delete("/v1/secure/follows/<gh7>")
def unfollow_place(gh7: str):
    u = user()
    if not re.fullmatch(r"[0-9b-hjkmnp-z]{7}", gh7 or ""):
        raise BadRequestError("bad place id")
    store.delete(f"FOLLOW#{u['id']}", gh7)
    return {"ok": True}


@app.post("/v1/secure/follows/<gh7>/test")
def test_heads_up(gh7: str):
    """Send the person a heads-up for this place now, with today's forecast, so they see what one looks like."""
    import alerts
    u = user()
    f = store.get(f"FOLLOW#{u['id']}", gh7 if re.fullmatch(r"[0-9b-hjkmnp-z]{7}", gh7 or "") else "-")
    if not f:
        raise NotFoundError("you do not follow this place")
    rate(u["id"], "heads-up-test")
    sub = heads_up_subscription(u)
    try:
        r = alerts.send_test(f)
    except alerts.ForecastUnavailable:
        raise ServiceError(503, "the weather forecast did not answer; try again in a minute")
    return {"ok": True, "status": sub["status"], "subject": r["subject"], "body": r["body"], "local": C.LOCAL}


# ------------------------------------------------------------------------------------------ record an RTI request
@app.post("/v1/secure/lakes/<lake_id>/rti")
def record_rti(lake_id: str):
    u = user()
    lk = lake_or_404(lake_id)
    b = body()
    office = str(b.get("office") or "").strip()[:200]
    if len(office) < 3:
        raise BadRequestError("name the office the request went to")
    try:
        filed = date.fromisoformat(str(b.get("filedOn") or date.today().isoformat())[:10])
    except ValueError:
        raise BadRequestError("filedOn must be a date (YYYY-MM-DD)")
    if filed > date.today() + timedelta(days=1) or filed < date.today() - timedelta(days=400):
        raise BadRequestError("the filing date must be within the last year")
    decide(u, "RecordRti", authz.lake_entity(lake_id, lk.get("areaId"), lk.get("kind", "lake")), lk.get("areaId"))
    rate(u["id"], "rti")
    area = A.AREAS.get(lk.get("areaId") or "")
    country = area.country if area else geo.country(lk["lat"], lk["lon"])
    reply_days = 15 if country == "NP" else 30          # Nepal RTI Act 2007 s.7; India RTI Act 2005 s.7(1)
    rid, now = store.new_id("rti"), store.now_iso()
    rec = {"office": office, "filedOn": filed.isoformat(), "dueBy": (filed + timedelta(days=reply_days)).isoformat(),
           "reference": str(b.get("reference") or "").strip()[:120] or None,
           "channel": b.get("channel") if b.get("channel") in ("online", "post", "hand") else None,
           "items": [str(x)[:40] for x in (b.get("items") or []) if isinstance(x, str)][:10], "by": u["pseudonym"],
           "country": country}
    entry = ledger.append(lake_id, "rti", rid, ledger.sha256_hex(ledger.canonical(rec)), u["pseudonym"])
    store.put({"PK": f"RTI#{rid}", "SK": "META", "rtiId": rid, "lakeId": lake_id, "lakeName": lk.get("name"),
               "areaId": lk.get("areaId"), **rec, "createdAt": now, "creatorId": u["id"], "ledgerSeq": entry["seq"],
               "GSI1PK": f"LAKE#{lake_id}", "GSI1SK": f"RTI#{now}", "GSI2PK": f"USER#{u['id']}", "GSI2SK": f"RTI#{now}"})
    store.bump_stats(rti=1)
    return {"ok": True, "rtiId": rid, "dueBy": rec["dueBy"], "ledgerSeq": entry["seq"]}


# ------------------------------------------------------------------------------------------ report standing water
@app.post("/v1/secure/waterlogging/upload")
def water_report_upload():
    u = user()
    b = body()
    ctype = b.get("contentType", "image/jpeg")
    if ctype not in C.EVIDENCE_TYPES:
        raise BadRequestError("photos only: JPEG, PNG or WebP")
    if int(b.get("size") or 0) > C.EVIDENCE_MAX_BYTES:
        raise BadRequestError("photo is larger than 12 MB")
    device = None
    if b.get("lat") is not None and b.get("lon") is not None:
        lat, lon = lat_lon(b)
        acc = b.get("accuracyM")
        device = {"lat": round(lat, 6), "lon": round(lon, 6),
                  "accuracyM": round(float(acc)) if isinstance(acc, (int, float)) and acc >= 0 else None}
    area = A.area_for(device["lat"], device["lon"]) if device else None
    area_id = area.id if area else "other"
    decide(u, "ReportWaterlogging", authz.area_entity(area_id), area_id)
    rate(u["id"], "waterlog")
    rate("site", "waterlog-all")
    rid, now = store.new_id("wl"), store.now_iso()
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[ctype]
    store.put({"PK": f"WLOG#{rid}", "SK": "META", "reportId": rid, "status": "uploading", "createdAt": now,
               "uploaderId": u["id"], "uploader": u["pseudonym"], "device": device,
               "depth": b.get("depth") if b.get("depth") in ("ankle", "knee", "waist", "vehicle") else None,
               "note": str(b.get("note") or "").strip()[:300] or None, "contentType": ctype,
               "areaId": area.id if area else None,
               "GSI2PK": f"USER#{u['id']}", "GSI2SK": f"WLOG#{now}", "GSI3PK": f"QUEUE#WLOG#{area_id}",
               "GSI3SK": f"uploading#{now}"})
    post = storage.presigned_post(f"evidence/waterlogging/{rid}.{ext}", ctype, C.EVIDENCE_MAX_BYTES)
    return {"reportId": rid, "upload": post, "maxBytes": C.EVIDENCE_MAX_BYTES}


@app.get("/v1/secure/waterlogging/<report_id>")
def my_water_report(report_id: str):
    u = user()
    r = store.get(f"WLOG#{check_id(report_id, 'report id')}")
    if not r or (r.get("uploaderId") != u["id"] and u["role"] == "citizen"):
        raise NotFoundError("no such report")
    return {**waterlog.public(r), "status": r.get("status")}


@app.post("/v1/secure/waterlogging/<report_id>/review")
def review_water_report(report_id: str):
    u = user()
    r = store.get(f"WLOG#{check_id(report_id, 'report id')}")
    if not r or r.get("status") not in ("live", "hidden", "verified", "rejected"):
        raise NotFoundError("no such report")
    b = body()
    decision_ = b.get("decision")
    if decision_ not in ("verified", "rejected"):
        raise BadRequestError("decision must be verified or rejected")
    note = str(b.get("note") or "").strip()[:600]
    res, stub = authz.report_entity(r)
    decide(u, "ReviewReport", res, r.get("areaId") or "other", {"hasNote": len(note) >= 10}, [stub])
    waterlog.apply_review(report_id, {"decision": decision_, "by": u["pseudonym"], "role": u["role"], "at": store.now_iso(),
                                      "note": note})
    return {"ok": True, "status": decision_}


@app.post("/v1/secure/lakes/<lake_id>/evidence/upload")
def evidence_upload(lake_id: str):
    u = user()
    lk = lake_or_404(lake_id)
    b = body()
    ctype = b.get("contentType", "image/jpeg")
    if ctype not in C.EVIDENCE_TYPES:
        raise BadRequestError("photos only: JPEG, PNG or WebP")
    size = int(b.get("size") or 0)
    if size and size > C.EVIDENCE_MAX_BYTES:
        raise BadRequestError("photo is larger than 12 MB")
    decide(u, "UploadEvidence", authz.lake_entity(lake_id, lk.get("areaId"), lk.get("kind", "lake")), lk.get("areaId"))
    rate(u["id"], "evidence")
    eid = store.new_id("ev")
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[ctype]
    now = store.now_iso()
    note = str(b.get("note") or "")[:500] or None
    store.put({"PK": f"EVID#{eid}", "SK": "META", "evidenceId": eid, "lakeId": lake_id, "areaId": lk.get("areaId"),
               "lakeName": lk.get("name"), "status": "uploading", "createdAt": now, "uploaderId": u["id"],
               "uploader": u["pseudonym"], "note": note, "contentType": ctype,
               "GSI1PK": f"LAKE#{lake_id}", "GSI1SK": f"EVID#{now}", "GSI2PK": f"USER#{u['id']}", "GSI2SK": f"EVID#{now}",
               "GSI3PK": f"QUEUE#EVID#{lk.get('areaId') or 'other'}", "GSI3SK": f"uploading#{now}"})
    post = storage.presigned_post(f"evidence/{lake_id}/{eid}.{ext}", ctype, C.EVIDENCE_MAX_BYTES)
    return {"evidenceId": eid, "upload": post, "maxBytes": C.EVIDENCE_MAX_BYTES}


@app.get("/v1/secure/evidence/<evidence_id>")
def my_evidence(evidence_id: str):
    u = user()
    e = store.get(f"EVID#{check_id(evidence_id, 'evidence id')}")
    if not e or (e.get("uploaderId") != u["id"] and u["role"] == "citizen"):
        raise NotFoundError("no such evidence")
    out = {**public_evidence(e), "moderation": e.get("moderation"), "labels": e.get("labels")}
    if e.get("status") == "unrelated":               # why it was kept private, in the uploader's own words
        out.update(unrelatedReason=e.get("unrelatedReason"), textWords=e.get("textWords"),
                   scene=(e.get("ai") or {}).get("scene"))
    return out


@app.post("/v1/secure/lakes/<lake_id>/dossiers")
def create_dossier(lake_id: str):
    u = user()
    lk = lake_or_404(lake_id)
    b = body()
    lang = b.get("language", "hi")
    if lang not in C.DOSSIER_LANGUAGES:
        raise BadRequestError("unsupported language")
    area = A.AREAS.get(lk.get("areaId") or "")
    auths = area.authorities if area else A.default_authorities("IN")
    rec = next((a for a in auths if a["id"] == b.get("recipientId")), auths[0])
    decide(u, "CreateDossier", authz.lake_entity(lake_id, lk.get("areaId"), lk.get("kind", "lake")), lk.get("areaId"))
    rate(u["id"], "dossier")
    did = store.new_id("ds")
    now = store.now_iso()
    store.put({"PK": f"DOSS#{did}", "SK": "META", "dossierId": did, "lakeId": lake_id, "areaId": lk.get("areaId"),
               "lakeName": lk.get("name"), "status": "drafting", "createdAt": now, "creatorId": u["id"],
               "creator": u["pseudonym"], "language": lang, "recipient": {k: rec.get(k) for k in ("id", "name", "kind", "url", "how")},
               "evidenceIds": [e for e in (b.get("evidenceIds") or []) if isinstance(e, str)][:6],
               "timeline": [{"at": now, "status": "drafting", "by": u["pseudonym"], "note": "Dossier requested"}],
               "GSI1PK": f"LAKE#{lake_id}", "GSI1SK": f"DOSS#{now}", "GSI2PK": f"USER#{u['id']}", "GSI2SK": f"DOSS#{now}",
               "GSI3PK": f"QUEUE#DOSS#{lk.get('areaId') or 'other'}", "GSI3SK": f"drafting#{now}"})
    send_job({"type": "dossier", "dossierId": did})
    return Response(202, "application/json", json.dumps({"dossierId": did, "status": "drafting"}))


@app.post("/v1/secure/dossiers/<dossier_id>/submitted")
def mark_submitted(dossier_id: str):
    u = user()
    d = store.get(f"DOSS#{check_id(dossier_id, 'dossier id')}")
    if not d:
        raise NotFoundError("no such dossier")
    b = body()
    res, stub = authz.dossier_entity(d)
    decide(u, "MarkSubmitted", res, d.get("areaId"), extra=[stub])
    if d.get("status") != "ready":
        raise BadRequestError("only a signed, ready dossier can be marked submitted")
    sub = {"portal": str(b.get("portal") or "")[:120], "reference": str(b.get("reference") or "")[:120], "at": store.now_iso()}
    entry = ledger.append(d["lakeId"], "submitted", dossier_id, ledger.sha256_hex(ledger.canonical(sub)), u["pseudonym"])
    tl = (d.get("timeline") or []) + [{"at": sub["at"], "status": "submitted", "by": u["pseudonym"],
                                       "note": f"Submitted via {sub['portal'] or 'unspecified'}" + (f", ref {sub['reference']}" if sub["reference"] else "")}]
    store.update(f"DOSS#{dossier_id}", "META", sets={"status": "submitted", "submission": sub, "timeline": tl,
                                                     "GSI3SK": f"submitted#{d['createdAt']}", "submittedSeq": entry["seq"]})
    return {"ok": True, "status": "submitted"}


@app.post("/v1/secure/lakes/<lake_id>/watch")
def watch_lake(lake_id: str):
    u = user()
    lk = lake_or_404(lake_id)
    decide(u, "WatchLake", authz.lake_entity(lake_id, lk.get("areaId"), lk.get("kind", "lake")), lk.get("areaId"))
    rate(u["id"], "watch")
    email = u.get("email")
    if not email or not u.get("emailVerified"):
        raise BadRequestError("confirm your email address first: alerts go only to a verified address")
    if store.get(f"WATCH#{lake_id}", f"USER#{u['id']}"):
        return {"ok": True, "status": "already watching"}
    arn = "local"
    if not C.LOCAL:
        import boto3
        sns = boto3.client("sns", region_name=C.REGION)
        topic = sns.create_topic(Name=C.lake_topic_name(lake_id),
                                 Attributes={"DisplayName": "JalSmriti lake watch"})["TopicArn"]   # idempotent
        arn = sns.subscribe(TopicArn=topic, Protocol="email", Endpoint=email, ReturnSubscriptionArn=True)["SubscriptionArn"]
    now = store.now_iso()
    store.put({"PK": f"WATCH#{lake_id}", "SK": f"USER#{u['id']}", "lakeId": lake_id, "lakeName": lk.get("name"),
               "subscriptionArn": arn, "status": "pending confirmation" if arn != "local" else "active", "createdAt": now,
               "GSI2PK": f"USER#{u['id']}", "GSI2SK": f"WATCH#{lake_id}"})
    store.update("WATCHED", lake_id, adds={"count": 1}, sets={"lakeName": lk.get("name"), "areaId": lk.get("areaId")})
    store.bump_stats(watchers=1)
    return {"ok": True, "status": "check your email and confirm the subscription"}


@app.delete("/v1/secure/lakes/<lake_id>/watch")
def unwatch_lake(lake_id: str):
    u = user()
    w = store.get(f"WATCH#{check_id(lake_id, 'lake id')}", f"USER#{u['id']}")
    if not w:
        return {"ok": True, "status": "not watching"}
    arn = w.get("subscriptionArn", "")
    if not C.LOCAL and arn.startswith("arn:"):
        import boto3
        try:
            boto3.client("sns", region_name=C.REGION).unsubscribe(SubscriptionArn=arn)
        except Exception as ex:
            logger.info("unsubscribe failed (maybe never confirmed): %s", ex)
    store.delete(f"WATCH#{lake_id}", f"USER#{u['id']}")
    store.update("WATCHED", lake_id, adds={"count": -1})
    return {"ok": True, "status": "stopped watching"}


# ------------------------------------------------------------------------------------------ console (verifiers, officers)
def _area_param() -> str:
    a = q("area") or ""
    if a not in A.AREAS and a != "other":
        raise BadRequestError("choose an area")
    return a


@app.get("/v1/secure/console/queue")
def console_queue():
    u = user()
    area = _area_param()
    decide(u, "ViewQueue", authz.area_entity(area), area)
    kind = q("type", "evidence")
    if kind == "evidence":
        items = store.query_all(f"QUEUE#EVID#{area}", index="GSI3", cap=300)
        items = [public_evidence(i) for i in items if i.get("status") in ("new", "verified", "rejected")]
    elif kind == "waterlogging":
        items = store.query_all(f"QUEUE#WLOG#{area}", index="GSI3", cap=300)
        items = [{**waterlog.public(i), "status": i.get("status")} for i in items
                 if i.get("status") in ("live", "hidden", "verified", "rejected")]
    else:
        items = store.query_all(f"QUEUE#DOSS#{area}", index="GSI3", cap=300)
        items = [public_dossier(i, full=False) for i in items if i.get("status") not in ("drafting", "failed")]
    order = {"new": 0, "submitted": 0, "hidden": 0, "live": 1, "acknowledged": 1, "ready": 2, "verified": 3, "action_taken": 3,
             "rejected": 4, "closed": 5}
    items.sort(key=lambda i: (order.get(i.get("status"), 9), i.get("createdAt", "")))
    return {"area": area, "type": kind, "items": items}


@app.post("/v1/secure/evidence/<evidence_id>/review")
def review_evidence(evidence_id: str):
    u = user()
    e = store.get(f"EVID#{check_id(evidence_id, 'evidence id')}")
    if not e or e.get("status") in ("uploading", "blocked", "unrelated"):
        raise NotFoundError("no such evidence")
    b = body()
    decision_ = b.get("decision")
    if decision_ not in ("verified", "rejected"):
        raise BadRequestError("decision must be verified or rejected")
    note = str(b.get("note") or "").strip()[:600]
    res, stub = authz.evidence_entity(e)
    decide(u, "ReviewEvidence", res, e.get("areaId"), {"hasNote": len(note) >= 10}, [stub])
    rv = {"decision": decision_, "by": u["pseudonym"], "role": u["role"], "at": store.now_iso(), "note": note}
    entry = ledger.append(e["lakeId"], "review", evidence_id, ledger.sha256_hex(ledger.canonical(rv)), u["pseudonym"])
    store.update(f"EVID#{evidence_id}", "META", sets={"status": decision_, "review": {**rv, "ledgerSeq": entry["seq"]},
                                                      "GSI3SK": f"{decision_}#{e['createdAt']}"})
    return {"ok": True, "status": decision_}


@app.post("/v1/secure/dossiers/<dossier_id>/respond")
def respond_dossier(dossier_id: str):
    u = user()
    d = store.get(f"DOSS#{check_id(dossier_id, 'dossier id')}")
    if not d:
        raise NotFoundError("no such dossier")
    b = body()
    status = b.get("status")
    if status not in ("acknowledged", "action_taken", "rejected", "closed"):
        raise BadRequestError("status must be acknowledged, action_taken, rejected or closed")
    note = str(b.get("note") or "").strip()[:1000]
    res, stub = authz.dossier_entity(d)
    decide(u, "RespondDossier", res, d.get("areaId"), {"hasNote": len(note) >= 10}, [stub])
    resp = {"status": status, "by": u["pseudonym"], "role": u["role"], "at": store.now_iso(), "note": note}
    entry = ledger.append(d["lakeId"], "response", dossier_id, ledger.sha256_hex(ledger.canonical(resp)), u["pseudonym"])
    tl = (d.get("timeline") or []) + [{**resp, "ledgerSeq": entry["seq"]}]
    store.update(f"DOSS#{dossier_id}", "META", sets={"status": status, "timeline": tl, "GSI3SK": f"{status}#{d['createdAt']}"})
    return {"ok": True, "status": status}


@app.get("/v1/secure/console/audit")
def console_audit():
    u = user()
    area = _area_param()
    decide(u, "ViewAudit", authz.area_entity(area), area)
    items, _ = store.query(f"AUDIT#{area}", forward=False, limit=200)
    return {"area": area, "entries": [{k: i.get(k) for k in ("SK", "action", "pseudonym", "role", "resource", "allowed",
                                                              "explanation", "policies", "extra")} for i in items]}


@logger.inject_lambda_context(clear_state=True)
def handler(event, context):
    if C.ORIGIN_SECRET:   # only CloudFront knows this value; direct calls to the API address are refused
        h = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        if h.get("x-jalsmriti-origin") != C.ORIGIN_SECRET:
            return {"statusCode": 403, "headers": {"content-type": "application/json"},
                    "body": json.dumps({"message": "use the website address"})}
    return app.resolve(event, context)

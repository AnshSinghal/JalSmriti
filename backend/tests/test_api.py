"""The API end to end through the Lambda handler, as API Gateway (HTTP API, payload v2) calls it: a citizen adds a
photo, a verifier confirms it, a signed dossier is built and verified, submitted and answered by an officer."""
import base64
import hashlib
import io
import json
import time
import uuid
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from PIL import Image


def claims(sub, groups=None, juris=None):
    c = {"sub": sub, "email": f"{sub}@example.com", "email_verified": "true", "cognito:username": sub}
    if groups:
        c["cognito:groups"] = f"[{groups}]"
    if juris:
        c["custom:jurisdictions"] = juris
    return c


CITIZEN, VERIFIER, OFFICER = claims("u-citizen"), claims("u-verifier", "verifier", "bengaluru"), claims("u-officer", "officer", "bengaluru")


def call(method, path, body=None, who=None, query=None, headers=None):
    import api
    event = {
        "version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "&".join(f"{k}={v}" for k, v in (query or {}).items()),
        "headers": {"content-type": "application/json", **(headers or {})}, "queryStringParameters": query,
        "requestContext": {"http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.9", "userAgent": "pytest"},
                           "requestId": str(uuid.uuid4()), "routeKey": "$default", "stage": "$default", "timeEpoch": int(time.time() * 1000)},
        "body": json.dumps(body) if body is not None else None, "isBase64Encoded": False,
    }
    if who:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": who, "scopes": None}}
    ctx = SimpleNamespace(function_name="api", function_version="$LATEST", memory_limit_in_mb=512, aws_request_id="r",
                          invoked_function_arn="arn:aws:lambda:us-west-2:000000000000:function:api", log_group_name="g",
                          log_stream_name="s", get_remaining_time_in_millis=lambda: 29000)
    r = api.handler(event, ctx)
    data = json.loads(r["body"]) if r.get("body") else None
    if isinstance(data, dict) and isinstance(data.get("message"), str) and data["message"].startswith("{"):
        data = json.loads(data["message"])                         # 403s carry the Cedar decision
    return r["statusCode"], data


def photo(lat, lon) -> bytes:
    img = Image.new("RGB", (640, 480), (90, 120, 100))
    exif = Image.Exif()
    def dms(v):
        d = int(v); m = int((v - d) * 60); s = round(((v - d) * 60 - m) * 60, 2)
        return (float(d), float(m), float(s))
    exif[0x8825] = {1: "N", 2: dms(lat), 3: "E", 4: dms(lon)}
    exif[0x0132] = "2026:10:09 08:30:00"
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, exif=exif)
    return buf.getvalue()


def test_public_reads(aws, lake):
    assert call("GET", "/v1/health")[1]["ok"] is True
    s, areas = call("GET", "/v1/areas")
    assert s == 200 and len(areas["areas"]) == 9 and "hi" in areas["uiLanguages"]
    s, lk = call("GET", f"/v1/lakes/{lake['lakeId']}")
    assert s == 200 and lk["authorities"] and lk["laws"] and lk["area"]["id"] == "bengaluru"
    assert call("GET", "/v1/lakes/nope-0000000")[0] == 404
    assert call("POST", "/v1/places", {"lat": 51.5, "lon": -0.12})[0] == 400        # outside India and Nepal
    s, pol = call("GET", "/v1/policies")
    assert "no-self-verification" in pol["rules"]


def test_signed_in_routes_need_a_token(aws, lake):
    s, body = call("GET", "/v1/secure/me")
    assert s == 401
    s, me = call("GET", "/v1/secure/me", who=VERIFIER)
    assert me["user"]["role"] == "verifier" and me["consoleAreas"] == ["bengaluru"]


def test_photo_to_signed_dossier_to_response(aws, lake):
    import evidence_ingest
    import jobs
    from jalsmriti import ledger, storage
    lid = lake["lakeId"]

    # 1. a citizen uploads a photo taken inside the lake outline
    s, up = call("POST", f"/v1/secure/lakes/{lid}/evidence/upload", {"contentType": "image/jpeg", "size": 50_000, "note": "Debris on the bund"}, CITIZEN)
    assert s == 200 and up["upload"]["url"] == "/local-upload"
    ev = evidence_ingest.process(up["evidenceId"], photo(12.935, 77.665))
    assert ev["status"] == "new" and ev["gpsCheck"] == "inside" and len(ev["sha256"]) == 64
    assert storage.get("site", ev["thumbUrl"].lstrip("/"))[:2] == b"\xff\xd8"   # public JPEG copy exists

    # 2. Cedar: the uploader cannot verify it, a verifier can (with a note)
    s, d = call("POST", f"/v1/secure/evidence/{up['evidenceId']}/review", {"decision": "verified", "note": "Matches the site visit."}, CITIZEN)
    assert s == 403 and d["decision"]["policies"] == ["no-self-verification"]
    s, d = call("POST", f"/v1/secure/evidence/{up['evidenceId']}/review", {"decision": "verified", "note": "short"}, VERIFIER)
    assert s == 403
    s, d = call("POST", f"/v1/secure/evidence/{up['evidenceId']}/review", {"decision": "verified", "note": "Matches the site visit."}, VERIFIER)
    assert s == 200 and d["status"] == "verified"

    # 3. the citizen asks for a dossier; the jobs worker drafts, renders and signs it
    s, created = call("POST", f"/v1/secure/lakes/{lid}/dossiers", {"language": "kn"}, CITIZEN)
    assert s == 202 and created["status"] == "drafting"
    built = jobs.build_dossier(created["dossierId"])
    assert built["status"] == "ready" and built["pdfUrl"].endswith(".pdf")

    # 4. anyone can verify it: signature over the attestation, and the PDF's fingerprint
    s, v = call("GET", f"/v1/verify/{created['dossierId']}")
    assert s == 200 and v["serverCheck"] is True and v["ledger"]["ok"]
    raw = base64.b64decode(v["signature"]["raw"])
    key = serialization.load_der_public_key(base64.b64decode(v["publicKey"]["spki"]))
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.verify(der, v["attestationCanonical"].encode(), ec.ECDSA(hashes.SHA256()))
    pdf_bytes = storage.get("site", v["pdfUrl"].lstrip("/"))
    assert hashlib.sha256(pdf_bytes).hexdigest() == v["attestation"]["pdfSha256"] == json.loads(v["attestationCanonical"])["pdfSha256"]

    # 5. officers answer only once it is submitted, and only the creator records the submission
    did = created["dossierId"]
    s, d = call("POST", f"/v1/secure/dossiers/{did}/respond", {"status": "acknowledged", "note": "Received at the office."}, OFFICER)
    assert s == 403 and d["decision"]["policies"] == ["respond-only-after-submission"]
    assert call("POST", f"/v1/secure/dossiers/{did}/submitted", {"portal": "CPGRAMS", "reference": "X"}, VERIFIER)[0] == 403
    assert call("POST", f"/v1/secure/dossiers/{did}/submitted", {"portal": "CPGRAMS", "reference": "DARPG/E/2026/1"}, CITIZEN)[0] == 200
    s, d = call("POST", f"/v1/secure/dossiers/{did}/respond", {"status": "acknowledged", "note": "Site inspection next week."}, OFFICER)
    assert s == 200

    # 6. the lake's record shows every step and the chain holds
    s, led = call("GET", f"/v1/lakes/{lid}/ledger")
    assert [e["kind"] for e in led["entries"]] == ["evidence", "review", "dossier", "submitted", "response"]
    assert led["verification"]["ok"] and ledger.verify(lid)["ok"]
    s, dd = call("GET", f"/v1/dossiers/{did}")
    assert dd["status"] == "acknowledged" and [t["status"] for t in dd["timeline"]] == ["drafting", "ready", "submitted", "acknowledged"]

    # 7. the console and audit log are for officials; denials are logged too
    assert call("GET", "/v1/secure/console/queue", who=CITIZEN, query={"area": "bengaluru"})[0] == 403
    s, q = call("GET", "/v1/secure/console/queue", who=VERIFIER, query={"area": "bengaluru", "type": "evidence"})
    assert s == 200 and any(i["evidenceId"] == up["evidenceId"] for i in q["items"])
    s, audit = call("GET", "/v1/secure/console/audit", who=OFFICER, query={"area": "bengaluru"})
    actions = {(a["action"], a["allowed"]) for a in audit["entries"]}
    assert ("ReviewEvidence", False) in actions and ("RespondDossier", True) in actions


def test_watch_and_unwatch(aws, lake):
    lid = lake["lakeId"]
    assert call("POST", f"/v1/secure/lakes/{lid}/watch", who=CITIZEN)[1]["ok"]
    assert call("POST", f"/v1/secure/lakes/{lid}/watch", who=CITIZEN)[1]["status"] == "already watching"
    s, act = call("GET", "/v1/secure/me/activity", who=CITIZEN)
    assert any(w["lakeId"] == lid for w in act["watches"])
    assert call("DELETE", f"/v1/secure/lakes/{lid}/watch", who=CITIZEN)[1]["status"] == "stopped watching"


@pytest.mark.parametrize("bad", [{"contentType": "application/pdf"}, {"contentType": "image/jpeg", "size": 50 * 1024 * 1024}])
def test_upload_limits(aws, lake, bad):
    assert call("POST", f"/v1/secure/lakes/{lake['lakeId']}/evidence/upload", bad, CITIZEN)[0] == 400


def test_watch_needs_a_verified_email(aws, lake):
    unverified = {**CITIZEN, "sub": "u-unverified", "email_verified": "false"}
    s, body = call("POST", f"/v1/secure/lakes/{lake['lakeId']}/watch", who=unverified)
    assert s == 400 and "verified" in body["message"]


def test_only_cloudfront_may_call_the_api(aws, monkeypatch):
    import api
    monkeypatch.setattr(api.C, "ORIGIN_SECRET", "s3cret")
    assert call("GET", "/v1/health")[0] == 403
    assert call("GET", "/v1/health", headers={"x-jalsmriti-origin": "wrong"})[0] == 403
    assert call("GET", "/v1/health", headers={"x-jalsmriti-origin": "s3cret"})[0] == 200


def test_client_address_ignores_forged_forwarding(aws, monkeypatch):
    import api
    monkeypatch.setattr(api.C, "ORIGIN_SECRET", "s3cret")
    seen = []
    monkeypatch.setattr(api, "rate", lambda who, action: seen.append((who, action)))
    monkeypatch.setattr(api, "start_execution", lambda *a: None)
    # the caller wrote 1.2.3.4; CloudFront appended the real viewer 198.51.100.7; the API saw CloudFront's 203.0.113.9
    call("POST", "/v1/lakes/find", {"lat": 12.93, "lon": 77.66},
         headers={"x-jalsmriti-origin": "s3cret", "x-forwarded-for": "1.2.3.4, 198.51.100.7, 203.0.113.9"})
    assert ("198.51.100.7", "lake") in seen and ("site", "lake-all") in seen


def test_site_wide_daily_cap(aws, monkeypatch):
    import api
    monkeypatch.setitem(api.C.RATE_LIMIT_PER_DAY, "lake-all", 1)
    monkeypatch.setattr(api, "start_execution", lambda *a: None)
    from jalsmriti import store
    store.delete(f"RATE#site#{__import__('datetime').datetime.now(__import__('datetime').timezone.utc):%Y%m%d}", "lake-all")
    assert call("POST", "/v1/lakes/find", {"lat": 12.93, "lon": 77.66})[0] == 202
    assert call("POST", "/v1/lakes/find", {"lat": 12.94, "lon": 77.67})[0] == 429

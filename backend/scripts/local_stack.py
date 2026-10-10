"""Run the whole JalSmriti site on this computer: real satellite reads, AWS mocked, no account needed.

    python backend/scripts/local_stack.py [--port 8787] [--no-jobs]

What it serves on http://127.0.0.1:8787 :
  /v1/...          the real API handler (handlers/api.py) behind an API Gateway HTTP API (v2) event adapter
  /local-auth/...  a stand-in for the Amazon Cognito user-pool API (sign up, sign in, refresh, reset)
  /local-upload    the stand-in for the presigned S3 POST; runs the evidence pipeline on the photo
  /local-run/rain-check  POST: run the daily rain heads-up check now (EventBridge Scheduler does it daily in AWS)
  /pub/...         what CloudFront serves from the site bucket (.local/site/pub)
  everything else  the built website (web/dist) with the single-page-app fallback

DynamoDB is moto, loaded from .local/table-*.json (written by run_area_local.py) and saved back to
.local/table-zz-app.json, so evidence, dossiers and accounts survive a restart. Place checks, on-demand lake
analysis and dossiers run in background threads, the way Step Functions and SQS run them in AWS.

Demo accounts (local only), password Demo-pass-2026:
  citizen@example.com, verifier@example.com (all areas), officer@example.com (Bengaluru, Chennai, Kochi),
  admin@example.com. New sign-ups confirm with the code 123456.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import signal
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localenv import LOCAL, ROOT, create_table, dump_table, load_table, setup_env  # noqa: E402

setup_env()

from moto import mock_aws  # noqa: E402

log = logging.getLogger("local_stack")
DEMO_PASSWORD = "Demo-pass-2026"
CONFIRM_CODE = "123456"
DEMO_USERS = {
    "citizen@example.com": ([], ""),
    "verifier@example.com": (["verifier"], "*"),
    "officer@example.com": (["officer"], "bengaluru,chennai,kochi"),
    "admin@example.com": (["admin"], "*"),
}
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/geo+json", ".geojson")
mimetypes.add_type("font/woff2", ".woff2")


# ------------------------------------------------------------------------------------------ accounts and tokens
class Accounts:
    """Users in .local/users.json; ID tokens are HMAC-signed JWTs with the same claims Cognito puts in them."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.users: dict = json.loads(path.read_text()) if path.exists() else {}
        secret_file = path.with_name("local-auth-secret")
        if not secret_file.exists():
            secret_file.write_text(secrets.token_hex(32))
        self.secret = secret_file.read_text().strip().encode()
        self.refresh: dict[str, str] = {}
        for email, (groups, juris) in DEMO_USERS.items():
            if email not in self.users:
                self._create(email, DEMO_PASSWORD, confirmed=True, groups=groups, juris=juris)
        self._save()

    def _hash(self, password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()

    def _create(self, email, password, confirmed, groups=(), juris=""):
        salt = secrets.token_hex(8)
        self.users[email] = {"sub": str(uuid.uuid4()), "salt": salt, "hash": self._hash(password, salt),
                             "confirmed": confirmed, "groups": list(groups), "jurisdictions": juris}

    def _save(self):
        self.path.write_text(json.dumps(self.users, indent=1))

    @staticmethod
    def _b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    def token(self, email: str) -> str:
        u = self.users[email]
        now = int(time.time())
        claims = {"sub": u["sub"], "email": email, "email_verified": True, "cognito:username": u["sub"],
                  "iss": "jalsmriti-local", "aud": "local", "token_use": "id", "iat": now, "exp": now + 3600}
        if u["groups"]:
            claims["cognito:groups"] = u["groups"]
        if u["jurisdictions"]:
            claims["custom:jurisdictions"] = u["jurisdictions"]
        head = self._b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        body = self._b64(json.dumps(claims).encode())
        sig = self._b64(hmac.new(self.secret, f"{head}.{body}".encode(), hashlib.sha256).digest())
        return f"{head}.{body}.{sig}"

    def claims(self, token: str) -> dict | None:
        try:
            head, body, sig = token.split(".")
            good = self._b64(hmac.new(self.secret, f"{head}.{body}".encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(good, sig):
                return None
            c = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            return c if c.get("exp", 0) > time.time() else None
        except Exception:
            return None

    def call(self, target: str, b: dict) -> tuple[int, dict]:
        """The subset of the Cognito user-pool API the website uses."""
        with self.lock:
            user = (b.get("Username") or (b.get("AuthParameters") or {}).get("USERNAME") or "").strip().lower()
            if target == "SignUp":
                if user in self.users:
                    return 400, {"__type": "UsernameExistsException", "message": "An account with this email already exists. Sign in instead."}
                pw = b.get("Password", "")
                if len(pw) < 10 or pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
                    return 400, {"__type": "InvalidPasswordException", "message": "Use at least 10 characters with upper and lower case letters and a number."}
                self._create(user, pw, confirmed=False)
                self._save()
                log.info("local sign-up %s: confirm with code %s", user, CONFIRM_CODE)
                return 200, {"UserConfirmed": False, "UserSub": self.users[user]["sub"],
                             "CodeDeliveryDetails": {"Destination": user, "DeliveryMedium": "EMAIL", "AttributeName": "email"}}
            if target in ("ConfirmSignUp", "ConfirmForgotPassword"):
                if user not in self.users:
                    return 400, {"__type": "UserNotFoundException", "message": "No account with this email."}
                if b.get("ConfirmationCode") != CONFIRM_CODE:
                    return 400, {"__type": "CodeMismatchException", "message": f"That code is not right. The local stack always uses {CONFIRM_CODE}."}
                if target == "ConfirmForgotPassword":
                    salt = secrets.token_hex(8)
                    self.users[user].update(salt=salt, hash=self._hash(b.get("Password", ""), salt))
                self.users[user]["confirmed"] = True
                self._save()
                return 200, {}
            if target in ("ResendConfirmationCode", "ForgotPassword"):
                log.info("local code for %s: %s", user, CONFIRM_CODE)
                return 200, {"CodeDeliveryDetails": {"Destination": user, "DeliveryMedium": "EMAIL"}}
            if target == "InitiateAuth":
                flow = b.get("AuthFlow")
                params = b.get("AuthParameters") or {}
                if flow == "REFRESH_TOKEN_AUTH":
                    email = self.refresh.get(params.get("REFRESH_TOKEN", ""))
                    if not email:
                        return 400, {"__type": "NotAuthorizedException", "message": "Session expired. Sign in again."}
                    return 200, {"AuthenticationResult": {"IdToken": self.token(email), "ExpiresIn": 3600, "TokenType": "Bearer"}}
                u = self.users.get(user)
                if not u or self._hash(params.get("PASSWORD", ""), u["salt"]) != u["hash"]:
                    return 400, {"__type": "NotAuthorizedException", "message": "That email and password do not match."}
                if not u["confirmed"]:
                    return 400, {"__type": "UserNotConfirmedException", "message": "Confirm your email first: enter the code we sent you."}
                rt = secrets.token_urlsafe(32)
                self.refresh[rt] = user
                return 200, {"AuthenticationResult": {"IdToken": self.token(user), "RefreshToken": rt, "ExpiresIn": 3600, "TokenType": "Bearer"}}
            return 400, {"__type": "InvalidParameterException", "message": f"{target} is not supported by the local stack"}


# ------------------------------------------------------------------------------------------ background work (Step Functions / SQS stand-ins)
POOL = ThreadPoolExecutor(6, thread_name_prefix="job")
STATE = {"dirty": False}


def _background(fn, *args) -> None:
    def run():
        try:
            fn(*args)
        finally:
            STATE["dirty"] = True
    POOL.submit(run)


def _run_place(payload: dict) -> None:
    import geo_worker
    ev = {k: payload[k] for k in ("jobId", "lat", "lon")}
    try:
        with ThreadPoolExecutor(4) as ex:
            futs = {t: ex.submit(geo_worker.handler, {**ev, "task": t})
                    for t in ("place.static", "place.optical", "place.radar", "place.heat")}
            futs["place.static"].result()                      # the workflow fails without the static layers ...
            for t in ("place.optical", "place.radar", "place.heat"):   # ... but carries on without imagery, radar or heat
                try:
                    futs[t].result()
                except Exception as e:
                    log.warning("%s skipped: %s", t, e)
        geo_worker.handler({"task": "place.score", "jobId": ev["jobId"]})
    except Exception as e:
        traceback.print_exc()
        geo_worker.handler({"task": "place.failed", "jobId": ev["jobId"], "error": {"Error": type(e).__name__, "Cause": str(e)}})


def _run_lake(payload: dict) -> None:
    import geo_worker
    job = payload["jobId"]
    try:
        found = geo_worker.handler({"task": "lake.find", "jobId": job, "lat": payload["lat"], "lon": payload["lon"]})
        if found.get("done"):
            return
        ev = {"jobId": job, "lakeId": found["lakeId"]}
        with ThreadPoolExecutor(3) as ex:
            futs = {t: ex.submit(geo_worker.handler, {**ev, "task": t}) for t in ("lake.looks", "lake.static", "lake.latest")}
            futs["lake.looks"].result()
            futs["lake.static"].result()
            try:
                futs["lake.latest"].result()
            except Exception as e:
                log.warning("lake.latest skipped: %s", e)
        geo_worker.handler({"task": "lake.aggregate", **ev})
    except Exception as e:
        traceback.print_exc()
        geo_worker.handler({"task": "lake.failed", "jobId": job, "error": {"Error": type(e).__name__, "Cause": str(e)}})


def _run_job(msg: dict) -> None:
    import jobs
    r = jobs.handler({"Records": [{"messageId": "local", "body": json.dumps(msg), "attributes": {"ApproximateReceiveCount": "3"}}]})
    if r.get("batchItemFailures"):
        log.warning("job failed: %s", msg)


def _ingest(evidence_id: str, data: bytes) -> None:
    import evidence_ingest
    try:
        evidence_ingest.process(evidence_id, data)
    except Exception:
        traceback.print_exc()


def wire_background(api_module, run_jobs: bool) -> None:
    def start_execution(arn, name, payload):
        if not run_jobs:
            log.info("--no-jobs: not starting %s", name)
            return
        _background(_run_lake if str(name).startswith("lk") else _run_place, payload)

    def send_job(msg):
        if run_jobs:
            _background(_run_job, msg)

    api_module.start_execution = start_execution
    api_module.send_job = send_job


# ------------------------------------------------------------------------------------------ persistence
def snapshot(path: Path) -> None:
    """Save what the app created (accounts' evidence, dossiers, ledgers, audit, on-demand lakes, jobs)."""
    import boto3
    from jalsmriti.store import plain
    t = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"]).Table("jalsmriti")
    items, start = [], None
    while True:
        r = t.scan(**({"ExclusiveStartKey": start} if start else {}))
        items += r["Items"]
        start = r.get("LastEvaluatedKey")
        if not start:
            break
    keep = [plain(i) for i in items if not i["PK"].startswith("AREA#")
            and not (i["PK"].startswith("LAKE#") and not str(i.get("lakeId", "")).startswith("x-") and not i.get("evidenceCount"))]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(keep, ensure_ascii=False))
    tmp.replace(path)


# ------------------------------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "JalSmritiLocal/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if not str(args[0] if args else "").startswith(("GET /assets", "GET /pub")):
            log.info("%s %s", self.address_string(), fmt % args)

    # -- helpers
    def _send(self, status: int, body: bytes, ctype: str = "application/json", headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj):
        self._send(status, json.dumps(obj).encode())

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _file(self, path: Path, cache: str = "no-cache"):
        if not path.is_file():
            return self._json(404, {"message": "Not Found"})
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype, {"Cache-Control": cache})

    # -- routes
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def do_DELETE(self):
        self._route()

    def do_OPTIONS(self):
        self._send(204, b"", headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Authorization, Content-Type",
                                      "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS"})

    def _route(self):
        try:
            u = urlsplit(self.path)
            p = unquote(u.path)
            if p.startswith("/v1/"):
                return self._api(u)
            if p.startswith("/local-auth/") and self.command == "POST":
                status, out = self.server.accounts.call(p.rsplit("/", 1)[-1], json.loads(self._body() or b"{}"))
                return self._json(status, out)
            if p == "/local-upload" and self.command == "POST":
                return self._upload()
            if p == "/local-run/rain-check" and self.command == "POST":
                import alerts
                before = len(alerts.OUTBOX)
                r = alerts.rain_check()
                STATE["dirty"] = True
                return self._json(200, {**r, "emails": [{"subject": s_, "body": b_} for s_, b_, _u in alerts.OUTBOX[before:]]})
            if p == "/config.json":
                return self._json(200, {"apiBase": "", "region": os.environ["AWS_REGION"], "authMode": "local", "mapKey": None,
                                        "siteUrl": f"http://127.0.0.1:{self.server.server_port}"})
            if p.startswith("/pub/"):
                return self._file(self._safe(LOCAL / "site", p[1:]), "public, max-age=60")
            if p.startswith("/local-data/"):
                return self._file(self._safe(LOCAL / "data", p[len("/local-data/"):]))
            dist = ROOT / "web" / "dist"
            f = self._safe(dist, p.lstrip("/") or "index.html")
            if f.is_file():
                return self._file(f, "public, max-age=31536000, immutable" if "/assets/" in p else "no-cache")
            if "." in p.rsplit("/", 1)[-1]:
                return self._json(404, {"message": "Not Found"})
            return self._file(dist / "index.html")
        except BrokenPipeError:
            pass
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"message": f"local stack error: {e}"})

    @staticmethod
    def _safe(root: Path, rel: str) -> Path:
        f = (root / rel).resolve()
        if root.resolve() not in f.parents and f != root.resolve():
            return root / "__nope__"
        return f

    def _api(self, u):
        import api
        claims = None
        if u.path.startswith("/v1/secure/"):
            auth = self.headers.get("Authorization", "")
            claims = self.server.accounts.claims(auth[7:]) if auth.startswith("Bearer ") else None
            if not claims:
                return self._json(401, {"message": "Unauthorized"})
            claims = {k: (f"[{' '.join(v)}]" if isinstance(v, list) else str(v)) for k, v in claims.items()}
        raw = self._body()
        qs = dict(parse_qsl(u.query, keep_blank_values=True)) or None
        now = time.time()
        event = {
            "version": "2.0", "routeKey": "$default", "rawPath": u.path, "rawQueryString": u.query,
            "headers": {k.lower(): v for k, v in self.headers.items()}, "queryStringParameters": qs,
            "requestContext": {"accountId": "000000000000", "apiId": "local", "domainName": "127.0.0.1",
                               "http": {"method": self.command, "path": u.path, "protocol": "HTTP/1.1",
                                        "sourceIp": self.client_address[0], "userAgent": self.headers.get("User-Agent", "")},
                               "requestId": str(uuid.uuid4()), "routeKey": "$default", "stage": "$default",
                               "time": time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime(now)), "timeEpoch": int(now * 1000)},
            "body": raw.decode("utf-8") if raw else None, "isBase64Encoded": False,
        }
        if claims:
            event["requestContext"]["authorizer"] = {"jwt": {"claims": claims, "scopes": None}}
        ctx = SimpleNamespace(function_name="jalsmriti-api-local", function_version="$LATEST", memory_limit_in_mb=512,
                              aws_request_id=event["requestContext"]["requestId"], log_group_name="local", log_stream_name="local",
                              invoked_function_arn="arn:aws:lambda:local:000000000000:function:jalsmriti-api-local",
                              get_remaining_time_in_millis=lambda: 29_000)
        r = api.handler(event, ctx)
        body = r.get("body") or ""
        data = base64.b64decode(body) if r.get("isBase64Encoded") else body.encode("utf-8")
        hdrs = {k: v for k, v in (r.get("headers") or {}).items() if k.lower() not in ("content-length", "content-type")}
        ctype = (r.get("headers") or {}).get("Content-Type") or (r.get("headers") or {}).get("content-type") or "application/json"
        self._send(int(r.get("statusCode", 200)), data, ctype, hdrs)
        if self.command in ("POST", "DELETE"):
            STATE["dirty"] = True

    def _upload(self):
        raw = self._body()
        m = re.search(r'boundary="?([^";]+)"?', self.headers.get("Content-Type", ""))
        fields, data = {}, None
        for part in (raw.split(b"--" + m.group(1).encode())[1:-1] if m else []):
            head, _, body = part.partition(b"\r\n\r\n")
            body = body[:-2] if body.endswith(b"\r\n") else body
            nm = re.search(rb'name="([^"]*)"', head)
            if not nm:
                continue
            if nm.group(1) == b"file":
                data = body
            else:
                fields[nm.group(1).decode()] = body.decode("utf-8", "replace").strip()
        key = fields.get("key", "")
        if not data or not key.startswith("evidence/") or len(data) > 12 * 1024 * 1024 or len(data) < 1024:
            return self._send(400, b"<Error><Code>EntityTooSmallOrLarge</Code></Error>", "application/xml")
        from jalsmriti import storage
        storage.put_data(key, data, fields.get("Content-Type", "image/jpeg"))
        evidence_id = key.rsplit("/", 1)[-1].split(".")[0]
        _background(_ingest, evidence_id, data)
        STATE["dirty"] = True
        self._send(204, b"")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-jobs", action="store_true", help="do not run place checks, lake analysis or dossiers")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("rasterio").setLevel(logging.WARNING)
    if not (ROOT / "web" / "dist" / "index.html").exists():
        log.warning("web/dist is missing: run `npm ci && npm run build` in web/ (or use `npm run dev` on port 5173)")

    mock = mock_aws()
    mock.start()
    create_table()
    app_snap = LOCAL / "table-zz-app.json"
    total = 0
    for f in sorted(LOCAL.glob("table-*.json")):
        total += load_table(f)
    log.info("loaded %d items from %s", total, ", ".join(f.name for f in sorted(LOCAL.glob("table-*.json"))) or "nothing")

    import api
    wire_background(api, not args.no_jobs)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    srv.accounts = Accounts(LOCAL / "users.json")

    def saver():
        while True:
            time.sleep(10)
            if STATE["dirty"]:
                STATE["dirty"] = False
                try:
                    snapshot(app_snap)
                except Exception as e:
                    log.warning("snapshot failed: %s", e)
    threading.Thread(target=saver, daemon=True).start()

    def stop(*_):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)     # one stop is enough; let the final save finish
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)

    print(f"\nJalSmriti local stack on http://{args.host}:{args.port}\n"
          f"  demo accounts: {', '.join(DEMO_USERS)} (password {DEMO_PASSWORD})\n"
          f"  sign-up confirmation code: {CONFIRM_CODE}\n", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            snapshot(app_snap)
        except Exception:
            pass
        mock.stop()


if __name__ == "__main__":
    main()

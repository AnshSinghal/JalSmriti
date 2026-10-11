#!/usr/bin/env python3
"""Deploy JalSmriti to your AWS account with one command.

    python3 deploy.py

You need Python 3.9 or newer and an access key for an IAM user with the AdministratorAccess policy. Nothing else: no
Docker, Node, AWS CLI or SAM CLI. On first run the script makes its own Python environment in .build/venv with a
current boto3 (so nothing is installed into your system Python), then it

  1. checks your keys and the AWS services the app uses (Bedrock Nova, Translate, Rekognition, Location ...),
  2. builds the two Lambda layers on your computer (pip downloads Linux wheels for Python 3.12),
  3. uploads code, layers, workflows and the template to an artifacts bucket in your account,
  4. deploys one CloudFormation stack (AWS SAM template): CloudFront, S3, API Gateway, Lambda, Step Functions,
     DynamoDB, Cognito, KMS, SNS, SQS, EventBridge Scheduler, CloudWatch,
  5. uploads the website, creates demo accounts, and starts the satellite preload of the nine areas,
  6. waits for the first area (Bengaluru), runs smoke tests on the live site and prints the address and passwords.

Other commands
  python3 deploy.py --status           URLs, demo accounts and how far the preload has got
  python3 deploy.py --show-passwords   print the demo account passwords again
  python3 deploy.py --preload          start (or restart) the preload of all areas
  python3 deploy.py --web-only         re-upload only the website
  python3 deploy.py --destroy          delete everything this script created

Keys are read from the environment (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY), from a .env file next to this
script, or typed in when asked. They stay in memory: never written to disk, uploaded or logged.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import gzip
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import ssl
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 or newer is needed (you have %d.%d)." % sys.version_info[:2])

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".build" / "venv"
MIN_BOTO3 = (1, 40)


def _bootstrap() -> None:
    """Re-run this script inside .build/venv with a current boto3 (works with Homebrew, python.org and Xcode Python)."""
    py = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if Path(sys.prefix).resolve() == VENV.resolve():
        sys.exit("boto3 could not be installed into .build/venv. Delete the .build folder and run python3 deploy.py again.")
    if not py.exists():
        print("Setting up a private Python environment for the deploy (one time, about a minute) ...", flush=True)
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
        except Exception:
            sys.exit("Python could not create a virtual environment. On Debian/Ubuntu install python3-venv; on macOS "
                     "install Python from python.org or Homebrew, then run python3 deploy.py again.")
    subprocess.check_call([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade",
                           "pip", "boto3>=1.40"])
    os.execv(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]])


try:
    import boto3
    if tuple(int(x) for x in boto3.__version__.split(".")[:2]) < MIN_BOTO3:
        raise ImportError("boto3 too old")
    from botocore.config import Config
    from botocore.exceptions import ClientError, NoCredentialsError, WaiterError
except ImportError:
    _bootstrap()

BUILD = ROOT / ".build"
DEFAULT_REGION = "us-west-2"      # next to Sentinel-2 and Landsat on AWS Open Data; Amazon Nova runs here
AREAS = ["bengaluru", "chennai", "hyderabad", "delhi-ncr", "kochi", "sivasagar", "bhadrak", "kathmandu", "butwal"]
DEMO_USERS = {   # username (email) -> (group, jurisdictions)
    "citizen@example.com": (None, ""),
    "verifier@example.com": ("verifier", "*"),
    "officer@example.com": ("officer", "bengaluru,chennai,kochi"),
    "admin@example.com": ("admin", "*"),
}
BOTO = Config(retries={"max_attempts": 10, "mode": "adaptive"}, user_agent_extra="jalsmriti-deploy")
PLATFORMS = ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64", "manylinux_2_34_x86_64"]


# --------------------------------------------------------------------------------------------- output
def say(msg: str = ""):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def step(n: int, total: int, msg: str):
    say(f"\n[{n}/{total}] {msg}")


def warn(msg: str):
    say(f"  ! {msg}")


def die(msg: str, code: int = 1):
    say(f"\nStopped: {msg}")
    sys.exit(code)


# --------------------------------------------------------------------------------------------- credentials
def read_dotenv(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def make_session(args) -> "boto3.Session":
    if args.profile:
        return boto3.Session(profile_name=args.profile, region_name=args.region)
    env = {**read_dotenv(ROOT / ".env"), **{k: v for k, v in os.environ.items() if k.startswith("AWS_")}}
    key, secret, token = env.get("AWS_ACCESS_KEY_ID"), env.get("AWS_SECRET_ACCESS_KEY"), env.get("AWS_SESSION_TOKEN")
    if not key or not secret:
        say("Enter the access key of an IAM user with AdministratorAccess (the secret is not shown while you type).")
        key = input("  AWS access key ID: ").strip()
        secret = getpass.getpass("  AWS secret access key: ").strip()
        if key.startswith("ASIA") and not token:
            token = getpass.getpass("  AWS session token (temporary keys only): ").strip() or None
    if not key or not secret:
        die("an access key ID and a secret access key are needed")
    return boto3.Session(aws_access_key_id=key, aws_secret_access_key=secret, aws_session_token=token or None,
                         region_name=args.region)


def client(session, name: str, region: str | None = None):
    return session.client(name, config=BOTO, **({"region_name": region} if region else {}))


# --------------------------------------------------------------------------------------------- preflight
TINY_JPEG = base64.b64decode(  # 64x64 grey JPEG for the Rekognition check
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7"
    "Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7"
    "Ozs7Ozs7Ozv/wAARCABAAEADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUF"
    "BAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVW"
    "V1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi"
    "4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAEC"
    "AxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVm"
    "Z2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq"
    "8vP09fb3+Pn6/9oADAMBAAIRAxEAPwCaiiiuo5QooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACii"
    "igAooooAKKKKACiiigD/2Q==")


HOME_REGIONS = ("ap-southeast-2", "us-east-2", "eu-north-1", "us-east-1")
NEW_SIGNUP = ("Accounts opened with AWS's new sign-up (AWS Settings and projects) may create resources in one Region only, "
              "chosen from the contact address: ap-southeast-2 (Sydney) for India and the rest of Asia Pacific, us-east-2 "
              "for the Americas, eu-north-1 for Europe and Africa. AWS Settings > Projects > Additional info shows it.")


def blocked_by_org(ex: Exception) -> bool:
    """An AccessDenied caused by an organisation policy (SCP): no IAM permission on the user can lift it."""
    msg = ((getattr(ex, "response", None) or {}).get("Error") or {}).get("Message") or str(ex)
    return "service control policy" in msg


def lambda_settings(session, region: str):
    """Lambda's account settings in a region (a cheap regional call that SCPs apply to), or the exception."""
    try:
        return client(session, "lambda", region).get_account_settings()["AccountLimit"]
    except Exception as ex:
        return ex


def resolve_region(session, region: str, explicit: bool) -> str:
    """The Region asked for; or, when none was asked for and an organisation policy (SCP) blocks the default, the one
    Region this account may use (AWS's new sign-up gives each account exactly one)."""
    acct = lambda_settings(session, region)
    if explicit or not (isinstance(acct, Exception) and blocked_by_org(acct)):
        return region
    allowed = next((r for r in HOME_REGIONS if r != region and not isinstance(lambda_settings(session, r), Exception)), None)
    if allowed:
        say(f"This AWS account may only create resources in {allowed} (AWS's new sign-up gives each account one Region), "
            f"so JalSmriti is deployed there.")
        return allowed
    return region          # check_region explains what to do


def rebind(session, region: str, profile: str | None):
    """The same credentials (still only in memory) for another Region."""
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    c = session.get_credentials().get_frozen_credentials()
    return boto3.Session(aws_access_key_id=c.access_key, aws_secret_access_key=c.secret_key, aws_session_token=c.token,
                         region_name=region)


def nova_candidates(session, prefix: str) -> list:
    """Amazon Nova Lite model IDs to try from this Region: the Region's cross-Region profile, any other Nova Lite
    profiles Bedrock lists here (APAC, Australia, global, Nova 2), then the in-Region model IDs."""
    found, token = [], None
    try:
        bedrock = client(session, "bedrock")
        for _ in range(10):
            page = bedrock.list_inference_profiles(typeEquals="SYSTEM_DEFINED", maxResults=1000,
                                                   **({"nextToken": token} if token else {}))
            for p in page.get("inferenceProfileSummaries", []):
                pid = p.get("inferenceProfileId", "")
                if p.get("status", "ACTIVE") == "ACTIVE" and re.search(r"\.amazon\.nova-(2-)?lite-v1:0$", pid):
                    found.append(pid)
            token = page.get("nextToken")
            if not token:
                break
    except Exception:
        pass                # an older boto3 or no permission to list: the fixed candidates below still apply
    found.sort(key=lambda m: ("nova-2" in m, m.startswith("global.")))
    ids = [f"{prefix}.amazon.nova-lite-v1:0"] + found + ["amazon.nova-lite-v1:0", f"{prefix}.amazon.nova-2-lite-v1:0",
                                                         "global.amazon.nova-2-lite-v1:0", "amazon.nova-2-lite-v1:0"]
    return list(dict.fromkeys(ids))


def check_region(session, region: str):
    """Stop early, with the command to run, when an organisation policy keeps this account out of the region."""
    acct = lambda_settings(session, region)
    if not (isinstance(acct, Exception) and blocked_by_org(acct)):
        return acct
    allowed = next((r for r in HOME_REGIONS if r != region and not isinstance(lambda_settings(session, r), Exception)), None)
    if allowed:
        die(f"this AWS account may only create resources in {allowed}. An organisation policy (SCP) blocks {region}, "
            f"and no IAM permission can lift that. {NEW_SIGNUP}\n\nDeploy there instead:\n\n"
            f"  python3 deploy.py --region {allowed}\n")
    die(f"an organisation policy (SCP) blocks {region} for this AWS account, and no IAM permission can lift that. "
        f"{NEW_SIGNUP} If the account belongs to a company organisation, ask its administrator which Region is allowed, "
        "then run  python3 deploy.py --region <that Region>.")


def preflight(session, region: str) -> dict:
    try:
        ident = client(session, "sts").get_caller_identity()
    except (ClientError, NoCredentialsError) as ex:
        die(f"these AWS keys do not work ({ex})")
    say(f"  account {ident['Account']} as {ident['Arn'].split(':')[-1]} in {region}")
    acct = check_region(session, region)
    if region != DEFAULT_REGION:
        warn(f"the satellite archives are in {DEFAULT_REGION}; {region} works but imagery reads are slower")
    res = {"account": ident["Account"]}
    # Lambda concurrency decides how many scenes are processed at once
    unreserved = None if isinstance(acct, Exception) else int(acct.get("UnreservedConcurrentExecutions", 1000))
    # an area run uses maxConcurrency scene readers + 1 side chain; keep 3 for the API, photos and dossiers
    res["concurrency"] = max(1, min(20, (unreserved or 10) - 4))
    if unreserved is not None and unreserved <= 10:
        warn(f"your account allows {unreserved} Lambda runs at once (new accounts start at 10), so imagery is read "
             f"{res['concurrency']} scenes at a time. It works; it is just slower. You can ask AWS Support to raise "
             "'Concurrent executions' in Service Quotas.")
    # the AWS free plan (accounts opened since July 2025): credits and an end date
    try:
        plan = client(session, "freetier", "us-east-1").get_account_plan_state()
        if plan.get("accountPlanType") == "FREE":
            left = plan.get("accountPlanRemainingCredits") or {}
            ends = plan.get("accountPlanExpirationDate")
            say(f"  AWS free plan: {left.get('amount', '?')} {left.get('unit', 'USD')} of credits left"
                + (f", until {ends:%d %b %Y}" if hasattr(ends, "strftime") else ""))
            warn("on the free plan the account is closed when the credits or the six months run out, unless you upgrade "
                 "it in the AWS console. JalSmriti itself costs about 1-2 USD a month at demo traffic.")
    except Exception:
        pass   # older accounts, or an API this boto3 does not know: nothing to report
    # Amazon Nova on Bedrock (enabled by default since late 2025; cross-region profiles depend on the region)
    prefix = {"us": "us", "ca": "us", "eu": "eu", "ap": "apac"}.get(region.split("-")[0], "us")
    candidates = nova_candidates(session, prefix)
    res["bedrock"], last, tried = None, None, 0
    for mid in candidates:
        tried += 1
        try:
            client(session, "bedrock-runtime").converse(
                modelId=mid, messages=[{"role": "user", "content": [{"text": "Reply with OK."}]}],
                inferenceConfig={"maxTokens": 5, "temperature": 0})
            res["bedrock"] = mid
            break
        except Exception as ex:
            last = ex
    res["modelPrefix"] = prefix
    # the model that answered first, then the untried ones as run-time fallbacks
    res["models"] = ([res["bedrock"]] if res["bedrock"] else []) + candidates[tried:]
    if res["bedrock"]:
        say(f"  Amazon Bedrock: {res['bedrock']} answers")
    else:
        code = getattr(last, "response", {}).get("Error", {}).get("Code") or str(last)[:120]
        warn(f"Amazon Bedrock could not run Amazon Nova Lite here ({code}). The app deploys anyway: letters use a plain "
             "template and photo descriptions are skipped. Amazon models are enabled automatically in most regions; "
             "if your account plan blocks Bedrock, upgrading the plan enables it.")
    try:
        client(session, "translate").translate_text(Text="Lake", SourceLanguageCode="en", TargetLanguageCode="hi")
        say("  Amazon Translate: works")
        res["translate"] = True
    except ClientError as ex:
        plan = (" (on accounts opened with AWS's new sign-up, Translate comes with the Paid Plan: AWS Settings > Billing "
                "> Upgrade)") if blocked_by_org(ex) else ""
        nova = "Amazon Nova translates the letters instead, with the same number checks" if res["bedrock"] else \
            "letters stay in English until it or Bedrock works"
        warn(f"Amazon Translate is not available ({ex.response['Error']['Code']}){plan}; {nova}.")
        res["translate"] = False
    try:
        client(session, "rekognition").detect_labels(Image={"Bytes": TINY_JPEG}, MaxLabels=1)
        say("  Amazon Rekognition: works")
    except ClientError as ex:
        code = ex.response["Error"]["Code"]
        if code not in ("InvalidImageFormatException", "ImageTooLargeException", "InvalidParameterException"):
            warn(f"Amazon Rekognition failed ({code}); photo moderation and face blurring will fail until it works.")
        else:
            say("  Amazon Rekognition: reachable")
    try:
        # Kajal and Aditi list Indian English first and Hindi as an additional language
        voices = client(session, "polly").describe_voices(LanguageCode="hi-IN", IncludeAdditionalLanguageCodes=True)["Voices"]
        if any(v["Id"] == "Kajal" and "neural" in v.get("SupportedEngines", []) for v in voices):
            say("  Amazon Polly: the Kajal voice reads Hindi and Indian English")
        elif any(v["Id"] == "Aditi" for v in voices):
            say("  Amazon Polly: Kajal is not offered here, so 'Listen' uses the standard voice Aditi (Hindi and Indian English)")
        else:
            warn("Amazon Polly has no Hindi voice in this region; 'Listen' will not work here (us-west-2 has one).")
    except Exception as ex:
        warn(f"Amazon Polly is not available ({str(ex)[:120]}); 'Listen' will not work until it is.")
    try:
        client(session, "geo-places").geocode(QueryText="Bengaluru", MaxResults=1)
        say("  Amazon Location Service: works")
        res["location"] = True
    except Exception as ex:
        warn(f"Amazon Location Service is not available ({str(ex)[:120]}); search uses OpenStreetMap instead.")
        res["location"] = False
    return res


# --------------------------------------------------------------------------------------------- build
def sha_files(paths) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def layer_extras(name: str) -> list:
    """Files copied into the layer root next to python/ (backend/layers/<name>/; lib/ becomes /opt/lib on Lambda)."""
    base = ROOT / "backend" / "layers" / name
    return sorted(f for f in base.rglob("*") if f.is_file() and f.name != "README.md") if base.exists() else []


def build_layer(name: str) -> Path:
    """pip-download Linux wheels for Python 3.12 and unpack them into python/ (the Lambda layer layout)."""
    lock = ROOT / "backend" / "requirements" / f"{name}.lock.txt"
    req = lock if lock.exists() else ROOT / "backend" / "requirements" / f"{name}.txt"
    extras = layer_extras(name)
    extra_sig = sha_files(extras) if extras else ""
    tag = hashlib.sha256((req.read_text() + "|".join(PLATFORMS) + "|v5|" + extra_sig).encode()).hexdigest()[:12]
    out = BUILD / f"layer-{name}-{tag}.zip"
    if out.exists():
        say(f"  {name} layer: cached ({out.stat().st_size / 1e6:.0f} MB)")
        return out
    wheels = BUILD / f"wheels-{name}-{tag}"
    shutil.rmtree(wheels, ignore_errors=True)
    wheels.mkdir(parents=True)
    cmd = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--quiet", "--only-binary=:all:",
           "--python-version", "3.12", "--implementation", "cp", "-d", str(wheels), "-r", str(req)]
    if req.name.endswith(".lock.txt"):
        cmd.append("--no-deps")       # the lock already lists every package
    for p in PLATFORMS:
        cmd += ["--platform", p]
    say(f"  {name} layer: downloading Linux wheels with pip (one time, ~{'60' if name == 'geo' else '45'} MB) ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-6:]
        if "No module named pip" in (r.stderr or ""):
            die("pip is missing. Run:  python3 -m ensurepip --upgrade   then run this script again.")
        die("pip could not download the layer packages:\n    " + "\n    ".join(tail) +
            "\n  Check your internet connection (pypi.org must be reachable) and try again.")
    stage = BUILD / f"stage-{name}"
    shutil.rmtree(stage, ignore_errors=True)
    py = stage / "python"
    py.mkdir(parents=True)
    for whl in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(whl) as z:
            z.extractall(py)
    for data_dir in list(py.glob("*.data")):   # wheel .data folders: purelib/platlib belong at the top level
        for sub in ("purelib", "platlib"):
            d = data_dir / sub
            if d.exists():
                for item in d.iterdir():
                    shutil.move(str(item), str(py / item.name))
        shutil.rmtree(data_dir, ignore_errors=True)
    removed = 0
    for pattern in ("**/__pycache__", "**/tests", "**/testing"):
        for d in list(py.glob(pattern)):
            keep = any(part in ("numpy",) for part in d.parts) and d.name == "testing"   # numpy.testing is imported
            if d.is_dir() and not keep:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    base = ROOT / "backend" / "layers" / name
    for f in extras:      # e.g. lib/libexpat.so.1, which GDAL needs and the python3.12 runtime does not have
        dest = stage / f.relative_to(base)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    size = sum(f.stat().st_size for f in stage.rglob("*") if f.is_file())
    if size > 245e6:
        die(f"the {name} layer is {size / 1e6:.0f} MB unzipped, over the Lambda limit of 250 MB")
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(stage).as_posix())
    tmp.rename(out)
    shutil.rmtree(stage, ignore_errors=True)
    say(f"  {name} layer: {size / 1e6:.0f} MB unzipped, {out.stat().st_size / 1e6:.0f} MB zipped")
    return out


def unzipped_mb(path: Path) -> float:
    with zipfile.ZipFile(path) as z:
        return sum(i.file_size for i in z.infolist()) / 1e6


def build_code() -> Path:
    src = ROOT / "backend" / "src"
    files = [p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    out = BUILD / f"code-{sha_files(files)}.zip"
    if not out.exists():
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(files):
                rel = p.relative_to(src)
                arc = rel.as_posix()
                if rel.parts[0] == "handlers":          # handler modules sit at the top of the zip
                    arc = "/".join(rel.parts[1:])
                info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, p.read_bytes())
    say(f"  function code: {out.stat().st_size / 1e6:.1f} MB")
    return out


# --------------------------------------------------------------------------------------------- artifacts
def artifact_bucket(session, project: str, account: str, region: str) -> str:
    s3 = client(session, "s3")
    name = f"{project}-artifacts-{account}-{region}"
    try:
        s3.head_bucket(Bucket=name)
        return name
    except ClientError:
        pass
    kw = {"Bucket": name}
    if region != "us-east-1":
        kw["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**kw)
    s3.put_public_access_block(Bucket=name, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    say(f"  created {name}")
    return name


def upload(session, bucket: str, key: str, path: Path | None = None, data: bytes | None = None) -> str:
    s3 = client(session, "s3")
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return key
    except ClientError:
        pass
    if path is not None:
        s3.upload_file(str(path), bucket, key)
    else:
        s3.put_object(Bucket=bucket, Key=key, Body=data)
    return key


def pack_template(session, bucket: str, region: str) -> str:
    """Upload the workflow definitions and point the template at them (what `sam package` would do)."""
    text = (ROOT / "infra" / "template.yaml").read_text(encoding="utf-8")

    def repl(m):
        p = ROOT / "infra" / "statemachines" / f"{m.group(1)}.asl.json"
        data = p.read_bytes()
        json.loads(data)  # must be valid JSON
        key = f"statemachines/{m.group(1)}-{hashlib.sha256(data).hexdigest()[:12]}.json"
        upload(session, bucket, key, data=data)
        return f"DefinitionUri: {{Bucket: {bucket}, Key: {key}}}"

    packed = re.sub(r"DefinitionUri: statemachines/([a-z]+)\.asl\.json", repl, text)
    key = f"templates/template-{hashlib.sha256(packed.encode()).hexdigest()[:12]}.yaml"
    upload(session, bucket, key, data=packed.encode())
    host = "s3.amazonaws.com" if region == "us-east-1" else f"s3.{region}.amazonaws.com"
    return f"https://{bucket}.{host}/{key}"


# --------------------------------------------------------------------------------------------- CloudFormation
def stack_status(cfn, name: str) -> str | None:
    try:
        return cfn.describe_stacks(StackName=name)["Stacks"][0]["StackStatus"]
    except ClientError as ex:
        if "does not exist" in str(ex):
            return None
        raise


def stack_params(cfn, name: str) -> dict:
    try:
        s = cfn.describe_stacks(StackName=name)["Stacks"][0]
    except ClientError:
        return {}
    return {p["ParameterKey"]: p.get("ParameterValue") for p in s.get("Parameters", [])}


def last_failure_was_cloudfront(cfn, name: str) -> bool:
    """Did the stack's last create or update roll back because AWS has not verified the account for CloudFront?"""
    if stack_status(cfn, name) not in ("ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "CREATE_FAILED"):
        return False
    try:
        events = cfn.describe_stack_events(StackName=name)["StackEvents"][:200]
    except ClientError:
        return False
    return any(CLOUDFRONT_UNVERIFIED in (e.get("ResourceStatusReason") or "") for e in events)


def stack_outputs(cfn, name: str) -> dict:
    try:
        s = cfn.describe_stacks(StackName=name)["Stacks"][0]
    except ClientError:
        return {}
    return {o["OutputKey"]: o["OutputValue"] for o in s.get("Outputs", [])}


KNOWN = [
    ("must be verified before you can add new CloudFront", "New AWS accounts must be verified before they can create "
     "CloudFront distributions. Open a case in the AWS Support Center (Account and billing > Account verification), wait "
     "for the reply, then run python3 deploy.py again."),
    ("Your account is not authorized to perform this operation", "This AWS account plan blocks one of the services. On "
     "the free plan, check the AWS Free Tier page for the list of available services, or upgrade the plan."),
    ("ConcurrentExecutions", "Lambda concurrency is too low for a setting in the template. Ask AWS Support to raise it."),
    ("MemorySize", "This account allows less Lambda memory than the template asks for (new accounts are capped at "
     "3008 MB). Ask AWS Support to raise the Lambda memory quota, or lower MemorySize in infra/template.yaml."),
    ("service control policy", "An organisation policy (SCP) blocks this, and no IAM permission can lift it. " + NEW_SIGNUP
     + " Run python3 deploy.py --region <that Region>."),
]


def follow_stack(cfn, name: str, since: datetime) -> str:
    seen, last_note = set(), 0.0
    while True:
        st = stack_status(cfn, name)
        try:
            events = cfn.describe_stack_events(StackName=name)["StackEvents"]
        except ClientError:
            events = []
        for e in reversed(events):
            if e["Timestamp"] < since or e["EventId"] in seen:
                continue
            seen.add(e["EventId"])
            s = e["ResourceStatus"]
            if s.endswith("_COMPLETE") or s.endswith("FAILED"):
                reason = f"  ({e.get('ResourceStatusReason')})" if "FAILED" in s and e.get("ResourceStatusReason") else ""
                say(f"    {e['LogicalResourceId']:<28} {s.lower().replace('_', ' ')}{reason}")
        if st is None:            # the stack was deleted while we watched
            return "DELETED"
        if not st.endswith("IN_PROGRESS"):
            return st
        if time.time() - last_note > 300:
            last_note = time.time()
            if any(e.get("ResourceType") == "AWS::CloudFront::Distribution" and e["ResourceStatus"] == "CREATE_IN_PROGRESS"
                   for e in events):
                say("    (the CloudFront distribution usually takes 5-15 minutes)")
        time.sleep(10)


def deploy_stack(session, name: str, template_url: str, params: dict) -> dict:
    cfn = client(session, "cloudformation")
    p = [{"ParameterKey": k, "ParameterValue": str(v)} for k, v in params.items()]
    caps = ["CAPABILITY_IAM", "CAPABILITY_AUTO_EXPAND"]
    status = stack_status(cfn, name)
    if status and status.endswith("IN_PROGRESS"):
        say(f"  {name} is busy ({status.lower().replace('_', ' ')}); waiting for it ...")
        follow_stack(cfn, name, datetime.now(timezone.utc))
        status = stack_status(cfn, name)
    if status in ("ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "DELETE_FAILED", "CREATE_FAILED"):
        say(f"  removing {name} left over from a failed first deploy ...")
        cfn.delete_stack(StackName=name)
        try:
            cfn.get_waiter("stack_delete_complete").wait(StackName=name, WaiterConfig={"Delay": 15, "MaxAttempts": 240})
        except WaiterError as ex:
            die(f"the old stack could not be deleted ({ex}). Delete '{name}' in the CloudFormation console "
                "(choose to retain the resources it cannot delete), then run python3 deploy.py again.")
        status = None
    since = datetime.now(timezone.utc)
    try:
        if status is None:
            cfn.create_stack(StackName=name, TemplateURL=template_url, Parameters=p, Capabilities=caps,
                             OnFailure="ROLLBACK", Tags=[{"Key": "project", "Value": params["Project"]}])
            say("  creating the stack (about 15-25 minutes the first time) ...")
        else:
            cfn.update_stack(StackName=name, TemplateURL=template_url, Parameters=p, Capabilities=caps)
            say("  updating the stack ...")
    except ClientError as ex:
        if "No updates are to be performed" in str(ex):
            say("  the stack is already up to date")
            return stack_outputs(cfn, name)
        raise
    final = follow_stack(cfn, name, since)
    if final not in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
        reasons = []
        for e in cfn.describe_stack_events(StackName=name)["StackEvents"]:
            if e["Timestamp"] >= since and e["ResourceStatus"].endswith("FAILED") and e.get("ResourceStatusReason"):
                reasons.append(f"{e['LogicalResourceId']}: {e['ResourceStatusReason']}")
        raise StackFailed(final, reasons)
    return stack_outputs(cfn, name)


class StackFailed(Exception):
    def __init__(self, final: str, reasons: list):
        super().__init__(final)
        self.final, self.reasons = final, reasons

    def explain(self):
        for pat, hint in KNOWN:
            if any(pat in r for r in self.reasons):
                say(f"\n  ! {hint}")
        die(f"the stack ended in {self.final}:\n    " + "\n    ".join(self.reasons[:8] or ["see the CloudFormation console"]))


CLOUDFRONT_UNVERIFIED = "must be verified before you can add new CloudFront"


def public_site_allowed(session, account: str) -> bool:
    """Without CloudFront the site bucket needs a public-read policy: is that allowed at the account level?"""
    try:
        c = client(session, "s3control").get_public_access_block(AccountId=account)["PublicAccessBlockConfiguration"]
    except ClientError as ex:
        return ex.response.get("Error", {}).get("Code") == "NoSuchPublicAccessBlockConfiguration"
    except Exception:
        return True
    return not (c.get("BlockPublicPolicy") or c.get("RestrictPublicBuckets"))


def deploy_with_fallback(session, project: str, template_url: str, params: dict, account: str, explicit: bool) -> dict:
    """Deploy; if AWS has not yet verified this new account for CloudFront, serve the site through API Gateway."""
    try:
        return deploy_stack(session, project, template_url, params)
    except StackFailed as ex:
        unverified = any(CLOUDFRONT_UNVERIFIED in r for r in ex.reasons)
        if not (unverified and params.get("Website") == "cloudfront" and not explicit):
            ex.explain()
    say("\n  AWS has not verified this new account for CloudFront yet (that takes a Support case). The site goes live "
        "without it: API Gateway serves the website and public data from the site bucket, over HTTPS.")
    if not public_site_allowed(session, account):
        die("this account blocks public S3 bucket policies (S3 > Block Public Access settings for this account), so the "
            "site cannot be served without CloudFront either. Either clear 'Block public access ... through new public "
            "bucket or access point policies' and '... through any public bucket or access point policies' there, or open "
            "a case in the AWS Support Center (Account and billing > Account verification) to get CloudFront verified. "
            "Then run python3 deploy.py again.")
    try:
        return deploy_stack(session, project, template_url, {**params, "Website": "api"})
    except StackFailed as ex:
        ex.explain()


# --------------------------------------------------------------------------------------------- website
CTYPES = {".js": "application/javascript", ".mjs": "application/javascript", ".css": "text/css",
          ".html": "text/html; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
          ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
          ".woff2": "font/woff2", ".woff": "font/woff", ".txt": "text/plain; charset=utf-8", ".webmanifest": "application/manifest+json",
          ".xml": "application/xml", ".map": "application/json"}


def upload_web(session, out: dict, map_key: str | None, region: str) -> int:
    dist = ROOT / "web" / "dist"
    if not (dist / "index.html").exists():
        die("web/dist is missing. It ships prebuilt; if you changed the website, build it with:  cd web && npm ci && npm run build")
    s3 = client(session, "s3")
    bucket = out["SiteBucketName"]
    n = 0
    direct = not out.get("DistributionId")     # served by API Gateway, which does not compress: store scripts gzipped
    for f in sorted(dist.rglob("*")):
        if not f.is_file() or f.name == "config.json":
            continue
        key = f.relative_to(dist).as_posix()
        ctype = CTYPES.get(f.suffix.lower()) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        cache = "public, max-age=31536000, immutable" if key.startswith("assets/") else "public, max-age=60, must-revalidate"
        body, extra = f.read_bytes(), {}
        if direct and key.startswith("assets/") and f.suffix.lower() in (".js", ".mjs", ".css", ".svg", ".json"):
            body, extra = gzip.compress(body, mtime=0), {"ContentEncoding": "gzip"}
        s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=ctype, CacheControl=cache, **extra)
        n += 1
    cfg = {"apiBase": "", "region": region, "userPoolId": out["UserPoolId"], "userPoolClientId": out["UserPoolClientId"],
           "authMode": "cognito", "siteUrl": out["SiteUrl"], "mapKey": map_key, "mapRegion": region,
           "deployedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    s3.put_object(Bucket=bucket, Key="config.json", Body=json.dumps(cfg).encode(), ContentType="application/json",
                  CacheControl="no-cache")
    if direct:
        return n
    try:
        client(session, "cloudfront").create_invalidation(DistributionId=out["DistributionId"], InvalidationBatch={
            "Paths": {"Quantity": 3, "Items": ["/index.html", "/config.json", "/"]},
            "CallerReference": str(time.time())})
    except ClientError as ex:
        warn(f"CloudFront invalidation failed ({ex}); the site updates within a few minutes anyway")
    return n


def map_api_key(session, project: str, site_url: str, region: str) -> str | None:
    """An Amazon Location Service API key for the basemap, limited to map tiles and to this website."""
    loc = client(session, "location")
    name = f"{project}-maps"
    rules = {"AllowActions": ["geo-maps:GetTile", "geo-maps:GetStaticMap"],
             "AllowResources": [f"arn:aws:geo-maps:{region}::provider/default"],
             "AllowReferers": [f"{site_url}/*", f"{site_url}"]}
    try:
        key = loc.describe_key(KeyName=name)["Key"]
        try:      # the site address changes if the stack was ever recreated
            loc.update_key(KeyName=name, Restrictions=rules, NoExpiry=True, ForceUpdate=True)
        except ClientError as ex:
            warn(f"could not update the map key's allowed address ({str(ex)[:120]})")
        return key
    except ClientError:
        pass
    try:
        r = loc.create_key(KeyName=name, NoExpiry=True, Description="JalSmriti basemap (map tiles only, this site only)",
                           Restrictions=rules)
        return r["Key"]
    except Exception as ex:
        warn(f"could not create an Amazon Location map key ({str(ex)[:140]}); the site uses an open basemap instead")
        return None


# --------------------------------------------------------------------------------------------- demo accounts
def new_password() -> str:
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "O0Il1")
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(14)) + "-7"
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def provision_users(session, project: str, pool_id: str, reset: bool = False) -> dict:
    idp, ssm = client(session, "cognito-idp"), client(session, "ssm")
    param = f"/{project}/demo-users"
    try:
        stored = json.loads(ssm.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"])
    except ClientError:
        stored = {}
    out = {}
    for user, (group, juris) in DEMO_USERS.items():
        attrs = [{"Name": "email", "Value": user}, {"Name": "email_verified", "Value": "true"}]
        if juris:
            attrs.append({"Name": "custom:jurisdictions", "Value": juris})
        try:
            idp.admin_create_user(UserPoolId=pool_id, Username=user, MessageAction="SUPPRESS", UserAttributes=attrs,
                                  TemporaryPassword=new_password())
            created = True
        except idp.exceptions.UsernameExistsException:
            created = False
            idp.admin_update_user_attributes(UserPoolId=pool_id, Username=user, UserAttributes=attrs)
        pw = stored.get(user) if (stored.get(user) and not created and not reset) else new_password()
        idp.admin_set_user_password(UserPoolId=pool_id, Username=user, Password=pw, Permanent=True)
        if group:
            idp.admin_add_user_to_group(UserPoolId=pool_id, Username=user, GroupName=group)
        out[user] = pw
    ssm.put_parameter(Name=param, Value=json.dumps(out), Type="SecureString", Overwrite=True,
                      Description="JalSmriti demo account passwords (deploy.py)")
    return out


def stored_passwords(session, project: str) -> dict:
    try:
        return json.loads(client(session, "ssm").get_parameter(Name=f"/{project}/demo-users", WithDecryption=True)["Parameter"]["Value"])
    except ClientError:
        return {}


# --------------------------------------------------------------------------------------------- preload
def area_rows(session, table: str) -> dict:
    ddb = session.resource("dynamodb", config=BOTO)
    t = ddb.Table(table)
    out = {}
    for a in AREAS:
        it = t.get_item(Key={"PK": f"AREA#{a}", "SK": "META"}).get("Item") or {}
        out[a] = it
    return out


def start_preload(session, out: dict, conc: int, areas: list) -> str:
    sfn = client(session, "stepfunctions")
    running = sfn.list_executions(stateMachineArn=out["PreloadStateMachineArn"], statusFilter="RUNNING")["executions"]
    if running:
        say("  a preload is already running; following it")
        return running[0]["executionArn"]
    name = "preload-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    r = sfn.start_execution(stateMachineArn=out["PreloadStateMachineArn"], name=name,
                            input=json.dumps({"areas": areas, "maxConcurrency": conc}))
    return r["executionArn"]


def follow_preload(session, out: dict, until_area: str | None, max_minutes: int = 90) -> bool:
    """Print area progress; return True once `until_area` is ready (or the whole preload when None)."""
    sfn = client(session, "stepfunctions")
    last, t0 = {}, time.time()
    try:
        while True:
            rows = area_rows(session, out["TableName"])
            for a, it in rows.items():
                line = f"{it.get('status', 'waiting')}" + (f" - {it.get('stage')}" if it.get("stage") and it.get("status") == "running" else "")
                if it.get("status") == "ready" and it.get("stats"):
                    s = it["stats"]
                    line = f"ready: {s.get('lakes')} water bodies, {s.get('lostHa')} ha of water lost since 1984"
                if last.get(a) != line and (it or a == until_area):
                    say(f"  {int(time.time() - t0) // 60:>3} min  {a:<10} {line}")
                    last[a] = line
            if until_area and rows.get(until_area, {}).get("status") == "ready":
                return True
            if until_area and rows.get(until_area, {}).get("status") == "failed":
                warn(f"{until_area} failed: {rows[until_area].get('error', '')[:300]}")
                return False
            ex = sfn.list_executions(stateMachineArn=out["PreloadStateMachineArn"], maxResults=1)["executions"]
            if not until_area and ex and ex[0]["status"] != "RUNNING":
                return ex[0]["status"] == "SUCCEEDED"
            if time.time() - t0 > max_minutes * 60:
                warn("still running; it continues in AWS. Check with:  python3 deploy.py --status")
                return False
            time.sleep(30)
    except KeyboardInterrupt:
        say("\n  Stopped watching. The preload keeps running in AWS; check it with:  python3 deploy.py --status")
        return False


def _invoke(lam, function: str, payload: dict) -> dict:
    r = lam.invoke(FunctionName=function, Payload=json.dumps(payload).encode())
    body = json.loads(r["Payload"].read() or b"{}")
    if r.get("FunctionError") or (isinstance(body, dict) and body.get("errorMessage")):
        raise RuntimeError((body or {}).get("errorMessage") or r.get("FunctionError"))
    return body


def maintain(session, out: dict) -> dict:
    """After an update, bring data made by older code up to today's rules, without reading imagery again:
    water bodies without a name of their own are named after what is near them, and photos still awaiting review
    get today's photo checks (one that is not a photo of the lake is withdrawn on the lake's record)."""
    from botocore.config import Config
    lam = session.client("lambda", config=Config(read_timeout=900, connect_timeout=10, retries={"max_attempts": 1}))
    renamed, done = 0, []
    for a, it in area_rows(session, out["TableName"]).items():
        if it.get("status") != "ready":
            continue
        try:
            r = _invoke(lam, out["GeoFunctionName"], {"task": "area.rename", "areaId": a})
        except Exception as ex:
            warn(f"naming the water bodies of {a} failed ({str(ex)[:160]}); run  python3 deploy.py --maintain  again")
            continue
        renamed += r.get("renamed", 0)
        done.append(a)
    if done:
        say(f"  water bodies with no name of their own named after what is near them: {renamed} renamed in "
            f"{len(done)} areas")
    res = {"renamed": renamed, "areas": done, "withdrawn": []}
    try:
        r = _invoke(lam, out["EvidenceFunctionName"], {"maintenance": "recheck-evidence"})
    except Exception as ex:
        warn(f"the photo re-check failed ({str(ex)[:160]}); run  python3 deploy.py --maintain  again")
        return res
    res["withdrawn"] = r.get("withdrawn") or []
    say(f"  photo re-check: {r.get('checked', 0)} photos awaiting review checked, {len(res['withdrawn'])} withdrawn "
        "as not photos of the lake")
    if res["withdrawn"] and out.get("DistributionId"):
        try:
            client(session, "cloudfront").create_invalidation(DistributionId=out["DistributionId"], InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": ["/pub/evidence/*"]}, "CallerReference": f"recheck-{time.time()}"})
        except ClientError as ex:
            warn(f"CloudFront invalidation failed ({ex}); withdrawn photos may show from the cache for a while")
    return res


# --------------------------------------------------------------------------------------------- smoke tests
def _ssl_context():
    """python.org Python on macOS has no CA certificates until 'Install Certificates' is run; boto3's bundle works."""
    try:
        from botocore.httpsession import where
        return ssl.create_default_context(cafile=where())
    except Exception:
        return ssl.create_default_context()


def http(method: str, url: str, token: str | None = None, body: dict | None = None, timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "jalsmriti-deploy"})
    if data is not None:
        req.add_header("content-type", "application/json")
    if token:
        req.add_header("authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if "json" in r.headers.get("content-type", "") else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except Exception as e:
        return 0, str(e)


def sign_in(session, out: dict, user: str, password: str) -> str:
    r = client(session, "cognito-idp").initiate_auth(ClientId=out["UserPoolClientId"], AuthFlow="USER_PASSWORD_AUTH",
                                                     AuthParameters={"USERNAME": user, "PASSWORD": password})
    return r["AuthenticationResult"]["IdToken"]


def smoke_tests(session, out: dict, passwords: dict, area_ready: bool) -> tuple:
    site = out["SiteUrl"]
    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        say(f"  {'PASS' if ok else 'FAIL'}  {name}{('  - ' + str(detail)[:160]) if detail else ''}")
        return ok

    s, b = http("GET", f"{site}/v1/health")
    via = "CloudFront" if out.get("DistributionId") else "API Gateway"
    check(f"API through {via}", s == 200 and isinstance(b, dict) and b.get("ok"), b if s != 200 else "")
    s, page = http("GET", site)
    check("website loads", s == 200 and b"<html" in (page if isinstance(page, bytes) else b"").lower())
    s, cfg = http("GET", f"{site}/config.json")
    check("website configured", s == 200 and isinstance(cfg, dict) and cfg.get("userPoolId") == out["UserPoolId"])
    tokens = {}
    for user in passwords:
        try:
            tokens[user] = sign_in(session, out, user, passwords[user])
        except ClientError as ex:
            check(f"sign in as {user}", False, ex)
    check("demo accounts sign in", len(tokens) == len(passwords))
    cit, ver = tokens.get("citizen@example.com"), tokens.get("verifier@example.com")
    if cit:
        s, b = http("GET", f"{site}/v1/secure/me", cit)
        check("Cognito token accepted by the API", s == 200 and b.get("user", {}).get("role") == "citizen", b if s != 200 else "")
        s, b = http("GET", f"{site}/v1/secure/console/queue?area=bengaluru", cit)
        check("Cedar denies the console to a citizen", s == 403, (b or {}).get("message") if isinstance(b, dict) else b)
    if ver:
        s, b = http("GET", f"{site}/v1/secure/console/queue?area=bengaluru", ver)
        check("Cedar allows the console to a verifier", s == 200, b if s != 200 else "")
    if not area_ready:
        warn("skipping the data tests: Bengaluru has not finished loading yet")
        return sum(results), len(results)
    s, b = http("GET", f"{site}/v1/areas/bengaluru/lakes")
    lakes = b.get("lakes", []) if s == 200 else []
    check("Bengaluru water bodies served", len(lakes) > 50, f"{len(lakes)} water bodies")
    named = [l for l in lakes if l.get("kind") == "lake" and l.get("grade") and "Unnamed" not in (l.get("name") or "")]
    if cit and named:
        lake = sorted(named, key=lambda l: l.get("areaHa") or 0)[0]   # a small lake, so the demo lakes stay clean
        s, b = http("POST", f"{site}/v1/secure/lakes/{lake['lakeId']}/dossiers", cit, {"language": "kn"})
        did = b.get("dossierId") if isinstance(b, dict) else None
        if check("dossier requested", s == 202 and did, b if s != 202 else lake["name"]):
            d = {}
            for _ in range(40):
                time.sleep(6)
                s, d = http("GET", f"{site}/v1/dossiers/{did}")
                if isinstance(d, dict) and d.get("status") in ("ready", "failed"):
                    break
            ok = isinstance(d, dict) and d.get("status") == "ready"
            check("letter drafted by Amazon Nova, translated, PDF rendered and signed with KMS", ok,
                  (d.get("letter") or {}).get("subject") if ok else (d.get("error") if isinstance(d, dict) else d))
            if ok:
                s, v = http("GET", f"{site}/v1/verify/{did}")
                check("signature verifies", s == 200 and v.get("serverCheck") is True)
                s, pdf = http("GET", site + d["pdfUrl"])
                check("PDF downloads", s == 200 and isinstance(pdf, bytes) and pdf[:5] == b"%PDF-", f"{len(pdf) if isinstance(pdf, bytes) else 0} bytes")
                lang_ok = bool((d.get("translation") or {}).get("body"))
                check("Kannada letter produced", lang_ok, (d.get("translation") or {}).get("engine"))
    s, b = http("POST", f"{site}/v1/places", None, {"lat": 12.9352, "lon": 77.6807, "label": "Bellandur, Bengaluru"})
    job = b.get("jobId") if isinstance(b, dict) else None
    if s == 200 and isinstance(b, dict) and b.get("status") == "done":
        check("place check (cached)", True)
    elif check("place check started", s == 202 and job, b if s != 202 else ""):
        j = {}
        for _ in range(50):
            time.sleep(6)
            s, j = http("GET", f"{site}/v1/jobs/{job}")
            if isinstance(j, dict) and j.get("status") in ("done", "failed"):
                break
        ok = isinstance(j, dict) and j.get("status") == "done"
        check("place check finished (water history, terrain, frames, radar, summer heat)", ok,
              f"water memory {((j.get('result') or {}).get('memory') or {}).get('index')}/100" if ok else (j or {}).get("error") if isinstance(j, dict) else j)
    s, b = http("GET", f"{site}/v1/forecast?lat=12.9352&lon=77.6807")
    check("rain forecast for a place (Open-Meteo)", s == 200 and isinstance(b, dict) and b.get("days"), b if s != 200 else "")
    s, b = http("POST", f"{site}/v1/speech", None, {"kind": "place", "lat": 12.9352, "lon": 77.6807, "lang": "hi"})
    if check("report read aloud in Hindi (Amazon Polly)", s == 200 and isinstance(b, dict) and b.get("url"), b if s != 200 else ""):
        s, audio = http("GET", site + b["url"])
        check("narration audio downloads", s == 200 and isinstance(audio, bytes) and len(audio) > 2000,
              f"{len(audio) if isinstance(audio, bytes) else 0} bytes")
    s, b = http("POST", f"{site}/v1/places/report", None, {"lat": 12.9352, "lon": 77.6807, "lang": "kn", "persona": "home"})
    rid = b.get("reportId") if isinstance(b, dict) else None
    if check("signed place report requested", s in (200, 202) and rid, b if s not in (200, 202) else ""):
        r = b
        for _ in range(30):
            if r.get("status") in ("ready", "failed"):
                break
            time.sleep(4)
            s, r = http("GET", f"{site}/v1/reports/{rid}")
            r = r if isinstance(r, dict) else {}
        ok = r.get("status") == "ready"
        check("Kannada place report rendered and signed with KMS", ok, r.get("pdfUrl") if ok else r.get("error"))
        if ok:
            s, v = http("GET", f"{site}/v1/verify/{rid}")
            check("report signature verifies", s == 200 and v.get("serverCheck") is True)
    return sum(results), len(results)


# --------------------------------------------------------------------------------------------- destroy
def empty_bucket(session, bucket: str | None):
    if not bucket:
        return
    s3 = client(session, "s3")
    try:
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
            objs = [{"Key": o["Key"], "VersionId": o["VersionId"]} for o in page.get("Versions", []) + page.get("DeleteMarkers", [])]
            for i in range(0, len(objs), 1000):
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objs[i:i + 1000], "Quiet": True})
    except ClientError as ex:
        if "NoSuchBucket" not in str(ex):
            raise


def destroy(session, project: str, account: str, region: str, yes: bool):
    cfn = client(session, "cloudformation")
    if not yes:
        say(f"This deletes the JalSmriti website, API, data, accounts and artifacts ('{project}' in {region}).")
        if input(f"  Type {project} to confirm: ").strip() != project:
            die("not confirmed", 0)
    out = stack_outputs(cfn, project)
    sfn = client(session, "stepfunctions")
    for key in ("PreloadStateMachineArn", "AreaStateMachineArn", "PlaceStateMachineArn", "LakeStateMachineArn", "WeeklyStateMachineArn"):
        if out.get(key):
            try:
                for e in sfn.list_executions(stateMachineArn=out[key], statusFilter="RUNNING")["executions"]:
                    sfn.stop_execution(executionArn=e["executionArn"], cause="deploy.py --destroy")
            except ClientError:
                pass
    if out:
        say("  stopping running workflows and emptying buckets ...")
        time.sleep(20)
        for b in (out.get("SiteBucketName"), out.get("DataBucketName")):
            empty_bucket(session, b)
    if stack_status(cfn, project):
        say(f"  deleting stack {project} (CloudFront takes a while) ...")
        for attempt in (1, 2):
            cfn.delete_stack(StackName=project)
            try:
                cfn.get_waiter("stack_delete_complete").wait(StackName=project, WaiterConfig={"Delay": 20, "MaxAttempts": 270})
                break
            except WaiterError:
                if attempt == 2:
                    die("the stack did not delete cleanly; see the CloudFormation console")
                for b in (out.get("SiteBucketName"), out.get("DataBucketName")):
                    empty_bucket(session, b)
    art = f"{project}-artifacts-{account}-{region}"
    empty_bucket(session, art)
    try:
        client(session, "s3").delete_bucket(Bucket=art)
    except ClientError:
        pass
    for name in (f"/{project}/demo-users", f"/{project}/site-url"):
        try:
            client(session, "ssm").delete_parameter(Name=name)
        except ClientError:
            pass
    try:
        client(session, "location").delete_key(KeyName=f"{project}-maps", ForceDelete=True)
    except Exception:
        pass
    sns = client(session, "sns")      # topics the app creates: one per watched lake, one per person following places
    try:
        for page in sns.get_paginator("list_topics").paginate():
            for t in page["Topics"]:
                if t["TopicArn"].split(":")[-1].startswith((f"{project}-lake-", f"{project}-user-")):
                    sns.delete_topic(TopicArn=t["TopicArn"])
    except ClientError:
        pass
    logs = client(session, "logs")
    for prefix in (f"/aws/lambda/{project}-", "/aws/vendedlogs/states/" + project):
        try:
            for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix):
                for g in page["logGroups"]:
                    logs.delete_log_group(logGroupName=g["logGroupName"])
        except ClientError:
            pass
    say("  everything is deleted (the KMS signing key is scheduled for deletion in 7 days, as AWS requires)")


# --------------------------------------------------------------------------------------------- main
def summary(out: dict, passwords: dict | None):
    say("\nJalSmriti is live.")
    say(f"  Website   {out.get('SiteUrl')}")
    say(f"  API       {out.get('SiteUrl')}/v1/health")
    if out.get("Website") == "api":
        say("  Served by API Gateway without CloudFront, because AWS has not verified this new account for CloudFront "
            "yet. Once it has (Support Center > Account verification), run  python3 deploy.py --website cloudfront")
    if passwords:
        say("  Demo accounts (sign in with the email; keep these private; show again with --show-passwords):")
        for u, pw in passwords.items():
            role = DEMO_USERS.get(u, ("citizen", ""))[0] or "citizen"
            say(f"    {role:<9} {u:<24} {pw}")
    say("  Anyone can also sign up with their own email on the website.")


def main():
    ap = argparse.ArgumentParser(description="Deploy JalSmriti to AWS")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION)
    ap.add_argument("--project", default="jalsmriti")
    ap.add_argument("--profile", help="use a named AWS CLI profile instead of access keys")
    ap.add_argument("--destroy", action="store_true")
    ap.add_argument("--yes", action="store_true", help="no confirmation prompt for --destroy")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--show-passwords", action="store_true")
    ap.add_argument("--reset-passwords", action="store_true")
    ap.add_argument("--preload", action="store_true", help="start the preload of all areas and follow it")
    ap.add_argument("--skip-preload", action="store_true")
    ap.add_argument("--areas", help="comma-separated subset of areas to preload")
    ap.add_argument("--web-only", action="store_true")
    ap.add_argument("--no-smoke", action="store_true")
    ap.add_argument("--maintain", action="store_true",
                    help="only bring stored data up to today's rules (names of water bodies, photo checks)")
    ap.add_argument("--website", choices=["cloudfront", "api"],
                    help="cloudfront (normal) or api (no CloudFront; chosen automatically while AWS has not verified a "
                         "new account for CloudFront). Run --website cloudfront once AWS has verified the account.")
    args = ap.parse_args()
    session = make_session(args)
    explicit = any(a == "--region" or a.startswith("--region=") for a in sys.argv[1:]) or \
        bool(os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
    region = resolve_region(session, args.region, explicit)
    if region != args.region:
        args.region = region
        session = rebind(session, region, args.profile)
    project = args.project
    cfn = client(session, "cloudformation")

    if args.destroy:
        acct = client(session, "sts").get_caller_identity()["Account"]
        return destroy(session, project, acct, region, args.yes)
    if args.status or args.show_passwords:
        out = stack_outputs(cfn, project)
        if not out:
            die(f"'{project}' is not deployed in {region}")
        if args.status:
            for a, it in area_rows(session, out["TableName"]).items():
                st = it.get("stats") or {}
                extra = f"{st.get('lakes')} water bodies" if it.get("status") == "ready" else (it.get("stage") or "")
                say(f"  {a:<10} {it.get('status', 'not started'):<9} {extra}")
        summary(out, stored_passwords(session, project) if args.show_passwords else None)
        return
    if args.web_only:
        out = stack_outputs(cfn, project)
        if not out:
            die(f"'{project}' is not deployed in {region}")
        key = map_api_key(session, project, out["SiteUrl"], region)
        say(f"  uploaded {upload_web(session, out, key, region)} files")
        return
    if args.maintain:
        out = stack_outputs(cfn, project)
        if not out:
            die(f"'{project}' is not deployed in {region}")
        maintain(session, out)
        return
    if args.preload:
        out = stack_outputs(cfn, project)
        if not out:
            die(f"'{project}' is not deployed in {region}")
        conc = preflight(session, region)["concurrency"]
        start_preload(session, out, conc, (args.areas or ",".join(AREAS)).split(","))
        follow_preload(session, out, None, max_minutes=600)
        return

    total = 7
    say("JalSmriti deploy  -  water remembers")
    step(1, total, "Checking your AWS account and services")
    pf = preflight(session, region)
    step(2, total, "Building the Lambda layers and code on this computer")
    BUILD.mkdir(exist_ok=True)
    geo, app, code = build_layer("geo"), build_layer("app"), build_code()
    for layer in (geo, app):          # Lambda's 250 MB limit counts a function's layers and code together
        mb = unzipped_mb(layer) + unzipped_mb(code)
        if mb > 249:
            die(f"{layer.name} plus the function code is {mb:.0f} MB unzipped, over Lambda's 250 MB limit")
    step(3, total, "Uploading artifacts")
    bucket = artifact_bucket(session, project, pf["account"], region)
    keys = {"GeoLayerKey": upload(session, bucket, f"layers/{geo.name}", geo),
            "AppLayerKey": upload(session, bucket, f"layers/{app.name}", app),
            "CodeKey": upload(session, bucket, f"code/{code.name}", code)}
    template_url = pack_template(session, bucket, region)
    say(f"  uploaded to {bucket}")
    step(4, total, "Deploying the stack (CloudFormation + AWS SAM)")
    today = datetime.now(timezone.utc)
    season = today.year if today.month >= 6 else today.year - 1        # the monsoon season being watched
    px = pf.get("modelPrefix", "us")
    models = pf.get("models") or [f"{px}.amazon.nova-lite-v1:0", "amazon.nova-lite-v1:0"]   # the one that answered first
    params = {"Project": project, "CodeBucket": bucket, **keys, "CurrentSeason": str(season),
              "TextModelIds": ",".join(models[:5] + [f"{px}.amazon.nova-pro-v1:0"]),
              "VisionModelIds": ",".join(models[:4])}
    website, explicit_site = args.website, bool(args.website)
    if not website:
        prev = stack_params(cfn, project)
        website = prev.get("Website") or "cloudfront"
        if website == "cloudfront" and last_failure_was_cloudfront(cfn, project):
            say("  the last attempt stopped because AWS has not verified this account for CloudFront yet: serving the "
                "website through API Gateway instead")
            if not public_site_allowed(session, pf["account"]):
                warn("this account blocks public S3 bucket policies, so trying CloudFront again")
            else:
                website = "api"
    params["Website"] = website
    out = deploy_with_fallback(session, project, template_url, params, pf["account"], explicit_site)
    client(session, "ssm").put_parameter(Name=f"/{project}/site-url", Value=out["SiteUrl"], Type="String", Overwrite=True)
    step(5, total, "Website and demo accounts")
    key = map_api_key(session, project, out["SiteUrl"], region)
    say(f"  uploaded {upload_web(session, out, key, region)} website files")
    passwords = provision_users(session, project, out["UserPoolId"], reset=args.reset_passwords)
    say(f"  demo accounts ready: {', '.join(passwords)}")
    step(6, total, "Satellite preload (Bengaluru first; the other areas continue in AWS)")
    area_ready = area_rows(session, out["TableName"]).get("bengaluru", {}).get("status") == "ready"
    if args.skip_preload:
        say("  skipped (run  python3 deploy.py --preload  later)")
    elif area_ready:
        say("  areas already loaded (run  python3 deploy.py --preload  to rebuild them)")
        maintain(session, out)
    else:
        start_preload(session, out, pf["concurrency"], (args.areas or ",".join(AREAS)).split(","))
        say("  reading 40 years of Landsat and Sentinel images; Bengaluru takes about 15-25 minutes ...")
        area_ready = follow_preload(session, out, "bengaluru", max_minutes=60)
    if not args.no_smoke:
        step(7, total, "Smoke tests on the live site")
        passed, n = smoke_tests(session, out, passwords, area_ready)
        say(f"  {passed}/{n} checks passed")
    summary(out, passwords)
    if not args.skip_preload:
        say("\n  The other areas keep loading in AWS (about 15-25 minutes each). See progress:  python3 deploy.py --status")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\nCancelled. Anything already running in AWS continues; re-running python3 deploy.py is always safe.")
        sys.exit(130)
    except StackFailed as ex:
        ex.explain()
    except ClientError as ex:
        err = ex.response.get("Error", {})
        hint = (f"\n\nAn organisation policy (SCP) blocks this, and no IAM permission can lift it. {NEW_SIGNUP} Then run  "
                "python3 deploy.py --region <that Region>") if blocked_by_org(ex) else ""
        die(f"AWS said {err.get('Code')}: {err.get('Message')}{hint}")

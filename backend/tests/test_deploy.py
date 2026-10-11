"""deploy.py and the template agree: code zip layout, packed workflows, parameters and outputs, cfn-lint."""
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import boto3
import pytest
import yaml

import deploy

ROOT = Path(deploy.__file__).resolve().parent


class _CfnLoader(yaml.SafeLoader):
    """Read CloudFormation YAML, keeping intrinsic functions (!Ref, !Sub ...) as plain values."""


_CfnLoader.add_multi_constructor("!", lambda loader, suffix, node: (
    loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode)
    else loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)))


def template(text=None):
    return yaml.load(text or (ROOT / "infra" / "template.yaml").read_text(), Loader=_CfnLoader)


def test_code_zip_puts_handlers_at_the_top(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "BUILD", tmp_path)
    with zipfile.ZipFile(deploy.build_code()) as z:
        names = set(z.namelist())
    assert {"api.py", "jobs.py", "geo_worker.py", "evidence_ingest.py", "area.py"} <= names
    assert {"jalsmriti/authz.py", "jalsmriti/policies/jalsmriti.cedar", "jalsmriti/data/place_reference.json"} <= names
    assert any(n.startswith("jalsmriti/fonts/") and n.endswith(".ttf") for n in names)
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


def test_every_function_handler_exists_in_the_code():
    t = template()
    src = ROOT / "backend" / "src" / "handlers"
    for name, res in t["Resources"].items():
        if res["Type"] == "AWS::Serverless::Function":
            module, func = res["Properties"]["Handler"].rsplit(".", 1)
            text = (src / f"{module}.py").read_text()
            assert re.search(rf"^def {func}\(", text, re.M), f"{name}: {module}.{func} missing"


def test_deploy_parameters_and_outputs_match_the_template():
    t = template()
    params = set(t["Parameters"])
    assert {"Project", "CodeBucket", "GeoLayerKey", "AppLayerKey", "CodeKey", "CurrentSeason", "TextModelIds", "VisionModelIds"} <= params
    used = set(re.findall(r'out\["([A-Za-z]+)"\]', (ROOT / "deploy.py").read_text()))
    assert used <= set(t["Outputs"]), used - set(t["Outputs"])


def test_pack_template_uploads_every_workflow(aws):
    s3 = boto3.client("s3", region_name="us-west-2")
    s3.create_bucket(Bucket="artifacts-test", CreateBucketConfiguration={"LocationConstraint": "us-west-2"})
    url = deploy.pack_template(boto3.Session(region_name="us-west-2"), "artifacts-test", "us-west-2")
    key = url.split(".amazonaws.com/", 1)[1]
    packed = s3.get_object(Bucket="artifacts-test", Key=key)["Body"].read().decode()
    machines = {n: r for n, r in template(packed)["Resources"].items() if r["Type"] == "AWS::Serverless::StateMachine"}
    assert len(machines) == 5
    for name, res in machines.items():
        loc = res["Properties"]["DefinitionUri"]
        body = s3.get_object(Bucket=loc["Bucket"], Key=loc["Key"])["Body"].read()
        definition = json.loads(body)
        assert definition["StartAt"] in definition["States"], name


@pytest.mark.skipif(shutil.which("cfn-lint") is None and not Path(sys.executable).with_name("cfn-lint").exists(),
                    reason="cfn-lint not installed")
def test_template_passes_cfn_lint(tmp_path):
    text = (ROOT / "infra" / "template.yaml").read_text()
    packed = re.sub(r"DefinitionUri: statemachines/([a-z]+)\.asl\.json", r"DefinitionUri: {Bucket: b, Key: \1.json}", text)
    f = tmp_path / "template.yaml"
    f.write_text(packed)
    exe = shutil.which("cfn-lint") or str(Path(sys.executable).with_name("cfn-lint"))
    r = subprocess.run([exe, "--regions", "us-west-2", "ap-southeast-2", "us-east-2", "eu-north-1", "--", str(f)],
                       capture_output=True, text=True)
    errors = [ln for ln in r.stdout.splitlines() if re.match(r"^E\d", ln)]
    assert not errors, r.stdout


def test_dotenv_reader(tmp_path):
    f = tmp_path / ".env"
    f.write_text('# keys\nAWS_ACCESS_KEY_ID = "AKIAEXAMPLE"\nAWS_SECRET_ACCESS_KEY=\'abc=def\'\n\nNOISE\n')
    assert deploy.read_dotenv(f) == {"AWS_ACCESS_KEY_ID": "AKIAEXAMPLE", "AWS_SECRET_ACCESS_KEY": "abc=def"}


def test_web_build_is_shipped():
    dist = ROOT / "web" / "dist"
    assert (dist / "index.html").exists(), "run npm run build in web/ before packaging"
    assert any((dist / "assets").glob("index-*.js"))


def _scp_denied():
    from botocore.exceptions import ClientError
    return ClientError({"Error": {"Code": "AccessDeniedException", "Message": (
        "User: arn:aws:iam::111122223333:user/deploy is not authorized to perform: lambda:GetAccountSettings with an "
        "explicit deny in a service control policy: arn:aws:organizations::444455556666:policy/o-x/service_control_policy/p-x")}},
        "GetAccountSettings")


def test_region_lock_stops_with_the_command_for_the_allowed_region(monkeypatch, capsys):
    """AWS's new sign-up allows one Region per account; an SCP denies the rest. deploy.py finds it and says so."""
    monkeypatch.setattr(deploy, "lambda_settings",
                        lambda session, region: {"UnreservedConcurrentExecutions": 10} if region == "ap-southeast-2" else _scp_denied())
    with pytest.raises(SystemExit):
        deploy.check_region(None, "us-west-2")
    out = capsys.readouterr().out
    assert "python3 deploy.py --region ap-southeast-2" in out and "no IAM permission" in out


def test_region_check_passes_through_when_the_region_is_allowed(monkeypatch):
    monkeypatch.setattr(deploy, "lambda_settings", lambda session, region: {"UnreservedConcurrentExecutions": 1000})
    assert deploy.check_region(None, "us-west-2") == {"UnreservedConcurrentExecutions": 1000}


def test_only_scp_denials_count_as_organisation_blocks():
    from botocore.exceptions import ClientError
    plain = ClientError({"Error": {"Code": "AccessDeniedException",
                                   "Message": "User is not authorized to perform: lambda:GetAccountSettings"}}, "GetAccountSettings")
    assert deploy.blocked_by_org(_scp_denied()) and not deploy.blocked_by_org(plain)


def test_without_a_region_flag_the_accounts_only_region_is_used(monkeypatch, capsys):
    monkeypatch.setattr(deploy, "lambda_settings",
                        lambda session, region: {"UnreservedConcurrentExecutions": 10} if region == "ap-southeast-2" else _scp_denied())
    assert deploy.resolve_region(None, "us-west-2", explicit=False) == "ap-southeast-2"
    assert "ap-southeast-2" in capsys.readouterr().out
    assert deploy.resolve_region(None, "us-west-2", explicit=True) == "us-west-2"     # asked for: check_region explains


def test_nova_candidates_prefer_the_regions_profile_then_listed_ones(monkeypatch):
    class Bedrock:
        def list_inference_profiles(self, **kw):
            return {"inferenceProfileSummaries": [
                {"inferenceProfileId": "global.amazon.nova-2-lite-v1:0", "status": "ACTIVE"},
                {"inferenceProfileId": "au.amazon.nova-lite-v1:0", "status": "ACTIVE"},
                {"inferenceProfileId": "apac.anthropic.claude-x", "status": "ACTIVE"}]}

    monkeypatch.setattr(deploy, "client", lambda session, name, region=None: Bedrock())
    ids = deploy.nova_candidates(None, "apac")
    assert ids[:3] == ["apac.amazon.nova-lite-v1:0", "au.amazon.nova-lite-v1:0", "global.amazon.nova-2-lite-v1:0"]
    assert "amazon.nova-lite-v1:0" in ids and len(ids) == len(set(ids)) and not any("claude" in i for i in ids)


def test_an_unverified_cloudfront_account_goes_live_through_api_gateway(monkeypatch, capsys):
    seen = []

    def fake_deploy(session, name, url, params):
        seen.append(params["Website"])
        if params["Website"] == "cloudfront":
            raise deploy.StackFailed("ROLLBACK_COMPLETE", [
                "Distribution: Resource handler returned message: \"Access denied for operation 'AWS::CloudFront::Distribution'"
                ": Your account must be verified before you can add new CloudFront resources.\""])
        return {"SiteUrl": "https://abc.execute-api.ap-southeast-2.amazonaws.com", "Website": "api"}

    monkeypatch.setattr(deploy, "deploy_stack", fake_deploy)
    monkeypatch.setattr(deploy, "public_site_allowed", lambda session, account: True)
    out = deploy.deploy_with_fallback(None, "jalsmriti", "u", {"Website": "cloudfront"}, "111122223333", explicit=False)
    assert seen == ["cloudfront", "api"] and out["Website"] == "api"
    assert "API Gateway" in capsys.readouterr().out

    seen.clear()      # asked for CloudFront explicitly: no silent switch
    with pytest.raises(SystemExit):
        deploy.deploy_with_fallback(None, "jalsmriti", "u", {"Website": "cloudfront"}, "111122223333", explicit=True)
    assert seen == ["cloudfront"]


def test_template_serves_the_site_without_cloudfront_when_asked():
    t = template()
    res = t["Resources"]
    for name in ("Distribution", "SiteOAC", "SpaRouter"):
        assert res[name].get("Condition") == "UseCdn", name
    routes = {r["Properties"]["RouteKey"] for r in res.values() if r["Type"] == "AWS::ApiGatewayV2::Route"}
    assert {"$default", "GET /assets/{proxy+}", "GET /pub/{proxy+}", "GET /config.json", "GET /favicon.svg"} <= routes
    assert all(r.get("Condition") == "NoCdn" for r in res.values() if r["Type"].startswith("AWS::ApiGatewayV2::"))
    dist = ROOT / "web" / "dist"
    root_files = {p.name for p in dist.iterdir() if p.is_file()}
    assert root_files <= {"index.html", "config.json", "favicon.svg"}, "add a route for every file at the site root"
    assert t["Outputs"]["DistributionId"].get("Condition") == "UseCdn"


def test_geo_layer_ships_the_libexpat_gdal_needs_on_python312():
    """rasterio's GDAL links the system libexpat.so.1, which the python3.12 Lambda runtime lacks: the layer brings it."""
    names = {f.relative_to(ROOT / "backend" / "layers" / "geo").as_posix() for f in deploy.layer_extras("geo")}
    assert "lib/libexpat.so.1" in names
    lib = (ROOT / "backend" / "layers" / "geo" / "lib" / "libexpat.so.1").read_bytes()
    assert lib[:4] == b"\x7fELF" and len(lib) > 100_000
    assert deploy.layer_extras("app") == []


def test_maintain_renames_ready_areas_and_rechecks_photos(monkeypatch, capsys):
    import io
    calls, invalidations = [], []

    class Lambda:
        def invoke(self, FunctionName, Payload):
            p = json.loads(Payload)
            calls.append((FunctionName, p))
            if p.get("task") == "area.rename":
                body = {"ok": True, "renamed": 120 if p["areaId"] == "bengaluru" else 7}
            else:
                body = {"checked": 3, "withdrawn": [{"evidenceId": "ev1", "lakeId": "ben-x", "reason": "text"}]}
            return {"Payload": io.BytesIO(json.dumps(body).encode())}

    class CloudFront:
        def create_invalidation(self, DistributionId, InvalidationBatch):
            invalidations.append((DistributionId, InvalidationBatch["Paths"]["Items"]))

    class Session:
        def client(self, name, config=None, **kw):
            assert name == "lambda" and config.read_timeout >= 900
            return Lambda()

    monkeypatch.setattr(deploy, "area_rows", lambda session, table: {
        "bengaluru": {"status": "ready"}, "chennai": {"status": "ready"}, "delhi": {"status": "running"}, "pune": {}})
    monkeypatch.setattr(deploy, "client", lambda session, name, region=None: CloudFront())
    out = {"TableName": "t", "GeoFunctionName": "jalsmriti-geo", "EvidenceFunctionName": "jalsmriti-evidence",
           "DistributionId": "E123"}
    res = deploy.maintain(Session(), out)
    assert [c for c in calls if c[0] == "jalsmriti-geo"] == [
        ("jalsmriti-geo", {"task": "area.rename", "areaId": "bengaluru"}),
        ("jalsmriti-geo", {"task": "area.rename", "areaId": "chennai"})]          # only areas that are ready
    assert ("jalsmriti-evidence", {"maintenance": "recheck-evidence"}) in calls
    assert res["renamed"] == 127 and len(res["withdrawn"]) == 1
    assert invalidations == [("E123", ["/pub/evidence/*"])]
    text = capsys.readouterr().out
    assert "127 renamed in 2 areas" in text and "1 withdrawn" in text

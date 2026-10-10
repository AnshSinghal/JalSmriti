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
    r = subprocess.run([exe, "--regions", "us-west-2", "--", str(f)], capture_output=True, text=True)
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

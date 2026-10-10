"""Test setup: AWS is mocked with moto, the local stand-ins for Bedrock, Translate and KMS are on, and storage goes
to a temporary folder. Nothing here touches the network or a real AWS account."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend" / "src"
LOCAL_DIR = Path(tempfile.mkdtemp(prefix="jalsmriti-test-"))

# configuration is read when the modules are imported, so set it first
os.environ.update({
    "JALSMRITI_LOCAL": "1", "JALSMRITI_LOCAL_DIR": str(LOCAL_DIR), "TABLE_NAME": "jalsmriti",
    "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-west-2", "AWS_REGION": "us-west-2", "SITE_URL": "https://example.test",
    "POWERTOOLS_SERVICE_NAME": "jalsmriti-test", "POWERTOOLS_LOG_LEVEL": "WARNING",
})
for p in (SRC, SRC / "handlers", ROOT / "backend" / "scripts", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture(scope="session")
def aws():
    """One mocked AWS for the whole session, with the app's single DynamoDB table."""
    from moto import mock_aws
    with mock_aws():
        from localenv import create_table
        create_table()
        yield


@pytest.fixture()
def lake(aws):
    """A small graded lake record (as the area pipeline writes it) with a unique id."""
    from jalsmriti import store
    lake_id = "ben-" + store.new_id()[-7:]
    ring = [[77.660, 12.930], [77.670, 12.930], [77.670, 12.940], [77.660, 12.940], [77.660, 12.930]]
    item = {
        "PK": f"LAKE#{lake_id}", "SK": "META", "lakeId": lake_id, "areaId": "bengaluru", "name": "Test Kere",
        "kind": "lake", "areaHa": 40.0, "lon": 77.665, "lat": 12.935,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "metrics": {"historicHa": 40.0, "lostHa": 12.5, "lostPct": 31.2, "builtHa": 2.5, "builtPct": 6.2,
                    "retention": {"ratio": 0.55}, "quality": {"weedPct": 41.0, "date": "2026-10-04"},
                    "storageLost": {"millionLitresLow": 125, "millionLitresHigh": 250, "olympicPoolsLow": 50, "olympicPoolsHigh": 100},
                    "grade": {"grade": "C", "score": 55, "parts": []}, "builtByYear": {"2023": 2.5},
                    "series": [{"season": 1990, "waterHa": 38.0, "source": "LS"}, {"season": 2025, "waterHa": 22.0, "source": "S2"}]},
        "findings": [], "frames": [],
    }
    store.put(item)
    return item

import json
from pathlib import Path

import pytest


@pytest.fixture
def pune_request() -> dict:
    sample = Path(__file__).resolve().parents[1] / "samples" / "pune_ingestion_request.json"
    return json.loads(sample.read_text(encoding="utf-8"))

import gzip
import json
from pathlib import Path

import pytest

from openpayer.ingest.mrf import parse_mrf

SAMPLE = {
    "reporting_entity_name": "Test Payer",
    "provider_references": [
        {"provider_group_id": 1, "provider_groups": [{"name": "Clinic A", "tin": {"type": "ein", "value": "12-3456789"}, "npi": [1111111111]}]},
        {"provider_group_id": 2, "provider_groups": [{"name": "Clinic B", "tin": {"type": "ein", "value": "98-7654321"}, "npi": [2222222222]}]},
    ],
    "in_network": [
        {
            "name": "Office visit", "billing_code_type": "CPT", "billing_code": "99213",
            "negotiated_rates": [{"negotiated_prices": [{"negotiated_type": "negotiated", "negotiated_rate": 100.0, "billing_class": "professional"}], "provider_references": [1]}],
        },
        {
            "name": "Other code", "billing_code_type": "CPT", "billing_code": "99999",
            "negotiated_rates": [{"negotiated_prices": [{"negotiated_type": "negotiated", "negotiated_rate": 999.0, "billing_class": "professional"}], "provider_references": [2]}],
        },
    ],
}


def _write(tmp_path: Path) -> Path:
    p = tmp_path / "sample.json.gz"
    with gzip.open(p, "wt") as fh:
        json.dump(SAMPLE, fh)
    return p


def test_keeps_only_allowlisted(tmp_path):
    rows = list(parse_mrf(str(_write(tmp_path)), {"99213"}, payer="Test"))
    assert len(rows) == 1
    assert rows[0]["billing_code"] == "99213"
    assert rows[0]["negotiated_rate"] == 100.0
    assert rows[0]["provider_name"] == "Clinic A"
    assert rows[0]["tin"] == "12-3456789"


def test_empty_allowlist_refuses(tmp_path):
    with pytest.raises(ValueError, match="empty code allowlist"):
        list(parse_mrf(str(_write(tmp_path)), set()))

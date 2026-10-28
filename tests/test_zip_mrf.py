import json
import zipfile

from openpayer.ingest.mrf import parse_mrf

_DOC = {
    "reporting_entity_name": "Zip Payer",
    "provider_references": [
        {
            "provider_group_id": 1,
            "provider_groups": [
                {"tin": {"type": "ein", "value": "12-3456789", "business_name": "Clinic Zip"}, "npi": [1234567893]}
            ],
        }
    ],
    "in_network": [
        {
            "billing_code": "99213",
            "billing_code_type": "CPT",
            "negotiated_rates": [
                {
                    "provider_references": [1],
                    "negotiated_prices": [
                        {"negotiated_type": "negotiated", "negotiated_rate": 88.5, "billing_class": "professional"}
                    ],
                }
            ],
        }
    ],
}


def test_parse_zip_wrapped_mrf(tmp_path):
    path = tmp_path / "rates.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("README.txt", "partner archive")
        zf.writestr("in-network-rates.json", json.dumps(_DOC))
    rows = list(parse_mrf(str(path), {"99213"}, payer="Zip"))
    assert len(rows) == 1
    assert rows[0]["negotiated_rate"] == 88.5
    assert rows[0]["provider_name"] == "Clinic Zip"

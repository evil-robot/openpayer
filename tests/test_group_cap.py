import json

from openpayer.ingest.mrf import parse_mrf


def _doc(n_groups: int) -> dict:
    return {
        "reporting_entity_name": "Big Payer",
        "provider_references": [
            {
                "provider_group_id": i + 1,
                "provider_groups": [
                    {"tin": {"type": "ein", "value": f"12-3456{i:03d}", "business_name": f"Clinic {i}"}, "npi": [1000000000 + i]}
                ],
            }
            for i in range(n_groups)
        ],
        "in_network": [
            {
                "billing_code": "99213",
                "billing_code_type": "CPT",
                "negotiated_rates": [
                    {
                        "provider_references": list(range(1, n_groups + 1)),
                        "negotiated_prices": [
                            {"negotiated_type": "negotiated", "negotiated_rate": 100.0, "billing_class": "professional"}
                        ],
                    }
                ],
            }
        ],
    }


def test_group_cap_keeps_fixed_sample(tmp_path):
    path = tmp_path / "big.json"
    path.write_text(json.dumps(_doc(10)))
    rows = list(parse_mrf(str(path), {"99213"}, payer="Big", group_cap=3, group_threshold=5))
    tins = {r["tin"] for r in rows}
    assert len(tins) == 3
    # Same sample on a second parse: the cap is by stable tax ID hash.
    rows2 = list(parse_mrf(str(path), {"99213"}, payer="Big", group_cap=3, group_threshold=5))
    assert {r["tin"] for r in rows2} == tins


def test_group_cap_off_under_threshold(tmp_path):
    path = tmp_path / "small.json"
    path.write_text(json.dumps(_doc(4)))
    rows = list(parse_mrf(str(path), {"99213"}, payer="Big", group_cap=3, group_threshold=5))
    assert len({r["tin"] for r in rows}) == 4

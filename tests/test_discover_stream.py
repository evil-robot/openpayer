import gzip
import json

from openpayer.ingest.discover import collect_toc


def _toc_doc(n_structures: int) -> dict:
    return {
        "reporting_entity_name": "Test Payer",
        "last_updated_on": "2026-10-01",
        "reporting_structure": [
            {
                "reporting_plans": [{"plan_name": f"PLAN {i}", "plan_id": f"EIN{i}"}],
                "in_network_files": [
                    {"location": f"https://example.test/rates-{i}.json.gz", "description": "In-Network Negotiated Rates Files"}
                ],
            }
            for i in range(n_structures)
        ],
    }


def test_collect_toc_streams_plain_and_counts_all(tmp_path):
    path = tmp_path / "index.json"
    path.write_text(json.dumps(_toc_doc(4)))
    kept, total, date, capped = collect_toc(str(path), limit=2)
    assert total == 4
    assert capped is False
    assert date == "2026-10-01"
    assert [k["location"] for k in kept] == [
        "https://example.test/rates-0.json.gz",
        "https://example.test/rates-1.json.gz",
    ]
    assert kept[0]["plan_name"] == "PLAN 0"


def test_collect_toc_streams_gzip(tmp_path):
    path = tmp_path / "index.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(_toc_doc(3), fh)
    kept, total, date, capped = collect_toc(str(path))
    assert total == 3
    assert len(kept) == 3
    assert date == "2026-10-01"
    assert capped is False


def test_collect_toc_count_cap_reports_floor(tmp_path):
    path = tmp_path / "index.json"
    path.write_text(json.dumps(_toc_doc(10)))
    kept, total, _date, capped = collect_toc(str(path), limit=2, count_cap=5)
    assert total == 5
    assert capped is True
    assert len(kept) == 2

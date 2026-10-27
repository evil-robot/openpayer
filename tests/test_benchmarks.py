import duckdb

from openpayer.benchmarks import rates_for_code, summary_by_code_payer
from openpayer.store import SCHEMA


def _db(tmp_path):
    db = tmp_path / "rates.duckdb"
    con = duckdb.connect(str(db))
    con.execute(SCHEMA)
    rows = [
        ("PayerA", "99213", "CPT", "negotiated", 80.0, "professional", "", "", "", "Clinic A", "ein", "11-1111111", "1111111111", "https://example.com/a.json.gz", "a.jsonl.gz"),
        ("PayerA", "99213", "CPT", "negotiated", 100.0, "professional", "", "", "", "Clinic B", "ein", "22-2222222", "2222222222", "https://example.com/a.json.gz", "a.jsonl.gz"),
        ("PayerA", "99213", "CPT", "negotiated", 120.0, "professional", "", "", "", "Clinic C", "ein", "33-3333333", "3333333333", "https://example.com/a.json.gz", "a.jsonl.gz"),
        ("PayerA", "99213", "CPT", "percentage", 150.0, "professional", "", "", "", "Clinic C", "ein", "33-3333333", "3333333333", "https://example.com/a.json.gz", "a.jsonl.gz"),
    ]
    con.executemany("INSERT INTO rates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.close()
    return db


def test_summary_excludes_non_dollar_rates(tmp_path):
    out = summary_by_code_payer(_db(tmp_path))
    assert len(out) == 1
    assert out[0]["n_rates"] == 3
    assert out[0]["median"] == 100.0
    assert out[0]["p25"] == 90.0
    assert out[0]["n_provider_groups"] == 3


def test_rates_for_code(tmp_path):
    rows = rates_for_code("99213", _db(tmp_path))
    assert [r["negotiated_rate"] for r in rows] == [80.0, 100.0, 120.0]

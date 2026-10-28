import duckdb

from openpayer import flags, reference
from openpayer.benchmarks import flags_input
from openpayer.store import SCHEMA


def rate(payer, code, rtype, amount, tin="12-3456789"):
    return {
        "payer": payer,
        "billing_code": code,
        "negotiated_type": rtype,
        "negotiated_rate": amount,
        "tin": tin,
    }


def kinds(fs):
    return {(f["kind"], f["payer"], f["billing_code"]) for f in fs}


def test_every_flag_carries_its_clearing_test():
    rows = [rate("PayerA", "99213", "negotiated", 500.0, tin=f"{i}") for i in range(5)]
    fs = flags.compute_flags(rows)
    assert fs and all(f["clears_if"] for f in fs)
    assert all(f["lever"] for f in fs)


def test_nppes_lookup_contract():
    assert reference.nppes_lookup("") is None
    assert reference.nppes_lookup("9999999999") is None
    info = reference.nppes_info()
    assert "source" in info and "npis_matched" in info


def test_medicare_reference_loaded():
    assert reference.medicare_rate("99213") == 95.19
    assert reference.medicare_rate("G2212") == 34.07
    assert reference.medicare_rate("00000") is None
    assert reference.medicare_rate("99213", locality="NY") is None
    assert round(reference.percent_of_medicare("99213", 190.38)) == 200


def test_median_far_above_medicare_flagged():
    rows = [rate("PayerA", "99213", "negotiated", 500.0, tin=f"{i}") for i in range(5)]
    rows += [rate("PayerB", "99213", "negotiated", 90.0, tin=f"{i}") for i in range(5)]
    fs = flags.compute_flags(rows)
    assert ("median_far_above_medicare", "PayerA", "99213") in kinds(fs)
    assert ("median_far_above_medicare", "PayerB", "99213") not in kinds(fs)
    hit = next(f for f in fs if f["kind"] == "median_far_above_medicare")
    assert hit["medicare_rate"] == 95.19
    assert hit["evidence"]["median_percent_of_medicare"] == 525
    assert "not a finding" in hit["note"]


def test_placeholder_rates_flagged():
    rows = [rate("PayerA", "99447", "fee schedule", 0.0, tin=f"{i}") for i in range(10)]
    rows += [rate("PayerA", "99447", "fee schedule", 30.0, tin=f"{i}") for i in range(10, 30)]
    fs = flags.compute_flags(rows)
    assert ("placeholder_rates", "PayerA", "99447") in kinds(fs)
    hit = next(f for f in fs if f["kind"] == "placeholder_rates")
    assert hit["evidence"]["n_at_or_below_1_dollar"] == 10


def test_extreme_rates_need_three():
    rows = [rate("PayerA", "99446", "negotiated", 250.0, tin=f"{i}") for i in range(2)]
    rows += [rate("PayerA", "99446", "negotiated", 20.0, tin=f"{i}") for i in range(2, 12)]
    assert ("extreme_rates", "PayerA", "99446") not in kinds(flags.compute_flags(rows))
    rows.append(rate("PayerA", "99446", "negotiated", 300.0, tin="x"))
    assert ("extreme_rates", "PayerA", "99446") in kinds(flags.compute_flags(rows))


def test_single_amount_many_groups_flagged():
    rows = [rate("PayerA", "99452", "fee schedule", 37.07, tin=f"tin-{i}") for i in range(60)]
    rows += [rate("PayerA", "99452", "fee schedule", 40.0, tin=f"tin-x{i}") for i in range(5)]
    fs = flags.compute_flags(rows)
    assert ("single_amount_many_groups", "PayerA", "99452") in kinds(fs)


def test_code_not_published_flagged():
    rows = [rate("PayerA", "G2212", "negotiated", 30.0), rate("PayerB", "G2212", "negotiated", 31.0)]
    rows += [rate("PayerC", "99213", "negotiated", 95.0)]
    fs = flags.compute_flags(rows)
    assert ("code_not_published", "PayerC", "G2212") in kinds(fs)
    assert ("code_not_published", "PayerA", "G2212") not in kinds(fs)


def test_flags_input_excludes_percentage_and_keeps_shape(tmp_path):
    db = tmp_path / "rates.duckdb"
    con = duckdb.connect(str(db))
    con.execute(SCHEMA)
    rows = [
        ("PayerA", "99213", "CPT", "negotiated", 500.0, "professional", "", "", "", "Clinic A", "ein", "11-1111111", "1111111111", "https://example.com/a.json.gz", "a.jsonl.gz"),
        ("PayerA", "99213", "CPT", "percentage", 150.0, "professional", "", "", "", "Clinic A", "ein", "11-1111111", "1111111111", "https://example.com/a.json.gz", "a.jsonl.gz"),
        ("PayerA", "99213", "CPT", "negotiated", None, "professional", "", "", "", "Clinic A", "ein", "11-1111111", "1111111111", "https://example.com/a.json.gz", "a.jsonl.gz"),
    ]
    con.executemany("INSERT INTO rates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.close()
    out = flags_input(db)
    assert len(out) == 1
    assert out[0]["tin"] == "11-1111111"
    assert out[0]["negotiated_rate"] == 500.0


def test_percentage_rows_never_flagged():
    rows = [rate("PayerA", "99213", "percentage", 99999.0, tin=f"{i}") for i in range(30)]
    assert flags.compute_flags(rows) == []

"""The homepage strip: distinct prices with counts, per-code scales.

The failure these tests guard: hundreds of identical fee-schedule
prices drawn as individual dots fused into a blob that read as a
spread of different prices, on one global scale that crushed most
rows into the left edge. The mark is now one distinct price with its
provider-group count printed, on a scale each code sets for itself.
"""
from openpayer.api import _corpus_total_line, _price_stacks, _strip_svg


def _row(v, tin, payer="TestPayer"):
    return {
        "negotiated_rate": v,
        "negotiated_type": "negotiated",
        "payer": payer,
        "provider_name": f"Clinic {tin}",
        "npi": "1234567890",
        "tin": tin,
        "source_url": "https://example.com/file.json.gz",
    }


def test_identical_prices_collapse_to_one_stack():
    rows = [_row(52.0, f"12-{i:07d}") for i in range(40)] + [_row(60.0, "98-7654321")]
    stacks = _price_stacks(rows)
    assert len(stacks) == 2
    big = next(s for s in stacks if s["v"] == 52.0)
    assert big["g"] == 40
    assert big["n"] == 40
    assert len(big["groups"]) == 40


def test_rows_without_tax_id_count_as_rates_never_as_groups():
    rows = []
    for i in range(6):
        r = _row(25.0, "")
        r["npi"] = f"12345678{i:02d}"
        rows.append(r)
    stacks = _price_stacks(rows)
    assert len(stacks) == 1
    assert stacks[0]["n"] == 6
    assert stacks[0]["g"] == 0
    assert len(stacks[0]["groups"]) == 6


def test_strip_prints_count_and_distinct_instead_of_blob():
    rows = [_row(52.0, f"12-{i:07d}") for i in range(40)] + [_row(60.0, "98-7654321")]
    svg, notes, data = _strip_svg(
        {"99213": [{"rtype": "negotiated", "rows": rows}]},
        {"99213": 75.0},
        {"99213": "CPT"},
    )
    assert "×40" in svg
    assert "2 distinct" in svg
    assert "most $52 ×40" in svg
    assert 'class="dot"' not in svg
    assert '"g": 40' in data


def test_each_code_gets_its_own_scale_and_outliers_are_named():
    cheap = [_row(10.0 + i, f"12-{i:07d}") for i in range(5)] + [_row(80.0, "98-7654321")]
    pricey = [_row(200.0 + 10 * i, f"34-{i:07d}") for i in range(5)]
    svg, notes, _ = _strip_svg(
        {
            "99213": [{"rtype": "negotiated", "rows": cheap}],
            "99449": [{"rtype": "negotiated", "rows": pricey}],
        },
        {"99213": 50.0, "99449": 300.0},
        {"99213": "CPT", "99449": "CPT"},
    )
    assert "scale $0 to $50" in svg
    assert "scale $0 to $300" in svg
    assert any("above the $50 scale" in n and "highest $80" in n for n in notes)


def test_many_distinct_prices_switch_to_counted_bins():
    rows = [_row(10.0 + i, f"12-{i:07d}") for i in range(40)]
    svg, notes, _ = _strip_svg(
        {"99213": [{"rtype": "fee schedule", "rows": rows}]},
        {"99213": 75.0},
        {"99213": "CPT"},
    )
    assert any("bars count provider groups in $5 price bins" in n for n in notes)
    assert "40 distinct" in svg


def test_future_index_date_is_named_not_clamped_to_zero():
    from datetime import date, timedelta

    from openpayer.api import _freshness

    future = (date.today() + timedelta(days=4)).isoformat()
    text, cls = _freshness(
        {
            "configured": True,
            "pulled_at": date.today().isoformat(),
            "index_last_updated_on": future,
            "index_url": "https://example.com/index.json",
        }
    )
    assert "4 days from now" in text
    assert "0 days old" not in text
    assert cls == "fresh-fresh"


def test_corpus_total_line_explains_itself():
    line = _corpus_total_line({"total_rows": 48242, "source_files": 79, "provider_groups": 2021})
    assert "48,242 single prices" in line
    assert "79 insurer files" in line
    assert "billing group is one doctor's office or clinic" in line
    assert "rate rows" not in line

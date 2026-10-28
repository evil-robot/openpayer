from openpayer import pilot


def _data():
    sample = pilot.load_sample()
    return sample, pilot.compute_flags(sample)


def test_planted_cases_fire_and_only_those():
    sample, flags = _data()
    kinds = {(f["type"], f["enrollee"]) for f in flags}
    for want in [
        ("duplicative_billing", "PT-0003"),
        ("outside_scope", "PT-0007"),
        ("rate_mismatch", "PT-0011"),
        ("cash_also_billed", "PT-0014"),
        ("ghost_enrollee", "PT-0077"),
        ("billed_after_death", "PT-0021"),
        ("stacked_prescribing", "PT-0031"),
    ]:
        assert want in kinds
    planted = {"PT-0003", "PT-0007", "PT-0011", "PT-0014", "PT-0077", "PT-0021", "PT-0031"}
    assert {f["enrollee"] for f in flags} <= planted


def test_gate_separates_ghost_and_never_scores_housing():
    sample, _ = _data()
    ghost = next(e for e in sample["enrollees"] if e["id"] == "PT-0077")
    g = pilot.gate_score(ghost, sample["claims"])
    assert g["flagged"] and g["score"] < 8
    assert "never scored" in g["note"]
    ordinary = next(e for e in sample["enrollees"] if e["id"] == "PT-0005")
    assert pilot.gate_score(ordinary, sample["claims"])["score"] >= 8


def test_ghost_traces_to_northstar_web():
    sample, flags = _data()
    trace = pilot.entity_trace(sample, flags, "E06")
    sibling_ids = {s["id"] for s in trace["siblings"]}
    assert {"E04", "E05"} <= sibling_ids
    assert trace["parent"] == "NorthStar Care Holdings LLC"
    assert trace["web_flagged_dollars"] >= 1560


def test_sample_is_synthetic_and_bannered():
    sample, _ = _data()
    assert "SYNTHETIC" in sample["note"]
    assert sample["state"] == "Minnesota"

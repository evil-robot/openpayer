"""New York and Florida state samples, and the pilot glass box.

Gerry's question was whether the Minnesota example can be made for
other states. These tests pin the contract: every state sample is
synthetic and bannered, carries its provenance (file, seed, generated
date), fires the same planted cases through the same checks, and the
glass box states every check with what would clear it.
"""
import pytest

from openpayer import pilot


def test_state_registry_lists_three_states():
    assert pilot.state_list() == [
        ("minnesota", "Minnesota"),
        ("new-york", "New York"),
        ("florida", "Florida"),
    ]


@pytest.mark.parametrize("slug,name", pilot.state_list())
def test_each_state_is_synthetic_with_provenance(slug, name):
    sample = pilot.load_sample(slug)
    assert sample["state"] == name
    assert "SYNTHETIC" in sample["note"]
    assert sample["seed"] > 0
    assert sample["generated"]
    assert sample["generator"].endswith("make_pilot_states.py")
    assert len(sample["enrollees"]) == 61
    assert len(sample["entities"]) == 10


@pytest.mark.parametrize("slug,name", pilot.state_list())
def test_each_state_fires_the_planted_cases(slug, name):
    sample = pilot.load_sample(slug)
    flags = pilot.compute_flags(sample)
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
    ghost = next(e for e in sample["enrollees"] if e["id"] == "PT-0077")
    assert pilot.gate_score(ghost, sample["claims"])["flagged"]


def test_states_do_not_share_one_dataset():
    mn = pilot.load_sample("minnesota")
    ny = pilot.load_sample("new-york")
    fl = pilot.load_sample("florida")
    assert len({len(s["claims"]) for s in (mn, ny, fl)}) == 3
    assert mn["entities"][0]["name"] != ny["entities"][0]["name"] != fl["entities"][0]["name"]


def test_unknown_state_raises():
    with pytest.raises(KeyError):
        pilot.load_sample("texas")


def test_check_guide_covers_every_flag_type():
    assert set(pilot.CHECK_GUIDE) == set(pilot.FLAG_TYPES)
    for guide in pilot.CHECK_GUIDE.values():
        assert guide["rule"] and guide["fires"] and guide["clears"]


def test_state_pages_carry_the_glass_box():
    from openpayer.api import pilot_home, pilot_onepager

    home = pilot_home("florida")
    assert "/assets/medtruth-lockup.svg" in home
    assert "Florida: one state's records" in home
    assert "What is our software, and what is the example" in home
    assert "florida.json" in home and "20261030" in home
    assert "How every flag is made" in home
    assert "What clears it" in home

    paper = pilot_onepager("new-york")
    assert "New York (sample): what the record shows before payment" in paper
    assert "It is not evidence about New York." in paper
    assert "new_york.json" in paper
    assert "The ask" in paper


def test_minnesota_pages_still_render():
    from openpayer.api import pilot_home, pilot_onepager

    assert "Minnesota: one state's records" in pilot_home("minnesota")
    assert "Minnesota (sample)" in pilot_onepager("minnesota")

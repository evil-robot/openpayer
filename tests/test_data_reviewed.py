"""'The data we reviewed' section: live counts, curated shape notes.

The section is the site's institutional memory of the corpus. These
tests pin the contract: counts come from the inventory (never typed),
a payer with no rows says so, every configured payer gets its note,
and the lessons list renders.
"""
from openpayer.api import _data_reviewed_section

_INV = {
    "by_payer": [
        {"payer": "Aetna", "rows": 38773, "files": 6, "groups": 196},
        {"payer": "TestPayer", "rows": 12, "files": 1, "groups": 4},
    ]
}
_DETAILS = [
    {"payer": "Aetna"},
    {"payer": "Humana"},
    {"payer": "TestPayer"},
]


def test_section_carries_live_counts_and_notes():
    out = _data_reviewed_section(_INV, _DETAILS)
    assert "The data we reviewed" in out
    assert "38,773 rates from 6 files, covering 196 provider groups" in out
    assert "direct list of 80 files" in out
    assert "What the files taught us" in out


def test_payer_with_no_rows_says_nothing_yet():
    out = _data_reviewed_section(_INV, _DETAILS)
    assert "In the corpus: nothing yet." in out
    assert "developer portal" in out


def test_unknown_payer_gets_counts_without_a_note():
    out = _data_reviewed_section(_INV, _DETAILS)
    assert "12 rates from 1 file, covering 4 provider groups" in out

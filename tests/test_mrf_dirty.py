import gzip
import json
from pathlib import Path

from openpayer.ingest.mrf import parse_mrf


def test_trailing_commas_and_numeric_ids(tmp_path: Path):
    # Mirrors real payer dirt: trailing commas, group name only in tin.business_name,
    # NPIs and tax IDs as bare numbers, a comma inside a text string.
    text = (
        '{"provider_references":[{"provider_group_id":7,"provider_groups":['
        '{"npi":[1033290101],"tin":{"type":"ein","value":205902190,"business_name":"DOE, JANE MD"}},]},'
        '], "in_network":[{"billing_code_type":"CPT","billing_code":"99213",'
        '"negotiated_rates":[{"negotiated_prices":[{"negotiated_type":"negotiated","negotiated_rate":42.5,'
        '"billing_class":"professional"}],"provider_references":[7]}]}]}'
    )
    p = tmp_path / "dirty.json"
    p.write_text(text)
    rows = list(parse_mrf(str(p), {"99213"}, payer="DirtyPayer"))
    assert len(rows) == 1
    assert rows[0]["negotiated_rate"] == 42.5
    assert rows[0]["provider_name"] == "DOE, JANE MD"
    assert rows[0]["tin"] == "205902190"
    assert rows[0]["npi"] == "1033290101"


def test_bare_npi_reference_is_kept(tmp_path: Path):
    # Some payers cite a 10-digit NPI directly instead of a defined provider group.
    text = (
        '{"provider_references":[], "in_network":[{"billing_code_type":"CPT","billing_code":"99213",'
        '"negotiated_rates":[{"negotiated_prices":[{"negotiated_type":"negotiated","negotiated_rate":45.0,'
        '"billing_class":"professional"}],"provider_references":[1850376175]}]}]}'
    )
    p = tmp_path / "bare.json"
    p.write_text(text)
    rows = list(parse_mrf(str(p), {"99213"}, payer="BarePayer"))
    assert len(rows) == 1
    assert rows[0]["npi"] == "1850376175"
    assert rows[0]["provider_name"] == ""

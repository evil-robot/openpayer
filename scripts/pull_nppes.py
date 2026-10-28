#!/usr/bin/env python3
"""Join NPPES (NPI registry) details for the NPIs in our corpus only.

Source: CMS NPPES Data Dissemination monthly file (public domain
federal data), https://download.cms.gov/nppes/NPI_Files.html
The full registry holds every US provider; we keep only the NPIs
that appear in pulled rates (a few thousand), so the committed
extract stays small. Kept per NPI: provider or organization name,
practice city, state, ZIP, and primary taxonomy code.

Run:
    uv run python scripts/pull_nppes.py --npis /tmp/npis.txt
Without --npis, NPIs are read from the local DuckDB store
(data/rates.duckdb). In production the same list comes out of
Lakebase with one SELECT DISTINCT; export it and pass the file.

Writes: src/openpayer/data/reference/nppes.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONTHS = [
    "October_2026", "September_2026", "August_2026", "July_2026",
    "June_2026", "May_2026", "April_2026",
]
BASE = "https://download.cms.gov/nppes/NPPES_Data_Dissemination_{}_V2.zip"

COLS = {
    "npi": "NPI",
    "entity": "Entity Type Code",
    "org": "Provider Organization Name (Legal Business Name)",
    "last": "Provider Last Name (Legal Name)",
    "first": "Provider First Name",
    "city": "Provider Business Practice Location Address City Name",
    "state": "Provider Business Practice Location Address State Name",
    "zip": "Provider Business Practice Location Address Postal Code",
    "taxonomy": "Healthcare Provider Taxonomy Code_1",
    "primary": "Healthcare Provider Primary Taxonomy Switch_1",
}


def find_url() -> str:
    for month in MONTHS:
        url = BASE.format(month)
        req = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed CMS URL)
                if resp.status == 200:
                    return url
        except Exception:
            continue
    raise SystemExit("no NPPES dissemination zip found at the expected CMS addresses")


def load_npis(args) -> set[str]:
    if args.npis:
        return {ln.strip() for ln in Path(args.npis).read_text().splitlines() if ln.strip().isdigit()}
    sys.path.insert(0, str(ROOT / "src"))
    from openpayer.store import connect

    con = connect(ROOT / "data" / "rates.duckdb")
    out: set[str] = set()
    for (v,) in con.execute("SELECT DISTINCT npi FROM rates WHERE npi <> ''").fetchall():
        for part in str(v).split(","):
            p = part.strip()
            if p.isdigit() and len(p) == 10:
                out.add(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--npis", default="", help="text file, one 10-digit NPI per line")
    ap.add_argument("--zip", default="", help="use a local dissemination zip instead of downloading")
    args = ap.parse_args()

    wanted = load_npis(args)
    print(f"NPIs wanted: {len(wanted)}")
    if args.zip:
        blob_path = Path(args.zip)
        zf = zipfile.ZipFile(blob_path)
        source_url = str(blob_path)
    else:
        url = find_url()
        print(f"downloading {url}")
        with urllib.request.urlopen(url) as resp:  # noqa: S310 (fixed CMS URL)
            blob = resp.read()
        zf = zipfile.ZipFile(io.BytesIO(blob))
        source_url = url
    member = next(n for n in zf.namelist() if n.startswith("npidata_pfile_") and n.endswith(".csv"))
    print(f"streaming {member}")

    found: dict[str, dict] = {}
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        reader = csv.reader(text)
        header = next(reader)
        idx = {key: header.index(col) for key, col in COLS.items()}
        for row in reader:
            npi = row[idx["npi"]]
            if npi not in wanted:
                continue
            if row[idx["entity"]] == "2":
                name = row[idx["org"]]
            else:
                name = f"{row[idx['first']]} {row[idx['last']]}".strip()
            found[npi] = {
                "name": name,
                "city": row[idx["city"]],
                "state": row[idx["state"]],
                "zip": row[idx["zip"]],
                "taxonomy": row[idx["taxonomy"]] if row[idx["primary"]] == "Y" else row[idx["taxonomy"]],
            }
            if len(found) == len(wanted):
                break
    payload = {
        "source": "CMS NPPES Data Dissemination monthly file (NPI registry), filtered to NPIs appearing in pulled rates",
        "source_url": source_url,
        "member_file": member,
        "npis_wanted": len(wanted),
        "npis_matched": len(found),
        "npis": found,
    }
    target = ROOT / "src" / "openpayer" / "data" / "reference" / "nppes.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"matched {len(found)} of {len(wanted)}; wrote {target} ({target.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()

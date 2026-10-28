#!/usr/bin/env python3
"""Pull the CMS Physician Fee Schedule (RVU file) for our codes only.

Source: CMS 2026 National Physician Fee Schedule Relative Value File
(RVU26A, January release, updated 12/29/2025), public domain federal
data. We keep only the configured codes from config/codes.json and
only the numbers: Work RVU, non-facility PE RVU, MP RVU, total
non-facility RVU, and the conversion factor printed in the same file.
AMA code descriptions in the file are never copied out.

National Medicare rate = total non-facility RVU x conversion factor,
which is the fee schedule amount before geographic adjustment
(every GPCI = 1.0). Locality-adjusted rates come later from the
GPCI file in the same zip if a flag ever needs them.

Run: uv run python scripts/pull_mpfs.py
Writes: src/openpayer/data/reference/mpfs.json
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RVU_URL = "https://www.cms.gov/files/zip/rvu26a.zip"
MEMBER_SUFFIX = "PPRRVU2026_Jan_nonQPP.csv"


def configured_codes() -> list[str]:
    raw = json.loads((ROOT / "config" / "codes.json").read_text())
    return [str(c["code"]).upper() for c in raw["codes"]]


def parse_rvu(csv_text: str, codes: list[str]) -> dict:
    rows = list(csv.reader(io.StringIO(csv_text)))
    header_at = next(i for i, r in enumerate(rows) if r and r[0].strip() == "HCPCS")
    data = [r for r in rows[header_at + 1 :] if len(r) > 26 and r[0].strip().upper() in codes]
    # Conversion factor column: the one column where every wanted row
    # carries the same dollar-scale value (30 to 40). Found, not assumed.
    cf_idx = None
    for idx in range(13, 32):
        vals = set()
        for r in data:
            try:
                vals.add(float(r[idx]))
            except (ValueError, IndexError):
                vals.add(None)
        vals.discard(None)
        if len(vals) == 1 and 30 < next(iter(vals)) < 40:
            cf_idx = idx
            break
    if cf_idx is None:
        raise SystemExit("conversion factor column not found; CMS changed the file layout")
    out: dict[str, dict] = {}
    cf = None
    for r in data:
        code, mod, status = r[0].strip().upper(), r[1].strip(), r[3].strip()
        if mod or status != "A":
            continue
        work, pe, mp, total = float(r[5]), float(r[6]), float(r[10]), float(r[11])
        cf = float(r[cf_idx])
        out[code] = {
            "work_rvu": work,
            "pe_rvu_nonfacility": pe,
            "mp_rvu": mp,
            "total_rvu_nonfacility": total,
            "medicare_rate_national": round(total * cf, 2),
        }
    missing = [c for c in codes if c not in out]
    if missing:
        raise SystemExit(f"codes missing or inactive in MPFS file: {missing}")
    return {"conversion_factor": cf, "codes": out}


def main() -> None:
    codes = configured_codes()
    with urllib.request.urlopen(RVU_URL) as resp:  # noqa: S310 (fixed CMS URL)
        blob = resp.read()
    zf = zipfile.ZipFile(io.BytesIO(blob))
    member = next(n for n in zf.namelist() if n.endswith(MEMBER_SUFFIX))
    parsed = parse_rvu(zf.read(member).decode("utf-8-sig", errors="replace"), codes)
    payload = {
        "source": "CMS National Physician Fee Schedule Relative Value File, 2026 January release (RVU26A, updated 12/29/2025)",
        "source_url": RVU_URL,
        "member_file": member,
        "basis": "National rate before geographic adjustment: total non-facility RVU x conversion factor from the same file (all GPCI = 1.0). Dollar figures only; no AMA code descriptions are reproduced.",
        "conversion_factor": parsed["conversion_factor"],
        "codes": parsed["codes"],
    }
    target = ROOT / "src" / "openpayer" / "data" / "reference" / "mpfs.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n")
    for code, v in payload["codes"].items():
        print(f"{code}: total RVU {v['total_rvu_nonfacility']} x {payload['conversion_factor']} = ${v['medicare_rate_national']:,.2f}")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

from __future__ import annotations

"""Reference data, wired but intentionally not downloaded until codes exist.

1. NPPES (NPI registry): free monthly file from CMS. Gives provider name,
   practice state/ZIP, and NUCC taxonomy (specialty) per NPI. Code independent,
   but we only join NPIs that appear in the filtered rates, so the join stays small.
   Source: https://download.cms.gov/nppes/NPI_Files.html

2. Medicare Physician Fee Schedule (MPFS): free from CMS. Gives the Medicare
   rate per HCPCS/CPT code and locality. We filter it to the same allowlist,
   then report each negotiated rate as a percent of Medicare.
   Source: CMS Physician Fee Schedule / RVU files.

Both loaders are stubs that fail loudly today, so nobody mistakes placeholder
numbers for benchmarks. Implement the download inside these functions when the
code list lands; the API already treats medicare_rate as optional.
"""


def nppes_lookup(npi: str) -> dict | None:
    """Return {name, city, state, zip, taxonomy} for an NPI, or None if not loaded."""
    return None


def medicare_rate(code: str, locality: str = "national") -> float | None:
    """Return the Medicare rate for a code, or None if MPFS is not loaded."""
    return None

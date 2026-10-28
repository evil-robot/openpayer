from __future__ import annotations

"""Reference data joins.

1. NPPES (NPI registry): free monthly file from CMS. Gives provider name,
   practice state/ZIP, and NUCC taxonomy (specialty) per NPI. Code independent,
   but we only join NPIs that appear in the filtered rates, so the join stays
   small. Source: https://download.cms.gov/nppes/NPI_Files.html
   Loaded: scripts/pull_nppes.py filters the monthly dissemination file
   to NPIs appearing in pulled rates and writes data/reference/nppes.json.

2. Medicare Physician Fee Schedule (MPFS): loaded. CMS publishes the
   Relative Value File (RVU26A, January 2026 release); scripts/pull_mpfs.py
   filters it to the configured codes and writes data/reference/mpfs.json
   with dollar figures only (no AMA descriptions). The rate stored is the
   national amount before geographic adjustment: total non-facility RVU
   times the conversion factor printed in the same file.
"""

import json
from functools import lru_cache
from pathlib import Path

_MPFS_PATH = Path(__file__).resolve().parents[2] / "data" / "reference" / "mpfs.json"


_NPPES_PATH = Path(__file__).resolve().parents[2] / "data" / "reference" / "nppes.json"


@lru_cache(maxsize=1)
def _nppes() -> dict:
    if not _NPPES_PATH.exists():
        return {}
    return json.loads(_NPPES_PATH.read_text())


def nppes_info() -> dict:
    """Provenance for the loaded NPPES extract: source and match counts."""
    d = _nppes()
    return {k: d.get(k) for k in ("source", "source_url", "npis_wanted", "npis_matched")}


def nppes_lookup(npi: str) -> dict | None:
    """Return {name, city, state, zip, taxonomy} for an NPI, or None if not loaded."""
    if not npi:
        return None
    row = _nppes().get("npis", {}).get(str(npi).strip())
    return dict(row) if row else None


@lru_cache(maxsize=1)
def _mpfs() -> dict:
    if not _MPFS_PATH.exists():
        return {}
    return json.loads(_MPFS_PATH.read_text())


def mpfs_info() -> dict:
    """Provenance for the loaded MPFS extract: source, basis, factor."""
    d = _mpfs()
    return {k: d.get(k) for k in ("source", "source_url", "basis", "conversion_factor")}


def medicare_rate(code: str, locality: str = "national") -> float | None:
    """Medicare national non-facility rate for a code, or None if not loaded.

    Only the national basis exists today; a locality argument other than
    "national" returns None rather than silently serving national numbers
    under a locality label.
    """
    if locality != "national":
        return None
    row = _mpfs().get("codes", {}).get(str(code).upper())
    return float(row["medicare_rate_national"]) if row else None


def percent_of_medicare(code: str, amount: float) -> float | None:
    """Amount as a percent of the Medicare national rate (100 = at Medicare)."""
    rate = medicare_rate(code)
    if not rate:
        return None
    return amount / rate * 100.0

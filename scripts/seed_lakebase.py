"""Seed Lakebase (Postgres) from the kept raw files in data/raw.

Usage:
    LAKEBASE_DSN="host=... dbname=openpayer user=... password=..." \
        uv run python scripts/seed_lakebase.py

Rebuilds the rates table contents from data/raw/*.jsonl.gz, the same
source files the DuckDB load uses, so both backends hold identical rows.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openpayer.pg_store import DDL, insert_rows  # noqa: E402


def main() -> int:
    if not os.environ.get("LAKEBASE_DSN"):
        print("Set LAKEBASE_DSN first (see DEPLOY.md). Nothing was written.")
        return 2
    raw_dir = Path(__file__).resolve().parents[1] / "data" / "raw"
    files = sorted(raw_dir.glob("*.jsonl.gz"))
    if not files:
        print("No kept files in data/raw. Run openpayer-pull first.")
        return 2

    import psycopg

    from openpayer import pg_store

    pg_store.ensure_schema()
    with psycopg.connect(pg_store.dsn()) as con:
        con.execute("DELETE FROM rates")
    total = 0
    for f in files:
        rows = [json.loads(line) for line in gzip.open(f, "rt", encoding="utf-8")]
        n = insert_rows(rows, f.name)
        total += n
        print(f"{f.name}: {n} rows")
    print(f"Seeded {total} rows into Lakebase.")

    status_file = Path(__file__).resolve().parents[1] / "data" / "source_status.json"
    if status_file.exists():
        from openpayer.pg_store import upsert_source_status

        recorded = json.loads(status_file.read_text())
        n = upsert_source_status(list(recorded.values()))
        print(f"Upserted {n} source status rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

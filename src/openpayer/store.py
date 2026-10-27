from __future__ import annotations

from pathlib import Path

import duckdb

from .config import DATA_DIR

DB_PATH = DATA_DIR / "rates.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rates (
  payer VARCHAR, billing_code VARCHAR, billing_code_type VARCHAR,
  negotiated_type VARCHAR, negotiated_rate DOUBLE, billing_class VARCHAR,
  billing_code_modifier VARCHAR, service_code VARCHAR, expiration_date VARCHAR,
  provider_name VARCHAR, tin_type VARCHAR, tin VARCHAR, npi VARCHAR,
  source_url VARCHAR, loaded_file VARCHAR
);
"""


def load(db_path: Path = DB_PATH, raw_dir: Path | None = None) -> int:
    raw_dir = raw_dir or (DATA_DIR / "raw")
    files = sorted(raw_dir.glob("*.jsonl.gz"))
    if not files:
        print("No raw files in data/raw. Run the pull first (needs codes in config/codes.json).")
        return 0
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA)
    con.execute("DELETE FROM rates")
    n = 0
    cols = (
        "payer, billing_code, billing_code_type, negotiated_type, negotiated_rate, "
        "billing_class, billing_code_modifier, service_code, expiration_date, "
        "provider_name, tin_type, tin, npi, source_url"
    )
    for f in files:
        before = con.execute("SELECT count(*) FROM rates").fetchone()[0]
        try:
            con.execute(
                f"INSERT INTO rates ({cols}, loaded_file) SELECT {cols}, ? "
                "FROM read_json_auto(?, format='newline_delimited', compression='gzip', ignore_errors=false)",
                [f.name, str(f)],
            )
        except Exception as exc:
            print(f"Skipped unreadable kept file {f.name}: {exc}")
            continue
        n += con.execute("SELECT count(*) FROM rates").fetchone()[0] - before
    total = con.execute("SELECT count(*) FROM rates").fetchone()[0]
    con.close()
    print(f"Loaded {total} rows into {db_path}")
    return total


def connect(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def main() -> None:
    load()


if __name__ == "__main__":
    main()

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row

# Lakebase (Databricks managed Postgres) serving backend.
# Same query contract as benchmarks.py (DuckDB): dollar types grouped by
# rate type, percentage excluded, nothing interpolated.

DDL = """
CREATE TABLE IF NOT EXISTS rates (
  payer TEXT, billing_code TEXT, billing_code_type TEXT,
  negotiated_type TEXT, negotiated_rate DOUBLE PRECISION, billing_class TEXT,
  billing_code_modifier TEXT, service_code TEXT, expiration_date TEXT,
  provider_name TEXT, tin_type TEXT, tin TEXT, npi TEXT,
  source_url TEXT, loaded_file TEXT
);
CREATE INDEX IF NOT EXISTS rates_code_idx ON rates (billing_code);
CREATE INDEX IF NOT EXISTS rates_payer_idx ON rates (payer);
CREATE INDEX IF NOT EXISTS rates_npi_idx ON rates (npi);
CREATE TABLE IF NOT EXISTS source_status (
  payer TEXT PRIMARY KEY, source_type TEXT, index_url TEXT,
  index_last_updated_on TEXT, files_in_index INTEGER,
  files_attempted INTEGER, files_with_rows INTEGER, rows_kept INTEGER,
  failures INTEGER, pulled_at TEXT
);
"""


def dsn() -> str:
    return os.environ.get("LAKEBASE_DSN", "") or os.environ.get("DATABASE_URL", "")


def enabled() -> bool:
    return os.environ.get("OPENPAYER_STORE", "duckdb").lower() == "lakebase" and bool(dsn())


def _connect():
    return psycopg.connect(dsn(), row_factory=dict_row)


def ensure_schema() -> None:
    with _connect() as con:
        con.execute(DDL)


def insert_rows(rows: list[dict], loaded_file: str) -> int:
    cols = [
        "payer", "billing_code", "billing_code_type", "negotiated_type", "negotiated_rate",
        "billing_class", "billing_code_modifier", "service_code", "expiration_date",
        "provider_name", "tin_type", "tin", "npi", "source_url",
    ]
    with _connect() as con:
        with con.cursor() as cur:
            cur.executemany(
                f"INSERT INTO rates ({','.join(cols)}, loaded_file) VALUES ({','.join(['%s'] * len(cols))}, %s)",
                [tuple(r.get(c) for c in cols) + (loaded_file,) for r in rows],
            )
    return len(rows)


def summary_by_code_payer() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            """
            SELECT billing_code, billing_code_type, payer, negotiated_type,
                   count(*) AS n_rates,
                   count(DISTINCT NULLIF(tin, '')) AS n_provider_groups,
                   min(negotiated_rate) AS min_rate,
                   percentile_cont(0.25) WITHIN GROUP (ORDER BY negotiated_rate) AS p25,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY negotiated_rate) AS median,
                   percentile_cont(0.75) WITHIN GROUP (ORDER BY negotiated_rate) AS p75,
                   max(negotiated_rate) AS max_rate
            FROM rates
            WHERE negotiated_type <> 'percentage' AND negotiated_rate IS NOT NULL
            GROUP BY billing_code, billing_code_type, payer, negotiated_type
            ORDER BY billing_code, payer, negotiated_type
            """
        ).fetchall()
    return rows


def summary_all_payers() -> list[dict]:
    """Aggregate per code and rate type across every payer.

    Types are still never pooled: negotiated and fee schedule stay
    separate rows. The payer count rides on every row so a one-payer
    aggregate is never dressed up as a market.
    """
    with _connect() as con:
        rows = con.execute(
            """
            SELECT billing_code, billing_code_type, negotiated_type,
                   count(*) AS n_rates,
                   count(DISTINCT payer) AS n_payers,
                   count(DISTINCT NULLIF(tin, '')) AS n_provider_groups,
                   min(negotiated_rate) AS min_rate,
                   percentile_cont(0.25) WITHIN GROUP (ORDER BY negotiated_rate) AS p25,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY negotiated_rate) AS median,
                   percentile_cont(0.75) WITHIN GROUP (ORDER BY negotiated_rate) AS p75,
                   max(negotiated_rate) AS max_rate
            FROM rates
            WHERE negotiated_type <> 'percentage' AND negotiated_rate IS NOT NULL
            GROUP BY billing_code, billing_code_type, negotiated_type
            ORDER BY billing_code, negotiated_type
            """
        ).fetchall()
    return rows


def rates_for_code(code: str, payer: str | None = None, limit: int = 500) -> list[dict]:
    sql = (
        "SELECT payer, negotiated_rate, negotiated_type, billing_class, provider_name, tin, npi, source_url "
        "FROM rates WHERE billing_code = %s AND negotiated_type <> 'percentage' AND negotiated_rate IS NOT NULL"
    )
    params: list = [code]
    if payer:
        sql += " AND payer = %s"
        params.append(payer)
    sql += " ORDER BY negotiated_rate LIMIT %s"
    params.append(limit)
    with _connect() as con:
        return con.execute(sql, params).fetchall()


def upsert_source_status(rows: list[dict]) -> int:
    cols = [
        "payer", "source_type", "index_url", "index_last_updated_on", "files_in_index",
        "files_attempted", "files_with_rows", "rows_kept", "failures", "pulled_at",
    ]
    with _connect() as con:
        with con.cursor() as cur:
            cur.executemany(
                f"INSERT INTO source_status ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))}) "
                "ON CONFLICT (payer) DO UPDATE SET source_type=EXCLUDED.source_type, index_url=EXCLUDED.index_url, "
                "index_last_updated_on=EXCLUDED.index_last_updated_on, files_in_index=EXCLUDED.files_in_index, "
                "files_attempted=EXCLUDED.files_attempted, files_with_rows=EXCLUDED.files_with_rows, "
                "rows_kept=EXCLUDED.rows_kept, failures=EXCLUDED.failures, pulled_at=EXCLUDED.pulled_at",
                [tuple(r.get(c) for c in cols) for r in rows],
            )
    return len(rows)


def list_source_status() -> list[dict]:
    with _connect() as con:
        return con.execute("SELECT * FROM source_status ORDER BY payer").fetchall()


def _fmt_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:,.1f} {unit}"
        f /= 1024
    return f"{f:,.1f} TB"


def data_inventory() -> dict:
    with _connect() as con:
        inv: dict = {}
        inv["total_rows"] = con.execute("SELECT count(*) AS n FROM rates").fetchone()["n"]
        inv["source_files"] = con.execute("SELECT count(DISTINCT loaded_file) AS n FROM rates").fetchone()["n"]
        inv["distinct_npis"] = con.execute("SELECT count(DISTINCT npi) AS n FROM rates WHERE npi <> ''").fetchone()["n"]
        inv["provider_groups"] = con.execute("SELECT count(DISTINCT tin) AS n FROM rates WHERE tin <> ''").fetchone()["n"]
        inv["providers_named"] = con.execute("SELECT count(DISTINCT provider_name) AS n FROM rates WHERE provider_name <> ''").fetchone()["n"]
        inv["by_payer"] = con.execute(
            "SELECT payer, count(*) AS rows, count(DISTINCT loaded_file) AS files FROM rates GROUP BY payer ORDER BY payer"
        ).fetchall()
        inv["by_code"] = con.execute(
            "SELECT billing_code, billing_code_type, count(*) AS rows FROM rates GROUP BY billing_code, billing_code_type ORDER BY billing_code"
        ).fetchall()
        inv["by_type"] = con.execute(
            "SELECT negotiated_type, count(*) AS rows FROM rates GROUP BY negotiated_type ORDER BY 2 DESC"
        ).fetchall()
        inv["sources"] = [r["source_url"] for r in con.execute("SELECT DISTINCT source_url FROM rates ORDER BY 1").fetchall()]
    inv["raw_bytes"] = 0
    inv["raw_size"] = "Lakebase (Postgres)"
    inv["raw_files_on_disk"] = inv["source_files"]
    inv["db_size"] = "Lakebase (Postgres)"
    return inv

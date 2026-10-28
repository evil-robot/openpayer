from __future__ import annotations

from pathlib import Path

from .store import DB_PATH, connect

# Benchmarks are computed from observed dollar rates only, grouped by rate
# type so a fee schedule is never blended with a negotiated rate.
# Nothing is interpolated. Percentiles use DuckDB quantile_cont.
# Percentage rates are not dollars and are excluded from dollar benchmarks.


def summary_by_code_payer(db_path: Path = DB_PATH) -> list[dict]:
    from . import pg_store

    if pg_store.enabled():
        return pg_store.summary_by_code_payer()
    con = connect(db_path)
    rows = con.execute(
        """
        SELECT billing_code, billing_code_type, payer, negotiated_type,
               count(*) AS n_rates,
               count(DISTINCT CASE WHEN tin <> '' THEN tin END) AS n_provider_groups,
               min(negotiated_rate) AS min_rate,
               quantile_cont(negotiated_rate, 0.25) AS p25,
               quantile_cont(negotiated_rate, 0.50) AS median,
               quantile_cont(negotiated_rate, 0.75) AS p75,
               max(negotiated_rate) AS max_rate
        FROM rates
        WHERE negotiated_type <> 'percentage' AND negotiated_rate IS NOT NULL
        GROUP BY ALL ORDER BY billing_code, payer, negotiated_type
        """
    ).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    return [dict(zip(cols, r)) for r in rows]


def summary_all_payers(db_path: Path = DB_PATH) -> list[dict]:
    from . import pg_store

    if pg_store.enabled():
        return pg_store.summary_all_payers()
    con = connect(db_path)
    rows = con.execute(
        """
        SELECT billing_code, billing_code_type, negotiated_type,
               count(*) AS n_rates,
               count(DISTINCT payer) AS n_payers,
               count(DISTINCT CASE WHEN tin <> '' THEN tin END) AS n_provider_groups,
               min(negotiated_rate) AS min_rate,
               quantile_cont(negotiated_rate, 0.25) AS p25,
               quantile_cont(negotiated_rate, 0.50) AS median,
               quantile_cont(negotiated_rate, 0.75) AS p75,
               max(negotiated_rate) AS max_rate
        FROM rates
        WHERE negotiated_type <> 'percentage' AND negotiated_rate IS NOT NULL
        GROUP BY ALL ORDER BY billing_code, negotiated_type
        """
    ).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    return [dict(zip(cols, r)) for r in rows]


def _fmt_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:,.1f} {unit}"
        f /= 1024
    return f"{f:,.1f} TB"


def data_inventory(db_path: Path = DB_PATH) -> dict:
    """Live inventory of what is actually in the demo database right now."""
    from . import pg_store

    if pg_store.enabled():
        return pg_store.data_inventory()
    con = connect(db_path)
    inv: dict = {}
    inv["total_rows"] = con.execute("SELECT count(*) FROM rates").fetchone()[0]
    inv["source_files"] = con.execute("SELECT count(DISTINCT loaded_file) FROM rates").fetchone()[0]
    inv["distinct_npis"] = con.execute(
        "SELECT count(DISTINCT npi) FROM rates WHERE npi IS NOT NULL AND npi <> ''"
    ).fetchone()[0]
    raw_dir = db_path.parent / "raw"
    raw_files = list(raw_dir.glob("*.jsonl.gz")) if raw_dir.exists() else []
    raw_bytes = sum(p.stat().st_size for p in raw_files)
    inv["raw_bytes"] = raw_bytes
    inv["raw_size"] = _fmt_bytes(raw_bytes)
    inv["raw_files_on_disk"] = len(raw_files)
    inv["db_size"] = _fmt_bytes(db_path.stat().st_size) if db_path.exists() else "0 B"
    inv["provider_groups"] = con.execute("SELECT count(DISTINCT tin) FROM rates WHERE tin <> ''").fetchone()[0]
    inv["providers_named"] = con.execute("SELECT count(DISTINCT provider_name) FROM rates WHERE provider_name <> ''").fetchone()[0]
    inv["by_payer"] = [
        {"payer": r[0], "rows": r[1], "files": r[2]}
        for r in con.execute(
            "SELECT payer, count(*), count(DISTINCT loaded_file) FROM rates GROUP BY payer ORDER BY payer"
        ).fetchall()
    ]
    inv["by_code"] = [
        {"billing_code": r[0], "billing_code_type": r[1], "rows": r[2]}
        for r in con.execute(
            "SELECT billing_code, billing_code_type, count(*) FROM rates GROUP BY ALL ORDER BY billing_code"
        ).fetchall()
    ]
    inv["by_type"] = [
        {"negotiated_type": r[0], "rows": r[1]}
        for r in con.execute("SELECT negotiated_type, count(*) FROM rates GROUP BY ALL ORDER BY 2 DESC").fetchall()
    ]
    inv["sources"] = [r[0] for r in con.execute("SELECT DISTINCT source_url FROM rates ORDER BY 1").fetchall()]
    con.close()
    return inv


def sources_detail() -> list[dict]:
    """Every configured source with pull status and freshness inputs.

    Merges config/sources.json (what could be pulled) with recorded pull
    status (what was pulled, when, and the payer index date). A configured
    source with no pull record reads as not pulled yet, never as missing.
    """
    import json as _json

    from .config import DATA_DIR, load_sources

    recorded: dict[str, dict] = {}
    from . import pg_store

    if pg_store.enabled():
        try:
            recorded = {r["payer"]: r for r in pg_store.list_source_status()}
        except Exception:
            recorded = {}
    else:
        status_file = DATA_DIR / "source_status.json"
        if status_file.exists():
            recorded = _json.loads(status_file.read_text())
    out: list[dict] = []
    for src in load_sources():
        rec = recorded.get(src.payer, {})
        out.append(
            {
                "payer": src.payer,
                "source_type": src.source_type,
                "configured": bool(src.toc_url or src.direct_mrf_urls),
                "index_url": src.toc_url,
                "index_last_updated_on": rec.get("index_last_updated_on", ""),
                "files_in_index": rec.get("files_in_index"),
                "index_count_capped": bool(rec.get("index_count_capped")),
                "files_attempted": rec.get("files_attempted"),
                "files_with_rows": rec.get("files_with_rows"),
                "rows_kept": rec.get("rows_kept"),
                "failures": rec.get("failures"),
                "pulled_at": rec.get("pulled_at", ""),
            }
        )
    return out


def rates_for_code(code: str, db_path: Path = DB_PATH, payer: str | None = None, limit: int = 500) -> list[dict]:
    from . import pg_store

    if pg_store.enabled():
        return pg_store.rates_for_code(code, payer=payer, limit=limit)
    con = connect(db_path)
    sql = (
        "SELECT payer, negotiated_rate, negotiated_type, billing_class, provider_name, tin, npi, source_url "
        "FROM rates WHERE billing_code = ? AND negotiated_type <> 'percentage' AND negotiated_rate IS NOT NULL"
    )
    params: list = [code]
    if payer:
        sql += " AND payer = ?"
        params.append(payer)
    sql += " ORDER BY negotiated_rate LIMIT ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    return [dict(zip(cols, r)) for r in rows]

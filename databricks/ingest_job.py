# Databricks job task: OpenPayer filtered ingest into Lakebase.
# Runs from the git source of evil-robot/openpayer (branch main).
# Parameters (job parameters): limit (files per payer, blank = all), workers.
import os
import subprocess
import sys

subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "ijson", "httpx", "psycopg[binary]", "databricks-sdk"])

from pathlib import Path as _Path

for _base in [_Path.cwd(), *_Path.cwd().parents]:
    if (_base / "src" / "openpayer").exists():
        sys.path.insert(0, str(_base / "src"))
        break
else:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "git+https://github.com/evil-robot/openpayer"])

from databricks.sdk import WorkspaceClient  # noqa: E402

from openpayer.config import code_set, load_codes, load_sources  # noqa: E402
from openpayer.ingest.discover import collect_toc, download_to_temp, suffix_for  # noqa: E402
from openpayer.ingest.mrf import parse_mrf, write_jsonl  # noqa: E402
from openpayer.pg_store import ensure_schema, insert_rows  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

# Lakebase credential for this workspace identity (expires in about an hour;
# the job mints a fresh one each run). The request_id must be unique per
# run: reusing one returns the cached, by-then-expired credential and
# Lakebase answers "OAuth: User is not authorized". Raw REST via the SDK
# api client: the preinstalled SDK on serverless can predate the
# database namespace.
import time as _time

w = WorkspaceClient()
api = w.api_client
cred = api.do("POST", "/api/2.0/database/credentials", body={"request_id": f"openpayer-ingest-{int(_time.time())}", "instance_names": ["ar-fleet"]})
instance = api.do("GET", "/api/2.0/database/instances/ar-fleet")
me = api.do("GET", "/api/2.0/preview/scim/v2/Me")
token = cred.get("token") if isinstance(cred, dict) else cred.token
dns = instance.get("read_write_dns") if isinstance(instance, dict) else instance.read_write_dns
user = me.get("userName") if isinstance(me, dict) else me.user_name
os.environ["LAKEBASE_DSN"] = f"host={dns} port=5432 dbname=openpayer user={user} password={token} sslmode=require"

print(f"argv: {sys.argv}")
limit_raw = os.environ.get("OPENPAYER_LIMIT", "")
only_arg = os.environ.get("OPENPAYER_ONLY", "")
workers_arg = os.environ.get("OPENPAYER_WORKERS", "")
group_cap_arg = os.environ.get("OPENPAYER_GROUP_CAP", "")
for _a in sys.argv[1:]:
    if _a.isdigit():
        limit_raw = _a
    elif _a.startswith("--limit="):
        limit_raw = _a.split("=", 1)[1]
    elif _a.startswith("--only="):
        only_arg = _a.split("=", 1)[1]
    elif _a.startswith("--workers="):
        workers_arg = _a.split("=", 1)[1]
    elif _a.startswith("--group-cap="):
        group_cap_arg = _a.split("=", 1)[1]
    elif _a.startswith("--smallest-first="):
        smallest_arg = _a.split("=", 1)[1]
smallest_first = str(globals().get("smallest_arg", "") or os.environ.get("OPENPAYER_SMALLEST_FIRST", "")).strip().lower() in ("1", "true", "yes")
limit = int(limit_raw) if str(limit_raw).strip().isdigit() else None
group_cap = int(group_cap_arg) if str(group_cap_arg).strip().isdigit() else 300

codes = load_codes()
allowed = code_set(codes)
assert allowed, "empty allowlist: refusing to pull"

ensure_schema()
total = 0
import re as _re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime as _dt, timezone as _tz

from openpayer.pg_store import upsert_source_status

only = {p.strip().lower() for p in only_arg.split(",") if p.strip()}
try:
    n_workers = max(1, int(workers_arg or "3"))
except ValueError:
    n_workers = 3
print(f"config: limit={limit} workers={n_workers} only={sorted(only) or 'all'} smallest_first={smallest_first}")


def _fresh_lakebase_dsn() -> None:
    """Mint a short-lived Lakebase credential and point pg_store at it.

    Credentials live about an hour and a national pull runs longer, so
    each file load mints its own instead of trusting the one from job
    start. Concurrent mints are harmless: every token names the same
    workspace identity.
    """
    c = api.do("POST", "/api/2.0/database/credentials", body={"request_id": f"openpayer-ingest-{int(_time.time() * 1000)}", "instance_names": ["ar-fleet"]})
    t = c.get("token") if isinstance(c, dict) else c.token
    os.environ["LAKEBASE_DSN"] = f"host={dns} port=5432 dbname=openpayer user={user} password={t} sslmode=require"


def _pull_file(job):
    """Download, filter to the allowlist, and load one MRF. Returns stats.

    Files already in the pulled_files ledger are counted from the ledger
    and skipped, so a rerun after a timeout resumes instead of starting
    over. The ledger is written only after the rows are in, which makes
    the rates table itself the receipt for the pull.
    """
    src, i, url = job
    slug = _re.sub(r"[^a-z0-9]+", "-", src.payer.lower()).strip("-")
    if smallest_first:
        # File identity from the URL, not list position: in this mode the
        # list is reordered by size, so position names would corrupt the
        # ledger. The URL guard below also skips anything an earlier
        # index-ordered run already loaded under a position name.
        import hashlib

        fname = f"{slug}-{hashlib.sha1(url.encode()).hexdigest()[:10]}.jsonl.gz"
    else:
        fname = f"{slug}-{i:04d}.jsonl.gz"
    from openpayer import pg_store

    _fresh_lakebase_dsn()
    done_rows = pg_store.file_rows_kept(fname)
    if done_rows is not None:
        print(f"SKIP (already pulled) {fname}: {done_rows} rows")
        return {"attempted": 1, "with_rows": 1 if done_rows else 0, "rows": done_rows, "failures": 0}
    if smallest_first:
        import psycopg as _pg_guard

        _fresh_lakebase_dsn()
        with _pg_guard.connect(pg_store.dsn()) as con:
            already = con.execute("SELECT count(*) FROM rates WHERE source_url = %s", [url]).fetchone()[0]
        if already:
            print(f"SKIP (url already in rates) {fname}: {already} rows")
            return {"attempted": 1, "with_rows": 1, "rows": already, "failures": 0}
    tmp = None
    try:
        if url.startswith(("http://", "https://")):
            tmp = download_to_temp(url, suffix=suffix_for(url))
            local = str(tmp)
        else:
            local = url
        rows = list(parse_mrf(local, allowed, payer=src.payer, source_url=url, group_cap=group_cap))
        kept = 0
        if rows:
            import psycopg

            _fresh_lakebase_dsn()
            with psycopg.connect(pg_store.dsn()) as con:
                con.execute("DELETE FROM rates WHERE loaded_file = %s", [fname])
            kept = insert_rows(rows, fname)
        pg_store.mark_file(fname, src.payer, kept)
        print(f"KEPT {kept} rows <- {fname}")
        return {"attempted": 1, "with_rows": 1 if kept else 0, "rows": kept, "failures": 0}
    except Exception as exc:
        print(f"FAILED {url}: {exc}")
        return {"attempted": 1, "with_rows": 0, "rows": 0, "failures": 1}
    finally:
        if tmp is not None:
            Path(tmp).unlink(missing_ok=True)


for src in load_sources():
    if only and src.payer.lower() not in only:
        print(f"- {src.payer}: skipped by OPENPAYER_ONLY")
        continue
    urls = list(src.direct_mrf_urls)
    toc_date = ""
    files_in_index = len(urls)
    index_capped = False
    if src.toc_url:
        try:
            collect_limit = max(limit * 8, 24) if (smallest_first and limit) else limit
            entries, index_total, toc_date, index_capped = collect_toc(src.toc_url, limit=collect_limit)
        except Exception as exc:
            print(f"- {src.payer}: index unreadable, skipped: {exc}")
            continue
        files_in_index = index_total
        urls.extend(f["location"] for f in entries)
        print(f"- {src.payer}: taking {len(urls)} of {'at least ' if index_capped else ''}{files_in_index} files from index dated {toc_date}")
    elif limit:
        urls = urls[:limit]
    # Payer indexes list the same file under many plans and entities.
    # A repeated URL is the same file: pull it once or the same rates
    # land twice under two ledger names.
    urls = list(dict.fromkeys(urls))
    if smallest_first and limit and len(urls) > limit:
        # First-pass coverage, fastest first: size every candidate with a
        # HEAD request and take the smallest. Giant national files parse
        # for hours; small state books carry the same codes and land in
        # minutes. Unknown sizes sort last, never first.
        import httpx as _httpx

        def _size(u):
            try:
                with _httpx.Client(follow_redirects=True, timeout=20) as cl:
                    r = cl.head(u)
                v = int(r.headers.get("content-length") or 0)
                return v if v > 0 else float("inf")
            except Exception:
                return float("inf")

        with ThreadPoolExecutor(max_workers=8) as pool:
            sizes = list(pool.map(_size, urls))
        order = sorted(range(len(urls)), key=lambda i: sizes[i])
        chosen = [(urls[i], sizes[i]) for i in order[:limit]]
        urls = [u for u, _ in chosen]
        print(f"- {src.payer}: smallest-first chose {len(urls)} of {len(order)} distinct candidates:")
        for u, s in chosen:
            print(f"    {s / 1e6:,.1f} MB  {u.rsplit('/', 1)[-1][:110]}")
    if not urls:
        print(f"- {src.payer}: no files, skipped")
        continue
    stats = {"files_attempted": 0, "files_with_rows": 0, "rows_kept": 0, "failures": 0}
    jobs = [(src, i, url) for i, url in enumerate(urls)]
    from openpayer import pg_store as _pg

    stop_at = 150  # provider groups per code: enough for a stable median
    for start in range(0, len(jobs), max(1, n_workers)):
        chunk = jobs[start : start + max(1, n_workers)]
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            for r in pool.map(_pull_file, chunk):
                stats["files_attempted"] += r["attempted"]
                stats["files_with_rows"] += r["with_rows"]
                stats["rows_kept"] += r["rows"]
                stats["failures"] += r["failures"]
        _fresh_lakebase_dsn()
        try:
            groups = _pg.payer_code_groups(src.payer)
        except Exception:
            groups = {}
        thin = [c for c in sorted(allowed) if groups.get(c, 0) < stop_at]
        print(f"- {src.payer}: after {stats['files_attempted']} files, groups per code {groups}; still thin: {thin}")
        if not thin:
            print(f"- {src.payer}: coverage stop reached ({stop_at}+ groups for every code)")
            break
    total += stats["rows_kept"]
    print(f"- {src.payer}: {stats}")
    upsert_source_status(
        [
            {
                "payer": src.payer,
                "source_type": src.source_type,
                "index_url": src.toc_url,
                "index_last_updated_on": toc_date,
                "files_in_index": files_in_index,
                "index_count_capped": index_capped,
                "pulled_at": _dt.now(_tz.utc).isoformat(timespec="seconds"),
                **stats,
            }
        ]
    )
print(f"OpenPayer ingest complete. Inserted {total} rows for codes {sorted(allowed)}.")

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
from openpayer.ingest.discover import collect_toc, download_to_temp  # noqa: E402
from openpayer.ingest.mrf import parse_mrf, write_jsonl  # noqa: E402
from openpayer.pg_store import ensure_schema, insert_rows  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

# Lakebase credential for this workspace identity (expires in about an hour;
# the job mints a fresh one each run). Raw REST via the SDK api client: the
# preinstalled SDK on serverless can predate the database namespace.
w = WorkspaceClient()
api = w.api_client
cred = api.do("POST", "/api/2.0/database/credentials", body={"request_id": "openpayer-ingest", "instance_names": ["ar-fleet"]})
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
print(f"config: limit={limit} workers={n_workers} only={sorted(only) or 'all'}")


def _pull_file(job):
    """Download, filter to the allowlist, and load one MRF. Returns stats."""
    src, i, url = job
    slug = _re.sub(r"[^a-z0-9]+", "-", src.payer.lower()).strip("-")
    fname = f"{slug}-{i:04d}.jsonl.gz"
    tmp = None
    try:
        if url.startswith(("http://", "https://")):
            tmp = download_to_temp(url, suffix=".json.gz" if url.split("?")[0].endswith(".gz") else ".json")
            local = str(tmp)
        else:
            local = url
        rows = list(parse_mrf(local, allowed, payer=src.payer, source_url=url, group_cap=group_cap))
        kept = 0
        if rows:
            import psycopg

            from openpayer import pg_store

            with psycopg.connect(pg_store.dsn()) as con:
                con.execute("DELETE FROM rates WHERE loaded_file = %s", [fname])
            kept = insert_rows(rows, fname)
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
    if src.toc_url:
        try:
            entries, index_total, toc_date = collect_toc(src.toc_url, limit=limit)
        except Exception as exc:
            print(f"- {src.payer}: index unreadable, skipped: {exc}")
            continue
        files_in_index = index_total
        urls.extend(f["location"] for f in entries)
        print(f"- {src.payer}: taking {len(urls)} of {files_in_index} files from index dated {toc_date}")
    elif limit:
        urls = urls[:limit]
    if not urls:
        print(f"- {src.payer}: no files, skipped")
        continue
    stats = {"files_attempted": 0, "files_with_rows": 0, "rows_kept": 0, "failures": 0}
    jobs = [(src, i, url) for i, url in enumerate(urls)]
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        for r in pool.map(_pull_file, jobs):
            stats["files_attempted"] += r["attempted"]
            stats["files_with_rows"] += r["with_rows"]
            stats["rows_kept"] += r["rows"]
            stats["failures"] += r["failures"]
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
                "pulled_at": _dt.now(_tz.utc).isoformat(timespec="seconds"),
                **stats,
            }
        ]
    )
print(f"OpenPayer ingest complete. Inserted {total} rows for codes {sorted(allowed)}.")

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
from openpayer.ingest.discover import iter_toc_files, load_toc  # noqa: E402
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

limit_raw = os.environ.get("OPENPAYER_LIMIT", "")
if len(sys.argv) > 1 and sys.argv[1].isdigit():
    limit_raw = sys.argv[1]
limit = int(limit_raw) if limit_raw else None

codes = load_codes()
allowed = code_set(codes)
assert allowed, "empty allowlist: refusing to pull"

ensure_schema()
total = 0
for src in load_sources():
    urls = list(src.direct_mrf_urls)
    if src.toc_url:
        urls.extend(f["location"] for f in iter_toc_files(load_toc(src.toc_url)))
    if limit:
        urls = urls[:limit]
    for i, url in enumerate(urls):
        tmp = None
        try:
            if url.startswith(("http://", "https://")):
                from openpayer.ingest.discover import download_to_temp

                tmp = download_to_temp(url, suffix=".json.gz" if url.split("?")[0].endswith(".gz") else ".json")
                local = str(tmp)
            else:
                local = url
            rows = list(parse_mrf(local, allowed, payer=src.payer, source_url=url))
            if rows:
                import psycopg

                from openpayer import pg_store

                fname = f"{src.payer}-{i:04d}.jsonl.gz"
                with psycopg.connect(pg_store.dsn()) as con:
                    con.execute("DELETE FROM rates WHERE loaded_file = %s", [fname])
                total += insert_rows(rows, fname)
        except Exception as exc:
            print(f"FAILED {url}: {exc}")
        finally:
            if tmp is not None:
                Path(tmp).unlink(missing_ok=True)
print(f"OpenPayer ingest complete. Inserted {total} rows for codes {sorted(allowed)}.")

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import DATA_DIR, Source, code_set, load_codes, load_sources
from .discover import collect_toc, download_to_temp, suffix_for
from .mrf import parse_mrf, write_jsonl


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "file"


def _pull_one(src: Source, index: int, url: str, allowed: set[str], out_dir: Path, group_cap: int | None = 300) -> tuple[str, int, str]:
    tmp: Path | None = None
    local = url
    try:
        if url.startswith(("http://", "https://")):
            tmp = download_to_temp(url, suffix=suffix_for(url))
            local = str(tmp)
        out = out_dir / f"{_slug(src.payer)}-{index:04d}.jsonl.gz"
        n = write_jsonl(parse_mrf(local, allowed, payer=src.payer, source_url=url, group_cap=group_cap), out)
        return (url, n, "")
    except Exception as exc:
        return (url, 0, str(exc))
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def pull(dry_run: bool = False, limit: int | None = None, workers: int = 4, group_cap: int | None = 300) -> int:
    codes = load_codes()
    allowed = code_set(codes)
    if not allowed:
        print("No codes configured. Add codes to config/codes.json first.")
        print("By design, nothing is downloaded while the allowlist is empty.")
        return 2

    sources = load_sources()
    active = [s for s in sources if s.toc_url or s.direct_mrf_urls]
    if not active:
        print(f"Allowlist ready ({len(allowed)} codes), but no source has a toc_url or direct_mrf_urls yet.")
        print("Fill config/sources.json, then run again.")
        return 2

    print(f"Pulling {len(allowed)} codes: {sorted(allowed)}")
    total = 0
    out_dir = DATA_DIR / "raw"
    jobs: list[tuple[Source, int, str]] = []
    toc_dates: dict[str, str] = {}
    toc_totals: dict[str, int] = {}
    for src in sources:
        urls: list[str] = list(src.direct_mrf_urls)
        if src.toc_url:
            entries, index_total, index_date, _capped = collect_toc(src.toc_url, limit=limit)
            toc_dates[src.payer] = index_date
            toc_totals[src.payer] = index_total
            urls.extend(f["location"] for f in entries)
        if not urls:
            print(f"- {src.payer}: no files, skipped")
            continue
        if src.toc_url:
            print(f"- {src.payer}: taking {len(urls)} of {toc_totals[src.payer]} in-network files from its index")
        else:
            print(f"- {src.payer}: {len(urls)} direct in-network files")
        jobs.extend((src, i, url) for i, url in enumerate(urls))

    if dry_run:
        for _, _, url in jobs:
            print(f"  [dry-run] {url}")
        return 0

    from collections import defaultdict
    from datetime import datetime, timezone

    stats: dict[str, dict] = defaultdict(lambda: {"files_attempted": 0, "files_with_rows": 0, "rows_kept": 0, "failures": 0})
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for (src, _i, url), (_u, n, err) in zip(
            jobs, pool.map(lambda j: _pull_one(j[0], j[1], j[2], allowed, out_dir, group_cap), jobs), strict=True
        ):
            s = stats[src.payer]
            s["files_attempted"] += 1
            if err:
                s["failures"] += 1
                print(f"  FAILED {url}: {err}")
            else:
                total += n
                s["rows_kept"] += n
                if n:
                    s["files_with_rows"] += 1
                print(f"  kept {n} rows <- {url.rsplit('/', 1)[-1]}")

    status_path = DATA_DIR / "source_status.json"
    prior: dict = {}
    if status_path.exists():
        import json as _json

        prior = _json.loads(status_path.read_text())
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for src in sources:
        if src.payer in stats:
            prior[src.payer] = {
                "payer": src.payer,
                "source_type": src.source_type,
                "index_url": src.toc_url,
                "index_last_updated_on": toc_dates.get(src.payer, ""),
                "files_in_index": toc_totals.get(src.payer, len(src.direct_mrf_urls)),
                "pulled_at": now,
                **stats[src.payer],
            }
    import json as _json

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    status_path.write_text(_json.dumps(prior, indent=1))
    print(f"Wrote {status_path}")
    print(f"Done. Kept {total} rows total. Next: openpayer-load (builds DuckDB + benchmarks).")
    return 0


def main() -> None:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    limit = None
    workers = 4
    group_cap: int | None = 300
    for a in args:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
        if a.startswith("--workers="):
            workers = int(a.split("=", 1)[1])
        if a.startswith("--group-cap="):
            raw = a.split("=", 1)[1]
            group_cap = int(raw) if raw.isdigit() else None
    raise SystemExit(pull(dry_run=dry, limit=limit, workers=workers, group_cap=group_cap))


if __name__ == "__main__":
    main()

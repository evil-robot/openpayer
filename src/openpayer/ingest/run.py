from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import DATA_DIR, Source, code_set, load_codes, load_sources
from .discover import download_to_temp, iter_toc_files, load_toc
from .mrf import parse_mrf, write_jsonl


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "file"


def _pull_one(src: Source, index: int, url: str, allowed: set[str], out_dir: Path) -> tuple[str, int, str]:
    tmp: Path | None = None
    local = url
    try:
        if url.startswith(("http://", "https://")):
            suffix = ".json.gz" if url.split("?")[0].endswith(".gz") else ".json"
            tmp = download_to_temp(url, suffix=suffix)
            local = str(tmp)
        out = out_dir / f"{_slug(src.payer)}-{index:04d}.jsonl.gz"
        n = write_jsonl(parse_mrf(local, allowed, payer=src.payer, source_url=url), out)
        return (url, n, "")
    except Exception as exc:
        return (url, 0, str(exc))
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def pull(dry_run: bool = False, limit: int | None = None, workers: int = 4) -> int:
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
    for src in sources:
        urls: list[str] = list(src.direct_mrf_urls)
        if src.toc_url:
            toc = load_toc(src.toc_url)
            urls.extend(f["location"] for f in iter_toc_files(toc))
        if not urls:
            print(f"- {src.payer}: no files, skipped")
            continue
        if limit is not None:
            urls = urls[:limit]
        print(f"- {src.payer}: {len(urls)} in-network files")
        jobs.extend((src, i, url) for i, url in enumerate(urls))

    if dry_run:
        for _, _, url in jobs:
            print(f"  [dry-run] {url}")
        return 0

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for url, n, err in pool.map(lambda j: _pull_one(j[0], j[1], j[2], allowed, out_dir), jobs):
            if err:
                print(f"  FAILED {url}: {err}")
            else:
                total += n
                print(f"  kept {n} rows <- {url.rsplit('/', 1)[-1]}")
    print(f"Done. Kept {total} rows total. Next: openpayer-load (builds DuckDB + benchmarks).")
    return 0


def main() -> None:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    limit = None
    workers = 4
    for a in args:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
        if a.startswith("--workers="):
            workers = int(a.split("=", 1)[1])
    raise SystemExit(pull(dry_run=dry, limit=limit, workers=workers))


if __name__ == "__main__":
    main()

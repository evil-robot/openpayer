from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import ijson

from .mrf import open_local


def download_to_temp(url: str, suffix: str = ".json.gz") -> Path:
    """Stream a remote MRF to a temp file. Caller deletes it. One file at a time."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="mrf-")
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=180.0)) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
            tmp.write(chunk)
    tmp.close()
    return Path(tmp.name)


def iter_toc_files(toc: dict) -> Iterator[dict]:
    """Yield {location, description, plan_name, plan_id} from a TiC table-of-contents JSON."""
    for structure in toc.get("reporting_structure", []) or []:
        plans = structure.get("reporting_plans", []) or [{}]
        plan = plans[0] if plans else {}
        for f in structure.get("in_network_files", []) or []:
            loc = f.get("location", "")
            if loc:
                yield {
                    "location": loc,
                    "description": f.get("description", ""),
                    "plan_name": plan.get("plan_name", ""),
                    "plan_id": plan.get("plan_id", ""),
                }


def load_toc(toc_url: str) -> dict:
    if toc_url.startswith(("http://", "https://")):
        path = download_to_temp(toc_url, suffix=".json")
        try:
            return json.loads(path.read_text())
        finally:
            path.unlink(missing_ok=True)
    return json.loads(Path(toc_url).read_text())


def toc_meta(local_path: str) -> tuple[str, str]:
    """(last_updated_on, reporting_entity_name) read from the TOC head.

    National indexes run to gigabytes uncompressed, so nothing here loads
    the whole file: only the first chunk is decoded and scanned.
    """
    stream = open_local(local_path)
    try:
        head = stream.read(512 * 1024).decode("utf-8", "ignore")
    finally:
        stream.close()
    date = re.search(r'"last_updated_on"\s*:\s*"([^"]*)"', head)
    name = re.search(r'"reporting_entity_name"\s*:\s*"([^"]*)"', head)
    if not date and not local_path.split("?")[0].endswith(".gz"):
        # Some payers (Cigna) put last_updated_on at the end of the index.
        with open(local_path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 512 * 1024))
            tail = fh.read().decode("utf-8", "ignore")
        date = re.search(r'"last_updated_on"\s*:\s*"([^"]*)"', tail)
    return (date.group(1) if date else "", name.group(1) if name else "")


def iter_toc_file_dicts(local_path: str) -> Iterator[dict]:
    """Stream {location, description, plan_name, plan_id} from a local TOC.

    Same entry shape as iter_toc_files, but the TOC (plain or gzipped) is
    parsed as a stream, so a multi-gigabyte national index never has to
    fit in memory.
    """
    stream = open_local(local_path)
    try:
        for structure in ijson.items(stream, "reporting_structure.item", use_float=True):
            plans = structure.get("reporting_plans", []) or [{}]
            plan = plans[0] if plans else {}
            for f in structure.get("in_network_files", []) or []:
                loc = f.get("location", "")
                if loc:
                    yield {
                        "location": loc,
                        "description": f.get("description", ""),
                        "plan_name": plan.get("plan_name", ""),
                        "plan_id": plan.get("plan_id", ""),
                    }
    finally:
        stream.close()


def collect_toc(source: str, limit: int | None = None) -> tuple[list[dict], int, str]:
    """One streaming pass over a TOC (URL or local path).

    Returns (entries up to limit, total files in the index, index date).
    The whole index is counted even when only the first `limit` entries
    are kept, so coverage on the site compares pulled files against the
    true size of the payer's index, never against the sample.
    """
    tmp: Path | None = None
    local = source
    try:
        if source.startswith(("http://", "https://")):
            suffix = ".json.gz" if source.split("?")[0].endswith(".gz") else ".json"
            tmp = download_to_temp(source, suffix=suffix)
            local = str(tmp)
        date, _name = toc_meta(local)
        kept: list[dict] = []
        total = 0
        for entry in iter_toc_file_dicts(local):
            total += 1
            if limit is None or len(kept) < limit:
                kept.append(entry)
        return kept, total, date
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

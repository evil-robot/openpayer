from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import ijson

from .mrf import open_local


def suffix_for(url: str) -> str:
    """Temp-file suffix matching the payload format at a URL."""
    clean = url.split("?")[0].lower()
    if clean.endswith(".zip"):
        return ".zip"
    if clean.endswith(".gz"):
        return ".json.gz"
    return ".json"


def download_to_temp(url: str, suffix: str = ".json.gz", max_resumes: int = 10) -> Path:
    """Stream a remote MRF to a temp file. Caller deletes it. One file at a time.

    National in-network files run to many gigabytes and payers drop
    connections mid-body (UnitedHealthcare closed one at 2.8 GB of a
    15 GB file). A dropped body resumes with a Range request from the
    byte already on disk instead of starting over, so a file finishes
    unless the payer stays down for max_resumes consecutive attempts.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="mrf-")
    have = 0
    resumes = 0
    try:
        while True:
            headers = {"Range": f"bytes={have}-"} if have else {}
            try:
                with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=httpx.Timeout(30.0, read=180.0)) as resp:
                    if have and resp.status_code == 200:
                        # Range ignored: the payer restarted the body.
                        tmp.seek(0)
                        tmp.truncate()
                        have = 0
                    resp.raise_for_status()
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        tmp.write(chunk)
                        have += len(chunk)
                break
            except (httpx.TransportError, httpx.TimeoutException):
                resumes += 1
                if resumes > max_resumes:
                    raise
                tmp.flush()
                continue
    except BaseException:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise
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


def collect_toc(
    source: str, limit: int | None = None, count_cap: int = 250_000
) -> tuple[list[dict], int, str, bool]:
    """One streaming pass over a TOC (URL or local path).

    Returns (entries up to limit, files counted, index date, capped).
    The index is counted in the same pass that harvests entries, so
    coverage on the site compares pulled files against the size of the
    payer's index, never against the sample. Counting stops at
    `count_cap` entries (capped=True): Elevance's index holds about
    43 million files, and counting them all burns hours to produce a
    number whose only job is context. A capped count is a floor, and
    the site says "at least" wherever it appears.
    """
    tmp: Path | None = None
    local = source
    try:
        if source.startswith(("http://", "https://")):
            tmp = download_to_temp(source, suffix=suffix_for(source))
            local = str(tmp)
        date, _name = toc_meta(local)
        kept: list[dict] = []
        total = 0
        capped = False
        for entry in iter_toc_file_dicts(local):
            total += 1
            if limit is None or len(kept) < limit:
                kept.append(entry)
            if total >= count_cap:
                capped = True
                break
        return kept, total, date, capped
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path

import httpx


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

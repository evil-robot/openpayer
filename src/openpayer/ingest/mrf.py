from __future__ import annotations

import gzip
import io
import json
from collections.abc import Iterator
from pathlib import Path

import ijson


def open_local(source: str):
    """Open a local MRF (.json or .json.gz) as a seekable binary stream."""
    raw = io.BufferedReader(io.FileIO(source, "rb"))
    if source.split("?")[0].endswith(".gz"):
        return gzip.GzipFile(fileobj=raw)
    return raw


def _num_str(value) -> str:
    """Render a JSON number as a clean ID string (NPIs and group IDs arrive as numbers)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _sanitized_copy(path: str) -> Path:
    """Copy an MRF dropping commas that directly precede ] or } (trailing commas).

    Some payer files are invalid JSON for exactly this reason. The scan tracks
    string state, so commas inside text are untouched. Output goes to a temp
    file and is deleted by the caller.
    """
    import tempfile

    src = open_local(path)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", prefix="mrf-clean-")
    in_str = False
    escaped = False
    held: list[int] = []  # comma + whitespace seen outside a string, not yet written

    def feed(data: bytes):
        nonlocal in_str, escaped
        for byte in data:
            ch = chr(byte)
            if held:
                if ch in " \t\r\n":
                    held.append(byte)
                    continue
                if ch in "]}":
                    held.clear()  # drop the trailing comma
                else:
                    tmp.write(bytes(held))
                    held.clear()
            if in_str:
                tmp.write(bytes([byte]))
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                tmp.write(bytes([byte]))
            elif ch == ",":
                held.append(byte)
            else:
                tmp.write(bytes([byte]))

    while True:
        chunk = src.read(1024 * 1024)
        if not chunk:
            break
        feed(chunk)
    if held:
        tmp.write(bytes(held))
    tmp.close()
    src.close()
    return Path(tmp.name)


def _provider_index(path: str) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    stream = open_local(path)
    try:
        for ref in ijson.items(stream, "provider_references.item", use_float=True):
            gid = _num_str(ref.get("provider_group_id", ""))
            net_names = ref.get("network_name") or []
            groups = []
            for g in ref.get("provider_groups", []) or []:
                tin = g.get("tin") or {}
                groups.append(
                    {
                        "name": g.get("name") or tin.get("business_name") or (net_names[0] if net_names else ""),
                        "tin_type": tin.get("type", ""),
                        "tin": _num_str(tin.get("value", "")),
                        "npi": [_num_str(n) for n in (g.get("npi") or [])],
                    }
                )
            if gid:
                index[gid] = groups
    except Exception:
        pass
    finally:
        stream.close()
    return index


def parse_mrf(path: str, allowed: set[str], payer: str = "", source_url: str = "") -> Iterator[dict]:
    """Yield one row per negotiated price x provider group, allowlisted codes only.

    `path` must be a local file. Remote files are downloaded to a temp file by
    the caller (see run.py), parsed in two passes, then deleted, so peak disk
    is one compressed MRF and peak output is only the allowlisted codes.
    """
    if not allowed:
        raise ValueError("empty code allowlist: refusing to parse unfiltered (would pull the full MRF)")
    clean = _sanitized_copy(path)
    try:
        yield from _parse_clean(str(clean), allowed, payer, source_url)
    finally:
        clean.unlink(missing_ok=True)


def _parse_clean(path: str, allowed: set[str], payer: str, source_url: str) -> Iterator[dict]:
    providers = _provider_index(path)
    stream = open_local(path)
    try:
        for item in ijson.items(stream, "in_network.item", use_float=True):
            code = str(item.get("billing_code", "")).strip()
            if code not in allowed:
                continue
            for rate in item.get("negotiated_rates", []) or []:
                groups: list[dict] = []
                for gid in rate.get("provider_references", []) or []:
                    key = _num_str(gid)
                    if key in providers:
                        groups.extend(providers[key])
                    elif len(key) == 10 and key.isdigit():
                        # Some payers cite an NPI directly instead of a defined group.
                        groups.append({"name": "", "tin_type": "", "tin": "", "npi": [key]})
                for g in rate.get("provider_groups", []) or []:
                    tin = g.get("tin") or {}
                    groups.append(
                        {
                            "name": g.get("name") or tin.get("business_name") or "",
                            "tin_type": tin.get("type", ""),
                            "tin": _num_str(tin.get("value", "")),
                            "npi": [_num_str(n) for n in (g.get("npi") or [])],
                        }
                    )
                if not groups:
                    groups = [{"name": "", "tin_type": "", "tin": "", "npi": []}]
                for price in rate.get("negotiated_prices", []) or []:
                    for g in groups:
                        yield {
                            "payer": payer,
                            "billing_code": code,
                            "billing_code_type": item.get("billing_code_type", ""),
                            "negotiated_type": price.get("negotiated_type", ""),
                            "negotiated_rate": price.get("negotiated_rate"),
                            "billing_class": price.get("billing_class", ""),
                            "billing_code_modifier": ",".join(price.get("billing_code_modifier") or []),
                            "service_code": ",".join(price.get("service_code") or []),
                            "expiration_date": price.get("expiration_date", ""),
                            "provider_name": g["name"],
                            "tin_type": g["tin_type"],
                            "tin": g["tin"],
                            "npi": ",".join(g["npi"]),
                            "source_url": source_url or path,
                        }
    finally:
        stream.close()


def write_jsonl(rows: Iterator[dict], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
            n += 1
    if n == 0:
        out_path.unlink(missing_ok=True)  # an empty kept-file breaks schema detection on load
    return n

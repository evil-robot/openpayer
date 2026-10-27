from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


@dataclass(frozen=True)
class Code:
    code: str
    code_system: str
    note: str = ""


@dataclass(frozen=True)
class Source:
    payer: str
    source_type: str
    toc_url: str = ""
    direct_mrf_urls: tuple[str, ...] = ()


def load_codes(path: Path | None = None) -> list[Code]:
    raw = json.loads((path or CONFIG_DIR / "codes.json").read_text())
    codes = [
        Code(code=str(c["code"]).strip(), code_system=str(c.get("code_system", "CPT")).strip().upper(), note=str(c.get("note", "")))
        for c in raw.get("codes", [])
        if str(c.get("code", "")).strip()
    ]
    return codes


def code_set(codes: list[Code]) -> set[str]:
    return {c.code for c in codes}


def load_sources(path: Path | None = None) -> list[Source]:
    raw = json.loads((path or CONFIG_DIR / "sources.json").read_text())
    return [
        Source(
            payer=str(s["payer"]),
            source_type=str(s.get("source_type", "tic")),
            toc_url=str(s.get("toc_url", "")).strip(),
            direct_mrf_urls=tuple(s.get("direct_mrf_urls", [])),
        )
        for s in raw.get("sources", [])
    ]

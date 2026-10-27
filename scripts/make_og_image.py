"""Generate the Open Graph share image (1200x630) from the local DuckDB sample.

Run: uv run --extra dev python scripts/make_og_image.py
Writes src/openpayer/assets/og.png. Aggregate rates only; no provider rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw, ImageFont

from openpayer.benchmarks import rates_for_code
from openpayer.config import load_codes

W, H = 1200, 630
INK = (17, 24, 39)
TEAL = (15, 118, 110)
TEAL_100 = (204, 251, 241)
GREY = (107, 114, 128)
RULE = (229, 231, 235)
WHITE = (255, 255, 255)


def font(size: int, bold: bool = False):
    names = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            continue
    return ImageFont.load_default()


def main() -> int:
    codes = load_codes()
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=TEAL)
    d.text((64, 52), "OpenPayer", font=font(64, True), fill=INK)
    d.text((64, 132), "Real rates from the pricing files payers publish.", font=font(30), fill=INK)
    d.text((64, 176), "Real negotiated and fee schedule rates for a short list of billing codes.", font=font(24), fill=GREY)

    all_vals: list[float] = []
    per_code: dict[str, list[float]] = {}
    for c in codes:
        vals = sorted(r["negotiated_rate"] for r in rates_for_code(c.code, limit=2000) if r.get("negotiated_rate") is not None)
        per_code[c.code] = vals
        all_vals.extend(vals)
    xmax = max(all_vals) if all_vals else 100.0
    x0, x1 = 190, 1010
    top = 250
    row_h = 42
    for tick in range(0, int(xmax) + 1, 25):
        x = x0 + tick / xmax * (x1 - x0)
        d.line([x, top - 16, x, top + row_h * len(codes)], fill=RULE)
        d.text((x - 14, top - 40), f"${tick}", font=font(16), fill=GREY)
    for i, c in enumerate(codes):
        y = top + i * row_h + 14
        d.text((64, y - 10), c.code, font=font(21, True), fill=INK)
        vals = per_code[c.code]
        if not vals:
            d.text((x0 + 8, y - 9), "no rates found yet", font=font(18), fill=GREY)
            continue
        p25 = vals[len(vals) // 4]
        p75 = vals[(len(vals) * 3) // 4]
        med = vals[len(vals) // 2]
        d.rectangle([x0 + p25 / xmax * (x1 - x0), y - 7, x0 + p75 / xmax * (x1 - x0), y + 7], fill=TEAL_100)
        for v in vals:
            x = x0 + v / xmax * (x1 - x0)
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=INK)
        mx = x0 + med / xmax * (x1 - x0)
        d.line([mx, y - 10, mx, y + 10], fill=INK, width=3)
        d.text((x1 + 18, y - 10), f"${med:,.0f}", font=font(19, True), fill=INK)
    d.text((64, H - 56), "Source: payer files published under CMS price transparency rules. Sample: Cox HealthPlans. openpayer.medtruth.care", font=font(19), fill=GREY)
    out = Path(__file__).resolve().parents[1] / "src" / "openpayer" / "assets" / "og.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

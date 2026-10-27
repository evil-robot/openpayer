# OpenPayer

Open source payer rate search and benchmarks, built only from data that payers
and hospitals must publish for free under United States price transparency law.

Commercial tools sell access to this same public data. OpenPayer makes the
lookup open: pick a small set of billing codes (about 15), pull only those
codes out of the payer machine-readable files (MRFs), and search real
reimbursement rates by code, payer, and provider, with the source file shown
for every rate.

## Live sample in this repo's demo

The demo is configured for 8 codes and one regional payer to prove the chain
end to end:

- Codes: 99213, 99446, 99447, 99448, 99449, 99451, 99452, G2212
- Payer: Cox HealthPlans, Transparency in Coverage index dated 2026-09-16
- Result of the sample pull: 179 rate rows kept from 23 source files
  (9.1 KB gzipped kept, 780 KB searchable database)

| Code | Rate type | n | p25 | Median | p75 |
|---|---|---|---|---|---|
| 99213 | fee schedule | 34 | $71.73 | $93.73 | $97.97 |
| 99213 | negotiated | 1 | $45.00 | $45.00 | $45.00 |
| 99446 | fee schedule | 14 | $19.48 | $19.57 | $23.20 |
| 99447 | fee schedule | 14 | $38.62 | $38.80 | $46.00 |
| 99448 | fee schedule | 14 | $58.82 | $59.09 | $70.05 |
| 99449 | fee schedule | 14 | $77.97 | $78.33 | $92.85 |
| 99451 | fee schedule | 14 | $38.63 | $38.81 | $46.01 |
| 99452 | fee schedule | 14 | $36.12 | $36.29 | $43.02 |

G2212 returned zero rows in the Cox files pulled. It is a Medicare-specific
HCPCS code and this commercial payer does not publish it in those files. The
demo shows an explicit n=0 for it rather than inventing a number. Rates are
observed values only, grouped by rate type, never blended and never
interpolated. Percentage rates are stored and excluded from dollar benchmarks.

Reproduce it:

```bash
uv sync --extra dev
uv run openpayer-pull --limit=40 --workers=4
uv run openpayer-load
uv run openpayer-serve
```

Open http://127.0.0.1:8000 in a browser.

## Why only a few codes

A single payer MRF can be 100 GB to 10 TB, and the national payer corpus runs
to hundreds of terabytes. Nobody needs to store that to answer questions
about 15 codes. The parser streams each file and keeps only rows whose
billing code is on the allowlist in `config/codes.json`. Everything else is
discarded as it streams past. Peak disk is one compressed MRF at a time.

While the allowlist is empty, the pull refuses to run. That is deliberate:
an unfiltered pull is the firehose.

## Legal basis

- Hospital Price Transparency rule (45 CFR Part 180, from Jan 1, 2021) and
  the Transparency in Coverage rule (from Jul 1, 2022) require publication.
- Executive Order 14221 (Feb 25, 2025) directed faster enforcement.
- The CY 2026 OPPS final rule (effective Jan 1, 2026, enforced Apr 1, 2026)
  requires actual dollar amounts with median, 10th, and 90th percentile
  allowed amounts from remittance data, plus a named executive attestation.
- The Transparency in Coverage final rule CMS-9882-F (Oct 2026, effective
  Dec 7, 2026) standardizes payer files, adds executive attestation, and
  moves updates to quarterly.

Files must be public, free, and require no account.

CPT note: CPT numbers are published with the rates. This project does not
redistribute American Medical Association CPT description text. Add only
your own short notes in `config/codes.json` unless you hold a CPT license.

## Quick start

```bash
uv sync --extra dev
# 1. Edit the code allowlist (nothing downloads while it is empty)
$EDITOR config/codes.json
# 2. Add payer table-of-contents URLs
$EDITOR config/sources.json
# 3. Pull only your codes, then load, then serve
uv run openpayer-pull
uv run openpayer-load
uv run openpayer-serve
```

Dry run (lists files, downloads nothing):

```bash
uv run openpayer-pull --dry-run
```

Useful pull flags: `--limit=N` caps files per payer, `--workers=N` sets
parallel downloads. Downloads time out per file and fail that file, never
the run.

## What the site shows

- Live status and the configured codes
- A Data in the demo today inventory, computed from the database on every
  page load: total rows, kept size on disk, database size, source file
  counts, distinct NPIs, and counts by payer, code, and rate type
- Benchmarks per code, payer, and rate type: n, provider groups, min, p25,
  median, p75, max
- The Market Strip: every code on one shared dollar scale, one dot per
  observed dollar rate (filled = negotiated, hollow = fee schedule), the
  middle half (p25 to p75) shaded, the median marked, n printed per row,
  hover for payer, amount, and provider, and an explicit n=0 row for codes
  with no rates yet
- A per-code page with a dot plot, a See the numbers table, and a source
  file link on every rate
- A JSON API: `/api/codes`, `/api/summary`, `/api/rates/{code}`

What it does not do yet is listed on the landing page itself, with reasons:
NPPES provider geography, percent of Medicare, hospital MRF schema,
scheduled quarterly refresh, contract modeling, and claims repricing (the
last two are out of scope by decision).

## How it works

1. Discover: read each payer table-of-contents JSON and list in-network files.
2. Download one MRF to a temp file, stream-parse it in two passes
   (provider references, then in-network rates filtered to the allowlist),
   write kept rows to `data/raw/*.jsonl.gz`, delete the temp file.
3. Repair real-world dirt on the way in: some payer files are invalid JSON
   (trailing commas), bury provider names in the tax ID block, use bare
   numbers for NPIs and tax IDs, or cite a bare NPI instead of a defined
   provider group. Each has a normalizer and a regression test.
4. Load kept rows into DuckDB (`data/rates.duckdb`, gitignored).
5. Benchmark and serve as above.

## Layout

- `config/codes.json`: the code allowlist (start here)
- `config/sources.json`: payer table-of-contents URLs
- `src/openpayer/ingest/`: discovery, streaming parser, pull CLI
- `src/openpayer/store.py`: DuckDB load
- `src/openpayer/benchmarks.py`: percentile and inventory queries
- `src/openpayer/reference.py`: NPPES and Medicare fee schedule wiring
  (stubs returning None until loaded; the UI shows nothing rather than a
  placeholder number)
- `src/openpayer/api.py`: web UI and JSON API
- `tests/`: filter, guard, dirty-file, and benchmark tests
- `SPEC.md`: the full specification

## Tests

```bash
uv run pytest
```

## Docker

```bash
docker compose up --build
```

Then open http://127.0.0.1:8000.

## Gated hosting (openpayer.medtruth.care)

Set `OPENPAYER_AUTH_SECRET` and the gate turns on: only
@medtruth.care addresses (plus `OPENPAYER_ADMIN_EMAILS`) can sign in,
by emailed magic link with a scanner-proof confirm page and a 90-day
session, the same pattern as the MedTruth site. Variable names are in
`.env.example`. The full deploy handoff, written for the session that
deploys MedTruth services, is in `DEPLOY.md`. With no secret set the
app runs open, for local use.

## License

Apache-2.0. Data remains the public data of its publishers (CMS, payers,
hospitals). See the CPT note above before adding code descriptions.

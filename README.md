# OpenPayer

Open source payer rate search and benchmarks, built only from data that payers
and hospitals must publish for free under United States price transparency law.

Commercial tools sell access to this same public data. OpenPayer makes the
lookup open: pick a small set of billing codes (about 15), pull only those
codes out of the payer machine-readable files (MRFs), and search real
reimbursement rates by code, payer, and provider, with the source file shown
for every rate.

## Live sample in this repo's demo

The demo is configured for 8 codes: 99213, 99446, 99447, 99448, 99449,
99451, 99452, G2212.

Live today: Cox HealthPlans (index dated 2026-09-16), pulled server-side
by the Databricks job on 2026-10-27: 507 rate rows from 53 files, zero
failures. The live site reads these from Lakebase, so its numbers update
with every refresh.

Configured and pulling in bounded first passes (files searched of files
in index is shown live on the site; index sizes measured 2026-10-27):

| Payer | Index | Files in index |
|---|---|---|
| UnitedHealthcare | UnitedHealthcare Insurance Company table of contents | 1,013 |
| Aetna | Aetna Life Insurance Company via the HealthSparq manifest | 5,697 in-network files |
| Cigna | Cigna Health Life Insurance Company table of contents | 101,395 |
| Elevance Anthem BCBS | National Anthem index on S3 | about 43 million (count capped at 250,000 on the site) |
| Humana | Not configured: its published location sits behind a bot wall and no current files were found there for August 2026 | none |

The table below is the first local Cox sample (179 rows from 23 files),
kept as the reproducible starting point; run the pull to regenerate it.

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
parallel downloads, `--group-cap=N` sets the provider-group sample per
file (below). Downloads resume mid-body with Range requests when a payer
drops the connection, time out per attempt, and fail that file only,
never the run.

## What the site shows

- Live status and the configured codes
- The market across payers: aggregate benchmarks per code and rate type
  with the payer count on every row, then one section per payer with its
  own coverage line (index date, pulled date, files searched of files in
  index), its own strip and benchmark table on the same shared scale
- The Market Strip: one row per distinct pay pattern per rate type on a
  shared dollar scale starting at zero. Where a payer publishes identical
  amounts for several codes, those codes share one labeled row instead of
  repeating the same picture. One dot per observed dollar rate (filled =
  negotiated, hollow = fee schedule; at most 240 dots drawn per row,
  evenly spaced, with the row stating how many of n are drawn), the
  middle half (p25 to p75) shaded, the median marked, n printed per row,
  hover or tap for payer, amount, and provider, click to pin the panel
  and open the source file, and an explicit n=0 row for codes with no
  rates yet
- Explore tools: filter every table by code, payer chips that jump to
  each payer section, and CSV and JSON downloads (aggregate, by payer,
  per-code rates, sources)
- A per-code page with a median-by-payer table, payer filter, a dot
  plot, a See the numbers table, and a source file link on every rate
- A data inventory, computed from the database on every page load, plus
  a Data sources and freshness table built live from the pull records
- A JSON API: `/api/codes`, `/api/summary`, `/api/aggregate`,
  `/api/rates/{code}`, `/api/sources`, and `.csv` variants of the
  benchmark and rate endpoints

What it does not do yet is listed on the landing page itself, with reasons:
NPPES provider geography, percent of Medicare, hospital MRF schema,
scheduled quarterly refresh, contract modeling, and claims repricing (the
last two are out of scope by decision).

## How it works

1. Discover: stream each payer table-of-contents JSON (never loaded
   whole; Elevance's index is 4.2 GB) and list in-network files. The
   index count stops at 250,000 entries and is reported as a floor
   ("at least") wherever it appears.
2. Download one MRF to a temp file (JSON, gzipped JSON, or ZIP of
   either; dropped connections resume with Range requests),
   stream-parse it in two passes (provider references, then in-network
   rates filtered to the allowlist), write kept rows, delete the temp
   file. Valid files parse in place; the byte-by-byte sanitizer only
   runs on files that fail to parse.
3. Keep the row grain sane: one national file can name over 100,000
   provider groups and hold millions of rows for 8 codes (one Aetna
   file holds 15.9M). From any file naming more than 2,000 groups, the
   pull keeps the rates of about 300 provider groups, chosen the same
   way in every file by tax ID hash. Benchmarks rest on those kept
   groups and the counts beside them say so.
4. Repair real-world dirt on the way in: some payer files are invalid
   JSON (trailing commas), bury provider names in the tax ID block, use
   bare numbers for NPIs and tax IDs, or cite a bare NPI instead of a
   defined provider group. Each has a normalizer and a regression test.
5. Load kept rows into DuckDB (`data/rates.duckdb`, gitignored) locally,
   or into Lakebase Postgres in production.
6. Benchmark and serve as above.

Production pulls run as one Databricks serverless job per payer, in
parallel, following the house DataSpine pattern: the repo is the truth
the run executes, a per-file ledger (`pulled_files`) records what is
done so a rerun resumes instead of starting over, rows land before any
status row is written (the table is the receipt), and each payer stops
early once every code rests on at least 150 kept provider groups or its
file budget runs out. Credentials for Lakebase are minted per file
load; they expire in about an hour and pulls run longer.

## Layout

- `config/codes.json`: the code allowlist (start here)
- `config/sources.json`: payer table-of-contents URLs
- `src/openpayer/ingest/`: discovery (streaming, resumable), streaming
  parser, pull CLI
- `src/openpayer/store.py`: DuckDB load
- `src/openpayer/pg_store.py`: Lakebase Postgres backend (same query
  contract), pull ledger, source status
- `src/openpayer/benchmarks.py`: percentile and inventory queries
- `src/openpayer/reference.py`: NPPES and Medicare fee schedule wiring
  (stubs returning None until loaded; the UI shows nothing rather than a
  placeholder number)
- `src/openpayer/api.py`: web UI and JSON API
- `databricks/`: per-payer ingest job (serverless) and job definition
- `docs/`: design briefs, including the Market Strip redesign
- `tests/`: parser, dirt, guard, resume, cap, ZIP, TOC, and benchmark
  tests (18)
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

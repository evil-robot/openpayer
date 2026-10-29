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

Live today (checked against the production database on 2026-10-29):
96,201 rate rows from 131 kept files, 3,120 provider groups by tax ID,
read from Lakebase so the numbers update with every pull. The ingest job
also runs on a monthly Databricks schedule; see "How it works".

| Payer | In the corpus | Files | Provider groups | Note |
|---|---|---|---|---|
| Elevance Anthem BCBS | 46,534 rows | 51 | 1,857 | Broadest source; giant national books stay unpulled on purpose |
| Aetna | 38,773 rows | 6 | 196 | Saturated: its other files repeat the same groups |
| UnitedHealthcare | 7,694 rows | 19 | 925 | State books bring new groups; national books repeat one schedule |
| Cigna | 2,693 rows | 2 | 200 | Saturated at the group target |
| Cox HealthPlans | 507 rows | 53 | 0 | Names providers by NPI, no tax IDs, so groups read zero |
| Humana | 0 | 0 | 0 | Parked: no machine-readable index found at its developer portal |

Indexes behind these pulls: UnitedHealthcare 1,013 entries (77 distinct
files), Aetna a direct list of 80 files, Cigna 101,395 files, Elevance at
least 250,000 entries (count capped). The homepage carries a live corpus
meter plus a "The data we reviewed" section with per-payer shape notes,
and `openpayer-data-shape` lessons are kept with the project.

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

- A corpus meter on the homepage: rows, kept files, and provider groups
  per payer with index freshness, computed live from the database
- Fraud, waste, and abuse review flags: each payer and code is compared
  against Medicare (CMS 2026 Physician Fee Schedule) and against peer
  payers. A flag is a review signal with its evidence and what would
  clear it; it is never presented as a finding. Flag dossiers and a
  percent-of-Medicare figure travel with every benchmark
- The market across payers: aggregate benchmarks per code and rate type
  with the payer count on every row, then one section per payer with its
  own coverage line (index date, pulled date, files searched of files in
  index), its own strip and benchmark table on the same shared scale
- Price strips rebuilt for legibility: the mark is a distinct price with
  its provider-group count (stacks at 30 or fewer distinct prices, $5
  bins above), on a zero-based scale shared within each code. Prices
  above the scale are dotted below the row and named in the notes. Hover,
  tap, or keyboard steps price by price, with an exact-price link into
  the code page
- Explore tools: filter every table by code, payer chips that jump to
  each payer section, and CSV and JSON downloads (aggregate, by payer,
  per-code rates, sources, flags)
- A per-code page with a median-by-payer table, payer filter,
  percent-of-Medicare, a See the numbers table, and a source file link
  on every rate
- "The data we reviewed": live counts plus curated per-payer notes on
  what the files look like and what they taught us (for example,
  UnitedHealthcare national books repeat one schedule while its state
  books bring new groups; Cigna serves plain JSON at `.json.gz`
  addresses, so the reader sniffs bytes, not names)
- The CMS pilot prototype at `/pilot/{state}`: synthetic state samples
  for Minnesota, New York, and Florida run through deterministic checks
  (duplicative billing, outside scope, rate mismatch, cash also billed,
  ghost enrollee, billed after death, stacked prescribing), a validation
  gate, entity and ownership tracing, and a printable state one-pager.
  Every pilot page carries a glass box: what is our software, what is
  the invented example (sample file, generation date, fixed seed), how
  each flag is made, and what clears it
- A data inventory, computed from the database on every page load, plus
  a Data sources and freshness table built live from the pull records
- A JSON API: `/api/codes`, `/api/summary`, `/api/aggregate`,
  `/api/rates/{code}`, `/api/sources`, `/api/flags`, and `.csv` variants

Gaps stay explicit on the surface: NPPES provider geography is wired
but not loaded (the CMS bulk host was down), and hospital MRF schema,
contract modeling, and claims repricing are out of scope by decision.

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
load; they expire in about an hour and pulls run longer. File
containers are sniffed from the first bytes (gzip or ZIP magic), never
trusted from the file name. The job is also scheduled monthly on
Databricks (smallest files first), so the corpus keeps widening without
a laptop in the loop; the one recurring human task is rolling the
month-dated payer index addresses forward in `config/sources.json`.
A new file's yield is never assumed: the duplication check counts its
rows whose code, rate type, rate, and tax ID already exist under
another file before anyone calls a payer done.

## Layout

- `config/codes.json`: the code allowlist (start here)
- `config/sources.json`: payer table-of-contents URLs
- `src/openpayer/ingest/`: discovery (streaming, resumable), streaming
  parser, pull CLI
- `src/openpayer/store.py`: DuckDB load
- `src/openpayer/pg_store.py`: Lakebase Postgres backend (same query
  contract), pull ledger, source status
- `src/openpayer/benchmarks.py`: percentile and inventory queries
- `src/openpayer/reference.py`: Medicare fee schedule loader (CMS 2026
  Physician Fee Schedule, loaded; percent-of-Medicare is live) and NPPES
  wiring (loader exists, geography not yet populated; the UI shows
  nothing rather than a placeholder number)
- `src/openpayer/flags.py`: live fraud, waste, and abuse review flags
  against Medicare and peer payers
- `src/openpayer/pilot.py`: the CMS pilot prototype engine (deterministic
  checks, validation gate, entity tracing) over the synthetic state
  samples in `src/openpayer/data/demo/`
- `scripts/make_pilot_states.py`: regenerates the Minnesota, New York,
  and Florida pilot samples (fixed seed per state)
- `src/openpayer/api.py`: web UI and JSON API
- `databricks/`: per-payer ingest job (serverless, monthly schedule)
  and job definition
- `docs/`: design briefs, including the Market Strip redesign, and
  strategy notes
- `tests/`: parser, dirt, guard, resume, cap, ZIP, TOC, benchmark,
  strip, data-reviewed, and pilot tests (56)
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

Set `OPENPAYER_AUTH_SECRET` and the gate turns on: only allowed
addresses can sign in (@medtruth.care and @supertruth.ai domains, the
named Continental Strategy addresses for our lobbyists, plus
`OPENPAYER_ADMIN_EMAILS`), by emailed magic link with a scanner-proof
confirm page and a 90-day session, the same pattern as the MedTruth
site. The sign-in answer is identical for every address, allowed or
not. Variable names are in
`.env.example`. The full deploy handoff, written for the session that
deploys MedTruth services, is in `DEPLOY.md`. With no secret set the
app runs open, for local use.

## License

Apache-2.0. Data remains the public data of its publishers (CMS, payers,
hospitals). See the CPT note above before adding code descriptions.

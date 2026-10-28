# OpenPayer Specification

Version 0.2, October 28, 2026. Status: live Cox sample, national payers pulling, pre-release.

## 1. Purpose

OpenPayer is an open source rate search and benchmark tool over United States
healthcare price transparency data. It answers one question well:

> For a billing code I care about, what do payers actually reimburse,
> by payer and provider, and where does any given rate sit in that market?

Commercial products (PayerPrice, Turquoise Health, Serif Health) sell access
to the same underlying public data. OpenPayer exists so the lookup itself is
open, auditable, and self-hostable.

## 2. Scope

### In scope

- Rate search by billing code, payer, and provider (NPI and tax ID)
- Benchmarks per code, payer, and rate type: count, distinct provider
  groups, minimum, p25, median, p75, maximum
- A small code allowlist (about 15 codes) as the primary scope control
- Payer Transparency in Coverage (TiC) in-network MRFs as the first source
- Server-rendered web UI plus a JSON API
- Full lineage: every stored rate carries its source file URL
- Self-hosting with no paid service, account, or API key

### Out of scope (by decision)

- Contract upload, contract modeling, and negotiation workbooks
- Claims repricing and short-pay detection (requires private remits)
- Patient-facing cost estimates for a specific member or plan
- Any redistribution of AMA CPT description text without a license

### Later, in order

1. Percent of Medicare (Medicare Physician Fee Schedule joined per code)
2. Provider geography and specialty (NPPES join on pulled NPIs only), then
   a map view
3. Hospital Price Transparency MRFs (different schema, second source type)
4. Scheduled quarterly refresh matching the CMS-9882-F cadence
5. Additional national payers, then the long tail of plans
6. A published Parquet dataset for the configured codes

## 3. Legal basis and constraints

- 45 CFR Part 180 (Hospital Price Transparency, 2021) and the Transparency
  in Coverage rule (2022) require hospitals and payers to publish
  machine-readable files (MRFs) publicly, free, with no account.
- Executive Order 14221 (2025) directed enforcement. The CY 2026 OPPS final
  rule requires actual dollar amounts, median and 10th/90th percentile
  allowed amounts from 835 remittance history (12 to 15 month lookback),
  and a named executive attestation. CMS-9882-F (Oct 2026, effective
  Dec 7, 2026) standardizes TiC files, adds payer executive attestation,
  and moves TiC updates to quarterly.
- CPT is AMA property. The system stores and displays code numbers and
  rates (facts) and MUST NOT store or redistribute AMA description text,
  ordering, or editorial structure. User notes must be original short text.
- The underlying files contain no member PHI. Rates are provider-level
  contract facts. If a future feature touches claims, it leaves this spec
  and needs its own privacy review.

## 4. Users

- Provider contracting and finance teams benchmarking a fee schedule
- Independent practices checking whether a rate is below market
- Analysts and researchers who need a cited rate, not a sales demo
- Developers building on the JSON API or the kept dataset

## 5. Data sources

| Source | What | Cadence | Status |
|---|---|---|---|
| Payer TiC index (table of contents) JSON | Links to every in-network MRF per plan | Quarterly (CMS-9882-F) | Live |
| Payer TiC in-network MRFs | Negotiated rates by code and provider group | Quarterly | Live |
| NPPES NPI registry (CMS) | Provider name, practice address, taxonomy | Monthly | Stubbed |
| Medicare Physician Fee Schedule (CMS) | Medicare rate per code and locality | Annual/quarterly | Stubbed |
| Hospital Price Transparency MRFs | Standard charges per hospital | Annual | Planned |

Discovery: each payer publishes a table-of-contents JSON. The system reads
`reporting_structure[].in_network_files[].location` plus plan metadata.
Sources are configured in `config/sources.json`. A source with no URL is
skipped.

Configured payers (measured 2026-10-27): Cox HealthPlans (index 2026-09-16,
89 files); UnitedHealthcare (UnitedHealthcare Insurance Company index,
1,013 files); Aetna (Aetna Life Insurance Company via the HealthSparq
manifest at `mrf.healthsparq.com`, 5,697 deduped in-network files);
Cigna (Cigna Health Life Insurance Company index, 101,395 files, mixed
`.json.gz` and `.zip` payloads); Elevance Anthem BCBS (national S3
index, about 43 million files). Humana is intentionally unconfigured:
its published location sits behind a bot wall and trackers found no
current files there (none for August 2026). Indexes are republished
monthly with the month in the file name; dated URLs are bumped at each
refresh.

## 6. The code allowlist (core design decision)

National payer data is hundreds of terabytes. OpenPayer never stores it.

- `config/codes.json` holds the allowlist: `{code, code_system, note}`.
  Supported systems today: CPT, HCPCS. The schema also accepts MS-DRG,
  REV, and NDC for later parsers.
- The parser streams each MRF and keeps a row only when its billing code
  is on the allowlist. All other content is discarded in flight.
- Invariant: an empty allowlist MUST make the pull a no-op that exits
  nonzero with an explanation. This is tested.
- Consequence: the kept dataset for about 15 codes stays in megabytes
  even across many payers, and peak disk during a pull is one compressed
  MRF (downloaded to temp, parsed, deleted).

Sample state (Oct 28, 2026): codes 99213, 99446, 99447, 99448, 99449,
99451, 99452, G2212. Cox HealthPlans is fully pulled (507 rows from 53
files). The four national payers above are configured and pull in
bounded first passes (section 7). G2212 returned zero rows at Cox and
is reported as n=0; a full scan of one Aetna file shows Aetna does
publish G2212 rates, so its state updates when the Aetna pull lands.
See README for the benchmark table.

## 7. Ingest pipeline

Entry points: `openpayer-pull [--dry-run] [--limit=N] [--workers=N]
[--group-cap=N]` locally, and the Databricks job
(`databricks/ingest_job.py`, parameters `limit`, `only`, `workers`,
`group_cap`) in production. One job run per payer, in parallel.

1. Load allowlist and sources. Refuse to run with an empty allowlist.
2. For each payer, stream the index (never loaded whole; the largest is
   4.2 GB) and enumerate in-network file URLs. `--limit` caps the
   count, for samples and smoke tests. The index count stops at
   250,000 entries and is flagged as a floor when capped.
3. Process files with a bounded worker pool (default 4 local, 2 on
   serverless; four concurrent gigabyte files exhausted serverless
   memory):
   a. Stream-download one file to a temp file (`.json`, `.json.gz`, or
      `.zip` of either; the largest ZIP member is the rate file).
      Dropped bodies resume with Range requests (up to 10 resumes;
      UnitedHealthcare cut a 15.2 GB file at 2.8 GB). Per-attempt
      timeouts (30s connect, 180s read). A failure fails that file
      only and is logged.
   b. Parse valid files in place. Only a file that fails to parse pays
      for the sanitized copy that drops commas directly preceding `]`
      or `}` outside strings (trailing commas make some payer files
      invalid JSON). String-aware, streaming, tested.
   c. Pass 1: index `provider_references` by group ID. Provider name
      resolution order: group name, then TIN `business_name`, then the
      reference `network_name`. IDs and NPIs normalized from bare JSON
      numbers to clean strings.
   d. Provider-group sample: when a file names more than 2,000 groups,
      only about 300 groups are kept, ranked by a stable hash of the
      tax ID (else first NPI, else name), so the same providers are
      kept in every file. One national file can otherwise emit over
      15 million rows for 8 codes. `--group-cap` sets the target;
      `--group-cap=` (empty) disables it.
   e. Pass 2: stream `in_network` items. Skip non-allowlisted codes.
      For each negotiated price and kept provider group, emit one row.
      A 10-digit provider reference that matches no defined group is
      treated as a bare NPI (some payers cite NPIs directly) and is
      subject to the same sample.
   f. Locally, write kept rows to `data/raw/{payer}-{index}.jsonl.gz`
      (a zero-row file writes nothing). In production, COPY kept rows
      into Lakebase and record the file in the `pulled_files` ledger;
      a rerun counts ledgered files from the ledger and skips them.
4. Coverage stop (production): after each worker wave, stop the payer
   when every allowlisted code rests on at least 150 kept provider
   groups, or when the file budget runs out.
5. Status last: a payer's `source_status` row is upserted only after
   its files finish, with files attempted, files with rows, rows kept,
   failures, the index date, the index count (with capped flag), and
   the pull time. One file's failure never aborts the run.

Output row (one per price x provider group):

`payer, billing_code, billing_code_type, negotiated_type, negotiated_rate,
billing_class, billing_code_modifier, service_code, expiration_date,
provider_name, tin_type, tin, npi, source_url, loaded_file (added at load)`

AMA description text from the MRF is intentionally not stored.

## 8. Storage and benchmarks

Two backends, one query contract, chosen by `OPENPAYER_STORE`:

- Local: `openpayer-load` loads every `data/raw/*.jsonl.gz` into DuckDB
  at `data/rates.duckdb` (table `rates`), rebuilding the table each
  run. Unreadable kept files are skipped with a log line.
- Production: Lakebase Postgres (Databricks managed), database
  `openpayer` on the ar-fleet instance. Tables: `rates`,
  `source_status` (one row per payer, section 7 step 5), and
  `pulled_files` (the per-file ledger). The web app reads through a
  SELECT-only role; the ingest job mints a fresh Lakebase credential
  per file load because credentials expire in about an hour. Note:
  the `npi` column holds comma-joined NPI lists and MUST NOT be
  indexed (btree row-size limit fails whole file loads).

Benchmark query contracts (`benchmarks.py`, `pg_store.py`):

- `summary_by_code_payer`: group by billing code, code type, payer,
  and negotiated type. `summary_all_payers`: group by billing code,
  code type, and negotiated type across payers, with the payer count
  on every row. Rate types are never blended in either.
- Dollar benchmarks include every rate type except `percentage`
  (percentages are not dollars). Fee schedule and negotiated rates are
  benchmarked as separate rows.
- Statistics: count of rates, count of distinct non-empty TINs,
  minimum, p25, median, p75, maximum via `quantile_cont` (linear
  interpolation between closest ranks; observed dots are never
  interpolated).
- Nothing is winsorized or estimated. A benchmark always travels with
  its n, and an aggregate always travels with its payer count.

Inventory query contract (`benchmarks.data_inventory`): total rows,
source file count, distinct NPIs, kept raw size on disk, database size,
and counts by payer, code, and rate type. The landing page renders this
live so the site can never overstate its own data.

## 9. Presentation

Entry point: `openpayer-serve` (FastAPI, server-rendered, no build step).

### Landing page `/`

1. Headline computed from the aggregate 99213 row (payer count, median,
   middle half, n), a plain-English lede, and a coverage line naming
   every payer with its index date and pull date
2. Explore tools: code filter for every table, payer chips, CSV and
   JSON download links
3. The market across payers: aggregate Market Strip and aggregate
   benchmark table (code, rate type, payers, rates, provider groups,
   p25, median, p75, min, max)
4. One section per payer: coverage line (files searched of files in
   index, with the capped flag where it applies), its own strip and
   benchmark table on the same shared dollar scale, code links
   pre-filtered to that payer
5. Data sources and freshness: every configured source with index
   date, pull date, files searched, rows kept, and a freshness verdict,
   built live from `source_status` and the config
6. Data volume (live inventory, section 8) under a disclosure
7. What this system does today and what it does not do yet, each gap
   with its reason, under disclosures

### Code page `/code/{code}`

Median-by-payer table, payer filter chips (`?payer=`), dot plot of the
code's dollar rates (one dot per rate, median marked, hover shows the
amount), then a See the numbers table: payer, rate, rate type,
provider, TIN, and a source file link per row, plus CSV and JSON
download of the same rates.

### JSON API

- `GET /api/codes`: configured allowlist
- `GET /api/summary`: per-payer benchmark rows as JSON
- `GET /api/aggregate`: all-payer benchmark rows as JSON
- `GET /api/rates/{code}?payer=`: individual rates (dollar types only)
- `GET /api/sources`: configured sources with pull status
- `.csv` variants: `/api/summary.csv`, `/api/aggregate.csv`,
  `/api/rates/{code}.csv`
- No data yet returns 404 with a plain reason, never a stack trace

## 10. Visualization: the Market Strip

Purpose: let a reader compare, at a glance, where rates for each code
sit and how wide each market spreads. Comparison sentence: for each
code, most rates cluster in the middle half, and a rate below p25 is in
the cheapest quarter.

Encoding rules (these are requirements, not style):

- Small multiples on ONE shared dollar scale with labeled ticks every
  $25 from $0: the aggregate strip and every per-payer strip on the
  page use the same scale. Like compares with like; scale never
  changes per row.
- One row per distinct pay pattern per rate type. Where a payer
  publishes the identical dollar amounts for several codes, those
  codes share one row labeled with every code it covers; the per-code
  facts live in the tables. (Redesign after the first production data
  repeated one distribution six times; see
  `docs/DESIGN-STRIP-REDESIGN.md`.)
- Dots are observed dollar rates at true positions. Lie factor 1:
  position is the value, no area or size encoding of quantity. At most
  240 dots are drawn per row, evenly spaced after sorting, and the row
  states how many of n are drawn; every rate remains in the tables,
  downloads, and code pages.
- Middle half: the p25 to p75 interval is a light grey band behind the
  dots. It is a percentile interval of observed rates, explicitly not a
  confidence interval, and the caption says so.
- Median: a thick vertical tick, with median, middle-half range, and n
  printed as text at the right of every row.
- Rate type by shape, redundantly with the legend in words: filled dot
  = negotiated, hollow dot = fee schedule. The chart must survive a
  grey photocopy and a colorblind reader. House palette only: ink
  (#13151E), cream (#F0EEEB), and greys. No accent color.
- Percentage rates are excluded (not dollars) and the exclusion is
  stated on the surface.
- Missing data is explicit: a code with no dollar rates renders a row
  reading "No dollar rates found in the files pulled so far" with n=0.
  Absence is never rendered as a rate of zero.
- Interaction: hover (or tap) a dot reveals payer, rate type, amount,
  and provider or NPI. Hover is an addition, never the only path: the
  benchmark table above and the code page table carry every value in
  text, and the SVG carries a role and text description for screen
  readers.
- Documentation on the surface: source payer, index date, and the fact
  that counts are observed rates appear directly under the chart.

## 11. Reference data (stubbed, contracts fixed)

`reference.py` defines the joins. Both return None today, and the UI
shows nothing (never a placeholder number) until real data loads:

- `nppes_lookup(npi)`: provider name, city, state, ZIP, taxonomy.
  The loader must join only NPIs present in kept rates.
- `medicare_rate(code, locality)`: MPFS rate, enabling a percent of
  Medicare column in benchmarks and on the Market Strip.

## 12. Quality and testing

- Tests live in `tests/` and run with `uv run pytest` (18 tests).
  Current coverage: allowlist filtering, the empty-allowlist guard,
  trailing-comma repair with real payer dirt shapes (name in TIN
  block, bare-number IDs, a comma inside text), bare-NPI references,
  ZIP-wrapped files, streaming index reads with the capped count,
  resumable downloads against a server that drops connections on
  purpose, the provider-group sample (fixed and deterministic), and
  benchmark math including rate-type separation and aggregate payer
  counts.
- Rule: every new payer dirt shape found in the wild gets a failing
  test first, then the normalizer.
- A pull over a new payer is not done until its kept rows load and its
  benchmarks render.

## 13. Operations

- Runtime: Python 3.12+, managed with uv (`.venv` inside the project).
  DuckDB locally, Lakebase Postgres in production.
- Web: Railway service `openpayer` in the MedTruth project, gated to
  @medtruth.care magic-link sign-in (see DEPLOY.md). Railway routes
  traffic only after `/health` answers, so deploys do not 502
  sign-ins. All pages carry `noindex`.
- Pulls: one Databricks serverless job run per payer
  (`openpayer-ingest`, job 525519863957852), in parallel, following the
  house DataSpine pattern: repo is the executed truth, per-file ledger
  makes runs resumable, rows land before status (the table is the
  receipt). Workers 2 per run (memory), no job timeout, per-file
  Lakebase credential mints.
- Docker: `docker compose up --build` serves on port 8000 with `HOST`
  and `PORT` environment overrides.
- Cadence: payer indexes republish monthly under dated file names, so
  each refresh bumps the dates in `config/sources.json`; pulls refresh
  quarterly to match CMS-9882-F. A rerun skips ledgered files, so a
  refresh only pays for new files.
- Failure posture: per-file failures are logged and counted; the run
  reports totals. The site degrades to explicit empty states.

## 14. Decisions taken

| Decision | Choice | Why |
|---|---|---|
| License | Apache-2.0 | Widest reuse; dataset stays public data |
| Scope control | Code allowlist, about 15 codes | Avoids the national firehose entirely |
| Store | DuckDB, local file | Column scans for benchmarks; zero operations |
| UI | Server-rendered, no JS build | Shareable page, works anywhere, crawlable |
| CPT text | Numbers and rates only | AMA owns description text |
| Rate types | Benchmarked separately, percentages out of dollars | Types are different facts; never blend |
| Production store | Lakebase Postgres | Databricks Jobs write, web app reads; one contract with DuckDB |
| Row grain | About 300 provider groups per large file, fixed by tax-ID hash | One national file otherwise emits 15M+ rows for 8 codes |
| Pull shape | One Databricks job run per payer, ledgered, coverage stop at 150 groups per code | A sequential all-payer run timed out at 4 hours; reruns must resume |
| Pull pattern | DataSpine operating pattern (repo as truth, receipt before status) | The house system already proved it on 100+ sources |

## 15. Open questions

- G2212 and other Medicare-specific HCPCS: Cox publishes none, but a
  full scan of one Aetna file found 2.26M G2212 rows, so commercial
  publication exists. Its benchmark state settles when the Aetna pull
  lands; the MPFS loader remains the fallback reference.
- Humana: no readable index exists today (bot-walled published
  location, no current files found). Recheck monthly; add with a
  config-only change when one appears.
- Long-tail coverage: at what payer count does the hosted demo need
  object storage for kept extracts, and who pays for it? (Kept data is
  megabytes today; bandwidth and scan time, not storage, are the
  costs: one Aetna file is 1.1 GB compressed and about 18 minutes to
  scan; UnitedHealthcare files run to 15 GB with dropped connections.)
- AMA license for the hosted demo if code descriptions are ever shown?

## 16. Acceptance criteria for v0.1

- [x] Pull, load, and serve run end to end on a fresh clone
- [x] Empty allowlist provably downloads nothing
- [x] Sample: 8 codes against a live payer, benchmarks and Market Strip
      rendered from real pulled rates, n shown everywhere
- [x] Every rate links to its source payer file
- [x] Landing page states capabilities, data volume, and gaps honestly
- [x] Test suite green
- [ ] Second payer (one national) pulled with the same config-only change
- [ ] Four national payers live with coverage lines and payer counts
      matching the database
- [ ] NPPES names and geography on kept providers
- [ ] Percent of Medicare on benchmarks

# OpenPayer Specification

Version 0.3, October 29, 2026. Status: live at openpayer.medtruth.care
(MedTruth-gated). Corpus: 96,201 rate rows from 131 kept files across
five payers, 3,120 provider groups, plus the CMS pilot prototype with
three synthetic state samples. Pre-release; a rename decision is open
(see docs/STRATEGY.md).

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

1. Provider geography and specialty (NPPES join on pulled NPIs only), then
   a map view (loader ready, waiting on the CMS bulk host)
2. Hospital Price Transparency MRFs (different schema, second source type)
3. Additional national payers, then the long tail of plans
4. A published Parquet dataset for the configured codes

Done since 0.2: percent of Medicare (live, section 11), review flags
with dossiers, the pilot prototype with three synthetic state samples
and its glass box, and a monthly scheduled refresh (section 13; the
cadence tightens to quarterly with CMS-9882-F).

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
| NPPES NPI registry (CMS) | Provider name, practice address, taxonomy | Monthly | Loader ready, not populated (CMS bulk host down) |
| Medicare Physician Fee Schedule (CMS) | Medicare rate per code and locality | Annual/quarterly | Live (national rates; locality later) |
| Hospital Price Transparency MRFs | Standard charges per hospital | Annual | Planned |

Discovery: each payer publishes a table-of-contents JSON. The system reads
`reporting_structure[].in_network_files[].location` plus plan metadata.
Sources are configured in `config/sources.json`. A source with no URL is
skipped.

Configured payers (corpus measured live 2026-10-29): Elevance Anthem
BCBS 46,534 rows / 51 files / 1,857 provider groups (national S3 index,
at least 250,000 entries, count capped); Aetna 38,773 / 6 / 196 (direct
list of 80 files, saturated); UnitedHealthcare 7,694 / 19 / 925 (index
1,013 entries, 77 distinct files); Cigna 2,693 / 2 / 200 (index 101,395
files, mixed `.json.gz` and `.zip` payloads); Cox HealthPlans 507 / 53 /
0 groups (89-file index exhausted; NPI-only files, no tax IDs). Humana
is parked: its files sit behind a developer portal and no
machine-readable index has been found; it stays configured with an
empty source so the gap is visible. Indexes are republished monthly
with the month in the file name; dated URLs are bumped at each refresh.
A payer-declared index date in the future (UnitedHealthcare declared
2026-11-01 on a file pulled 2026-10-28) is shown as declared, never
clamped to today.

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

Sample state (Oct 29, 2026): codes 99213, 99446, 99447, 99448, 99449,
99451, 99452, G2212. Corpus 96,201 rows (per-payer counts in section 5).
G2212 is published by the national payers but unevenly: hundreds of
groups at UnitedHealthcare, nearly absent at Elevance (3 groups), and
n=0 at Cox, reported as n=0. A provider group is always a distinct
non-empty tax ID, the same definition in charts, tables, flags, and
the corpus meter; a rate filed without a tax ID counts as a rate,
never as a group. Rows inflate when plan books repeat one schedule, so
every count travels with its group count and distinct-price count.
A new file's yield is never assumed from its payer: the duplication
check counts rows whose (code, rate type, rate, tax ID) already exist
under another file. UnitedHealthcare's first large book scored
967/967 duplicates; a later state book scored 288/3,214 and tripled
its consult-code groups. See README for the benchmark table.

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

### Homepage additions

- Corpus meter: per-payer rows, kept files, provider groups, and index
  freshness, computed live on every load
- Fraud, waste, and abuse review flags (`src/openpayer/flags.py`):
  payer-by-code medians far above Medicare, extreme rates, placeholder
  rates, one amount across many groups, and codes a payer does not
  publish. Each flag carries its evidence and its Medicare basis and
  links to a dossier at `/flag`. Flags are review signals, never
  findings, and the wording says so at every appearance
- "The data we reviewed": live counts plus curated per-payer shape
  notes and corpus lessons, so a reader can judge the numbers above it
- Percent of Medicare on benchmarks and code pages (section 11)

### Pilot prototype `/pilot/{state}`

The pre-claim corpus answers what rates should be. The pilot answers
what happens when CMS hands over one state's claims and records.

- Routes: `/pilot/{state}` (dashboard), `/pilot/{state}/flag/{id}`,
  `/pilot/{state}/entity/{id}`, `/pilot/{state}/enrollee/{id}`,
  `/pilot/{state}/onepager`. `/pilot` and `/pilot/onepager` redirect
  to Minnesota. Unknown states render a plain not-found page
- States loaded: Minnesota, New York, Florida. Every state sample is
  synthetic and bannered as invented on every page; no real patient,
  provider, or claim appears anywhere
- Samples are generated by `scripts/make_pilot_states.py` (one fixed
  seed per state, per-state counties, entities, and providers, the
  same planted cases). Each sample carries its file name, generation
  date, generator, and seed, and the pages print them
- Checks (`src/openpayer/pilot.py`, deterministic, no models):
  duplicative billing, outside scope of practice, specialist vs GP
  rate mismatch, cash-pay service also billed, ghost enrollee, billed
  after death, stacked prescribing. Flags recompute from the sample
  on every page load; nothing is stored
- Validation gate: enrollee scores out of 10 (identity, condition,
  continuity); below 8 routes to review. Housing status is context
  for outreach and is never scored
- Entity trace: provider, billing entity, parent, siblings tied by
  parent, address, owner, or registered agent, with flagged dollars
  across the ownership web
- Glass box (requirement, not copy): every pilot page separates what
  is our software (engine, gate, tracing, pricing ruler) from what is
  the invented example, and every check is stated with what it
  compares, the exact condition that fires it (`CHECK_GUIDE`), and
  what would clear it. The one-pager repeats the separation, names
  its sample provenance, and ends with the ask: an ATO and a sandbox
  in a jurisdiction of CMS's choosing for a defined pilot term
- The standalone offline version lives in the cms-pilot-demo project;
  keep the check logic in sync

### JSON API

- `GET /api/codes`: configured allowlist
- `GET /api/summary`: per-payer benchmark rows as JSON
- `GET /api/aggregate`: all-payer benchmark rows as JSON
- `GET /api/rates/{code}?payer=`: individual rates (dollar types only)
- `GET /api/sources`: configured sources with pull status
- `GET /api/flags`, `/api/flags.csv`: live review flags
- `.csv` variants: `/api/summary.csv`, `/api/aggregate.csv`,
  `/api/rates/{code}.csv`
- No data yet returns 404 with a plain reason, never a stack trace

## 10. Visualization: the Market Strip

Purpose: let a reader compare, at a glance, where rates for each code
sit and how wide each market spreads. Comparison sentence: for each
code, most rates cluster in the middle half, and a rate below p25 is in
the cheapest quarter.

Encoding rules (these are requirements, not style):

- Small multiples on a zero-based dollar scale shared within each
  code, with labeled ticks: like compares with like; scale never
  changes inside a code. The scale covers the middle 99 percent of the
  code's observed rates; prices above it are drawn dotted below the
  row at their true value and named in the notes, never clipped
  silently.
- One row per distinct pay pattern per rate type. Where a payer
  publishes the identical dollar amounts for several codes, those
  codes share one row labeled with every code it covers; the per-code
  facts live in the tables. (Redesign after the first production data
  repeated one distribution six times; see
  `docs/DESIGN-STRIP-REDESIGN.md`.)
- The mark is a distinct observed price, printed with its
  provider-group count: one mark per price at its true position when
  a row has 30 or fewer distinct prices, $5 bins above that. Lie
  factor 1: position is the value, and the count is printed as a
  number beside the mark, never encoded as area or size. Every rate
  remains in the tables, downloads, and code pages.
- Middle half: the p25 to p75 interval is a light grey band behind the
  marks. It is a percentile interval of observed rates, explicitly not a
  confidence interval, and the caption says so.
- Median: a thick vertical tick, with median, middle-half range, and n
  printed as text at the right of every row.
- Rate type by shape, redundantly with the legend in words: filled
  mark = negotiated, hollow mark = fee schedule. The chart must survive
  a grey photocopy and a colorblind reader. MedTruth palette only:
  white, gray-900 ink, teal, gold, and greys.
- Percentage rates are excluded (not dollars) and the exclusion is
  stated on the surface.
- Missing data is explicit: a code with no dollar rates renders a row
  reading "No dollar rates found in the files pulled so far" with n=0.
  Absence is never rendered as a rate of zero.
- Interaction: hover, tap, or keyboard focus on a mark opens a panel
  that steps price by price, then group by group inside a price, with
  the exact price linked into the code page. Interaction is an
  addition, never the only path: the benchmark table above and the
  code page table carry every value in text, and the SVG carries a
  role and text description for screen readers.
- Documentation on the surface: source payer, index date, and the fact
  that counts are observed rates appear directly under the chart.

## 11. Reference data

`reference.py` defines the joins. The UI shows nothing (never a
placeholder number) where a join has no data:

- `medicare_rate(code)`: LIVE. CMS 2026 Physician Fee Schedule
  (RVU26A) national rates are bundled at
  `src/openpayer/data/reference/mpfs.json` (rebuild with
  `scripts/pull_mpfs.py`). Percent of Medicare is computed per code
  and shown on benchmarks, code pages, flags, and the pilot ruler.
  Locality (GPCI) adjustment is not applied; locality rates remain a
  later step.
- `nppes_lookup(npi)`: provider name, city, state, ZIP, taxonomy.
  Loader exists (`scripts/pull_nppes.py`); geography is not populated
  because the CMS NPPES bulk host was down when attempted. 5,041
  corpus NPIs are queued for the join. The loader joins only NPIs
  present in kept rates.

## 12. Quality and testing

- Tests live in `tests/` and run with `uv run pytest` (56 tests).
  Current coverage: allowlist filtering, the empty-allowlist guard,
  trailing-comma repair with real payer dirt shapes (name in TIN
  block, bare-number IDs, a comma inside text), bare-NPI references,
  ZIP-wrapped files, plain JSON served at `.json.gz` addresses
  (container sniffed from bytes), streaming index reads with the
  capped count, resumable downloads against a server that drops
  connections on purpose, the provider-group sample (fixed and
  deterministic), benchmark math including rate-type separation and
  aggregate payer counts, strip rendering (distinct prices, group
  counts, per-code scales), "The data we reviewed" (live counts,
  never typed), and the pilot: planted cases per state, gate scoring,
  entity traces, state registry, and the glass box.
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
  Lakebase credential mints. `smallest_first` ordering (size from HEAD
  on the first 5,000 index entries) buys cheap coverage; giant books
  (2.5 to 9.4 GB, hours each) are opened one at a time, deliberately.
- Unattended: the job is scheduled monthly on Databricks (1st, 11:00
  UTC, limit 60, workers 1, group cap 300, smallest first, one
  concurrent run, failure email to the operator), mirrored in
  `databricks/job.json`. No laptop is in the loop. The one recurring
  human task is rolling the month-dated index addresses forward in
  `config/sources.json`; until that is done, scheduled runs re-read
  the current indexes and the corpus meter ages honestly.
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
| Pilot checks | Deterministic rules only, no models | Same input, same answer; a CMS reviewer can state every rule in one sentence |
| Pilot data | Synthetic state samples, generated, seeded, bannered | Shows the software without anyone's records; planted cases give known right answers |
| Glass box | Real software vs invented example, every check with what clears it, on every pilot page | The audience must never mistake an example for evidence, or a flag for a finding |
| Refresh | Monthly Databricks schedule, smallest first; giant books deliberate | Keeps the corpus widening unattended without paying hours per book by default |
| New-file yield | Duplication check per file before calling a payer done | One UnitedHealthcare book was 967/967 duplicates; the next was 288/3,214. Payer-level guesses fail |

## 15. Open questions

- Product name: Trek Health launched a product called OpenPayer in
  February 2026, in this field, before this repo existed. The gated
  demo is unaffected; a public launch under this name is exposed.
  Rename before any public launch (candidates and evidence in
  docs/STRATEGY.md). Decision: JAS.
- UnitedHealthcare state books: one landed book brought about 200 new
  groups per code, so the remaining state books are real coverage,
  at hours each. Pull them one at a time on purpose, or leave them
  to the monthly smallest-first schedule, which will not reach them
  soon. Decision: JAS.
- Elevance giant national books: unpulled, hours each, with memory
  failures at higher worker counts. Open deliberately or not at all.
- NPPES geography: loader ready, CMS bulk host was down. Retry, then
  enable dossier geography and later a GPCI locality ruler. Exposure
  math, when it lands, must be labeled modeled, never observed loss.
- Humana: no readable machine-readable index found (developer portal
  only). Recheck monthly; add with a config-only change when one
  appears.
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
- [x] Test suite green (56 tests)
- [x] Second payer (one national) pulled with the same config-only change
- [x] Four national payers live with coverage lines and payer counts
      matching the database (96,201 rows, verified 2026-10-29)
- [x] Percent of Medicare on benchmarks, code pages, and flags
- [x] Review flags with dossiers, corpus meter, "The data we reviewed"
- [x] Pilot prototype: three synthetic state samples, glass box,
      validation gate, entity tracing, printable one-pagers
- [x] Monthly unattended ingest schedule on Databricks
- [ ] NPPES names and geography on kept providers

# OpenPayer Specification

Version 0.1, October 27, 2026. Status: sample-proved, pre-release.

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

Sample state (Oct 27, 2026): codes 99213, 99446, 99447, 99448, 99449,
99451, 99452, G2212 against Cox HealthPlans. 179 rows kept from 23 files.
G2212 (Medicare-specific HCPCS) returned zero rows and is reported as
n=0. See README for the benchmark table.

## 7. Ingest pipeline

Entry point: `openpayer-pull [--dry-run] [--limit=N] [--workers=N]`.

1. Load allowlist and sources. Refuse to run with an empty allowlist.
2. For each payer, load the index and enumerate in-network file URLs
   (`--limit` caps the count, for samples and smoke tests).
3. Process files with a bounded worker pool (default 4):
   a. Stream-download one file to a temp file. Per-file timeouts
      (30s connect, 180s read). A timeout or HTTP error fails that file
      only and is logged.
   b. Sanitize: produce a cleaned copy that drops commas directly
      preceding `]` or `}` outside strings (trailing commas make some
      payer files invalid JSON). String-aware, streaming, tested.
   c. Pass 1: index `provider_references` by group ID. Provider name
      resolution order: group name, then TIN `business_name`, then the
      reference `network_name`. IDs and NPIs normalized from bare JSON
      numbers to clean strings.
   d. Pass 2: stream `in_network` items. Skip non-allowlisted codes.
      For each negotiated price and provider group, emit one row.
      A 10-digit provider reference that matches no defined group is
      treated as a bare NPI (some payers cite NPIs directly).
   e. Write kept rows to `data/raw/{payer}-{index}.jsonl.gz`. A file
      with zero kept rows writes no file (empty files break schema
      detection downstream). Delete temp files.
4. Report kept rows per file and in total. One file's failure never
   aborts the run.

Output row (one per price x provider group):

`payer, billing_code, billing_code_type, negotiated_type, negotiated_rate,
billing_class, billing_code_modifier, service_code, expiration_date,
provider_name, tin_type, tin, npi, source_url, loaded_file (added at load)`

AMA description text from the MRF is intentionally not stored.

## 8. Storage and benchmarks

Entry point: `openpayer-load`. Loads every `data/raw/*.jsonl.gz` into
DuckDB at `data/rates.duckdb` (table `rates`), rebuilding the table each
run. Unreadable kept files are skipped with a log line. Data files are
gitignored; the database is a build artifact of the pull.

Benchmark query contract (`benchmarks.summary_by_code_payer`):

- Group by billing code, code type, payer, and negotiated type. Rate
  types are never blended.
- Dollar benchmarks include every rate type except `percentage`
  (percentages are not dollars). Fee schedule and negotiated rates are
  benchmarked as separate rows.
- Statistics: count of rates, count of distinct non-empty TINs,
  minimum, p25, median, p75, maximum via `quantile_cont`.
- Nothing is interpolated, winsorized, or estimated. A benchmark always
  travels with its n.

Inventory query contract (`benchmarks.data_inventory`): total rows,
source file count, distinct NPIs, kept raw size on disk, database size,
and counts by payer, code, and rate type. The landing page renders this
live so the site can never overstate its own data.

## 9. Presentation

Entry point: `openpayer-serve` (FastAPI, server-rendered, no build step).

### Landing page `/`

1. What OpenPayer is and its legal basis, in plain English
2. Live status (no codes / codes but no pull / live with data) and the
   configured code list
3. Data in the demo today (live inventory, section 8)
4. Benchmark table (code, payer, rate type, n, provider groups, p25,
   median, p75), each code linking to its code page
5. The Market Strip (section 10)
6. What this system does today: a complete capability inventory
7. What it does not do yet: each gap with its reason and what changes it

### Code page `/code/{code}`

Dot plot of the code's dollar rates (one dot per rate, median marked,
min and max labeled, hover shows the amount), then a See the numbers
table: payer, rate, rate type, provider, TIN, and a source file link per
row.

### JSON API

- `GET /api/codes`: configured allowlist
- `GET /api/summary`: benchmark rows as JSON
- `GET /api/rates/{code}?payer=`: individual rates (dollar types only)
- No data yet returns 404 with a plain reason, never a stack trace

## 10. Visualization: the Market Strip

Purpose: let a reader compare, at a glance, where rates for each code
sit and how wide each market spreads. Comparison sentence: for each
code, most rates cluster in the middle half, and a rate below p25 is in
the cheapest quarter.

Encoding rules (these are requirements, not style):

- Small multiples: one horizontal strip per code, all rows on ONE shared
  dollar scale with labeled ticks every $25 from $0. Like compares
  with like; scale never changes per row.
- One dot per observed dollar rate at its true position. Lie factor 1:
  position is the value, no area or size encoding of quantity.
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

- Tests live in `tests/` and run with `uv run pytest`. Current coverage:
  allowlist filtering, the empty-allowlist guard, trailing-comma repair
  with real payer dirt shapes (name in TIN block, bare-number IDs, a
  comma inside text), bare-NPI references, and benchmark math including
  rate-type separation.
- Rule: every new payer dirt shape found in the wild gets a failing
  test first, then the normalizer.
- A pull over a new payer is not done until its kept rows load and its
  benchmarks render.

## 13. Operations

- Runtime: Python 3.12+, managed with uv (`.venv` inside the project).
  DuckDB is the only store. No external services.
- Docker: `docker compose up --build` serves on port 8000 with `HOST`
  and `PORT` environment overrides.
- Cadence: pulls are manual today. Target cadence is quarterly to match
  CMS-9882-F. Each pull is a full refresh of kept rows per source file.
- Failure posture: per-file failures are logged and skipped; the run
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

## 15. Open questions

- G2212 and other Medicare-specific HCPCS: pull from a Medicare
  Advantage payer, or wait for the MPFS loader to supply the reference
  rate? (Sample shows commercial Cox publishes none.)
- Which national payer index is cheapest to pull second, given payer
  servers throttle hard (the Cox sample ran at roughly 200 KB/s per
  connection)?
- Long-tail coverage: at what payer count does a hosted public demo
  need object storage and a queue, and who pays for it?
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
- [ ] NPPES names and geography on kept providers
- [ ] Percent of Medicare on benchmarks

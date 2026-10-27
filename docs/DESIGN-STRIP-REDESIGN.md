# Market Strip redesign, October 2026

Trigger: with 507 production rows from Cox HealthPlans, the original strip
(15 rows, one per code per rate type, every rate a dot) broke down. JAS:
"this is fucked up and unhelpful now that we have more data." The page also
had to stop being a one-payer page: national payers (UnitedHealthcare,
Aetna, Cigna, Elevance Anthem BCBS) are pulled per payer index, so the
payer is a first-class dimension and aggregate (all-payer) costs show.

Rulings merged from the paired review (Tufte on evidence, UX on interface):

1. One row per distinct distribution, not per code. Where a payer
   publishes the identical dollar amounts for several codes (Cox does this
   for the 99446 to 99452 family, median $162, middle half $83 to $216),
   those codes share one row labeled with every code it covers. Median,
   band, and n are those of the shared set. The per-code facts live in the
   tables, which is where exact values belong.
2. The container was the first failure: fixed 940px width clipped the
   right-hand labels mid-word. The strip is now responsive SVG
   (width 100%, viewBox scale), right label column sized inside the view,
   so labels cannot clip at any viewport width.
3. Dots are thinned, honestly: at most 240 drawn per row, evenly spaced
   after sorting, with the row note saying how many of n are drawn. Every
   rate remains in the tables, the CSV/JSON downloads, and the code pages.
4. One shared zero-based dollar scale across the aggregate strip and
   every per-payer strip on the page, so payers compare against each
   other, not against re-scaled axes. Outliers keep their true position.
5. Rate types are still never pooled, anywhere: not in dots, bands,
   medians, tables, or aggregates. Percentage rates stay out of dollars.
6. Aggregates carry their payer count on every row. A one-payer aggregate
   is labeled with n payers = 1, never dressed up as a market.

Page structure after the rebuild:

- Headline computed from the aggregate 99213 row (payer count, median,
  middle half, n).
- Explore tools: code filter for every table, payer chips that jump to
  each payer's section, CSV and JSON downloads (aggregate, by payer,
  per-code rates, sources).
- "The market across payers": aggregate strip and aggregate table.
- One section per payer: coverage line (index date, pulled date, files
  searched of files in index), its own strip on the shared scale, its own
  benchmark table, code links pre-filtered to that payer.
- Data sources and freshness (unchanged contract: live from pull
  records), data volume, and how-it-works disclosures.

Code pages gained a median-by-payer table, payer filter chips and a
?payer= scope, and per-code CSV download.

Implementation: src/openpayer/api.py (_strip_svg, _merge_identical,
_sample, _strip_block, home, code_page), aggregates in
src/openpayer/benchmarks.py and src/openpayer/pg_store.py
(summary_all_payers). Covered by tests/test_benchmarks.py.

# OpenPayer Strategy

Living document. Started October 28, 2026, after the name-collision
research below. Update it as the product evolves; decisions and their
dates belong here, not in chat history.

## 1. The name problem (researched 2026-10-28)

### Trek Health's OpenPayer (openpayer.com)

| Fact | Evidence |
|---|---|
| Owner | Trek Health, San Ramon, CA, founded 2022 by Dilpreet Sahota; $2.7M seed (2022), $11M Series A (2025), 100 customers by 2024 |
| Launch | "Introduced OpenPayer" Feb 24, 2026, PR Newswire; it is on their official timeline after their Price Transparency Platform |
| Traction | 25,000 monthly users within 4 months (Jul 28, 2026 release); later posts claim 50,000 users |
| Data | Ingests Transparency in Coverage data plus 45,000+ standardized policy documents from 100+ commercial payers; NAIC, CMS enrollment, NPPES, NUCC |
| Product | Policy monitoring, prior-auth and coverage-criteria lookup, billing-code research, state benchmarks, payer/facility comparison, NPI Medicare/Medicaid profiles |
| Rates | Their free rates tool says "estimates built from public benchmarks"; negotiated-rate accuracy is the paid upsell ("Talk to an expert") |
| Trademark | No USPTO registration surfaced in search, and a USPTO API query returned nothing readable. Absence of a filing is not absence of rights: US trademark rights come from use in commerce, and theirs predates ours |

Sources: [Trek about page](https://www.trekhealth.io/company/about-us),
[launch release](https://www.prnewswire.com/news-releases/trek-health-introduces-openpayer-to-transform-payer-policy-intelligence-for-provider-organizations-302695178.html),
[their data sources page](https://www.openpayer.com/data-sources),
[their rates tool](https://www.openpayer.com/tools/billing-code-reimbursement-rates).

### CMS Open Payments

| Fact | Evidence |
|---|---|
| What it is | Federal disclosure program (Sunshine Act, Social Security Act §1128G): drug and device companies report payments to physicians and teaching hospitals |
| Scale | Program Year 2025: 17.07 million records, $14.67 billion, now published |
| Expanded | SUPPORT Act added physician assistants, nurse practitioners, clinical nurse specialists, CRNAs, and nurse midwives from 2022 reporting |
| Not rates | It holds industry payments to doctors (meals, consulting, research, ownership). It contains no payer negotiated rates |
| Name posture | CMS itself styles it "Open Payments ™" |

Sources: [CMS program page](https://www.cms.gov/priorities/key-initiatives/open-payments)
(read in full), [Open Payments data portal](https://openpaymentsdata.cms.gov/)
(403 to automated fetching; CMS's own page links there).

### What this means for us

| Question | Answer |
|---|---|
| Same name, same field? | Yes on both counts for Trek. Billing-code reimbursement intelligence, TiC data, provider buyers |
| Who was first? | Trek, Feb 2026. Our repo is Oct 2026 |
| Is CMS a collision? | Different data and a government program, but "Open Payments" crowds the same naming neighborhood |
| Does it block the demo? | Practically, no. MedTruth-gated and noindex today |
| Does it block going public as OpenPayer? | That is the exposure: SEO, user confusion ("the free one vs the Trek one"), and a plausible cease-and-desist once we market |

### Naming decision (open)

Recommendation on record: rename before any public launch, while the
rename is cheap (one invited collaborator, one gated subdomain). The
gated demo keeps the openpayer.medtruth.care address until the new
name lands. This is not legal advice; name candidates get a
legal-privacy review and the same collision check run here (web,
USPTO, domain) before anyone commits.

Candidate space noted 2026-10-28 (unchecked, examples only): names
that say rates and open, for example ClearRate, OpenRates, RateLedger.
Each needs the full check before use.

Decision needed from JAS: pick the rename path and timing, or accept
the exposure in writing here.

## 2. Where we differ from Trek (positioning)

Trek sells a closed intelligence platform. Our wedge, in order:

1. Open source (Apache-2.0). Anyone can run the whole chain and audit
   exactly how a number was produced.
2. Per-rate lineage. Every stored rate links to the payer file it came
   from. Trek's free tool publishes estimates; our benchmarks are
   observed rates only, never interpolated, never blended across rate
   types, with the count beside every figure.
3. Allowlist scope. About 15 codes pulled deeply instead of all codes
   shallowly. The same machinery widens by editing one config file.
4. Honest emptiness. n=0 states, capped index counts labeled as
   floors, files-searched-of-index on every payer. A benchmark never
   travels without its n and, for aggregates, its payer count.

What Trek has that we do not (and whether we want it): policy document
monitoring and prior-auth/coverage criteria (a document product, not a
rate product; out of scope unless the product definition changes), NPI
Medicare/Medicaid billing profiles (possible later via NPPES plus
Medicare data; our NPPES join is stubbed), payer market-share and
facility comparison (NAIC/Census data; possible later, different
sources).

## 3. Open Payments as a future dataset

Open Payments is NPI-keyed industry payments to providers. Joined to
our kept NPIs it could add a conflict-of-interest context layer
("this provider group also received $X from device makers"). It does
not price anything and must never be blended into rate benchmarks.
Recorded here as a possible later source; the NPPES join (already
stubbed in `reference.py`) is its prerequisite.

## 4. Product state (2026-10-28)

- Live: Cox HealthPlans fully pulled (507 rows), gated demo at
  openpayer.medtruth.care, multi-payer page with aggregate and
  per-payer views, CSV/JSON explore tools.
- Pulling: UnitedHealthcare, Aetna, Cigna, Elevance Anthem BCBS in
  bounded first passes (one Databricks job run per payer, per-file
  ledger, coverage stop at 150 provider groups per code). See SPEC.md
  section 7 and the sources table on the live site for current counts.
- Parked: Humana (no readable index exists today; recheck monthly).
- Out of scope by decision: contract modeling, claims repricing,
  patient-specific cost estimates, AMA CPT description text.

## 5. Decisions log

| Date | Decision | By |
|---|---|---|
| 2026-10-27 | Build open-source PayerPrice-style rate search on CMS transparency files, about 15 codes only | JAS |
| 2026-10-27 | Rate search + benchmarks only; no contract modeling or repricing | JAS |
| 2026-10-27 | Databricks Jobs for processing, Lakebase Postgres for storage/serving | JAS |
| 2026-10-27 | Gated demo in MedTruth, @medtruth.care emails only | JAS |
| 2026-10-28 | Pull pattern: one job per payer, ledgered, coverage stop, provider-group sample (DataSpine pattern) | JAS (plan approved) |
| 2026-10-28 | Rename recommended before public launch (Trek collision) | Assistant, pending JAS |
| 2026-10-28 | Reposition around fraud, waste, and abuse review: filed rates lined up against the CMS fee schedule, flags for human review, never public accusations | JAS |

## 6. Open questions

- New name and rename timing (section 1).
- Payer depth after the first pass: which payers earn a full-index
  pull, and what coverage (groups per code) is "deep enough" per code?
- Public demo posture after rename: open the gate, keep it gated, or
  publish the kept dataset (Parquet) as the public artifact?
- Open Payments layer: in or out, after NPPES lands?
- FWA flags: who is the first reviewer this is built for (CMS program
  integrity, a state Medicaid Fraud Control Unit, a payer SIU, or the
  public), and what do they need a flag to carry before they act on it?

## 7. Fraud, waste, and abuse: the CMS lineup (direction set 2026-10-28)

### Why now: the enforcement context (checked 2026-10-28)

- DOJ 2026 National Health Care Fraud Takedown (June 23, 2026): 455
  defendants including 90 doctors and licensed medical professionals,
  over $6.5 billion in alleged false claims, 56 federal districts, 45
  states and territories, 50 state Medicaid Fraud Control Units, over
  $182 million seized. In the same action CMS suspended 1,079
  providers and revoked billing privileges for 1,403, and HHS-OIG
  brought 25 actions seeking over $10 billion from payments CMS caught
  and suspended before they were paid. DOJ describes "the cutting-edge
  use of data analytics to target the worst actors."
  Source: https://www.justice.gov/opa/pr/national-health-care-fraud-takedown-results-455-defendants-charged-connection-over-65
- CMS Administrator Dr. Mehmet Oz, same release: "Prosecuting
  criminals who steal from American patients is necessary, but
  stopping them before a single dollar leaves the building is
  smarter. CMS is done playing catch-up. We're deploying advanced
  data analytics to expose fraud networks, freeze suspicious payments,
  and shut down bad actors before they can do damage."
- CMS, May 13, 2026: six-month nationwide moratoria on new Medicare
  enrollment for hospices and home health agencies, coordinated with
  the Vice President's Anti-Fraud Task Force, with "advanced data
  analytics" and accelerated removals during the window. Applies to
  initial enrollment and certain majority-ownership changes.
  Source: https://www.cms.gov/newsroom/press-releases/cms-announces-aggressive-nationwide-crackdown-fraud-six-month-hospice-home-health-agency-enrollment
- Oz to Minnesota Governor Walz (December 2025 letter, entered into
  the House Oversight record January 7, 2026 as
  HHRG-119-GO00-20260107-SD043): weekly fraud updates, a six-month
  freeze on high-risk provider enrollment, verification or removal of
  existing providers, and a corrective action plan, in 60 days, or
  the federal share stops. The programs named: Housing Stabilization
  Services (expected $2.6 million a year, paid over $100 million) and
  early autism intervention ($3 million in 2018 to nearly $400
  million in 2023). Our copy of the letter is a news reproduction in
  the hearing record; the CMS actions are the fact pattern, and the
  figures should be re-checked against CMS before any external use.
- The thread: CMS is standing up analytics to find bad actors before
  payment. This corpus is pre-claim by construction. It holds
  contracted rates as filed, before any claim exists, which is the
  one vantage the claims-trained tools below do not have.

### What this data can and cannot show

Can show: filed rates measured against the Medicare fee schedule;
placeholder pricing inside a payer's own file ($1 or less); one
default amount stretched across hundreds of provider groups; codes
or files a payer does not publish at all (transparency rules require
them, so absence is itself actionable); the same code priced wildly
differently across payers.

Cannot show: what was billed or paid (that is claims data), medical
necessity, upcoding in practice, kickbacks. We never claim otherwise,
on the site or anywhere else. A flag is a reason for a reviewer to
open the underlying payer file, which every rate here links to.

### Signals v1 (live 2026-10-28, `src/openpayer/flags.py`)

Thresholds are named constants at the top of the module, changed
only in the open. Medicare ruler: CMS 2026 Physician Fee Schedule
(RVU26A), national rate before geographic adjustment, via
`scripts/pull_mpfs.py` into `data/reference/mpfs.json`.

| Signal | Threshold | First live result |
|---|---|---|
| Median far above Medicare | median negotiated >= 4x Medicare | Cox consult codes: flat $162 median = 425% to 851% of Medicare (n=13 each) |
| Extreme rates | >= 3 rates at >= 10x Medicare | Cox 99446: 4 of 13 at 10x or more, max $332 = 1,744% |
| Placeholder prices | >= 20% of rates at $1.00 or less (n >= 20) | none yet |
| One amount, many groups | one amount on >= 50 groups and >= 90% of rates | Elevance: $131.22 across all 917 groups for 99447, same pattern 99451/99452 |
| Code not published | payer silent where >= 2 peers publish | G2212 missing at Cox and Elevance; 99446 missing at Elevance |

First run over the live corpus: 11 flags from 44,468 dollar rates.
Small samples say so (Cox flags rest on n=13 and read as thin,
correctly). Surfaced on the homepage flags table and at
`/api/flags` and `/api/flags.csv`.

### Prior art and landscape

| Project | What it is | State |
|---|---|---|
| zhousrhhh/Healthcare-Fraud-Detection | Notebook ML (PCA, KNN, isolation forest) on Medicare inpatient claims | 2023, dormant, no license |
| Pyligent/CMS-Medicare-Data-FRAUD-Detection | 2019 capstone, anomaly detection on Medicare claims and Part D | dormant |
| trytrench/trench | Open-source fraud and abuse prevention for product event streams | AGPL-3.0, dormant since 2024; different fraud, license blocks reuse |
| HHS on GitHub (hhs.github.io) | Healthcare Fraud Prevention Partnership exchange; Medicaid Provider Enrollment Screener with risk scoring | the government builds FWA tooling in the open too (CMSgov org) |

Every ML project above trains on claims after the money moved. Ours
reads filed rates before claims exist, with per-rate lineage to the
payer's own published file, under Apache-2.0.

### Build order

1. Done 2026-10-28: MPFS lineup, flags v1, homepage flags section,
   `/api/flags` JSON and CSV.
2. Done 2026-10-28: percent of Medicare on code pages (answer band,
   by-payer whiskers, median table).
3. Done 2026-10-28: flag dossiers at `/flag` (pattern, Medicare
   math, what would clear it, rate rows with file lineage), linked
   from every flag in the homepage table. Every flag also carries
   its clearing test (`clears_if`) in the JSON and CSV.
4. Geography, in progress: `scripts/pull_nppes.py` and
   `reference.nppes_lookup` are built and the dossier has the states
   block, but the NPPES download host (download.cms.gov/nppes) is
   down for maintenance "until further notice" as of 2026-10-28, so
   no states are claimed yet. 5,041 corpus NPIs are exported and
   waiting. When the file lands: states first, then the
   GPCI-adjusted local ruler from the MPFS zip.
5. Remaining: flags repeated inside homepage payer sections;
   exposure math (filed rate x Medicare utilization, labeled
   modeled, never observed loss); a payer compliance scoreboard
   (publishing at all, on time, placeholder share); refresh deltas
   between quarterly files.

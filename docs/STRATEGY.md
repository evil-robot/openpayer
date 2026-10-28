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

## 6. Open questions

- New name and rename timing (section 1).
- Payer depth after the first pass: which payers earn a full-index
  pull, and what coverage (groups per code) is "deep enough" per code?
- Public demo posture after rename: open the gate, keep it gated, or
  publish the kept dataset (Parquet) as the public artifact?
- Open Payments layer: in or out, after NPPES lands?

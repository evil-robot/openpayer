# Deploy: openpayer.medtruth.care

OpenPayer runs as its own Railway service, gated to @medtruth.care
addresses with the same sign-in pattern as the MedTruth site: email a
magic link, a scanner-proof confirm page, a 90-day session cookie.

Per the MedTruth repo rules, deploys and Railway changes for MedTruth
services are done by the session named "MedTruth". This file is the
handoff for that session. Nothing here needs invention.

## One-time setup (MedTruth session)

1. In the Railway `medtruth` project, create a new service from the
   GitHub repo `evil-robot/openpayer` (branch `main`). The repo root has
   a Dockerfile; Railway will build it.
2. Mount a volume at `/app/data` so the pulled rates, the DuckDB file,
   and the auth database survive deploys.
3. Set the variables from `.env.example` (names only there; values from
   Railway variables and the house credential locations, never from this
   repo). Generate `OPENPAYER_AUTH_SECRET` once with
   `openssl rand -hex 32` and do not rotate it without JAS.
4. Add the custom domain `openpayer.medtruth.care` to the service.
5. Deploy. `GET /health` answers `{"ok": true}` on any host and needs
   no sign-in.

## Seed the data (first deploy only)

The database is a build artifact and is not in git. In the service
shell, or once locally with the same `/app/data` volume:

```bash
openpayer-pull --limit=40 --workers=4
openpayer-load
```

That reproduces the 8-code Cox sample (179 rows). Later refreshes are
the same two commands; widen the codes in `config/codes.json` and the
payers in `config/sources.json` first.

## Access rules (what the gate does)

- Sign-in page at `/sign-in`. An address gets a link only when its
  domain is in `OPENPAYER_ALLOWED_DOMAINS` (live: `medtruth.care`) or
  it is in `OPENPAYER_ADMIN_EMAILS`. Every address sees the same
  "check your email" answer.
- The emailed link opens `/confirm`, a relay page with no link to the
  verify endpoint, so corporate mail scanners cannot spend the token.
  The button builds the verify URL in the browser on a real click.
- Verify spends the token once (7-day expiry) and sets an HttpOnly,
  SameSite=Lax session cookie for 90 days (Secure behind https).
- Anonymous page requests redirect to `/sign-in`. Anonymous API
  requests get 401. `/health` is public.
- There are no guest invites in v1. Domain plus admins only, as
  requested. Guests would mirror the MedTruth guest table if wanted.
- Production requires `RESEND_API_KEY` and `MAIL_FROM`. Without them
  the server prints a loud warning and prints links to the log, which
  is development behavior only.

## Local gated test

```bash
OPENPAYER_AUTH_SECRET=local-dev-secret OPENPAYER_AUTH_DB=/tmp/auth.sqlite \
uv run openpayer-serve
```

Request a link for an @medtruth.care address, copy the printed
`/confirm` link from the log, finish sign-in, reload. The same flow
is covered by `tests/test_auth.py` (10 tests total in the suite).

## Rollback

Remove the custom domain or delete the service. The MedTruth site
itself is untouched by this deploy; OpenPayer is a separate service
that only shares the sign-in pattern and the domain rule.

## Running unattended (no laptop in the loop)

The data pulls run as Databricks Job `openpayer-ingest` (workspace
`adb-7405614656617207.7.azuredatabricks.net`, job id
`525519863957852`), executing from this repo's `main` branch on
serverless compute and writing to Lakebase. Nothing in the pull path
lives on a workstation: the site is on Railway, the data is in
Lakebase, the compute is Databricks.

The job is scheduled monthly (1st of month, 11:00 UTC, one run at a
time, failure email to jas@medtruth.care) with defaults `limit=60`
files per payer, `workers=1`, `group_cap=300`. The per-file ledger
(`pulled_files`) makes every run a continuation: files already pulled
are skipped, so each month every payer advances up to 60 more files
inside whatever index `config/sources.json` points at. Manual runs
can override parameters per run (`only`, `limit`, `workers`,
`smallest_first`) without touching the schedule.

The one recurring human task is index freshness. Every source
address in `config/sources.json` is month-dated (for example
`2026-10-01_anthem_index.json.gz`). The scheduled run keeps working
through the current indexes for months (thousands of unpulled files
sit inside them), but picking up a payer's newly published index
means updating that payer's dated address on `main`. Until then the
site honestly ages: the corpus meter shows each index date and the
pulled date, and the freshness line turns past-due after a quarter.

Known gaps: Cigna's index holds about 101,000 files and grows only
in these bounded tranches. Humana has no source configured; no
readable current index has been found for it, so it contributes
nothing until that hunt succeeds.

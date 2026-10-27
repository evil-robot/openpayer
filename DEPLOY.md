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

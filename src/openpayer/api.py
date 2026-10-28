from __future__ import annotations

import html

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from . import auth as authmod
from .benchmarks import data_inventory, rates_for_code, summary_all_payers, summary_by_code_payer
from .config import load_codes
from .store import DB_PATH

app = FastAPI(title="OpenPayer", description="Rate search and benchmarks from CMS price transparency files")

PUBLIC_PATHS = {"/health", "/sign-in", "/confirm", "/auth/verify", "/og.png", "/assets/medtruth-lockup.svg", "/favicon.svg"}

OG_TITLE = "OpenPayer: what payers actually reimburse"
OG_DESC = (
    "Real negotiated and fee schedule rates for a short list of billing codes, "
    "pulled only from the pricing files payers must publish for free under federal "
    "price transparency law. Every rate links to its source payer file."
)


def og_head(canonical: str = "https://openpayer.medtruth.care/") -> str:
    base = authmod.base_url()
    img = f"{base}/og.png"
    return (
        f'<meta property="og:type" content="website"><meta property="og:site_name" content="OpenPayer">'
        f'<meta property="og:title" content="{OG_TITLE}"><meta property="og:description" content="{OG_DESC}">'
        f'<meta property="og:url" content="{canonical}"><meta property="og:image" content="{img}">'
        '<meta property="og:image:type" content="image/png"><meta property="og:image:width" content="1200">'
        '<meta property="og:image:height" content="630">'
        f'<meta property="og:image:alt" content="Dot plot of real payer rates by billing code">'
        '<meta name="twitter:card" content="summary_large_image">'
        f'<meta name="twitter:title" content="{OG_TITLE}"><meta name="twitter:description" content="{OG_DESC}">'
        f'<meta name="twitter:image" content="{img}">'
        f'<meta name="description" content="{OG_DESC}">'
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
        '<meta name="robots" content="noindex, nofollow, noarchive">'
    )


@app.get("/og.png")
def og_image():
    from pathlib import Path

    return FileResponse(Path(__file__).parent / "assets" / "og.png", media_type="image/png")


@app.get("/assets/medtruth-lockup.svg")
def lockup_image():
    from pathlib import Path

    return FileResponse(Path(__file__).parent / "assets" / "medtruth-lockup.svg", media_type="image/svg+xml")


@app.get("/favicon.svg")
def favicon_image():
    from pathlib import Path

    return FileResponse(Path(__file__).parent / "assets" / "favicon.svg", media_type="image/svg+xml")


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    if (
        not authmod.auth_enabled()
        or request.url.path in PUBLIC_PATHS
        or request.url.path.startswith("/.well-known/")
    ):
        return await call_next(request)
    if authmod.session_email(request.cookies.get(authmod.COOKIE)):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "sign in required"}, status_code=401)
    return RedirectResponse("/sign-in", status_code=303)


@app.get("/health")
def health():
    return {"ok": True}


def _bare(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<html><head><title>{html.escape(title)} | OpenPayer</title>{og_head()}<style>{STYLE}</style></head>"
        "<body><header class='site-header'><div class='wrap'>"
        "<a class='brand' href='/'>OpenPayer</a>"
        "</div></header><div class='auth-wrap'>"
        "<p class='auth-logo'><img src='/assets/medtruth-lockup.svg' alt='MedTruth' width='216' height='44'></p>"
        f"{body}</div></body></html>"
    )


@app.get("/sign-in", response_class=HTMLResponse)
def sign_in_page():
    domains = ", ".join(sorted(authmod.allowed_domains()))
    return _bare(
        "Sign in",
        "<h1>Sign in</h1>"
        "<p class='auth-sub'>OpenPayer at this address is for the MedTruth team. "
        f"Enter your work email. If it is an @{domains} address, a sign-in link is on its way.</p>"
        '<form class="auth-form" method="post" action="/sign-in">'
        '<label for="email">Work email</label>'
        '<input id="email" type="email" name="email" required autocomplete="email" placeholder="you@medtruth.care">'
        '<button class="btn-primary" type="submit">Email me a sign-in link</button></form>'
        "<div class='auth-note'><ul>"
        "<li>The link works for 7 days and signs you in for 90 days on this device.</li>"
        "<li>Use your work address. Personal email will not get a link, and the page will not tell you why.</li>"
        "<li>Nothing arrived? Check spam first, then request again. A few requests per 15 minutes are allowed.</li>"
        "<li>Your address is used only to send the link and hold your session. Nothing else.</li>"
        "</ul></div>",
    )


_attempts: dict[str, list[float]] = {}


@app.post("/sign-in", response_class=HTMLResponse)
def sign_in_submit(request: Request, email: str = Form(...)):
    import time as _time

    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    hits = [t for t in _attempts.get(ip, []) if now - t < 900]
    if len(hits) < 6:
        hits.append(now)
        _attempts[ip] = hits
        if authmod.is_allowed(email):
            token = authmod.create_token(email)
            authmod.send_sign_in_link(email, token)
    # Same answer for every address, allowed or not.
    safe_email = html.escape(email.strip())
    return _bare(
        "Check your email",
        "<h1>Check your email</h1>"
        f"<p class='auth-sub'>If <strong>{safe_email}</strong> may sign in, a link is on its way. It expires in 7 days.</p>"
        '<form class="auth-form" method="post" action="/sign-in">'
        f'<input type="hidden" name="email" value="{safe_email}">'
        '<button class="btn-primary" type="submit">Resend the link</button></form>'
        "<p><a href='/sign-in'>Use a different address</a></p>"
        "<div class='auth-note'><ul>"
        "<li>Nothing after a few minutes? Check spam, then resend. A few resends per 15 minutes are allowed.</li>"
        "<li>The newest link is the one that works. Earlier links for the same address still count down from when they were sent.</li>"
        "</ul></div>",
    )


@app.get("/confirm", response_class=HTMLResponse)
def confirm_page(token: str = ""):
    # Scanner-proof relay: no link or form action points at the verify URL.
    # The button builds it in the browser on a real click.
    safe = html.escape(token)
    return _bare(
        "Confirm sign-in",
        "<h1>One more press</h1>"
        "<p class='auth-sub'>Press the button to finish signing in. This extra step exists so a mail scanner that reads your email cannot spend the link before you do.</p>"
        f'<div class="auth-form"><button class="btn-primary" id="go" data-token="{safe}">Sign in to OpenPayer</button></div>'
        "<script>document.getElementById('go').addEventListener('click',function(){"
        "setTimeout(function(){location.href='/auth/verify?token='+encodeURIComponent("
        "document.getElementById('go').dataset.token);},350);});</script>",
    )


@app.get("/auth/verify")
def auth_verify(token: str = ""):
    email = authmod.verify_token(token)
    if not email:
        return _bare(
            "Link expired",
            "<h1>That link will not work</h1>"
            "<p class='auth-sub'>It is spent or past 7 days. Request a fresh one and use the newest email.</p>"
            "<p><a href='/sign-in'>Request a new link</a></p>",
        )
    resp = RedirectResponse("/", status_code=303)
    raw = authmod.create_session(email)
    resp.set_cookie(
        authmod.COOKIE, raw, max_age=authmod.SESSION_TTL, httponly=True,
        samesite="lax", secure=authmod.base_url().startswith("https://"),
    )
    return resp


@app.post("/sign-out")
def sign_out(request: Request):
    authmod.delete_session(request.cookies.get(authmod.COOKIE))
    resp = RedirectResponse("/sign-in", status_code=303)
    resp.delete_cookie(authmod.COOKIE)
    return resp

STYLE = """
:root{--st-green-50:#F0FDFA;--st-green-100:#CCFBF1;--st-green-600:#0D9488;--st-green-700:#0F766E;
--st-gold-600:#A16207;--st-gray-50:#F9FAFB;--st-gray-100:#F3F4F6;--st-gray-200:#E5E7EB;--st-gray-300:#D1D5DB;
--st-gray-500:#6B7280;--st-gray-700:#374151;--st-gray-900:#111827;--ink:var(--st-gray-900);--muted:var(--st-gray-700);
--rule:var(--st-gray-200);--bg:#ffffff;--panel:var(--st-gray-50);--link:var(--st-green-700);--focus:var(--st-gold-600);
--font:"Inter",system-ui,-apple-system,sans-serif;--mono:"JetBrains Mono","SF Mono","Fira Code",monospace}
*{box-sizing:border-box}
body{font-family:var(--font);margin:0;color:var(--ink);background:var(--bg);line-height:1.6;font-size:1rem}
.wrap{max-width:1080px;margin:0 auto;padding:0 1.25rem 3rem}
a{color:var(--link);text-decoration-thickness:1px;text-underline-offset:.15em}a:hover{text-decoration-thickness:2px}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px;border-radius:2px}
.skip{position:absolute;left:-999px;top:.5rem;background:var(--ink);color:#fff;padding:.5rem .75rem;z-index:20}
.skip:focus{left:.5rem}
.site-header{border-bottom:1px solid var(--rule);background:var(--panel)}
.site-header .wrap{display:flex;align-items:baseline;gap:1rem;padding-top:1rem;padding-bottom:1rem}
.brand{font-weight:700;font-size:1.35rem;color:var(--ink);text-decoration:none;letter-spacing:-.01em}
.brand-sub{color:var(--muted);font-size:.92rem}
.head-right{margin-left:auto;color:var(--muted);font-size:.9rem;display:flex;gap:.9rem;align-items:baseline}
.head-right form{display:inline}.head-right button{background:none;border:0;color:var(--link);cursor:pointer;font:inherit;padding:0;text-decoration:underline}
h1{font-size:clamp(1.7rem,3vw,2.3rem);line-height:1.2;letter-spacing:-.02em;text-wrap:balance;margin:1.6rem 0 .6rem;max-width:34ch}
h2{font-size:1.45rem;letter-spacing:-.015em;margin:2.2rem 0 .7rem;padding-top:.6rem;border-top:1px solid var(--rule);text-wrap:balance}
h3{font-size:1.08rem;font-weight:600;margin:1.4rem 0 .4rem}
.lede{font-size:1.12rem;max-width:68ch}.coverage{color:var(--muted);max-width:75ch}
.num{font-family:var(--mono);font-size:.92em}
.table-wrap{overflow-x:auto;margin:1rem 0 1.5rem}
table{border-collapse:collapse;width:100%;font-size:.95rem;line-height:1.45}
th,td{text-align:left;vertical-align:top;padding:.45rem .6rem;border-bottom:1px solid var(--rule)}
th{font-weight:600;border-bottom:2px solid var(--ink)}
td.n,th.n{text-align:right;font-family:var(--mono);font-size:.9em}
tbody tr:nth-child(even){background:var(--st-gray-50)}
.note,.meta{color:var(--muted);font-size:.92rem}
details{border:1px solid var(--rule);border-radius:8px;padding:.8rem 1rem;margin:1rem 0;background:#fff}
details summary{cursor:pointer;font-weight:600}
.dot{cursor:pointer}.dot:hover{stroke:var(--ink);stroke-width:2.6}
#tip{position:fixed;z-index:30;pointer-events:none;background:var(--ink);color:#fff;padding:.6rem .75rem;border-radius:8px;
font-size:.86rem;line-height:1.5;max-width:350px;display:none;box-shadow:0 4px 12px rgba(0,0,0,.18)}
svg.strip{width:100%;height:auto;display:block}
.tools{display:flex;flex-wrap:wrap;gap:.9rem;align-items:center;margin:1.2rem 0;padding:.8rem 1rem;background:var(--panel);border:1px solid var(--rule);border-radius:10px}
.tools input{padding:.4rem .6rem;border:1px solid var(--st-gray-300);border-radius:6px;font:inherit}
.chips{display:flex;flex-wrap:wrap;gap:.4rem}
.chip{border:1px solid var(--st-gray-300);border-radius:999px;padding:.15rem .7rem;font-size:.85rem;text-decoration:none}
.downloads{font-size:.85rem;color:var(--muted)}
.payer-section{margin-top:2.4rem;border-top:2px solid var(--rule);padding-top:.6rem}
#tip.pinned{pointer-events:auto}
#tip strong{font-size:1.05rem}#tip .src{color:var(--st-gray-300);font-size:.74rem;word-break:break-all}
#tip a{color:var(--st-green-100)}
.fresh-fresh{color:var(--st-green-700);font-weight:600}.fresh-stale{color:var(--st-gold-600);font-weight:600}
.auth-wrap{max-width:460px;margin:0 auto;padding:3.2rem 1.25rem 4rem}
.auth-wrap h1{font-size:1.9rem;margin:.2rem 0 .8rem}
.auth-sub{color:var(--muted);max-width:44ch}
.auth-form{margin:1.6rem 0 1.2rem}
.auth-form label{display:block;font-weight:600;font-size:.92rem;margin-bottom:.45rem}
.auth-form input[type=email]{width:100%;min-height:48px;padding:.65rem .8rem;border:1px solid var(--st-gray-300);
border-radius:8px;font:inherit;font-size:1rem;background:#fff;color:var(--ink)}
.auth-form input[type=email]::placeholder{color:var(--st-gray-500)}
.auth-form input[type=email]:focus{outline:3px solid var(--focus);outline-offset:1px;border-color:var(--focus)}
.btn-primary{display:inline-flex;align-items:center;justify-content:center;min-height:48px;width:100%;
padding:.7rem 1.1rem;margin-top:.9rem;background:var(--st-green-700);color:#fff;border:0;border-radius:8px;
font:inherit;font-weight:600;font-size:1rem;cursor:pointer}
.btn-primary:hover{background:var(--st-green-600)}
.auth-note{border-top:1px solid var(--rule);margin-top:1.6rem;padding-top:1rem;color:var(--muted);font-size:.9rem}
.auth-note li{margin:.3rem 0}
.auth-brand{display:flex;align-items:baseline;gap:.8rem}
.auth-logo{margin:0 0 1.4rem}.auth-logo img{display:block;height:auto;max-width:100%}
"""


def _has_data() -> bool:
    from . import pg_store

    if pg_store.enabled():
        try:
            return pg_store.data_inventory()["total_rows"] > 0
        except Exception:
            return False
    return DB_PATH.exists()


def _dot_plot(rows: list[dict]) -> str:
    rates = sorted(r["negotiated_rate"] for r in rows if r.get("negotiated_rate") is not None)
    if not rates:
        return "<p>No dollar rates yet for this code.</p>"
    lo, hi = 0.0, rates[-1]
    span = hi or 1.0
    width, height = 900, 160
    dots = []
    for i, v in enumerate(rates):
        x = 40 + (v - lo) / span * (width - 80)
        y = 30 + (i % 10) * 12
        dots.append(f'<circle cx="{x:.1f}" cy="{y}" r="3.5" fill="#111827"><title>${v:,.2f}</title></circle>')
    median = rates[len(rates) // 2]
    mx = 40 + (median - lo) / span * (width - 80)
    return (
        f'<svg width="{width}" height="{height}" role="img" aria-label="Dot plot of dollar rates on a scale starting at zero dollars">'
        + "".join(dots)
        + f'<line x1="{mx:.1f}" y1="15" x2="{mx:.1f}" y2="{height - 15}" stroke="#6B7280" stroke-dasharray="4"/>'
        + f'<text x="40" y="{height - 2}" font-size="11">$0 scale start</text>'
        + f'<text x="{width - 120}" y="{height - 2}" font-size="11">${hi:,.0f} max</text>'
        + f'<text x="{mx + 4:.1f}" y="14" font-size="11">median ${median:,.0f}</text></svg>'
    )


SYSTEM_DOES = """
<h2>What this system does today</h2>
<p>Everything below is built and tested in this repo. Status is shown per item.
If an item says waiting, the code is ready and only configuration or data is missing.</p>

<h3>1. Configuration: the only human inputs</h3>
<ul>
<li><strong>Code allowlist</strong> in <code>config/codes.json</code>: the billing codes to pull (about 15 by design; CPT, HCPCS, MS-DRG, REV, or NDC). This list is the whole scope control. <em>The live list appears at the top of this page.</em></li>
<li><strong>Payer sources</strong> in <code>config/sources.json</code>: one entry per payer with a Transparency in Coverage table-of-contents (index) URL. Payers with no URL are skipped. <em>Sample payer wired first; more added the same way.</em></li>
<li><strong>Empty-list guard:</strong> while the code list is empty, the pull exits and downloads nothing. An unfiltered pull would be the full multi-terabyte firehose, so the system refuses it by design.</li>
</ul>

<h3>2. Ingest: pull only your codes (<code>openpayer-pull</code>)</h3>
<ul>
<li><strong>Discovery:</strong> reads each payer table-of-contents JSON and lists every in-network rate file it points to, with plan name and plan ID.</li>
<li><strong>One file at a time:</strong> downloads a single machine-readable file (MRF) to a temp file. Peak disk use is one compressed file, however large the payer is.</li>
<li><strong>Two-pass streaming parse:</strong> first pass indexes provider groups (name, tax ID, NPIs). Second pass streams every service in the file and keeps only rows whose billing code is on the allowlist. Everything else is discarded as it streams past and is never stored.</li>
<li><strong>Kept rows only:</strong> one row per negotiated price per provider group, with payer, code, rate, rate type, billing class, provider name, tax ID, NPIs, expiry date, and the source file URL. Written as gzipped JSON lines to <code>data/raw/</code>. The temp MRF is then deleted.</li>
<li><strong>Per-file resilience:</strong> a failed file is logged and skipped. The run continues with the next file.</li>
<li><strong>Dry run:</strong> <code>openpayer-pull --dry-run</code> lists the files it would pull and downloads nothing.</li>
</ul>

<h3>3. Storage and benchmarks (<code>openpayer-load</code>)</h3>
<ul>
<li><strong>Load:</strong> loads every kept file into a local DuckDB database (<code>data/rates.duckdb</code>). Re-running the load rebuilds the table from the kept files.</li>
<li><strong>Benchmarks per code and payer:</strong> count of rates, count of distinct provider groups, minimum, 25th percentile, median, 75th percentile, and maximum.</li>
<li><strong>Dollar rates, grouped by type:</strong> benchmarks use observed dollar rates only, grouped by rate type (negotiated, fee schedule, and so on) so types are never blended. Percentage rates are not dollars and stay out of dollar percentiles. The count beside every benchmark says how many rates it rests on. Nothing is interpolated or estimated.</li>
</ul>

<h3>4. Search and viewing (this site)</h3>
<ul>
<li><strong>This landing page:</strong> live status, the configured codes, and the benchmark table when data exists.</li>
<li><strong>Code page</strong> at <code>/code/{code}</code>: a dot plot where each dot is one observed negotiated rate for one provider group (hover shows the dollar value), a dashed median line with min and max labeled, then a See the numbers table under it: payer, rate, provider, tax ID, and a source file link on every row. That link is the audit trail back to the payer file the rate came from.</li>
<li><strong>JSON API:</strong> <code>/api/codes</code> (configured codes), <code>/api/summary</code> (benchmark table as JSON), <code>/api/rates/{code}</code> (individual rates, filterable by payer). Returns 404 with a plain reason when no data is pulled yet.</li>
</ul>

<h3>5. Quality and legal posture</h3>
<ul>
<li><strong>Public data only:</strong> payer and hospital files published free, with no account, under the CMS Hospital Price Transparency rule and the Transparency in Coverage rule, strengthened by Executive Order 14221 (2025), the CY 2026 OPPS rule (actual dollar amounts, percentile allowed amounts, named executive attestation), and the Transparency in Coverage final rule CMS-9882-F (Oct 2026).</li>
<li><strong>No AMA text:</strong> the system stores and shows CPT numbers and rates. It does not store or redistribute American Medical Association CPT description text. Code notes are your own short notes.</li>
<li><strong>Tests:</strong> the code filter, the empty-list guard, and the benchmark math are covered by automated tests in <code>tests/</code>.</li>
<li><strong>Self-hosting:</strong> runs with <code>uv run openpayer-serve</code> or <code>docker compose up</code>. No paid service, no account, no key.</li>
</ul>

<h2>What it does not do yet</h2>
<ul>
<li><strong>Real payer files arrive dirty, and the system now copes.</strong> The first live payer file tested (Cox HealthPlans, Sep 2026) is invalid JSON (trailing commas), puts provider names inside the tax ID block, and uses bare numbers for NPIs and tax IDs. The parser repairs trailing commas with a string-aware scan and normalizes all three before storing anything. Dirt that cannot be repaired fails that one file and is logged, never silently blended in.</li>
<li><strong>Depth is whatever the sources table shows.</strong> Every payer row carries files searched out of files in its index, so a bounded first pass reads as a bounded first pass, never as the payer's whole book. Widen the code list to about 15 and add payer index addresses to grow it; no code changes needed.</li>
<li><strong>Provider details and geography:</strong> NPPES (NPI registry) wiring is stubbed in <code>reference.py</code>. Provider practice city, state, ZIP, and specialty, and any map view, wait on that loader. It is designed to join only providers already in the pulled rates, so it stays small.</li>
<li><strong>Percent of Medicare:</strong> Medicare fee schedule wiring is stubbed the same way. No percent-of-Medicare figure is shown until real fee schedule data is loaded. The system shows nothing rather than a placeholder number.</li>
<li><strong>Hospital files:</strong> only payer Transparency in Coverage in-network files are parsed today. Hospital MRFs use a different schema and are a later source type.</li>
<li><strong>No automatic refresh yet:</strong> pulls are run by hand today. A scheduled quarterly refresh matches the new CMS cadence and is on the roadmap.</li>
<li><strong>Out of scope by decision:</strong> contract upload and modeling, and claims repricing for short pays. Those need private contracts and remits. This system is rate search and benchmarks from public data only.</li>
</ul>
"""


def _header(request: Request) -> str:
    email = authmod.session_email(request.cookies.get(authmod.COOKIE)) if authmod.auth_enabled() else None
    right = (
        f"<span>{html.escape(email)}</span><form method='post' action='/sign-out'><button type='submit'>Sign out</button></form>"
        if email
        else "<a href='/api/codes'>API</a>"
    )
    return (
        "<header class='site-header'><div class='wrap'>"
        "<a class='brand' href='/'>OpenPayer</a>"
        f"<span class='head-right'>{right}</span></div></header>"
    )


def _freshness(detail: dict) -> tuple[str, str]:
    """Return (verdict text, css class) for one source record."""
    from datetime import date

    if not detail.get("configured"):
        return ("Not configured yet. No index address, so nothing can be pulled.", "")
    if not detail.get("pulled_at"):
        return ("Configured, not pulled yet.", "")
    idx = detail.get("index_last_updated_on") or ""
    try:
        age = (date.today() - date.fromisoformat(idx)).days
    except ValueError:
        return ("Pulled. Payer index date not recorded.", "")
    if age <= 120:
        return (f"Fresh. Index is {age} days old, inside the quarterly cycle.", "fresh-fresh")
    return (f"Past the quarterly cycle. Index is {age} days old, rates may have changed in newer files.", "fresh-stale")


def _sources_section() -> str:
    from .benchmarks import sources_detail

    rows = []
    for d in sources_detail():
        verdict, cls = _freshness(d)
        idx_link = (
            f"<a href='{html.escape(str(d['index_url']))}'>index</a>" if d["index_url"] else "not set"
        )
        rows.append(
            "<tr><td>{payer}</td><td>{stype}</td><td>{idx}</td><td>{idate}</td><td>{pulled}</td>"
            "<td class='n'>{files}</td><td class='n'>{kept}</td><td class='{cls}'>{verdict}</td></tr>".format(
                payer=html.escape(str(d["payer"])), stype=html.escape(str(d["source_type"])), idx=idx_link,
                idate=html.escape(str(d["index_last_updated_on"] or "not recorded")),
                pulled=html.escape(str((d["pulled_at"] or "never")[:10])),
                files=(f"{d['files_attempted']} of {d['files_in_index']} in index" if d["files_attempted"] is not None else "none"),
                kept=(d["rows_kept"] if d["rows_kept"] is not None else 0), cls=cls, verdict=html.escape(verdict),
            )
        )
    return (
        "<h2>Data sources and freshness</h2>"
        "<p>Every source the system can pull, what it last pulled, and how old the payer's own published index is. "
        "Payers refresh quarterly under the current federal rule, so an index inside 120 days reads Fresh. "
        "This table is built live from the pull records and the configuration, never typed by hand.</p>"
        "<div class='table-wrap'><table><tr><th>Payer</th><th>Type</th><th>Source</th><th>Payer index dated</th><th>We pulled</th><th>Files searched</th><th>Rows kept</th><th>Freshness</th></tr>"
        + "".join(rows)
        + "</table></div>"
        "<p class='note'>Not configured yet means the slot exists in config/sources.json and waits for that payer's index address. "
        "It is a to-do shown on purpose, not missing data pretending to be a result. "
        "One national file can name over 100,000 provider groups and hold millions of rows for our codes alone, so from any file that names more than 2,000 groups "
        "we keep the rates of about 300 provider groups, chosen the same way in every file by tax ID. Benchmarks rest on those kept groups, and the counts beside them say so.</p>"
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> str:
    codes = load_codes()
    header = _header(request)
    if not codes:
        body = "<h1>What payers actually reimburse, for the codes you choose</h1><p class='lede'>No codes are configured yet, so nothing has been pulled. Add codes to config/codes.json, add payer sources, then pull.</p>"
        return f"<html><head><title>OpenPayer</title>{og_head()}<style>{STYLE}</style></head><body><a class='skip' href='#rates'>Skip to rates</a>{header}<div class='wrap'>{body}{_sources_section()}</div></body></html>"
    if not _has_data():
        body = "<h1>What payers actually reimburse, for the codes you choose</h1><p class='lede'>Codes are configured and no pull has run yet.</p>"
        return f"<html><head><title>OpenPayer</title>{og_head()}<style>{STYLE}</style></head><body><a class='skip' href='#rates'>Skip to rates</a>{header}<div class='wrap'>{body}{_sources_section()}</div></body></html>"

    rows = summary_by_code_payer()
    agg = summary_all_payers()
    inv = data_inventory()
    from .benchmarks import sources_detail

    detail_by_payer = {d["payer"]: d for d in sources_detail()}
    cov_bits = []
    for p in inv["by_payer"]:
        d = detail_by_payer.get(p["payer"], {})
        cov_bits.append(f"{p['payer']}, index dated {d.get('index_last_updated_on') or 'not recorded'}, pulled {(d.get('pulled_at') or '')[:10] or 'date not recorded'}")
    coverage = "; ".join(cov_bits)
    payers = [p["payer"] for p in inv["by_payer"]] or sorted({str(r["payer"]) for r in rows})
    payer_phrase = payers[0] if len(payers) == 1 else f"{len(payers)} payers"

    headline = "What payers actually reimburse, for the codes you choose"
    neg13 = next((r for r in agg if r["billing_code"] == "99213" and r["negotiated_type"] == "negotiated"), None)
    fs13 = next((r for r in agg if r["billing_code"] == "99213" and r["negotiated_type"] == "fee schedule"), None)
    lead_row = neg13 or fs13
    if lead_row:
        kind = "negotiated rate" if lead_row["negotiated_type"] == "negotiated" else "fee schedule rate"
        headline = (
            f"Across {payer_phrase}, a 99213 office visit pays a median {kind} of ${lead_row['median']:,.0f} "
            f"(middle half ${lead_row['p25']:,.0f} to ${lead_row['p75']:,.0f}, n={lead_row['n_rates']})"
        )

    all_rows_by_code: dict[str, list[dict]] = {}
    all_vals: list[float] = []
    for c in codes:
        rs = [r for r in rates_for_code(c.code, limit=2000) if r.get("negotiated_rate") is not None]
        all_rows_by_code[c.code] = rs
        all_vals.extend(float(r["negotiated_rate"]) for r in rs)
    xmax = max(25.0, (int(max(all_vals) / 25) + 1) * 25) if all_vals else 100.0

    def _money(v) -> str:
        return f"${(v or 0):,.2f}"

    def _trs(subset, link_payer: str | None) -> str:
        out = []
        for r in subset:
            q = f"?payer={html.escape(str(link_payer))}" if link_payer else ""
            out.append(
                "<tr data-code='{code}'><td><a href='/code/{code}{q}'>{code}</a></td><td>{rtype}</td><td class='n'>{n}</td><td class='n'>{groups}</td>"
                "<td class='n'>{p25}</td><td class='n'>{med}</td><td class='n'>{p75}</td><td class='n'>{mn}</td><td class='n'>{mx}</td></tr>".format(
                    code=html.escape(str(r["billing_code"])), q=q, rtype=html.escape(str(r["negotiated_type"])), n=r["n_rates"],
                    groups=r["n_provider_groups"], p25=_money(r["p25"]), med=_money(r["median"]), p75=_money(r["p75"]),
                    mn=_money(r["min_rate"]), mx=_money(r["max_rate"]),
                )
            )
        return "".join(out)

    _TABLE_HEAD = (
        "<div class='table-wrap'><table class='filterable'><thead><tr><th>Code</th><th>Rate type</th><th>Rates</th><th>Provider groups</th>"
        "<th>p25</th><th>Median</th><th>p75</th><th>Min</th><th>Max</th></tr></thead><tbody>"
    )
    g_row = ""
    if not any(r["billing_code"] == "G2212" for r in agg):
        g_row = (
            "<tr data-code='g2212'><td>G2212</td><td>any</td><td class='n'>0</td><td class='n'>0</td>"
            "<td colspan='5'>Searched, found none. G2212 is a Medicare code and the commercial payers pulled so far do not publish it. Its price lives in the Medicare fee schedule, not here.</td></tr>"
        )
    chips = "".join(
        f"<a class='chip' href='#payer-{html.escape(_slug_payer(p))}'>{html.escape(p)}</a>" for p in payers
    )
    tools = (
        "<div class='tools'><label>Filter tables by code <input id='codefilter' type='search' placeholder='try 99213' autocomplete='off'></label>"
        f"<span class='chips'>{chips}</span>"
        "<span class='downloads'>Download: <a href='/api/aggregate.csv'>aggregate CSV</a> · <a href='/api/summary.csv'>by-payer CSV</a> · "
        "<a href='/api/aggregate'>aggregate JSON</a> · <a href='/api/summary'>by-payer JSON</a> · <a href='/api/sources'>sources JSON</a></span></div>"
    )
    market = (
        "<h2 id='rates'>The market across payers</h2>"
        "<p>All pulled payers together, per code and rate type. The payer count on every table row says how many payers that aggregate rests on. "
        "Each payer also gets its own section below with the same scale, so a payer can be read alone and compared honestly.</p>"
        + _strip_block(codes, all_rows_by_code, xmax)
        + "<h3>See the numbers: all payers</h3>"
        + ("<div class='table-wrap'><table class='filterable'><thead><tr><th>Code</th><th>Rate type</th><th>Payers</th><th>Rates</th><th>Provider groups</th>"
           "<th>p25</th><th>Median</th><th>p75</th><th>Min</th><th>Max</th></tr></thead><tbody>")
        + "".join(
            "<tr data-code='{code}'><td><a href='/code/{code}'>{code}</a></td><td>{rtype}</td><td class='n'>{payers}</td><td class='n'>{n}</td><td class='n'>{groups}</td>"
            "<td class='n'>{p25}</td><td class='n'>{med}</td><td class='n'>{p75}</td><td class='n'>{mn}</td><td class='n'>{mx}</td></tr>".format(
                code=html.escape(str(r["billing_code"])), rtype=html.escape(str(r["negotiated_type"])),
                payers=r["n_payers"], n=r["n_rates"], groups=r["n_provider_groups"],
                p25=_money(r["p25"]), med=_money(r["median"]), p75=_money(r["p75"]), mn=_money(r["min_rate"]), mx=_money(r["max_rate"]),
            )
            for r in agg
        )
        + g_row
        + "</tbody></table></div>"
        "<p class='note'>Columns: Payers counts the payers inside the aggregate. Rates is n. p25 is the rate a quarter of provider groups are at or below. "
        "The median is the middle rate. p75 is where only a quarter are paid more. Select a code for every rate and the payer file behind it.</p>"
    )

    sections = []
    for payer in payers:
        d = detail_by_payer.get(payer, {})
        sub = [r for r in rows if str(r["payer"]) == payer]
        sub_by_code = {c.code: [r for r in all_rows_by_code.get(c.code, []) if str(r["payer"]) == payer] for c in codes}
        searched = (
            f"{d.get('files_attempted')} of {d.get('files_in_index')} files in its index searched, {d.get('files_with_rows')} held rates for our codes"
            if d.get("files_attempted") is not None else "not pulled yet"
        )
        line = (
            f"Index dated {d.get('index_last_updated_on') or 'not recorded'}, pulled {(d.get('pulled_at') or '')[:10] or 'not yet'}: {searched}. "
            f"{sum(r['n_rates'] for r in sub)} benchmark rates in the tables below."
        )
        sections.append(
            f"<section class='payer-section' id='payer-{html.escape(_slug_payer(payer))}'>"
            f"<h2>{html.escape(payer)}</h2><p class='coverage'>{html.escape(line)}</p>"
            + _strip_block(codes, sub_by_code, xmax)
            + f"<h3>See the numbers: {html.escape(payer)}</h3>"
            + _TABLE_HEAD
            + _trs(sub, link_payer=payer)
            + "</tbody></table></div></section>"
        )

    volume = (
        f"<details><summary>How much data is in here right now</summary><p class='note'>Live from the database on every load. "
        f"Total rate rows stored: {inv['total_rows']}, only the configured codes. Everything else in each payer file was discarded during the pull. "
        f"Kept files: {inv['source_files']} source files. Distinct NPIs on kept rates: {inv['distinct_npis']}. "
        f"Distinct provider groups by tax ID: {inv['provider_groups']}, named providers: {inv['providers_named']}. "
        "Named providers can be zero when a payer cites NPIs without names. Names join later from the NPI registry.</p></details>"
    )
    how = f"<details><summary>How this works, and what it does not do yet</summary>{SYSTEM_DOES}</details>"
    lede = (
        "<p class='lede'>OpenPayer reads the pricing files payers must publish for free under federal price transparency law, "
        "keeps only the billing codes on our list, and shows what payers actually reimburse, by code, payer, and provider. "
        "Every rate links to the payer file it came from. Commercial tools sell this same public data. This one is open.</p>"
    )
    return (
        f"<html><head><title>OpenPayer</title>{og_head()}<style>{STYLE}</style></head><body><a class='skip' href='#rates'>Skip to rates</a>{header}<div class='wrap'>"
        f"<h1>{html.escape(headline)}</h1>{lede}"
        f"<p class='coverage'>Coverage right now: {html.escape(coverage)}. {inv['total_rows']} rate rows kept for {len(codes)} codes. Codes in scope: "
        + ", ".join(html.escape(c.code) for c in codes)
        + ".</p>"
        + tools + market + "".join(sections) + _sources_section() + volume + how
        + "<p class='note'>Source: payer machine readable files published under CMS price transparency rules. Counts sit beside every benchmark so a thin sample is never dressed up as a market.</p>"
        "</div></body></html>"
    )


def _slug_payer(payer: str) -> str:
    import re as _re

    return _re.sub(r"[^a-z0-9]+", "-", payer.lower()).strip("-")


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


_DOT_CAP = 240


def _merge_identical(groups: list[dict]) -> list[dict]:
    """Merge code groups whose dollar values are exactly the same set.

    Some payers publish the identical contracted amounts for a family of
    codes. Drawing that one distribution six times repeats a single fact
    and reads as fabricated, so the shared distribution is drawn once and
    labeled with every code it covers. Median, band, and counts are those
    of the shared set, and the label says each code carries this same set.
    """
    order: list[str] = []
    by_key: dict[tuple, dict] = {}
    for g in groups:
        vals = tuple(sorted(float(r["negotiated_rate"]) for r in g["rows"]))
        key = (g["rtype"], vals)
        if key in by_key:
            by_key[key]["codes"].append(g["code"])
        else:
            merged = dict(g)
            merged["codes"] = [g["code"]]
            by_key[key] = merged
            order.append(key)
    return [by_key[k] for k in order]


def _sample(rows: list[dict], cap: int = _DOT_CAP) -> tuple[list[dict], bool]:
    """Evenly spaced sample of at most `cap` rows after sorting by rate.

    Returns (sample, was_capped). Every rate still sits in the tables and
    on the code pages; only the drawn dots are thinned, and the row says so.
    """
    ordered = sorted(rows, key=lambda z: float(z["negotiated_rate"]))
    if len(ordered) <= cap:
        return ordered, False
    step = (len(ordered) - 1) / (cap - 1)
    return [ordered[round(i * step)] for i in range(cap)], True


def _strip_svg(code_groups: dict[str, list[dict]], xmax: float, codes_meta: dict[str, str]) -> tuple[str, list[str]]:
    """Draw one strip: one row per distinct distribution, shared zero scale.

    code_groups maps code -> rate-type groups ({rtype, rows}). Groups with
    identical dollar sets share a row labeled with all their codes (see
    _merge_identical). Returns (svg, sampling notes).
    """
    flat: list[dict] = []
    empties: list[str] = []
    for code, groups in code_groups.items():
        if not groups:
            empties.append(code)
        for g in groups:
            flat.append({"code": code, **g})
    merged = _merge_identical(flat)
    notes: list[str] = []
    width, label_w, plot_w, right_w = 980, 120, 640, 208
    sub_h = 40
    n_rows = len(merged) + len(empties)
    height = 34 + sub_h * max(1, n_rows) + 10
    x0 = label_w

    def X(v: float) -> float:
        return x0 + (v / xmax) * plot_w

    parts = [
        f'<svg class="strip" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Rate strip: one row per distinct pay pattern per rate type, one dot per observed dollar rate on a shared dollar scale starting at zero, middle half and median marked">'
    ]
    tick = 0
    while tick <= xmax:
        parts.append(f'<line x1="{X(tick):.0f}" y1="22" x2="{X(tick):.0f}" y2="{height - 8}" stroke="#E5E7EB"/>')
        parts.append(f'<text x="{X(tick):.0f}" y="14" font-size="10" fill="#374151" text-anchor="middle">${tick:,.0f}</text>')
        tick += 25
    y_cursor = 30
    for g in merged:
        mid = y_cursor + 18
        vals = sorted(float(r["negotiated_rate"]) for r in g["rows"])
        p25, med, p75 = _percentile(vals, 0.25), _percentile(vals, 0.5), _percentile(vals, 0.75)
        label = " · ".join(g["codes"])
        parts.append(f'<text x="0" y="{mid - 2}" font-size="12.5" font-weight="700">{html.escape(label)}</text>')
        parts.append(f'<text x="0" y="{mid + 12}" font-size="10" fill="#374151">{html.escape(str(g["rtype"]))}</text>')
        if len(g["codes"]) > 1:
            parts.append(f'<text x="{x0 + 2}" y="{mid - 13}" font-size="9.5" fill="#6B7280">same published amounts for each of these codes</text>')
        if len(vals) > 1:
            parts.append(f'<rect x="{X(p25):.1f}" y="{mid - 9}" width="{max(2.0, X(p75) - X(p25)):.1f}" height="18" fill="#CCFBF1"/>')
        drawn, capped = _sample(g["rows"])
        if capped:
            notes.append(f"{label} ({g['rtype']}): {len(drawn)} of {len(vals)} dots drawn, evenly spaced. Every rate is in the tables.")
        for j, r in enumerate(drawn):
            v = float(r["negotiated_rate"])
            y = mid - 5 + (j % 3) * 5
            who = r.get("provider_name") or ("NPI " + r["npi"] if r.get("npi") else "provider not named in file")
            title = html.escape(f"{r['payer']} | {r['negotiated_type']} | ${v:,.2f} | {who}")
            attrs = (
                f'class="dot" tabindex="0" data-code="{html.escape(label)}" data-rate="${v:,.2f}" '
                f'data-payer="{html.escape(str(r["payer"]))}" data-type="{html.escape(str(r["negotiated_type"]))}" '
                f'data-who="{html.escape(str(who))}" data-tin="{html.escape(str(r["tin"]))}" data-npi="{html.escape(str(r["npi"]))}" '
                f'data-src="{html.escape(str(r["source_url"]))}" '
                f'data-median="${med:,.2f}" data-band="${p25:,.2f} to ${p75:,.2f}"'
            )
            if g["rtype"] == "negotiated":
                parts.append(f'<circle {attrs} cx="{X(v):.1f}" cy="{y}" r="4" fill="#111827" fill-opacity="0.88"><title>{title}</title></circle>')
            else:
                parts.append(f'<circle {attrs} cx="{X(v):.1f}" cy="{y}" r="4" fill="#FFFFFF" stroke="#111827" stroke-width="1.3"><title>{title}</title></circle>')
        parts.append(f'<line x1="{X(med):.1f}" y1="{mid - 11}" x2="{X(med):.1f}" y2="{mid + 11}" stroke="#111827" stroke-width="3"/>')
        rx = x0 + plot_w + 12
        if len(vals) == 1:
            parts.append(f'<text x="{rx}" y="{mid + 4}" font-size="11">single rate ${med:,.0f} | n=1, no spread</text>')
        else:
            per = f" | n={len(vals)} each" if len(g["codes"]) > 1 else f" | n={len(vals)}"
            parts.append(
                f'<text x="{rx}" y="{mid - 2}" font-size="11">median ${med:,.0f}</text>'
                f'<text x="{rx}" y="{mid + 12}" font-size="10" fill="#374151">middle half ${p25:,.0f} to ${p75:,.0f}{per}</text>'
            )
        y_cursor += sub_h
    for code in empties:
        mid = y_cursor + 18
        parts.append(f'<text x="0" y="{mid - 2}" font-size="12.5" font-weight="700">{html.escape(code)}</text>')
        parts.append(f'<text x="0" y="{mid + 12}" font-size="10" fill="#374151">{html.escape(codes_meta.get(code, ""))}</text>')
        parts.append(f'<text x="{x0 + 6}" y="{mid + 4}" font-size="11" fill="#374151">No dollar rates found in the files pulled so far</text>')
        parts.append(f'<text x="{x0 + plot_w + 12}" y="{mid + 4}" font-size="11" fill="#374151">n=0</text>')
        y_cursor += sub_h
    parts.append("</svg>")
    return "".join(parts), notes


_STRIP_CAPTION = (
    "One row per distinct pay pattern and rate type, on one dollar scale that starts at zero for every row. "
    "Rate types are never pooled: a negotiated median and a fee schedule median are different facts. "
    "Where a payer publishes the identical amounts for several codes, those codes share one row instead of repeating the same picture. "
    "Each dot is one real dollar rate from a payer file. The teal band is the middle half of rates (p25 to p75). The thick tick is the median. "
    "Percentiles use linear interpolation between closest ranks. Observed dots are never interpolated. "
    "Filled dots are negotiated rates. Hollow dots are fee schedule rates. Percentage rates are not dollars and are left out. "
    "Hover any dot for payer, rate type, amount, and provider. Click or tap to pin its panel and open the source link. Tab works the same, Enter pins, Escape closes."
)


def _strip_block(codes, rows_by_code: dict[str, list[dict]], xmax: float) -> str:
    """Full strip markup (caption + svg + notes + detail panel + script)."""
    code_groups: dict[str, list[dict]] = {}
    for c in codes:
        by_type: dict[str, list[dict]] = {}
        for r in rows_by_code.get(c.code, []):
            by_type.setdefault(str(r["negotiated_type"]), []).append(r)
        code_groups[c.code] = [
            {"rtype": t, "rows": rs}
            for t, rs in sorted(by_type.items(), key=lambda kv: (kv[0] != "negotiated", kv[0]))
        ]
    svg, notes = _strip_svg(code_groups, xmax, {c.code: c.code_system for c in codes})
    note_html = "".join(f"<p class='note'>{html.escape(n)}</p>" for n in notes)
    return (
        f"<p>{_STRIP_CAPTION}</p>"
        + svg
        + note_html
        + '<div id="tip" role="status"></div>'
        + """<script>
(function(){
  var tip=document.getElementById('tip'), pinned=false;
  function fill(d, link){
    var pos='Market for this code and type: median '+d.median+', middle half '+d.band;
    var src=link?'<a href="'+d.src+'">source payer file</a>':'Source: '+d.src;
    tip.innerHTML='<strong>'+d.rate+'</strong> &nbsp;'+d.code+'<br>'+d.payer+' | '+d.type+
      '<br>'+d.who+(d.tin?'<br>TIN '+d.tin:'')+(d.npi && d.who.indexOf(d.npi)<0?'<br>NPI '+d.npi:'')+
      '<br>'+pos+'<br><span class="src">'+src+'</span>'+(link?'<br><span class="src">Click again or press Escape to close</span>':'');
  }
  function show(d){fill(d,false);tip.style.display='block';}
  function pin(d,el){
    pinned=true;tip.classList.add('pinned');fill(d,true);
    tip.style.display='block';tip.style.left='auto';tip.style.right='14px';tip.style.top='auto';tip.style.bottom='14px';
  }
  function unpin(){pinned=false;tip.classList.remove('pinned');tip.style.display='none';}
  function move(e){if(pinned)return;tip.style.left=Math.min(e.clientX+14,innerWidth-360)+'px';tip.style.top=Math.min(e.clientY+14,innerHeight-190)+'px';}
  document.querySelectorAll('.dot').forEach(function(el){
    el.addEventListener('mouseenter',function(e){if(!pinned){show(el.dataset);move(e);}});
    el.addEventListener('mousemove',move);
    el.addEventListener('mouseleave',function(){if(!pinned)tip.style.display='none';});
    el.addEventListener('click',function(){pinned?unpin():pin(el.dataset,el);});
    el.addEventListener('focus',function(){if(!pinned){show(el.dataset);var r=el.getBoundingClientRect();tip.style.left=Math.min(r.left+14,innerWidth-360)+'px';tip.style.top=(r.bottom+10)+'px';}});
    el.addEventListener('blur',function(){if(!pinned)tip.style.display='none';});
    el.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();pinned?unpin():pin(el.dataset,el);}});
  });
  document.addEventListener('keydown',function(e){if(e.key==='Escape')unpin();});
  var f=document.getElementById('codefilter');
  if(f){f.addEventListener('input',function(){
    var q=f.value.trim().toLowerCase();
    document.querySelectorAll('table.filterable tbody tr').forEach(function(tr){
      tr.style.display=(!q||(tr.dataset.code||'').indexOf(q)>-1)?'':'none';
    });
  });}
})();
</script>"""
    )


@app.get("/code/{code}", response_class=HTMLResponse)
def code_page(code: str, payer: str | None = None) -> str:
    if not _has_data():
        return f"<html><body style='font-family:system-ui'><h1>{html.escape(code)}</h1><p>No data pulled yet.</p></body></html>"
    bench = [r for r in summary_by_code_payer() if str(r["billing_code"]) == code]
    payer_links = "".join(
        f"<a class='chip' href='/code/{html.escape(code)}?payer={html.escape(str(p))}'>{html.escape(str(p))}</a>"
        for p in sorted({str(r["payer"]) for r in bench})
    )
    breakdown = ""
    if bench:
        breakdown = (
            "<h2>Median by payer</h2><div class='table-wrap'><table><tr><th>Payer</th><th>Rate type</th><th>Rates</th><th>p25</th><th>Median</th><th>p75</th></tr>"
            + "".join(
                "<tr><td>{p}</td><td>{t}</td><td class='n'>{n}</td><td class='n'>${a:,.2f}</td><td class='n'>${m:,.2f}</td><td class='n'>${b:,.2f}</td></tr>".format(
                    p=html.escape(str(r["payer"])), t=html.escape(str(r["negotiated_type"])), n=r["n_rates"],
                    a=r["p25"] or 0, m=r["median"] or 0, b=r["p75"] or 0,
                )
                for r in bench
            )
            + "</table></div>"
        )
    rows = rates_for_code(code, payer=payer, limit=500)
    plot = _dot_plot(rows)
    trs = "".join(
        "<tr><td>{p}</td><td>${v:,.2f}</td><td>{t}</td><td>{prov}</td><td>{tin}</td><td><a href='{src}'>source file</a></td></tr>".format(
            p=html.escape(str(r["payer"])), v=r["negotiated_rate"] or 0, t=html.escape(str(r["negotiated_type"])),
            prov=html.escape(str(r["provider_name"])), tin=html.escape(str(r["tin"])), src=html.escape(str(r["source_url"])),
        )
        for r in rows[:200]
    )
    table = "<table><tr><th>Payer</th><th>Rate</th><th>Type</th><th>Provider</th><th>TIN</th><th>Lineage</th></tr>" + trs + "</table>"
    if payer:
        scope = f"<p class='coverage'>Showing {html.escape(payer)} only. <a href='/code/{html.escape(code)}'>Show all payers</a></p>"
        shown = payer
    else:
        scope = f"<p class='coverage'>Filter by payer: <span class='chips'>{payer_links}</span></p>" if payer_links else ""
        shown = "all payers"
    csv_link = f"/api/rates/{html.escape(code)}.csv" + (f"?payer={html.escape(payer)}" if payer else "")
    return (
        f"<html><head><title>{html.escape(code)} rates</title>{og_head()}<style>{STYLE}</style></head><body><div class='wrap'>"
        f"<p><a href='/'>All codes</a></p><h1>Code {html.escape(code)}</h1>{scope}{breakdown}{plot}"
        f"<h2>See the numbers ({shown})</h2>{table}"
        f"<p class='note'>Each dot is one observed dollar rate for one provider group ({shown}). Dashed line is the median. Rates link to the payer file they came from. "
        f"Download: <a href='{csv_link}'>these rates as CSV</a> · <a href='/api/rates/{html.escape(code)}'>JSON</a>. First 200 rows shown; the CSV and JSON carry up to 500.</p></div></body></html>"
    )


@app.get("/api/sources")
def api_sources():
    from .benchmarks import sources_detail

    return sources_detail()


@app.get("/api/codes")
def api_codes():
    return [{"code": c.code, "code_system": c.code_system, "note": c.note} for c in load_codes()]


@app.get("/api/summary")
def api_summary():
    if not _has_data():
        return JSONResponse({"detail": "no data yet"}, status_code=404)
    return summary_by_code_payer()


@app.get("/api/aggregate")
def api_aggregate():
    if not _has_data():
        return JSONResponse({"detail": "no data yet"}, status_code=404)
    return summary_all_payers()


def _csv_response(rows: list[dict], cols: list[str], filename: str) -> PlainTextResponse:
    import csv as _csv
    import io

    buf = io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return PlainTextResponse(
        buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/summary.csv")
def api_summary_csv():
    if not _has_data():
        return JSONResponse({"detail": "no data yet"}, status_code=404)
    return _csv_response(
        summary_by_code_payer(),
        ["billing_code", "billing_code_type", "payer", "negotiated_type", "n_rates", "n_provider_groups", "min_rate", "p25", "median", "p75", "max_rate"],
        "openpayer-benchmarks-by-payer.csv",
    )


@app.get("/api/aggregate.csv")
def api_aggregate_csv():
    if not _has_data():
        return JSONResponse({"detail": "no data yet"}, status_code=404)
    return _csv_response(
        summary_all_payers(),
        ["billing_code", "billing_code_type", "negotiated_type", "n_rates", "n_payers", "n_provider_groups", "min_rate", "p25", "median", "p75", "max_rate"],
        "openpayer-benchmarks-all-payers.csv",
    )


@app.get("/api/rates/{code}.csv")
def api_rates_csv(code: str, payer: str | None = None):
    if not _has_data():
        return JSONResponse({"detail": "no data yet"}, status_code=404)
    return _csv_response(
        rates_for_code(code, payer=payer),
        ["payer", "negotiated_rate", "negotiated_type", "billing_class", "provider_name", "tin", "npi", "source_url"],
        f"openpayer-rates-{code}.csv",
    )


@app.get("/api/rates/{code}")
def api_rates(code: str, payer: str | None = None):
    if not _has_data():
        return JSONResponse({"detail": "no data yet"}, status_code=404)
    return rates_for_code(code, payer=payer)


def serve() -> None:
    import os

    import uvicorn

    if authmod.auth_enabled() and not (os.environ.get("RESEND_API_KEY") and os.environ.get("MAIL_FROM")):
        print("WARNING: auth is on but RESEND_API_KEY/MAIL_FROM are unset. Sign-in links will print to this log. Set both in production.")
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))

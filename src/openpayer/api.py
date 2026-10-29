from __future__ import annotations

import html

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from urllib.parse import urlencode as _urlencode

from . import auth as authmod
from . import reference
from .benchmarks import data_inventory, flags_input, rates_for_code, summary_all_payers, summary_by_code_payer
from .config import load_codes
from .store import DB_PATH

app = FastAPI(title="OpenPayer", description="Rate search and benchmarks from CMS price transparency files")

from starlette.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)

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
.mark{pointer-events:none}
.halo{pointer-events:none}
.striphit{cursor:crosshair;outline:none}
.striphit:focus{stroke:var(--focus);stroke-width:2}
#tip button{background:#fff;color:var(--ink);border:0;border-radius:6px;padding:.35rem .6rem;min-height:44px;font:inherit;cursor:pointer;margin:.35rem .35rem 0 0}
#tip{position:fixed;z-index:30;pointer-events:none;background:var(--ink);color:#fff;padding:.6rem .75rem;border-radius:8px;
font-size:.86rem;line-height:1.5;max-width:350px;display:none;box-shadow:0 4px 12px rgba(0,0,0,.18)}
svg.strip{width:100%;height:auto;display:block}
.tools{display:flex;flex-wrap:wrap;gap:.9rem;align-items:center;margin:1.2rem 0;padding:.8rem 1rem;background:var(--panel);border:1px solid var(--rule);border-radius:10px}
.tools input{padding:.4rem .6rem;border:1px solid var(--st-gray-300);border-radius:6px;font:inherit}
.chips{display:flex;flex-wrap:wrap;gap:.4rem}
.chip{border:1px solid var(--st-gray-300);border-radius:999px;padding:.45rem .85rem;min-height:44px;font-size:.88rem;text-decoration:none;background:#fff;color:var(--ink);cursor:pointer;font:inherit}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.downloads{font-size:.85rem;color:var(--muted)}
.payer-section{margin-top:2.4rem;border-top:2px solid var(--rule);padding-top:.6rem}
h1.hero{font-size:clamp(2rem,4.2vw,2.9rem);line-height:1.08;letter-spacing:-0.025em;max-width:24ch;text-wrap:balance}
.proof{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--rule);border:1px solid var(--rule);border-radius:12px;overflow:hidden;margin:1rem 0}
.proof div{background:#fff;padding:.85rem 1rem;font-size:.92rem;line-height:1.45}
.proof strong{display:block;font-size:.98rem}
.explorebar{position:sticky;top:0;z-index:15;background:#fff;border-bottom:1px solid var(--rule);padding:.75rem 0;display:flex;flex-wrap:wrap;gap:.7rem;align-items:center}
.seg{display:flex;border:1px solid var(--st-gray-300);border-radius:999px;overflow:hidden}
.seg button{border:0;background:#fff;padding:.45rem .8rem;min-height:44px;font:inherit;font-size:.88rem;cursor:pointer}
.seg button.on{background:var(--ink);color:#fff}
.resultline{font-size:.85rem;color:var(--muted);width:100%}
.answerband{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule);border-radius:12px;overflow:hidden;margin:1.1rem 0 1.5rem}
.answerband .cell{background:#fff;padding:1rem 1.1rem}
.answerband .lab{font-size:.82rem;font-weight:600;color:var(--muted)}
.answerband .med{font-family:var(--mono);font-size:1.55rem;line-height:1.15}
.lede-sm{font-size:1.05rem;max-width:68ch;margin:.2rem 0}
.code-head h1{font-size:clamp(2rem,4vw,2.75rem);line-height:1.1;letter-spacing:-0.02em;margin:.75rem 0 .35rem}
.code-head .cnum{font-family:var(--mono);font-weight:700}
.cellbar{display:block;height:6px;background:#9CA3AF;margin-bottom:2px}
.meter{border:1px solid var(--rule);border-radius:12px;padding:1rem 1.1rem .6rem;margin:1.2rem 0;background:#fff}
.meter h2{border-top:none;margin-top:.2rem;padding-top:0}
.mrow{display:grid;grid-template-columns:180px 1fr 290px;gap:.9rem;align-items:center;padding:.5rem 0;border-top:1px solid var(--rule)}
.mname{font-weight:600;font-size:.95rem;line-height:1.35}
.mname span{display:block;font-weight:400;color:var(--muted);font-size:.78rem}
.mtrack{background:#F3F4F6;height:14px;border-radius:3px}
.mfill{background:var(--ink);height:14px;border-radius:3px}
.mstat{font-size:.85rem;color:var(--muted);line-height:1.5}
.mstat span{display:block}
.chain{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--rule);border:1px solid var(--rule);border-radius:12px;overflow:hidden;margin:1rem 0}
.chain div{background:#fff;padding:.85rem 1rem;font-size:.92rem;line-height:1.45}
.chain strong{display:block;font-size:.98rem}
.banner{background:#FEF3C7;border:1px solid var(--gold);border-radius:10px;padding:.7rem 1rem;margin:1rem 0}
.trace{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin:1rem 0}
.trace .col{border:1px solid var(--rule);border-radius:10px;padding:.8rem 1rem}
.trace h3{margin:.1rem 0 .5rem;font-size:.95rem;color:var(--muted)}
.tie{display:inline-block;background:var(--panel);border:1px solid var(--rule);border-radius:999px;padding:.1rem .55rem;font-size:.78rem;margin:.15rem .2rem 0 0}
.gatecard{border:1px solid var(--rule);border-radius:10px;padding:.8rem 1rem;margin:.5rem 0}
.score{font-size:1.3rem;font-weight:700}
@media (max-width:700px){.chain{grid-template-columns:1fr}}
@media (max-width:700px){.mrow{grid-template-columns:1fr;gap:.3rem}}
@media (max-width:700px){.proof{grid-template-columns:1fr}.answerband{grid-template-columns:1fr}}
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
<li><strong>Flags for review:</strong> every rate is also measured against the Medicare fee schedule (CMS 2026 RVU file, national rate before geographic adjustment) and against peer payers. Patterns over the thresholds published in <code>flags.py</code> are listed on the landing page and at <code>/api/flags</code> with their counts. A flag is a review signal with its evidence attached, never a finding of fraud, waste, or abuse.</li>
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
<li><strong>Locality-adjusted Medicare:</strong> percent-of-Medicare today uses the national rate from the CMS 2026 RVU file (every geographic adjustment factor at 1.0), filtered to the configured codes by <code>scripts/pull_mpfs.py</code>. Per-locality rulers from the GPCI file in the same CMS zip are the same wiring when a flag needs one.</li>
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
        "<a class='brand' href='/'>OpenPayer</a><span class='brand-sub'>rate evidence for fraud, waste, and abuse review</span>"
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
    if not idx:
        if not detail.get("index_url"):
            return (f"Direct file list, no single payer index to age. Pulled {str(detail.get('pulled_at') or '')[:10]}.", "")
        return ("Pulled. Payer index date not recorded.", "")
    try:
        age = (date.today() - date.fromisoformat(idx)).days
    except ValueError:
        return ("Pulled. Payer index date not recorded.", "")
    if age < 0:
        return (
            f"Fresh. Index is dated {idx}, {-age} days from now: the payer posted its next monthly index before the month began.",
            "fresh-fresh",
        )
    if age <= 120:
        return (f"Fresh. Index is {age} days old, inside the quarterly cycle.", "fresh-fresh")
    return (f"Past the quarterly cycle. Index is {age} days old, rates may have changed in newer files.", "fresh-stale")


def _corpus_meter(inv: dict, summary_rows: list[dict], n_codes: int) -> str:
    """Front-page data legend: one bar per configured source.

    Bar length is rate rows kept in the corpus, scaled to the largest
    source. Freshness is the payer's own index date against today
    (quarterly cycle). A source with no rows says so in words; its bar
    stays empty rather than borrowing a minimum width.
    """
    from datetime import date as _date

    from .benchmarks import sources_detail

    by_payer = {p["payer"]: p for p in inv.get("by_payer", [])}
    codes_by_payer: dict[str, set] = {}
    for r in summary_rows:
        codes_by_payer.setdefault(str(r["payer"]), set()).add(str(r["billing_code"]))
    entries = []
    for d in sources_detail():
        ip = by_payer.get(d["payer"], {})
        entries.append((d, int(ip.get("rows") or 0), int(ip.get("files") or 0)))
    entries.sort(key=lambda e: (-e[1], e[0]["payer"]))
    max_rows = max((e[1] for e in entries), default=0) or 1
    parts = [
        "<section class='meter' aria-label='How much data from each source'>"
        "<h2>The corpus, source by source</h2>"
        "<p class='note'>Every rate here came from one of these published payer files, for the configured codes only. "
        "Bar length is rate rows kept, scaled to the largest source. Freshness compares the payer's own index date with today; "
        "payers refresh their files quarterly.</p>"
    ]
    for d, nrows, nfiles in entries:
        payer = html.escape(str(d["payer"]))
        idx = str(d.get("index_last_updated_on") or "")
        pulled = str(d.get("pulled_at") or "")[:10]
        ncodes = len(codes_by_payer.get(str(d["payer"]), ()))
        if not d.get("configured"):
            fresh = "<span>Not configured: no published index address found yet.</span>"
        elif nrows == 0:
            fresh = "<span>Searched, no rows kept yet.</span>"
        elif not pulled:
            fresh = "<span>Rows are in the corpus; this source's pull status is not recorded yet.</span>"
        elif not idx:
            fresh = f"<span>Direct file list, no single index date to age. Pulled {html.escape(pulled)}.</span>"
        else:
            try:
                age = (_date.today() - _date.fromisoformat(idx)).days
            except ValueError:
                age = None
            if age is None:
                fresh = f"<span>Pulled {html.escape(pulled)}. Index date not recorded.</span>"
            elif age < 0:
                fresh = f"<span class='fresh-fresh'>Index dated {html.escape(idx)}, {-age} days from now: the payer posted next month's index early.</span>"
            elif age <= 120:
                fresh = f"<span class='fresh-fresh'>Fresh: index {html.escape(idx)}, {age} days old.</span>"
            else:
                fresh = f"<span class='fresh-stale'>Past the quarterly cycle: index {html.escape(idx)}, {age} days old.</span>"
        pct = (nrows / max_rows * 100) if nrows else 0.0
        if nrows:
            stat = f"{nrows:,} rate rows · {nfiles} kept file{'s' if nfiles != 1 else ''} · {ncodes} of {n_codes} codes · pulled {html.escape(pulled) or 'date not recorded'}"
        else:
            stat = "0 rate rows kept"
        parts.append(
            f"<div class='mrow'><div class='mname'>{payer}<span>Transparency in Coverage file index</span></div>"
            f"<div class='mtrack'><div class='mfill' style='width:{pct:.1f}%'></div></div>"
            f"<div class='mstat'><span class='num'>{html.escape(stat)}</span>{fresh}</div></div>"
        )
    parts.append(_corpus_total_line(inv) + "</section>")
    return "".join(parts)


def _corpus_total_line(inv: dict) -> str:
    """The corpus total, written for a reader with no data background.

    Every term that needs one gets its explanation in the same sentence,
    so the counts can be repeated to a non-technical audience as-is.
    """
    total = int(inv.get("total_rows") or 0)
    files = int(inv.get("source_files") or 0)
    groups = int(inv.get("provider_groups") or 0)
    return (
        f"<p class='note'>What those numbers add up to: health insurers must publish the prices they "
        f"pay for care. We read those published price lists, kept only the prices for the eight "
        f"billing codes this site tracks, and discarded the rest. What remains is {total:,} single "
        f"prices, taken from {files} insurer files. Together they cover {groups:,} billing groups. "
        "A billing group is one doctor's office or clinic billing under a single tax number; one "
        "group can include many individual doctors. Every price on this page comes from one of those "
        "files, and the table further down lists each file with a link back to the original.</p>"
    )


_PAYER_SHAPE_NOTES = {
    "Aetna": (
        "Publishes a direct list of 80 files instead of one index, and we pulled the first 6. "
        "Each file keeps roughly 6,500 of our rows, but the same provider groups, about 196 tax IDs, "
        "recur across its plan variants, so its rows repeat its facts several times over. "
        "The other 74 files would add copies rather than coverage, and its pass stops there by design."
    ),
    "UnitedHealthcare": (
        "Its index lists 1,013 entries that dedupe to 77 files. The 40 smallest are mostly tiny "
        "employer plan files. Everything after that is a 2.5 to 9.4 GB book, and the one that finished "
        "repeated, row for row, rates already in the corpus from another of its books. For these codes "
        "it publishes one national schedule under many covers. Its index is dated 2026-11-01 and was "
        "posted before November began."
    ),
    "Elevance Anthem BCBS": (
        "Its index is the largest here, at least 250,000 entries, with 1,721 distinct files inside "
        "the first 5,000 entries alone. The 60 smallest files held almost none of our codes. The next "
        "size band carried real books, which is why this source is now the broadest in the corpus. "
        "Its giant national books remain unpulled; each takes hours and they are opened only deliberately."
    ),
    "Cigna": (
        "Its index holds about 101,000 files, and the two pulled already meet our group target for "
        "every code. It serves plain JSON at addresses ending in .json.gz, which our first reader "
        "trusted and failed on; the reader now sniffs the first bytes of every file instead of "
        "believing its name."
    ),
    "Cox HealthPlans": (
        "A small regional plan whose whole 89-file index has been attempted; 53 files held rates. "
        "Its files name providers by NPI but carry no tax IDs, so its provider-group count reads "
        "zero in our tables. Read its figures as rates, not groups."
    ),
    "Humana": (
        "Nothing yet. Its files sit behind a developer portal, and we have not found a "
        "machine-readable index we can pull from. It stays in the list so the gap is visible "
        "rather than silent."
    ),
}

_DATA_LESSONS = [
    "Rows are not evidence. Plan books repeat the same price for the same group under many covers, so every count on this site travels with its provider-group count and its distinct-price count.",
    "The smallest files are the least typical files a payer publishes. Ordering by size buys speed, and the first files from any source are tiny plans that often hold none of our codes.",
    "A pull stops at 150 provider groups per code for a payer. Past that, more files mostly recount groups already in the corpus.",
    "An index date is the payer's own label, and payers post next month's index before the month begins. Freshness is measured against that date and says so when the date is still ahead.",
    "A provider group is one tax ID, the same definition in the charts, the tables, and the flags. A rate filed without a tax ID counts as a rate, never as a group.",
    "Only the rows for the eight codes are kept, each with the address of the file it came from. The raw payer files, some of them 15 GB, are streamed once and not retained, and a per-file ledger lets every later pull resume instead of repeat.",
]


def _data_reviewed_section(inv: dict, details: list[dict] | None = None) -> str:
    """'The data we reviewed': what was read, what shape it arrived in.

    Counts are live from the inventory; the shape notes are curated and
    dated, and change only when a pull teaches us something new. This
    is the institutional memory of the corpus, written for the reader
    rather than the operator.
    """
    if details is None:
        from .benchmarks import sources_detail

        details = sources_detail()
    by_payer = {str(p["payer"]): p for p in inv.get("by_payer", [])}
    parts = [
        "<h2 id='data-reviewed'>The data we reviewed</h2>"
        "<p>Every rate on this site came out of the files below. This section says what we actually "
        "read, what shape it arrived in, and what it taught us, so the numbers above it can be judged "
        "rather than trusted. Counts are live from the database on every load. The notes are ours, "
        "last reviewed on October 29, 2026, and they change only when a pull teaches us something new.</p>"
    ]
    for d in details:
        payer = str(d["payer"])
        ip = by_payer.get(payer, {})
        nrows = int(ip.get("rows") or 0)
        if nrows:
            nfiles = int(ip.get("files") or 0)
            counts = (
                f"In the corpus: {nrows:,} rates from {nfiles} file{'s' if nfiles != 1 else ''}, "
                f"covering {int(ip.get('groups') or 0):,} provider groups."
            )
        else:
            counts = "In the corpus: nothing yet."
        note = _PAYER_SHAPE_NOTES.get(payer, "")
        parts.append(
            f"<h3>{html.escape(payer)}</h3><p class='coverage'>{html.escape(counts)}</p>"
            + (f"<p>{html.escape(note)}</p>" if note else "")
        )
    parts.append("<h3>What the files taught us</h3><ul>")
    parts.extend(f"<li>{html.escape(lesson)}</li>" for lesson in _DATA_LESSONS)
    parts.append("</ul>")
    return "".join(parts)


_FLAG_LABELS = {
    "median_far_above_medicare": "Median far above Medicare",
    "extreme_rates": "Rates at ten times Medicare or more",
    "placeholder_rates": "Placeholder-priced rates",
    "single_amount_many_groups": "One amount across many provider groups",
    "code_not_published": "Code not published at all",
}


def _flag_evidence(f: dict) -> str:
    e = f["evidence"]
    k = f["kind"]
    if k == "median_far_above_medicare":
        return f"Median ${e['median_rate']:,.0f} is {e['median_percent_of_medicare']}% of Medicare across {e['n_negotiated']:,} negotiated rates"
    if k == "extreme_rates":
        return f"{e['n_at_or_above_10x_medicare']} of {e['n_negotiated']:,} negotiated rates sit at ten times Medicare or more; highest ${e['max_rate']:,.0f} ({e['max_percent_of_medicare']}%)"
    if k == "placeholder_rates":
        return f"{e['n_at_or_below_1_dollar']:,} of {e['n_rates']:,} rates are priced at $1.00 or less ({e['share'] * 100:.0f}%)"
    if k == "single_amount_many_groups":
        return f"One amount, ${e['amount']:,.2f}, covers {e['provider_groups_at_amount']:,} provider groups ({e['share'] * 100:.0f}% of this payer's rates for the code)"
    if k == "code_not_published":
        return f"Publishes no rates for this code; {e['payers_publishing_code']} other payers in the corpus do"
    return ""


def _pct_text(code: str, amount) -> str:
    """Amount as a percent of the Medicare national rate, or empty."""
    from . import reference as _ref

    pct = _ref.percent_of_medicare(code, float(amount or 0))
    return f"{pct:,.0f}% of Medicare" if pct is not None else ""


def _flags_section() -> str:
    """Fraud, waste, and abuse review flags, computed live from the corpus."""
    from . import flags as _flags
    from . import reference as _ref

    computed = _flags.compute_flags(flags_input())
    info = _ref.mpfs_info()
    n_by_sev = {s: sum(1 for f in computed if f["severity"] == s) for s in ("high", "medium", "low")}
    parts = [
        "<h2>Flags for review: where the filed rates do not line up</h2>"
        "<p>Every stored rate is measured two ways: against Medicare, and against the other payers in the corpus. "
        f"The Medicare ruler is the CMS 2026 Physician Fee Schedule (file RVU26A), national rate before geographic adjustment, "
        f"conversion factor ${info.get('conversion_factor')}. Patterns over the thresholds published at the top of "
        "<code>flags.py</code> in the repo are listed here, with the counts that produced them. "
        "Download: <a href='/api/flags'>flags JSON</a> · <a href='/api/flags.csv'>flags CSV</a>.</p>"
        "<p>CMS has said it is done playing catch-up and is deploying data analytics to stop fraud before a dollar "
        "leaves the building (Department of Justice, 2026 National Health Care Fraud Takedown, June 23, 2026). "
        "This corpus works in that order: the filed rate exists before any claim does, so the flag does too.</p>"
        f"<p class='note'>{html.escape(_flags.FLAG_NOTE)}</p>"
    ]
    if not computed:
        parts.append("<p>No patterns over the current thresholds in the data pulled so far.</p>")
        return "".join(parts)
    parts.append(
        f"<p><strong>{len(computed)} flags: {n_by_sev['high']} high, {n_by_sev['medium']} medium, {n_by_sev['low']} low.</strong> "
        "High flags are measured against Medicare. Medium and low flags are measured against peer payers or against the shape of the payer's own file.</p>"
        "<div class='table-wrap'><table><thead><tr><th>Severity</th><th>Payer</th><th>Code</th><th>Signal</th><th>What we saw</th><th>Medicare rate</th></tr></thead><tbody>"
    )
    for f in computed:
        med = f"${f['medicare_rate']:,.2f}" if f.get("medicare_rate") else "not loaded"
        parts.append(
            "<tr><td>{sev}</td><td>{payer}</td><td><a href='/code/{code}?payer={payer}'>{code}</a></td>"
            "<td><a href='{dossier}'>{label}</a></td><td>{ev}</td><td class='n'>{med}</td></tr>".format(
                sev=html.escape(f["severity"].capitalize()),
                payer=html.escape(f["payer"]),
                code=html.escape(f["billing_code"]),
                dossier="/flag?" + _urlencode({"payer": f["payer"], "code": f["billing_code"], "kind": f["kind"]}),
                label=html.escape(_FLAG_LABELS.get(f["kind"], f["kind"])),
                ev=html.escape(_flag_evidence(f)),
                med=med,
            )
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _flag_dossier(f: dict) -> str:
    """One flag as a hand-off page: pattern, math, clearing test, rows.

    Built to be forwarded to a reviewer (CMS program integrity, HHS-OIG,
    a state Medicaid Fraud Control Unit, a payer's own integrity team).
    Print-clean. Every rate row links to the payer file it came from.
    """
    from collections import Counter
    from datetime import date as _date

    from . import reference as _ref

    payer, code, kind = f["payer"], f["billing_code"], f["kind"]
    label = _FLAG_LABELS.get(kind, kind)
    rows = rates_for_code(code, payer=payer, limit=500) if kind != "code_not_published" else []
    dollar = [r for r in rows if r.get("negotiated_rate") is not None]
    med_rate = f.get("medicare_rate")

    if kind in ("median_far_above_medicare", "extreme_rates"):
        show = sorted(dollar, key=lambda r: -float(r["negotiated_rate"]))[:50]
        shown_note = f"Highest {len(show)} of {len(dollar)} stored rates for this payer and code, highest first."
    elif kind == "placeholder_rates":
        show = [r for r in dollar if float(r["negotiated_rate"]) <= 1.0][:50]
        shown_note = f"Showing {len(show)} of the rates priced at $1.00 or less."
    elif kind == "single_amount_many_groups":
        amount = float(f["evidence"].get("amount") or 0)
        show = [r for r in dollar if float(r["negotiated_rate"]) == amount][:50]
        shown_note = f"Showing {len(show)} provider groups at the single amount of ${amount:,.2f}."
    else:
        show = []
        shown_note = ""

    trs = "".join(
        "<tr><td>${v:,.2f}</td><td class='n'>{pct}</td><td>{t}</td><td>{prov}</td><td>{tin}</td>"
        "<td><a href='{src}'>source file</a></td></tr>".format(
            v=float(r["negotiated_rate"]), pct=html.escape(_pct_text(code, r["negotiated_rate"])),
            t=html.escape(str(r["negotiated_type"])), prov=html.escape(str(r["provider_name"])),
            tin=html.escape(str(r["tin"])), src=html.escape(str(r["source_url"])),
        )
        for r in show
    )
    rates_block = (
        f"<h2>The rates underneath</h2><p>{html.escape(shown_note)}</p>"
        "<div class='table-wrap'><table><tr><th>Rate</th><th>% of Medicare</th><th>Type</th><th>Provider</th><th>TIN</th><th>Lineage</th></tr>"
        + trs + "</table></div>"
        if show else ""
    )

    states: Counter = Counter()
    named = 0
    for r in dollar:
        for one in str(r.get("npi") or "").split(","):
            hit = _ref.nppes_lookup(one)
            if hit:
                named += 1
                if hit.get("state"):
                    states[str(hit["state"])] += 1
    if named:
        geo = ", ".join(f"{s}: {n}" for s, n in states.most_common(12))
        geo_block = f"<h2>Where these rates sit</h2><p>Practice states from the NPI registry for {named} matched rates: {html.escape(geo)}.</p>"
    else:
        geo_block = (
            "<h2>Where these rates sit</h2><p>Geography joins from the NPI registry (NPPES) and is not loaded yet, "
            "so no state is claimed here. Provider names in the table are as the payer printed them, or unnamed.</p>"
        )

    ev_items = "".join(
        f"<tr><td>{html.escape(str(k).replace('_', ' '))}</td><td class='n'>{html.escape(str(v))}</td></tr>"
        for k, v in f["evidence"].items()
    )
    publishers = ""
    if kind == "code_not_published":
        others = sorted({str(r["payer"]) for r in summary_by_code_payer() if str(r["billing_code"]) == code})
        publishers = (
            "<h2>Who does publish this code</h2><p>"
            + ", ".join(f"<a href='/code/{html.escape(code)}?payer={html.escape(p)}'>{html.escape(p)}</a>" for p in others)
            + ". Their rates are one click from the files behind them.</p>"
        )
    info = _ref.mpfs_info()
    math_block = (
        f"<h2>The Medicare math</h2><p>Medicare national rate for {html.escape(code)}: "
        + (f"<strong>${med_rate:,.2f}</strong>" if med_rate else "not loaded")
        + f". Basis: {html.escape(str(info.get('basis') or ''))} Source: {html.escape(str(info.get('source') or ''))} "
        f"(conversion factor ${info.get('conversion_factor')}). Locality adjustment is not applied; the ruler is national.</p>"
    )
    return (
        f"<html><head><title>Flag: {html.escape(label)} | OpenPayer</title>{og_head()}<style>{STYLE}</style></head><body><div class='wrap'>"
        f"<p><a href='/'>All codes and flags</a></p>"
        f"<h1>{html.escape(label)}</h1>"
        f"<p class='lede-sm'>{html.escape(f['severity'].capitalize())} flag · {html.escape(payer)} · code {html.escape(code)} · prepared {_date.today().isoformat()} from the live corpus</p>"
        f"<p class='note'>{html.escape(f['note'])}</p>"
        f"<h2>What we saw</h2><p>{html.escape(_flag_evidence(f))}</p>"
        "<div class='table-wrap'><table><tr><th>Measure</th><th>Value</th></tr>" + ev_items + "</table></div>"
        + math_block
        + f"<h2>What would clear this flag</h2><p>{html.escape(f.get('clears_if') or '')}</p>"
        + f"<h2>Where this goes next</h2><p>{html.escape(f.get('lever') or '')} What happens after review is not this page's call: CMS, HHS-OIG, a state Medicaid Fraud Control Unit, or the payer's own integrity team decides.</p>"
        + publishers + rates_block + geo_block
        + "<p class='note'>Every figure on this page is computed from rates the payer published, each linked to its source file above. "
        "Counts are as stored in the corpus today; a deeper pull can change them, and the corpus meter on the home page says how deep the pull is.</p>"
        "</div></body></html>"
    )


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
                pulled=html.escape(str((d["pulled_at"] or "not recorded")[:10])),
                files=(
                    (f"{d['files_attempted']} of at least {d['files_in_index']:,} in index (count capped)" if d.get("index_count_capped")
                     else f"{d['files_attempted']} of {d['files_in_index']} in index") if d["files_attempted"] is not None else "none"
                ),
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

    headline = "Find the rates that do not belong."
    neg13 = next((r for r in agg if r["billing_code"] == "99213" and r["negotiated_type"] == "negotiated"), None)
    fs13 = next((r for r in agg if r["billing_code"] == "99213" and r["negotiated_type"] == "fee schedule"), None)
    lead_row = neg13 or fs13
    finding = ""
    if lead_row:
        kind = "negotiated rate" if lead_row["negotiated_type"] == "negotiated" else "fee schedule rate"
        finding = (
            f"Across {payer_phrase}, a 99213 office visit pays a median {kind} of ${lead_row['median']:,.0f} "
            f"(middle half ${lead_row['p25']:,.0f} to ${lead_row['p75']:,.0f}, n={lead_row['n_rates']}). "
        )

    all_rows_by_code: dict[str, list[dict]] = {}
    all_vals: list[float] = []
    for c in codes:
        rs = [r for r in rates_for_code(c.code, limit=100000) if r.get("negotiated_rate") is not None]
        all_rows_by_code[c.code] = rs
        all_vals.extend(float(r["negotiated_rate"]) for r in rs)
    # One scale per code, shared by every payer and rate type inside that
    # code: the next $25 above the larger of the code's 99th percentile
    # and its largest summary p75 (Tufte review, 2026-10-28). A single
    # global scale let one code's $300 rates crush another code's $6
    # medians into the left edge of every row. Prices above a code's
    # scale are drawn below the row and named, never clipped silently.
    xmax_by_code: dict[str, float] = {}
    for c in codes:
        vals = sorted(float(r["negotiated_rate"]) for r in all_rows_by_code[c.code])
        p75_peak = max(
            (float(r["p75"] or 0) for r in rows if str(r["billing_code"]) == c.code),
            default=0.0,
        )
        if vals:
            p99 = _percentile(vals, 0.99) if len(vals) >= 20 else max(vals)
            xmax_by_code[c.code] = max(25.0, (int(max(p99, p75_peak) / 25) + 1) * 25)
        else:
            xmax_by_code[c.code] = 100.0
    spread_peak = max((float(r["p75"] or r["median"] or 0) for r in rows), default=0.0)
    xmax = max(25.0, (int(max([*all_vals, spread_peak]) / 25) + 1) * 25) if (all_vals or spread_peak) else 100.0
    family_vals = [
        float(r["negotiated_rate"])
        for c in codes if c.code in _FAMILY
        for r in all_rows_by_code[c.code]
    ]
    family_peak = max(
        (float(r["p75"] or 0) for r in rows if str(r["billing_code"]) in _FAMILY),
        default=0.0,
    )
    ladder_xmax = (
        max(25.0, (int(max([*family_vals, family_peak]) / 25) + 1) * 25)
        if (family_vals or family_peak) else 100.0
    )

    def _money(v) -> str:
        return f"${(v or 0):,.2f}"

    def _trs(subset, link_payer: str | None) -> str:
        out = []
        for r in subset:
            q = f"?payer={html.escape(str(link_payer))}" if link_payer else ""
            out.append(
                "<tr data-code='{code}'><td><a href='/code/{code}{q}'>{code}</a></td><td>{rtype}</td><td class='n'>{n}</td><td class='n'>{groups}</td>"
                "<td class='n'>{p25}</td><td class='n'><span class='cellbar' style='width:{bar:.0f}%'></span>{med}</td><td class='n'>{p75}</td><td class='n'>{mn}</td><td class='n'>{mx}</td></tr>".format(
                    code=html.escape(str(r["billing_code"])), q=q, rtype=html.escape(str(r["negotiated_type"])), n=r["n_rates"],
                    groups=r["n_provider_groups"], p25=_money(r["p25"]), med=_money(r["median"]), p75=_money(r["p75"]),
                    mn=_money(r["min_rate"]), mx=_money(r["max_rate"]),
                    bar=(float(r["median"] or 0) / xmax * 100) if xmax else 0,
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
    payer_chips = "<button class='chip on' data-payer-chip=''>All payers</button>" + "".join(
        f"<button class='chip' data-payer-chip='{html.escape(p)}'>{html.escape(p)}</button>" for p in payers
    )
    total_rates = sum(int(r["n_rates"]) for r in agg)
    tools = (
        "<div class='explorebar' role='group' aria-label='Explore controls'>"
        "<span class='seg' role='group' aria-label='Rate type'><button data-type-btn='' class='on'>Both apart</button>"
        "<button data-type-btn='negotiated'>Negotiated</button><button data-type-btn='fee schedule'>Fee schedule</button></span>"
        f"<span class='chips'>{payer_chips}</span>"
        "<label>Code <input id='codefilter' type='search' placeholder='try 99213' autocomplete='off'></label>"
        "<span class='downloads'>Download: <a href='/api/aggregate.csv'>aggregate CSV</a> · <a href='/api/summary.csv'>by-payer CSV</a> · "
        "<a href='/api/aggregate'>aggregate JSON</a> · <a href='/api/summary'>by-payer JSON</a> · <a href='/api/sources'>sources JSON</a></span>"
        f"<span class='resultline' id='resultline'>Showing {len(codes)} codes · {len(payers)} payers · {total_rates} benchmark rates · each code on its own scale from $0, the same for every payer inside that code. {html.escape(finding)}</span></div>"
    )
    market = (
        "<h2 id='rates'>What each payer pays, code by code</h2>"
        "<p>One row per payer per rate type: the dot is the median, the line is the middle half of observed rates. "
        "Rate types are never pooled. Every row carries its count. Select a row label to open that code at that payer, where every rate sits with its source file. "
        "Further down, every distinct price is drawn once with its provider group count, so a price many groups share cannot look like a spread of prices.</p>"
        + _payer_spread(rows, codes, xmax_by_code)
        + "<h2>The consult family, panel by panel</h2>"
        "<p>One panel per code, one row per payer per rate type. The dot is the median (filled for negotiated, open for fee schedule), "
        "the bar is the middle half, and the gold line is Medicare's national rate for that code. Nothing connects across codes, "
        "because these are separate codes, not a trend. Where a payer files no rate, the row says so. "
        "Source: payer Transparency in Coverage files as filed; Medicare Physician Fee Schedule 2026; "
        "negotiated and fee schedule rates shown separately, never pooled. 99213 and G2212 are not in this family.</p>"
        + _family_ladder(rows, ladder_xmax)
        + "<h2>Every observed rate, payer by payer</h2>"
        + _strip_block(codes, all_rows_by_code, xmax_by_code, script=False)
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
            (f"{d.get('files_attempted')} of at least {d.get('files_in_index'):,} files in its index searched (index count capped), {d.get('files_with_rows')} held rates for our codes"
             if d.get("index_count_capped") else
             f"{d.get('files_attempted')} of {d.get('files_in_index')} files in its index searched, {d.get('files_with_rows')} held rates for our codes")
            if d.get("files_attempted") is not None else "not pulled yet"
        )
        line = (
            f"Index dated {d.get('index_last_updated_on') or 'not recorded'}, pulled {(d.get('pulled_at') or '')[:10] or 'not yet'}: {searched}. "
            f"{sum(r['n_rates'] for r in sub)} benchmark rates in the tables below."
        )
        sections.append(
            f"<section class='payer-section' id='payer-{html.escape(_slug_payer(payer))}'>"
            f"<h2>{html.escape(payer)}</h2><p class='coverage'>{html.escape(line)}</p>"
            + _strip_block(codes, sub_by_code, xmax_by_code, script=False, payer=payer)
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
        "<p class='lede'>OpenPayer reads the rate files payers must publish for eight billing codes, lines every rate up "
        "against the Medicare fee schedule and against the other payers, and flags the patterns a fraud, waste, and abuse "
        "reviewer should see first. Every flag carries its counts and the payer file behind it. "
        "A flag is a reason to look. It is never a finding.</p>"
    )
    proof = (
        "<div class='proof'>"
        "<div><strong>Open source, Apache 2.0</strong>Anyone can run the whole chain and audit exactly how a number was produced.</div>"
        "<div><strong>Observed, not estimated</strong>Every rate is taken from a real payer filing, linked to that file, with its count shown. Rate types are never blended or interpolated.</div>"
        "<div><strong>Flags, not verdicts</strong>Unusual patterns are listed as review flags with the evidence beside them. Filed rates are not claims, so nothing here accuses anyone. It tells a reviewer where to look first.</div>"
        "</div>"
    )
    chain = (
        "<div class='chain'>"
        "<div><strong>1 · The rate, as filed</strong>Payers publish contracted rates under federal transparency rules. This site reads those files for eight billing codes. Public data: no patient, no claim, no record access.</div>"
        "<div><strong>2 · The flag</strong>Each rate is measured against the Medicare fee schedule and against peer payers. Patterns over the published thresholds become review flags, each with its counts and the file it came from.</div>"
        "<div><strong>3 · The record check</strong>A flag is a reason to hold a provider's claims and check them against the patient's own clinical record before payment. That review is MedTruth's. CMS makes every call.</div>"
        "</div>"
    )
    return (
        f"<html><head><title>OpenPayer</title>{og_head()}<style>{STYLE}</style></head><body><a class='skip' href='#rates'>Skip to rates</a>{header}<div class='wrap'>"
        f"<h1 class='hero'>{html.escape(headline)}</h1>{lede}{proof}{chain}{_corpus_meter(inv, rows, len(codes))}{_flags_section()}{_pilot_band()}"
        f"<p class='coverage'>Coverage right now: {html.escape(coverage)}. {inv['total_rows']} rate rows kept for {len(codes)} codes. Codes in scope: "
        + ", ".join(html.escape(c.code) for c in codes)
        + ".</p>"
        + tools + market + "".join(sections) + _sources_section() + _data_reviewed_section(inv) + volume + how
        + "<p class='note'>Source: payer machine readable files published under CMS price transparency rules. Counts sit beside every benchmark so a thin sample is never dressed up as a market.</p>"
        + '<div id="tip" role="status"></div>' + _EXPLORE_SCRIPT + "</div></body></html>"
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


_STRIP_SEQ = [0]


def _price_stacks(rows: list[dict]) -> list[dict]:
    """Group rate rows by exact price: one stack per distinct dollar value.

    Each stack carries its rate count, its provider-group count (distinct
    tax IDs), and up to 50 example groups for the detail panel. This is
    the unit the strip draws and the reader selects: a price shared by
    400 groups is one mark with the count printed, never 400 dots fused
    into a blob that reads as a spread of different prices.
    """
    by_val: dict[float, dict] = {}
    for i, r in enumerate(rows):
        v = round(float(r["negotiated_rate"]), 2)
        s = by_val.setdefault(v, {"v": v, "n": 0, "tins": set(), "keys": set(), "groups": []})
        s["n"] += 1
        tin = str(r.get("tin") or "")
        if tin:
            s["tins"].add(tin)
        key = _group_key(r, i)
        if key in s["keys"]:
            continue
        s["keys"].add(key)
        if len(s["groups"]) < 50:
            who = r.get("provider_name") or ("NPI " + str(r["npi"]) if r.get("npi") else "provider not named in file")
            s["groups"].append(
                {
                    "who": str(who),
                    "tin": tin,
                    "npi": str(r.get("npi") or ""),
                    "payer": str(r.get("payer") or ""),
                    "src": str(r.get("source_url") or ""),
                }
            )
    out: list[dict] = []
    for v in sorted(by_val):
        s = by_val[v]
        out.append({"v": v, "n": s["n"], "g": len(s["tins"]), "groups": s["groups"]})
    return out


def _group_key(r: dict, i: int) -> str:
    """Identity for listing one provider group on a rate row.

    A tax ID when the file carries one, else the NPI, else the row
    itself, so tax-ID-less rows stay individually listed in the panel.
    Group counts (the g on a stack) use the site's definition, distinct
    tax IDs, the same count the tables and flags use; a rate with no
    tax ID counts as a rate, never as a group.
    """
    tin = str(r.get("tin") or "")
    if tin:
        return f"tin:{tin}"
    npi = str(r.get("npi") or "")
    if npi:
        return f"npi:{npi}"
    return f"row:{i}"


def _strip_svg(
    code_groups: dict[str, list[dict]],
    xmax_by_code: dict[str, float],
    codes_meta: dict[str, str],
    payer: str | None = None,
) -> tuple[str, list[str], str]:
    """Draw the rate strip: one block per code, one row per rate type.

    The mark is a distinct price, never an individual rate. A row with at
    most 30 distinct prices draws one stacked column per price (at most 8
    dots, then the group count printed). A row with more draws $5 price
    bins with the group count on every bar. Each code keeps its own
    zero-based scale, shared by every payer and both rate types inside
    that code, and the block says what its scale is. Prices above the
    scale are dotted below the row at the axis edge and named in the
    notes; nothing is clipped silently. Returns (svg, notes, data script)
    where the data script carries each row's price stacks for the detail
    panel, so hover and keyboard step price by price, not dot by dot.
    """
    import json as _json

    _STRIP_SEQ[0] += 1
    sid = _STRIP_SEQ[0]
    width, label_w, right_w = 1120, 118, 272
    plot_w = width - label_w - right_w - 12
    x0 = label_w
    row_h = 48
    notes: list[str] = []
    data_rows: list[dict] = []

    # First pass: measure height.
    height = 10
    blocks: list[tuple[str, list[dict], float]] = []
    for code, groups in code_groups.items():
        xc = float(xmax_by_code.get(code, 100.0))
        blocks.append((code, groups, xc))
        height += 38 + row_h * max(1, len(groups)) + 10

    parts = [
        f'<svg class="strip" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Rate strip: one block per billing code, one row per rate type, one mark per distinct price with its provider group count, middle half and median marked, each code on its own dollar scale starting at zero">'
    ]
    y = 8
    row_idx = 0
    for code, groups, xc in blocks:
        def X(v: float, xc: float = xc) -> float:
            return x0 + (v / xc) * plot_w

        mrate = reference.medicare_rate(code)
        parts.append(f'<text x="0" y="{y + 13}" font-size="13" font-weight="700">{html.escape(code)}</text>')
        head = f"scale $0 to ${xc:,.0f}, same for every payer in this code"
        if mrate:
            head += f" · gold tick is Medicare ${mrate:,.2f}"
        parts.append(f'<text x="64" y="{y + 13}" font-size="9.5" fill="#6B7280">{html.escape(head)}</text>')
        y += 22
        step = 25 if xc <= 150 else (50 if xc <= 400 else 100)
        tick = 0
        while tick <= xc:
            parts.append(f'<text x="{X(tick):.0f}" y="{y + 10}" font-size="9" fill="#374151" text-anchor="middle">${tick:,.0f}</text>')
            tick += step
        y += 16
        if not groups:
            mid = y + 24
            parts.append(f'<g class="srow" data-code="{html.escape(code.lower())}" data-type="">')
            parts.append(f'<text x="0" y="{mid - 2}" font-size="12.5" font-weight="700">{html.escape(code)}</text>')
            parts.append(f'<text x="0" y="{mid + 12}" font-size="10" fill="#374151">{html.escape(codes_meta.get(code, ""))}</text>')
            parts.append(f'<text x="{x0 + 6}" y="{mid + 4}" font-size="11" fill="#374151">No dollar rates found in the files pulled so far</text>')
            parts.append(f'<text x="{x0 + plot_w + 12}" y="{mid + 4}" font-size="11" fill="#374151">n=0</text>')
            parts.append("</g>")
            y += row_h + 10
            continue
        for g in groups:
            rows = g["rows"]
            rtype = str(g["rtype"])
            vals = sorted(float(r["negotiated_rate"]) for r in rows)
            p25, med, p75 = _percentile(vals, 0.25), _percentile(vals, 0.5), _percentile(vals, 0.75)
            stacks = _price_stacks(rows)
            n_distinct = len(stacks)
            n_groups = len({str(r.get("tin") or "") for r in rows} - {""})
            modal = max(stacks, key=lambda s: s["g"]) if stacks else {"v": 0.0, "g": 0}
            mid = y + 24
            # Panel data: a full group list only where stepping through
            # it is usable (12 or fewer groups); larger stacks carry one
            # example group and the exact-price link to the code page.
            # Source URLs repeat across groups, so each row stores them
            # once and groups point at the list by index.
            budget = 200
            srcs: list[str] = []
            json_stacks = []
            for s in stacks:
                step_ok = s["g"] <= 12 and budget >= s["g"]
                if step_ok:
                    budget -= s["g"]
                    embed = s["groups"]
                else:
                    embed = s["groups"][:1]
                jgroups = []
                for gr in embed:
                    if gr["src"] not in srcs:
                        srcs.append(gr["src"])
                    jgroups.append(
                        {"who": gr["who"], "tin": gr["tin"], "npi": gr["npi"], "payer": gr["payer"], "s": srcs.index(gr["src"])}
                    )
                json_stacks.append({"v": s["v"], "n": s["n"], "g": s["g"], "step": step_ok, "groups": jgroups})
            data_rows.append(
                {"code": code, "type": rtype, "med": med, "p25": p25, "p75": p75, "n": len(vals), "srcs": srcs, "stacks": json_stacks}
            )
            parts.append(f'<g class="srow" data-code="{html.escape(code.lower())}" data-type="{html.escape(rtype)}">')
            tick = 0
            while tick <= xc:
                parts.append(f'<line x1="{X(tick):.0f}" y1="{mid - 20}" x2="{X(tick):.0f}" y2="{mid + 20}" stroke="#F3F4F6"/>')
                tick += step
            if len(vals) > 1:
                parts.append(f'<rect x="{X(p25):.1f}" y="{mid - 9}" width="{max(2.0, X(p75) - X(p25)):.1f}" height="18" fill="#E5E7EB"/>')
            if mrate and mrate <= xc:
                parts.append(f'<line x1="{X(mrate):.1f}" y1="{mid - 15}" x2="{X(mrate):.1f}" y2="{mid + 15}" stroke="#A16207" stroke-width="1.5"><title>Medicare national rate ${mrate:,.2f}</title></line>')
            inliers = [s for s in stacks if s["v"] <= xc]
            outliers = [s for s in stacks if s["v"] > xc]
            if n_distinct <= 30:
                for s in inliers:
                    cx = X(s["v"])
                    dots = min(max(s["g"], 1), 8)
                    for k in range(dots):
                        cy = mid + (k - (dots - 1) / 2) * 7
                        if rtype == "negotiated":
                            parts.append(f'<circle class="mark" cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="#111827"><title>${s["v"]:,.2f} · {s["g"]} groups</title></circle>')
                        else:
                            parts.append(f'<circle class="mark" cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="#FFFFFF" stroke="#111827" stroke-width="1.2"><title>${s["v"]:,.2f} · {s["g"]} groups</title></circle>')
                    if s["g"] > 8:
                        parts.append(f'<text class="mark" x="{cx:.1f}" y="{mid - 27}" font-size="9" text-anchor="middle">×{s["g"]:,}</text>')
            else:
                bins: dict[int, int] = {}
                for s in inliers:
                    b = int(s["v"] // 5)
                    bins[b] = bins.get(b, 0) + s["g"]
                cmax = max(bins.values()) if bins else 1
                for b, cnt in sorted(bins.items()):
                    if cnt <= 0:
                        continue
                    bx, bw = X(b * 5), max(1.5, X(5) - X(0))
                    bh = (cnt / cmax) * 30
                    parts.append(f'<rect class="mark" x="{bx:.1f}" y="{mid + 15 - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="#111827" fill-opacity="0.85"><title>${b * 5:.0f} to ${b * 5 + 5:.0f}: {cnt:,} groups</title></rect>')
                    parts.append(f'<text class="mark" x="{bx + bw / 2:.1f}" y="{mid + 15 - bh - 3:.1f}" font-size="8.5" text-anchor="middle">{cnt:,}</text>')
                notes.append(
                    f"{code} ({rtype}): bars count provider groups in $5 price bins. "
                    "Every distinct price, with its group count, is behind the row's hover, tap, and arrow keys, and on the code page."
                )
            for i, s in enumerate(outliers[:5]):
                cx = X(xc) - 4 - i * 10
                parts.append(f'<circle class="mark" cx="{cx:.1f}" cy="{mid + 19}" r="3" fill="#FFFFFF" stroke="#111827"><title>observed price ${s["v"]:,.2f} · {s["g"]} groups, above this code\'s scale</title></circle>')
            if outliers:
                notes.append(
                    f"{code} ({rtype}): {len(outliers)} distinct prices sit above the ${xc:,.0f} scale; "
                    f"highest ${outliers[-1]['v']:,.2f}. Every one is listed on the code page."
                )
            parts.append(f'<line x1="{X(med):.1f}" y1="{mid - 16}" x2="{X(med):.1f}" y2="{mid + 16}" stroke="#111827" stroke-width="3"/>')
            parts.append(
                f'<a href="/code/{html.escape(code)}"><rect x="0" y="{mid - 24}" width="{label_w}" height="48" style="fill:#fff;fill-opacity:0"/>'
                f'<text x="0" y="{mid - 2}" font-size="11.5" font-weight="700" fill="#0F766E">{html.escape(rtype)}</text>'
                f'<text x="0" y="{mid + 12}" font-size="9.5" fill="#374151">{html.escape(payer or "all payers")}</text></a>'
            )
            rx = x0 + plot_w + 12
            if len(vals) == 1:
                parts.append(f'<text x="{rx}" y="{mid + 4}" font-size="11">single rate ${med:,.0f} · n=1, no spread</text>')
            else:
                pct = _pct_text(code, med)
                l1 = f"median ${med:,.0f}" + (f" · {pct}" if pct else "")
                parts.append(f'<text x="{rx}" y="{mid - 10}" font-size="11">{html.escape(l1)}</text>')
                parts.append(f'<text x="{rx}" y="{mid + 4}" font-size="10" fill="#374151">middle half ${p25:,.0f} to ${p75:,.0f}</text>')
                parts.append(
                    f'<text x="{rx}" y="{mid + 18}" font-size="9.5" fill="#374151">n={len(vals):,} rates · {n_groups:,} groups · {n_distinct} distinct · most ${modal["v"]:,.0f} ×{modal["g"]:,}</text>'
                )
            parts.append(
                f'<circle class="halo" data-sid="{sid}" data-row="{row_idx}" r="10" style="display:none" fill="none" stroke="#0F766E" stroke-width="2"/>'
            )
            parts.append(
                f'<rect class="striphit" data-sid="{sid}" data-row="{row_idx}" data-x0="{x0}" data-pw="{plot_w}" data-xmax="{xc}" data-mid="{mid}" '
                f'x="{x0}" y="{mid - 24}" width="{plot_w}" height="48" tabindex="0" focusable="true" role="slider" '
                f'aria-label="{html.escape(code)} {html.escape(rtype)} prices" aria-valuemin="{stacks[0]["v"] if stacks else 0}" '
                f'aria-valuemax="{stacks[-1]["v"] if stacks else 0}" aria-valuenow="{med}" '
                f'aria-valuetext="median ${med:,.2f} of {n_distinct} distinct prices for {html.escape(code)} {html.escape(rtype)}" '
                'style="fill:#fff;fill-opacity:0;pointer-events:all"/>'
            )
            parts.append("</g>")
            row_idx += 1
            y += row_h
        y += 10
    parts.append("</svg>")
    data_script = (
        f'<script type="application/json" class="stripdata" data-sid="{sid}">'
        + _json.dumps({"rows": data_rows}).replace("</", "<\\/")
        + "</script>"
    )
    return "".join(parts), notes, data_script


def _payer_spread(summary_rows: list[dict], codes, xmax_by_code: dict[str, float]) -> str:
    """Hero visual: one row per payer per rate type inside each code block.

    Whisker is the middle half (p25 to p75), dot is the median. Every code
    keeps its own block, its own rows, and its own zero-based scale, so a
    $6 median is not crushed by another code's $300 rates; the block
    prints its scale. Identical distributions are NOT merged here,
    because the repetition is the comparison. Row click goes to the code
    page filtered to that payer, where every rate lives.
    """
    width, label_w, plot_w = 1120, 235, 505
    x0 = label_w

    by_code: dict[str, list[dict]] = {}
    for r in summary_rows:
        by_code.setdefault(str(r["billing_code"]), []).append(r)
    row_h = 26
    total_rows = sum(max(1, len(by_code.get(c.code, []))) for c in codes)
    height = 24 + total_rows * row_h + len(codes) * 42 + 12
    parts = [
        f'<svg class="strip" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Payer spread: for each billing code, one row per payer and rate type showing the median and middle half of observed dollar rates, each code on its own scale starting at zero">'
    ]
    y = 12
    for c in codes:
        xc = float(xmax_by_code.get(c.code, 100.0))

        def X(v: float, xc: float = xc) -> float:
            return x0 + (v / xc) * plot_w

        parts.append(f'<text x="0" y="{y + 12}" font-size="13" font-weight="700">{html.escape(c.code)}</text>')
        note = c.note.replace("Sample code: ", "").replace("Interprofessional ", "")
        parts.append(f'<text x="54" y="{y + 12}" font-size="9.5" fill="#6B7280">{html.escape(note)} · scale $0 to ${xc:,.0f}</text>')
        y += 20
        step = 25 if xc <= 150 else (50 if xc <= 400 else 100)
        tick = 0
        while tick <= xc:
            parts.append(f'<text x="{X(tick):.0f}" y="{y + 10}" font-size="9" fill="#374151" text-anchor="middle">${tick:,.0f}</text>')
            tick += step
        y += 14
        block_top = y
        tick = 0
        while tick <= xc:
            parts.append(f'<line x1="{X(tick):.0f}" y1="{block_top}" x2="{X(tick):.0f}" y2="{block_top + max(1, len(by_code.get(c.code, []))) * row_h}" stroke="#F3F4F6"/>')
            tick += step
        rows = sorted(
            by_code.get(c.code, []),
            key=lambda r: (str(r["negotiated_type"]) != "negotiated", str(r["payer"])),
        )
        if not rows:
            parts.append(f'<g class="prow" data-code="{html.escape(c.code.lower())}" data-type="" data-payer=""><text x="{x0 + 6}" y="{y + 12}" font-size="11" fill="#374151">No dollar rates found in the files pulled so far</text><text x="{x0 + plot_w + 12}" y="{y + 12}" font-size="11" fill="#374151">n=0</text></g>')
            y += row_h
            continue
        seen_spread: list[tuple[tuple, str]] = []
        for r in rows:
            med, p25, p75 = float(r["median"] or 0), float(r["p25"] or 0), float(r["p75"] or 0)
            mid = y + 11
            payer = str(r["payer"])
            rtype = str(r["negotiated_type"])
            parts.append(f'<g class="prow" data-code="{html.escape(c.code.lower())}" data-type="{html.escape(rtype)}" data-payer="{html.escape(payer)}">')
            parts.append(f'<text x="34" y="{mid + 3}" font-size="10" fill="#374151">{html.escape(payer)} · {html.escape(rtype)}</text>')
            parts.append(f'<rect x="{X(p25):.1f}" y="{mid - 5}" width="{max(2.0, X(p75) - X(p25)):.1f}" height="10" fill="#E5E7EB"/>')
            parts.append(f'<line x1="{X(p25):.1f}" y1="{mid}" x2="{X(p75):.1f}" y2="{mid}" stroke="#111827" stroke-width="2"/>')
            if rtype == "negotiated":
                parts.append(f'<circle cx="{X(med):.1f}" cy="{mid}" r="5" fill="#111827"><title>{html.escape(payer)} {html.escape(c.code)} {html.escape(rtype)}: median ${med:,.2f}, middle half ${p25:,.2f} to ${p75:,.2f}, n={r["n_rates"]}</title></circle>')
            else:
                parts.append(f'<circle cx="{X(med):.1f}" cy="{mid}" r="5" fill="#FFFFFF" stroke="#111827" stroke-width="1.3"><title>{html.escape(payer)} {html.escape(c.code)} {html.escape(rtype)}: median ${med:,.2f}, middle half ${p25:,.2f} to ${p75:,.2f}, n={r["n_rates"]}</title></circle>')
            stat = f"median ${med:,.0f} · middle half ${p25:,.0f} to ${p75:,.0f} · n={int(r['n_rates']):,}"
            key = (round(med, 2), round(p25, 2), round(p75, 2), int(r["n_rates"]))
            dup_of = next((p for k, p in seen_spread if k == key), None)
            if dup_of:
                stat += f" · same as {dup_of} above"
            else:
                stat += f" · {int(r['n_provider_groups']):,} groups"
            seen_spread.append((key, payer))
            parts.append(
                f'<a href="/code/{html.escape(c.code)}?payer={html.escape(payer)}"><text x="{x0 + plot_w + 12}" y="{mid + 3}" font-size="10.5">{html.escape(stat)}</text></a>'
            )
            parts.append("</g>")
            y += row_h
        y += 6
    parts.append("</svg>")
    return "".join(parts)


_FAMILY = ["99446", "99447", "99448", "99449", "99451", "99452"]


def _family_ladder(summary_rows: list[dict], xmax: float) -> str:
    """The interprofessional consult family as small multiples.

    Tufte ruling (2026-10-28, on the rendered chart): the connected
    ladder dies. Ten traced lines on one axis cannot be read back to
    a payer, and segments between codes imply a continuum that does
    not exist. Instead: one panel per code, one row per payer per
    rate type inside it. Dot is the median (filled negotiated, open
    fee schedule), horizontal bar is the middle half, gold hairline
    is Medicare's national rate for that code. Nothing connects
    across codes. A payer with no rate for the code gets the words
    "no rate filed" and an empty row. The dollar scale is shared,
    zero-based, and fitted to the family whiskers so no bar can run
    off its panel.
    """
    from . import reference as _ref

    width = 1120
    cols, panel_w, panel_h, panel_top = 2, 560, 214, 6
    label_w, plot_w = 168, 118
    payers = sorted({str(r["payer"]) for r in summary_rows})
    by_key: dict[tuple[str, str, str], dict] = {}
    for r in summary_rows:
        if str(r["billing_code"]) in _FAMILY:
            by_key[(str(r["billing_code"]), str(r["payer"]), str(r["negotiated_type"]))] = r
    peak = max(
        (float(r["p75"] or r["median"] or 0) for r in by_key.values()),
        default=0.0,
    )
    ymax = max(175.0, (int(peak / 25) + 1) * 25)
    height = panel_top + panel_h * ((len(_FAMILY) + cols - 1) // cols)
    notes = {c.code: c.note.replace("Interprofessional ", "").replace("Sample code: ", "") for c in load_codes()}

    def X(px: float, v: float) -> float:
        return px + label_w + 6 + (min(v, ymax) / ymax) * plot_w

    parts = [
        f'<svg class="strip" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Consult family panels: one panel per code, one row per payer and rate type, dot is the median, bar is the middle half, gold line is the Medicare rate">'
    ]
    ticks = list(range(0, int(ymax) + 1, 50))
    for pi, code in enumerate(_FAMILY):
        px = (pi % cols) * panel_w
        py = panel_top + (pi // cols) * panel_h
        med_rate = _ref.medicare_rate(code)
        parts.append(f'<text x="{px + 2}" y="{py + 14}" font-size="11" font-weight="700">{code} · {html.escape(notes.get(code, ""))}</text>')
        if med_rate:
            parts.append(f'<line x1="{X(px, med_rate):.1f}" y1="{py + 20}" x2="{X(px, med_rate):.1f}" y2="{py + panel_h - 6}" stroke="#A16207" stroke-width="1"/>')
            parts.append(f'<text x="{X(px, med_rate) + 3:.1f}" y="{py + 27}" font-size="8.5" fill="#A16207">Medicare ${med_rate:,.0f}</text>')
        for t in ticks:
            parts.append(f'<line x1="{X(px, t):.1f}" y1="{py + 20}" x2="{X(px, t):.1f}" y2="{py + panel_h - 6}" stroke="#F3F4F6"/>')
            if pi < cols:
                parts.append(f'<text x="{X(px, t):.1f}" y="{py + 10}" font-size="8.5" fill="#6B7280" text-anchor="middle">${t}</text>')
        parts.append(f'<text x="{px + label_w + 12 + plot_w}" y="{py + 27}" font-size="8.5" fill="#6B7280">median · middle half · n</text>')
        seen: list[tuple[tuple, str]] = []
        ry = py + 34
        for payer in payers:
            for rtype in ("negotiated", "fee schedule"):
                r = by_key.get((code, payer, rtype))
                parts.append(f'<g class="prow" data-code="{code}" data-type="{html.escape(rtype)}" data-payer="{html.escape(payer)}">')
                parts.append(f'<text x="{px + label_w}" y="{ry + 3}" font-size="9.5" text-anchor="end">{html.escape(payer)} · {html.escape(rtype)}</text>')
                if r is None:
                    parts.append(f'<text x="{px + label_w + 12}" y="{ry + 3}" font-size="9.5" fill="#6B7280">no rate filed</text>')
                else:
                    med, p25, p75 = float(r["median"] or 0), float(r["p25"] or 0), float(r["p75"] or 0)
                    parts.append(f'<line x1="{X(px, p25):.1f}" y1="{ry}" x2="{X(px, p75):.1f}" y2="{ry}" stroke="#111827" stroke-width="3"/>')
                    if rtype == "negotiated":
                        parts.append(f'<circle cx="{X(px, med):.1f}" cy="{ry}" r="4" fill="#111827"><title>{html.escape(payer)} {code} {html.escape(rtype)}: median ${med:,.2f}, middle half ${p25:,.2f} to ${p75:,.2f}, n={int(r["n_rates"]):,}</title></circle>')
                    else:
                        parts.append(f'<circle cx="{X(px, med):.1f}" cy="{ry}" r="4" fill="#FFFFFF" stroke="#111827" stroke-width="1.3"><title>{html.escape(payer)} {code} {html.escape(rtype)}: median ${med:,.2f}, middle half ${p25:,.2f} to ${p75:,.2f}, n={int(r["n_rates"]):,}</title></circle>')
                    stat = f"${med:,.0f} · ${p25:,.0f} to ${p75:,.0f} · n={int(r['n_rates']):,}"
                    key = (round(med, 2), round(p25, 2), round(p75, 2), int(r["n_rates"]))
                    for prev_key, prev_payer in seen:
                        if prev_key == key:
                            stat += f" · same as {prev_payer} above"
                            break
                    seen.append((key, payer))
                    parts.append(f'<text x="{px + label_w + 12 + plot_w}" y="{ry + 3}" font-size="9.5">{html.escape(stat)}</text>')
                parts.append("</g>")
                ry += 16
            ry += 4
    parts.append("</svg>")
    return "".join(parts)

def _code_whiskers(bench: list[dict], xmax_code: float) -> str:
    """Code page payer chart: one row per payer per rate type.

    Thick line is the middle half, dot is the median, thin line is min
    to max when n is 10 or more. A light connector joins a payer's two
    type medians and labels the gap; it is a difference of two typical
    rates, never a pooled figure.
    """
    width, label_w, plot_w = 1120, 235, 505
    x0 = label_w

    def X(v: float) -> float:
        return x0 + (v / xmax_code) * plot_w

    rows = sorted(bench, key=lambda r: (str(r["payer"]), str(r["negotiated_type"]) != "negotiated"))
    row_h = 30
    height = 42 + max(1, len(rows)) * row_h + 8
    parts = [
        f'<svg class="strip" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="By payer: median and middle half of observed rates for this code, one row per payer and rate type">'
    ]
    tick = 0
    while tick <= xmax_code:
        parts.append(f'<line x1="{X(tick):.0f}" y1="28" x2="{X(tick):.0f}" y2="{height - 8}" stroke="#E5E7EB"/>')
        parts.append(f'<text x="{X(tick):.0f}" y="17" font-size="10" fill="#374151" text-anchor="middle">${tick:,.0f}</text>')
        tick += 25
    by_payer: dict[str, dict[str, tuple[dict, float]]] = {}
    y = 40
    for r in rows:
        med, p25, p75 = float(r["median"] or 0), float(r["p25"] or 0), float(r["p75"] or 0)
        mid = y + 12
        by_payer.setdefault(str(r["payer"]), {})[str(r["negotiated_type"])] = (r, mid)
        parts.append(f'<text x="0" y="{mid + 3}" font-size="11">{html.escape(str(r["payer"]))} · {html.escape(str(r["negotiated_type"]))}</text>')
        if int(r["n_rates"]) >= 10:
            parts.append(f'<line x1="{X(float(r["min_rate"] or 0)):.1f}" y1="{mid}" x2="{X(float(r["max_rate"] or 0)):.1f}" y2="{mid}" stroke="#9CA3AF" stroke-width="1"/>')
        parts.append(f'<line x1="{X(p25):.1f}" y1="{mid}" x2="{X(p75):.1f}" y2="{mid}" stroke="#111827" stroke-width="3.5"/>')
        if str(r["negotiated_type"]) == "negotiated":
            parts.append(f'<circle cx="{X(med):.1f}" cy="{mid}" r="5" fill="#111827"><title>median ${med:,.2f}, middle half ${p25:,.2f} to ${p75:,.2f}, n={r["n_rates"]}</title></circle>')
        else:
            parts.append(f'<circle cx="{X(med):.1f}" cy="{mid}" r="5" fill="#FFFFFF" stroke="#111827" stroke-width="1.3"><title>median ${med:,.2f}, middle half ${p25:,.2f} to ${p75:,.2f}, n={r["n_rates"]}</title></circle>')
        pct = _pct_text(str(r.get("billing_code") or ""), med)
        parts.append(f'<text x="{x0 + plot_w + 12}" y="{mid + 3}" font-size="10.5">median ${med:,.0f} · middle half ${p25:,.0f} to ${p75:,.0f} · n={int(r["n_rates"]):,}{(" · " + pct) if pct else ""}</text>')
        y += row_h
    for payer, types in by_payer.items():
        if "negotiated" in types and "fee schedule" in types:
            (rn, mn), (rf, mf) = types["negotiated"], types["fee schedule"]
            gap = abs(float(rn["median"] or 0) - float(rf["median"] or 0))
            gx = max(X(float(rn["median"] or 0)), X(float(rf["median"] or 0))) + 8
            parts.append(f'<line x1="{X(float(rn["median"] or 0)):.1f}" y1="{mn}" x2="{X(float(rf["median"] or 0)):.1f}" y2="{mf}" stroke="#9CA3AF" stroke-width="1"/>')
            parts.append(f'<text x="{gx:.1f}" y="{(mn + mf) / 2 + 3:.1f}" font-size="9.5" fill="#6B7280">typical gap ${gap:,.0f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _distribution_facets(rows_by_type: dict[str, list[dict]], xmax_code: float) -> str:
    """Observed distribution per rate type for one code.

    Dots while they can still be counted (n up to 120), a $10-bin
    histogram above that, with counts printed and outlying observed
    rates dotted below the axis with their values. Facets are separate
    panels; types are never combined.
    """
    out: list[str] = []
    for rtype in ("negotiated", "fee schedule"):
        rows = sorted(rows_by_type.get(rtype, []), key=lambda z: float(z["negotiated_rate"] or 0))
        if not rows:
            continue
        vals = [float(r["negotiated_rate"] or 0) for r in rows]
        med = _percentile(vals, 0.5)
        out.append(f"<h3>{html.escape(rtype)}: {len(vals)} observed rates, median ${med:,.0f}</h3>")
        width, label_w, plot_w = 980, 30, 700
        x0 = label_w

        def X(v: float) -> float:
            return x0 + (v / xmax_code) * plot_w

        if len(vals) <= 120:
            lanes = 6
            height = 120
            parts = [f'<svg class="strip" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Every observed {html.escape(rtype)} rate for this code as a dot">']
            for j, r in enumerate(rows):
                v = float(r["negotiated_rate"] or 0)
                y = 30 + (j % lanes) * 12
                who = r.get("provider_name") or ("NPI " + str(r["npi"]) if r.get("npi") else "provider not named in file")
                attrs = (
                    f'class="dot" data-code="" data-rate="${v:,.2f}" data-payer="{html.escape(str(r["payer"]))}" '
                    f'data-type="{html.escape(rtype)}" data-who="{html.escape(str(who))}" data-tin="{html.escape(str(r["tin"]))}" '
                    f'data-npi="{html.escape(str(r["npi"]))}" data-src="{html.escape(str(r["source_url"]))}" data-median="${med:,.2f}" data-band=""'
                )
                if rtype == "negotiated":
                    parts.append(f'<circle {attrs} cx="{X(v):.1f}" cy="{y}" r="4" fill="#111827" fill-opacity="0.88"><title>${v:,.2f}</title></circle>')
                else:
                    parts.append(f'<circle {attrs} cx="{X(v):.1f}" cy="{y}" r="4" fill="#FFFFFF" stroke="#111827" stroke-width="1.3"><title>${v:,.2f}</title></circle>')
            parts.append(f'<line x1="{X(med):.1f}" y1="18" x2="{X(med):.1f}" y2="104" stroke="#111827" stroke-width="2.5"/>')
            tick = 0
            while tick <= xmax_code:
                parts.append(f'<text x="{X(tick):.0f}" y="114" font-size="9.5" fill="#374151" text-anchor="middle">${tick:,.0f}</text>')
                tick += 25
            parts.append("</svg>")
            out.append("".join(parts))
        else:
            bin_w = 10.0
            nbins = max(1, int(xmax_code // bin_w))
            counts = [0] * (nbins + 1)
            for v in vals:
                counts[min(nbins, int(v // bin_w))] += 1
            cmax = max(counts) or 1
            height = 190
            base = 140
            parts = [f'<svg class="strip" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Histogram of observed {html.escape(rtype)} rates in ten dollar bins, counts printed">']
            for i, c in enumerate(counts):
                if not c:
                    continue
                bx, bw = X(i * bin_w), max(1.5, X(bin_w) - X(0))
                bh = (c / cmax) * 105
                parts.append(f'<rect x="{bx:.1f}" y="{base - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="#111827" fill-opacity="0.85"><title>${i * 10:.0f} to ${i * 10 + 10:.0f}: {c} rates</title></rect>')
                if c >= 3:
                    parts.append(f'<text x="{bx + bw / 2:.1f}" y="{base - bh - 4:.1f}" font-size="9" text-anchor="middle">{c}</text>')
            lo, hi = _percentile(vals, 0.01), _percentile(vals, 0.99)
            for r in rows:
                v = float(r["negotiated_rate"] or 0)
                if v < lo or v > hi:
                    parts.append(f'<circle cx="{X(v):.1f}" cy="{base + 14}" r="3.5" fill="#FFFFFF" stroke="#111827"><title>observed outlier ${v:,.2f}</title></circle>')
                    parts.append(f'<text x="{X(v):.1f}" y="{base + 30}" font-size="8.5" text-anchor="middle">${v:,.0f}</text>')
            parts.append(f'<line x1="{X(med):.1f}" y1="20" x2="{X(med):.1f}" y2="{base}" stroke="#111827" stroke-width="2.5"/>')
            tick = 0
            while tick <= xmax_code:
                parts.append(f'<text x="{X(tick):.0f}" y="{base + 46}" font-size="9.5" fill="#374151" text-anchor="middle">${tick:,.0f}</text>')
                tick += 25
            parts.append("</svg>")
            out.append("".join(parts))
            out.append(f"<p class='note'>Bars count observed rates in $10 bins. Dots below the axis are the observed rates outside the middle 98 percent, each labeled. No smoothing, nothing between observed rates.</p>")
    return "".join(out)


_STRIP_CAPTION = (
    "One block per billing code, one row per rate type. Each mark is one distinct price, not one rate: "
    "where many provider groups pay the same price, the dots stack and the count is printed, so one common "
    "price cannot masquerade as a spread of different prices. Rows with more than 30 distinct prices switch "
    "to $5 price bins with the provider group count on every bar. Hover, tap, or focus a row to read each "
    "price and how many groups sit on it; the left and right arrow keys step price by price, Enter pins the "
    "panel, Escape closes it. Group counts are distinct tax IDs, the same count the tables and flags use; "
    "a rate whose file row carries no tax ID counts as a rate, never as a group, and the panel says so. "
    "The grey band is the middle half of rates (p25 to p75) and the thick tick is "
    "the median. Each code has its own dollar scale starting at zero, the same for every payer inside that "
    "code, and the block prints its scale; prices above the scale are dotted below the row and named in the "
    "notes under the chart. Rate types are never pooled: a negotiated median and a fee schedule median are "
    "different facts. Filled dots are negotiated rates; hollow dots are fee schedule rates. Percentage "
    "rates are not dollars and are left out. Percentiles use linear interpolation between closest ranks; "
    "the prices themselves are observed values, never interpolated. Source: payer Transparency in "
    "Coverage files as filed. Every individual rate, with its provider and source file, sits on the code "
    "page behind the row label."
)


_EXPLORE_SCRIPT = """<script>
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
  function unpin(){pinned=false;pinKey=null;tip.classList.remove('pinned');tip.style.display='none';}
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
  var strips={};
  document.querySelectorAll('script.stripdata').forEach(function(s){
    try{ strips[s.getAttribute('data-sid')]=JSON.parse(s.textContent); }catch(e){}
  });
  var sel={}, grp={}, pinKey=null;
  function skey(sid,row){return sid+':'+row;}
  function hitEl(sid,row){return document.querySelector('.striphit[data-sid="'+sid+'"][data-row="'+row+'"]');}
  function haloEl(sid,row){return document.querySelector('.halo[data-sid="'+sid+'"][data-row="'+row+'"]');}
  function esc(t){return String(t==null?'':t).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function money(v){return '$'+Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}
  function stackIdx(rd,val){var bi=0,bd=Infinity;rd.stacks.forEach(function(s,i){var d=Math.abs(s.v-val);if(d<bd){bd=d;bi=i;}});return bi;}
  function renderTip(sid,row,pinned){
    var rd=strips[sid].rows[row], idx=sel[skey(sid,row)]||0, s=rd.stacks[idx];
    if(!s)return;
    var gidx=Math.min(grp[skey(sid,row)]||0, Math.max(0,s.groups.length-1));
    grp[skey(sid,row)]=gidx;
    var gr=s.groups[gidx]||{};
    var payers=[]; s.groups.forEach(function(g){if(g.payer&&payers.indexOf(g.payer)<0)payers.push(g.payer);});
    var payerLine=payers.length===1?payers[0]:'all payers in this row';
    var head=s.g>0
      ? '<strong>'+money(s.v)+'</strong> · '+s.g.toLocaleString()+' provider group'+(s.g===1?'':'s')+' at this exact price'
      : '<strong>'+money(s.v)+'</strong> · '+s.n.toLocaleString()+' rates at this price, no tax ID recorded for any of them';
    var gline;
    if(s.step){ gline='Group '+(gidx+1)+' of '+s.g.toLocaleString()+': '+esc(gr.who||'provider not named in file')+(gr.tin?'<br>TIN '+esc(gr.tin):'')+(gr.npi?'<br>NPI '+esc(gr.npi):''); }
    else { gline='One of '+s.g.toLocaleString()+' groups: '+esc(gr.who||'provider not named in file')+(gr.tin?'<br>TIN '+esc(gr.tin):'')+(gr.npi?'<br>NPI '+esc(gr.npi):''); }
    var out=head+'<br>'+esc(rd.code)+' · '+esc(rd.type)+' · '+esc(payerLine)+'<br>'+gline
      +'<br>This row: median '+money(rd.med)+' · middle half '+money(rd.p25)+' to '+money(rd.p75)+' · '+rd.n.toLocaleString()+' rates';
    if(s.step && s.g>1){ out+='<br><button type="button" data-act="prev">Prev group</button><button type="button" data-act="next">Next group</button>'; }
    if(pinned){
      var q='/code/'+encodeURIComponent(rd.code)+'?rate='+encodeURIComponent(s.v.toFixed(2))+(gr.payer?('&payer='+encodeURIComponent(gr.payer)):'');
      var src=(rd.srcs&&gr.s!==undefined)?rd.srcs[gr.s]:'';
      if(src){ out+='<br><a href="'+esc(src)+'">source payer file</a> · '; } else { out+='<br>'; }
      out+='<a href="'+q+'">See all '+s.g.toLocaleString()+' groups at '+money(s.v)+'</a>';
      out+='<br><span class="src">Left and right arrows step prices. Up and down step groups. Escape closes.</span>';
    }
    tip.innerHTML=out;
    tip.style.display='block';
  }
  function selectStack(sid,row,idx,pinned){
    var rd=strips[sid].rows[row]; if(!rd||!rd.stacks.length)return;
    idx=Math.max(0,Math.min(idx,rd.stacks.length-1));
    sel[skey(sid,row)]=idx; grp[skey(sid,row)]=0;
    var s=rd.stacks[idx], hit=hitEl(sid,row), halo=haloEl(sid,row);
    var x=parseFloat(hit.getAttribute('data-x0'))+(s.v/parseFloat(hit.getAttribute('data-xmax')))*parseFloat(hit.getAttribute('data-pw'));
    halo.setAttribute('cx',x.toFixed(1)); halo.setAttribute('cy',hit.getAttribute('data-mid')); halo.style.display='block';
    hit.setAttribute('aria-valuenow',s.v);
    hit.setAttribute('aria-valuetext',money(s.v)+', '+(s.g>0?(s.g+' provider group'+(s.g===1?'':'s')+' at this price'):(s.n+' rates at this price, no tax ID recorded'))+', price '+(idx+1)+' of '+rd.stacks.length+' for '+rd.code+' '+rd.type);
    renderTip(sid,row,pinned);
  }
  function pinTip(){
    tip.style.left='auto';tip.style.right='14px';tip.style.top='auto';tip.style.bottom='14px';
  }
  document.querySelectorAll('.striphit').forEach(function(hit){
    var sid=hit.getAttribute('data-sid'), row=hit.getAttribute('data-row'), key=skey(sid,row);
    function valAt(e){ var r=hit.getBoundingClientRect(); var f=(e.clientX-r.left)/Math.max(1,r.width); return Math.max(0,f)*parseFloat(hit.getAttribute('data-xmax')); }
    hit.addEventListener('pointermove',function(e){
      if(pinKey&&pinKey!==key)return;
      var rd=strips[sid].rows[row]; selectStack(sid,row,stackIdx(rd,valAt(e)),pinKey===key);
      if(pinKey!==key) move(e);
    });
    hit.addEventListener('pointerdown',function(e){
      var rd=strips[sid].rows[row]; var idx=stackIdx(rd,valAt(e));
      if(pinKey===key&&(sel[key]||0)===idx){ unpin(); return; }
      pinKey=key; pinned=true; tip.classList.add('pinned');
      selectStack(sid,row,idx,true); pinTip();
    });
    hit.addEventListener('mouseleave',function(){ if(pinKey!==key){tip.style.display='none'; var h=haloEl(sid,row); if(h)h.style.display='none';} });
    hit.addEventListener('focus',function(){
      if(pinKey&&pinKey!==key)return;
      var rd=strips[sid].rows[row]; var idx=sel[key]; if(idx===undefined){ idx=stackIdx(rd,rd.med); }
      selectStack(sid,row,idx,pinKey===key);
      var r=hit.getBoundingClientRect(); tip.style.left=Math.min(r.left+14,innerWidth-360)+'px'; tip.style.top=(r.bottom+10)+'px'; tip.style.right='auto'; tip.style.bottom='auto';
    });
    hit.addEventListener('blur',function(){ if(pinKey!==key) tip.style.display='none'; });
    hit.addEventListener('keydown',function(e){
      var rd=strips[sid].rows[row]; var idx=sel[key]||0; var s=rd.stacks[idx]; var isPin=pinKey===key;
      if(e.key==='ArrowRight'){e.preventDefault();selectStack(sid,row,idx+1,isPin);}
      else if(e.key==='ArrowLeft'){e.preventDefault();selectStack(sid,row,idx-1,isPin);}
      else if(e.key==='PageDown'){e.preventDefault();selectStack(sid,row,idx+10,isPin);}
      else if(e.key==='PageUp'){e.preventDefault();selectStack(sid,row,idx-10,isPin);}
      else if(e.key==='Home'){e.preventDefault();selectStack(sid,row,0,isPin);}
      else if(e.key==='End'){e.preventDefault();selectStack(sid,row,rd.stacks.length-1,isPin);}
      else if(e.key==='ArrowDown'){e.preventDefault(); if(s&&s.step){grp[key]=Math.min((grp[key]||0)+1,s.groups.length-1); renderTip(sid,row,isPin);} }
      else if(e.key==='ArrowUp'){e.preventDefault(); if(s&&s.step){grp[key]=Math.max((grp[key]||0)-1,0); renderTip(sid,row,isPin);} }
      else if(e.key==='Enter'||e.key===' '){e.preventDefault(); if(isPin){unpin();} else {pinKey=key;pinned=true;tip.classList.add('pinned');renderTip(sid,row,true);pinTip();} }
    });
  });
  tip.addEventListener('click',function(e){
    var b=e.target.closest?e.target.closest('button[data-act]'):null; if(!b||!pinKey)return;
    var parts=pinKey.split(':'), sid=parts[0], row=parts[1];
    var rd=strips[sid].rows[row], s=rd.stacks[sel[pinKey]||0]; if(!s||!s.step)return;
    var g=grp[pinKey]||0;
    grp[pinKey]=b.getAttribute('data-act')==='next'?Math.min(g+1,s.groups.length-1):Math.max(g-1,0);
    renderTip(sid,row,true);
  });
  var f=document.getElementById('codefilter');
  if(f){f.addEventListener('input',function(){
    var q=f.value.trim().toLowerCase();
    document.querySelectorAll('table.filterable tbody tr').forEach(function(tr){
      tr.style.display=(!q||(tr.dataset.code||'').indexOf(q)>-1)?'':'none';
    });
    document.querySelectorAll('.srow,.prow').forEach(function(g){
      g.style.display=(!q||(g.dataset.code||'').indexOf(q)>-1)?'':'none';
    });
  });}
  var curType='', curPayer='';
  function applyExplore(){
    document.querySelectorAll('.prow,.lrow,.srow').forEach(function(g){
      var t=g.dataset.type||'', p=g.dataset.payer;
      var hideT=curType && t && t!==curType;
      var fadeP=curPayer && p!==undefined && p!=='' && p!==curPayer;
      g.style.display=hideT?'none':'';
      if(!hideT) g.style.opacity=fadeP?'0.15':'';
    });
    var n=0; document.querySelectorAll('.prow').forEach(function(g){if(g.style.display!=='none'&&g.style.opacity!=='0.15')n++;});
    var rl=document.getElementById('resultline');
    if(rl) rl.textContent='Showing '+n+' payer rows in the spread · rate type: '+(curType||'both apart')+' · payer: '+(curPayer||'all')+'. Scale and counts unchanged; nothing was pooled or rescaled.';
  }
  document.querySelectorAll('[data-type-btn]').forEach(function(b){
    b.addEventListener('click',function(){
      document.querySelectorAll('[data-type-btn]').forEach(function(x){x.classList.remove('on');});
      b.classList.add('on'); curType=b.dataset.typeBtn; applyExplore();
    });
  });
  document.querySelectorAll('[data-payer-chip]').forEach(function(b){
    b.addEventListener('click',function(){
      document.querySelectorAll('[data-payer-chip]').forEach(function(x){x.classList.remove('on');});
      b.classList.add('on'); curPayer=b.dataset.payerChip; applyExplore();
    });
  });
})();
</script>"""


def _strip_block(
    codes,
    rows_by_code: dict[str, list[dict]],
    xmax_by_code: dict[str, float],
    script: bool = True,
    payer: str | None = None,
) -> str:
    """Full strip markup (caption + svg + notes + stack data + script)."""
    code_groups: dict[str, list[dict]] = {}
    for c in codes:
        by_type: dict[str, list[dict]] = {}
        for r in rows_by_code.get(c.code, []):
            by_type.setdefault(str(r["negotiated_type"]), []).append(r)
        code_groups[c.code] = [
            {"rtype": t, "rows": rs}
            for t, rs in sorted(by_type.items(), key=lambda kv: (kv[0] != "negotiated", kv[0]))
        ]
    svg, notes, data_script = _strip_svg(code_groups, xmax_by_code, {c.code: c.code_system for c in codes}, payer=payer)
    note_html = "".join(f"<p class='note'>{html.escape(n)}</p>" for n in notes)
    return (
        f"<p>{_STRIP_CAPTION}</p>"
        + svg
        + data_script
        + note_html
        + ('<div id="tip" role="status"></div>' if script else "")
        + (_EXPLORE_SCRIPT if script else "")
    )


@app.get("/flag", response_class=HTMLResponse)
def flag_page(payer: str, code: str, kind: str) -> str:
    from . import flags as _flags

    if not _has_data():
        return f"<html><body style='font-family:system-ui'><h1>Flag</h1><p>No data pulled yet.</p></body></html>"
    match = next(
        (f for f in _flags.compute_flags(flags_input())
         if f["payer"] == payer and f["billing_code"] == code and f["kind"] == kind),
        None,
    )
    if match is None:
        return (
            f"<html><head><title>Flag not found | OpenPayer</title>{og_head()}<style>{STYLE}</style></head><body><div class='wrap'>"
            "<p><a href='/'>All codes and flags</a></p><h1>No such flag in the current corpus</h1>"
            "<p>Flags are computed live from the stored rates. This one is not over its threshold today, "
            "or the payer, code, and signal do not match a computed flag.</p></div></body></html>"
        )
    return _flag_dossier(match)


_PILOT_CACHE: dict = {}


def _pilot_data():
    if not _PILOT_CACHE:
        from . import pilot

        sample = pilot.load_sample()
        flags = pilot.compute_flags(sample)
        _PILOT_CACHE.update(sample=sample, flags=flags, summary=pilot.state_summary(sample, flags))
    return _PILOT_CACHE


def _pilot_band() -> str:
    s = _pilot_data()["summary"]
    return (
        "<h2>The pilot, run on one state's records</h2>"
        "<p>The corpus above works before a claim exists. The pilot prototype answers the next question: "
        "hand us one state's claims and records, and the same discipline runs forward. "
        f"On a synthetic {html.escape(s['state'])} sample ({s['enrollees']} enrollees, {s['claims']} claims), "
        f"deterministic checks raise {s['flags']} flags and ${s['flagged_dollars']:,.0f} in flagged claims, "
        "each traced to its billing entity and ownership web. "
        "<a href='/pilot'>Open the pilot prototype</a> · <a href='/pilot/onepager'>the state one-pager</a></p>"
    )


def _pilot_page(body: str, title: str) -> str:
    return (
        f"<html><head><title>{html.escape(title)} | OpenPayer</title>{og_head()}<style>{STYLE}</style></head>"
        f"<body><div class='wrap'>{body}</div></body></html>"
    )


_PILOT_BANNER = "<div class='banner'><strong>Synthetic demonstration data.</strong> Every person, provider, entity, and dollar here is invented for the demo. No real patient, provider, or claim appears anywhere.</div>"


@app.get("/pilot", response_class=HTMLResponse)
def pilot_home() -> str:
    from . import pilot

    d = _pilot_data()
    sample, flags, s = d["sample"], d["flags"], d["summary"]
    kpis = "".join(
        f"<div class='cell'><span class='lab'>{lab}</span><div class='med'>{val}</div></div>"
        for val, lab in [
            (f"{s['enrollees']}", "enrollees in sample"), (f"{s['claims']}", "claims checked"),
            (f"${s['claims_dollars']:,.0f}", "claim dollars"), (f"{s['flags']}", "flags raised"),
            (f"${s['flagged_dollars']:,.0f}", "flagged dollars"), (f"{s['gate_flagged']}", "below the gate (under 8 of 10)"),
        ]
    )
    ruler = " · ".join(
        f"{html.escape(c)} ${reference.medicare_rate(c):,.2f}"
        for c in sample["codes"] if reference.medicare_rate(c)
    )
    rows = "".join(
        "<tr><td>{sev}</td><td><a href='/pilot/flag/{fid}'>{label}</a></td>"
        "<td><a href='/pilot/enrollee/{pid}'>{pid}</a></td><td>{prov}<br><small>NPI {npi}</small></td>"
        "<td><a href='/pilot/entity/{eid}'>{eid}</a></td><td class='n'>${dollars:,.0f}</td></tr>".format(
            sev=html.escape(f["severity"]), fid=f["id"], label=html.escape(f["label"]), pid=f["enrollee"],
            prov=html.escape(f["provider_name"]), npi=f["npi"], eid=f["entity"], dollars=f["dollars"],
        )
        for f in flags
    )
    flagged_people = []
    for e in sample["enrollees"]:
        g = pilot.gate_score(e, sample["claims"])
        if g["flagged"]:
            nflags = sum(1 for f in flags if f["enrollee"] == e["id"])
            flagged_people.append(
                f"<div class='gatecard'><span class='score'>{g['score']} of 10</span> · "
                f"<a href='/pilot/enrollee/{e['id']}'><b>{e['id']}</b></a> · identity {g['identity_evidence']} · "
                f"condition {g['condition_evidence']} · continuity {g['continuity']} · housing: {html.escape(g['housing_context'])} "
                f"(context only) · {nflags} flags</div>"
            )
    body = (
        "<p><a href='/'>All codes and flags</a></p>"
        "<h1>One state's records, checked before payment</h1>"
        + _PILOT_BANNER
        + "<p class='lede'>Claims show what was billed. The record shows what happened. "
          "Deterministic checks only: no models, same input, same answer every time. "
          "Click any flag to trace it to the billing entity and its ownership web.</p>"
        f"<div class='answerband'>{kpis}</div>"
        "<h2>The pricing ruler</h2>"
        f"<p class='note'>Medicare national rates, CMS 2026 Physician Fee Schedule (RVU26A), the same ruler the corpus flags use: {ruler}.</p>"
        "<h2>Flags for review</h2>"
        "<div class='table-wrap'><table><thead><tr><th>Severity</th><th>Signal</th><th>Enrollee</th><th>Provider</th><th>Entity</th><th>Flagged $</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        "<h2>Validation gate</h2>"
        "<p class='note'>Every enrollee scores out of 10 on evidence a person exists, evidence the condition supports "
        "what is billed, and continuity of care. Below 8 routes to review before payment. Housing status is context "
        "for outreach and is never scored: being displaced or sheltered is a circumstance, not a suspicion.</p>"
        + "".join(flagged_people)
        + "<p><a href='/pilot/onepager'>Open the printable state one-pager</a></p>"
    )
    return _pilot_page(body, "Pilot prototype: one state's records")


@app.get("/pilot/flag/{fid}", response_class=HTMLResponse)
def pilot_flag(fid: str) -> str:
    from . import pilot

    d = _pilot_data()
    sample, flags = d["sample"], d["flags"]
    f = next((x for x in flags if x["id"] == fid), None)
    if f is None:
        return _pilot_page("<p><a href='/pilot'>Pilot home</a></p><h1>No such flag</h1>", "Flag not found")
    trace = pilot.entity_trace(sample, flags, f["entity"])
    enr = next(e for e in sample["enrollees"] if e["id"] == f["enrollee"])
    g = pilot.gate_score(enr, sample["claims"])
    sibs = "".join(
        f"<div class='col'><h3>Sibling entity</h3><b>{html.escape(s['name'])}</b><br>{html.escape(s['kind'])} · {html.escape(s['city'])}<br>"
        + "".join(f"<span class='tie'>{html.escape(t)}</span>" for t in s["ties"]) + "</div>"
        for s in trace["siblings"]
    )
    provs = "<br>".join(f"{html.escape(p['name'])} ({html.escape(p['specialty'])})" for p in trace["providers"])
    multi = ""
    if trace["multi_entity_providers"]:
        p0 = trace["multi_entity_providers"][0]
        multi = f"<br><span class='tie'>{html.escape(p0['name'])} bills under {len(p0['entities'])} entities</span>"
    body = (
        "<p><a href='/pilot'>Pilot home</a></p>"
        f"<h1>{html.escape(f['id'])}: {html.escape(f['label'])}</h1>"
        + _PILOT_BANNER
        + f"<p class='lede-sm'>{html.escape(f['severity'])} · enrollee <a href='/pilot/enrollee/{f['enrollee']}'>{f['enrollee']}</a> · ${f['dollars']:,.0f} flagged</p>"
        + "<ul>" + "".join(f"<li>{html.escape(e)}</li>" for e in f["evidence"]) + "</ul>"
        f"<p><b>Enrollee gate:</b> <span class='score'>{g['score']} of 10</span> (identity {g['identity_evidence']}, "
        f"condition {g['condition_evidence']}, continuity {g['continuity']}). Housing context: {html.escape(g['housing_context'])}, never scored.</p>"
        "<div class='trace'>"
        f"<div class='col'><h3>Provider</h3><b>{html.escape(f['provider_name'])}</b><br>{html.escape(f['specialty'])}<br>NPI {f['npi']}{multi}</div>"
        f"<div class='col'><h3>Billing entity</h3><b>{html.escape(trace['entity']['name'])}</b><br>{html.escape(trace['entity']['kind'])} · "
        f"{html.escape(trace['entity']['city'])}<br>TIN {html.escape(trace['entity']['tin'])}<br>{provs}</div>"
        f"<div class='col'><h3>Parent</h3><b>{html.escape(trace['parent'] or 'none recorded')}</b><br>Owner: {html.escape(trace['entity']['owner'])}<br>"
        f"Registered agent: {html.escape(trace['entity']['agent'])}<br>{html.escape(trace['entity']['address'])}</div>"
        + sibs + "</div>"
        f"<p><b>Across this ownership web: {len(trace['flags_in_web'])} flags, ${trace['web_flagged_dollars']:,.0f} flagged.</b> "
        "Flags are review signals, not findings. A clinician and CMS make every call.</p>"
    )
    return _pilot_page(body, f"Flag {f['id']}: {f['label']}")


@app.get("/pilot/entity/{eid}", response_class=HTMLResponse)
def pilot_entity(eid: str) -> str:
    from . import pilot

    d = _pilot_data()
    sample, flags = d["sample"], d["flags"]
    entities = {e["id"]: e for e in sample["entities"]}
    if eid not in entities:
        return _pilot_page("<p><a href='/pilot'>Pilot home</a></p><h1>No such entity</h1>", "Entity not found")
    trace = pilot.entity_trace(sample, flags, eid)
    ent = trace["entity"]
    claims_here = [c for c in sample["claims"] if c["entity"] == eid]
    sib_rows = "".join(
        f"<tr><td><a href='/pilot/entity/{s['id']}'>{html.escape(s['name'])}</a></td><td>{html.escape(s['kind'])}</td>"
        f"<td>{html.escape(', '.join(s['ties']))}</td></tr>" for s in trace["siblings"]
    )
    flag_rows = "".join(
        f"<tr><td>{html.escape(f['severity'])}</td><td><a href='/pilot/flag/{f['id']}'>{html.escape(f['label'])}</a></td>"
        f"<td>{f['enrollee']}</td><td class='n'>${f['dollars']:,.0f}</td></tr>" for f in trace["flags_in_web"]
    )
    body = (
        "<p><a href='/pilot'>Pilot home</a></p>"
        f"<h1>{html.escape(ent['name'])}</h1>"
        + _PILOT_BANNER
        + f"<p class='lede-sm'>{html.escape(ent['kind'])} · {html.escape(ent['city'])} · TIN {html.escape(ent['tin'])}<br>"
        f"Parent: {html.escape(trace['parent'] or 'none recorded')} · Owner: {html.escape(ent['owner'])} · "
        f"Registered agent: {html.escape(ent['agent'])}<br>{html.escape(ent['address'])}</p>"
        f"<p>{len(claims_here)} claims in the sample, ${sum(c['paid'] for c in claims_here):,.0f}. "
        f"Flags on this entity: {len(trace['flags_here'])}. Flags across its ownership web: {len(trace['flags_in_web'])} "
        f"(${trace['web_flagged_dollars']:,.0f}).</p>"
        "<h2>Ownership web</h2>"
        f"<div class='table-wrap'><table><tr><th>Sibling entity</th><th>Kind</th><th>Ties</th></tr>{sib_rows}</table></div>"
        "<h2>Flags touching this web</h2>"
        f"<div class='table-wrap'><table><tr><th>Severity</th><th>Signal</th><th>Enrollee</th><th>Flagged $</th></tr>{flag_rows}</table></div>"
    )
    return _pilot_page(body, ent["name"])


@app.get("/pilot/enrollee/{pid}", response_class=HTMLResponse)
def pilot_enrollee(pid: str) -> str:
    from . import pilot

    d = _pilot_data()
    sample, flags = d["sample"], d["flags"]
    enr = next((e for e in sample["enrollees"] if e["id"] == pid), None)
    if enr is None:
        return _pilot_page("<p><a href='/pilot'>Pilot home</a></p><h1>No such enrollee</h1>", "Enrollee not found")
    g = pilot.gate_score(enr, sample["claims"])
    mine = [c for c in sample["claims"] if c["enrollee"] == pid]
    claim_rows = "".join(
        f"<tr><td>{c['date']}</td><td>{c['code']}</td><td>{html.escape(c['npi'])}</td>"
        f"<td><a href='/pilot/entity/{c['entity']}'>{c['entity']}</a></td><td>{html.escape(c['payer'])}</td>"
        f"<td class='n'>${c['paid']:,.0f}</td></tr>" for c in mine
    )
    flag_rows = "".join(
        f"<tr><td>{html.escape(f['severity'])}</td><td><a href='/pilot/flag/{f['id']}'>{html.escape(f['label'])}</a></td>"
        f"<td class='n'>${f['dollars']:,.0f}</td></tr>" for f in flags if f["enrollee"] == pid
    )
    body = (
        "<p><a href='/pilot'>Pilot home</a></p>"
        f"<h1>{html.escape(pid)}</h1>"
        + _PILOT_BANNER
        + f"<p class='lede-sm'>Age {enr['age']} · {html.escape(enr['county'])} County · {html.escape(enr['program'])} · "
        f"diagnoses: {html.escape(', '.join(enr['diagnoses']) or 'none in record')} · visits {enr['visits']} · "
        f"immunizations {enr['immunizations']}" + (f" · died {enr['death_date']}" if enr.get("death_date") else "") + "</p>"
        f"<div class='gatecard'><span class='score'>{g['score']} of 10</span> · identity evidence {g['identity_evidence']} of 4 · "
        f"condition evidence {g['condition_evidence']} of 3 · continuity {g['continuity']} of 3 · "
        f"housing: {html.escape(g['housing_context'])} (context for outreach, never scored)"
        + (" · <b>below the gate: routes to review before payment</b>" if g["flagged"] else "") + "</div>"
        "<h2>Claims</h2>"
        f"<div class='table-wrap'><table><tr><th>Date</th><th>Code</th><th>Provider NPI</th><th>Entity</th><th>Payer</th><th>Paid</th></tr>{claim_rows}</table></div>"
        "<h2>Flags</h2>"
        f"<div class='table-wrap'><table><tr><th>Severity</th><th>Signal</th><th>Flagged $</th></tr>{flag_rows}</table></div>"
    )
    return _pilot_page(body, f"Enrollee {pid}")


@app.get("/pilot/onepager", response_class=HTMLResponse)
def pilot_onepager() -> str:
    d = _pilot_data()
    sample, flags, s = d["sample"], d["flags"], d["summary"]
    by_type: dict[str, list] = {}
    for f in flags:
        by_type.setdefault(f["type"], []).append(f)
    from . import pilot as _pilot

    rows = "".join(
        f"<tr><td>{html.escape(_pilot.FLAG_TYPES[k])}</td><td class='n'>{len(v)}</td>"
        f"<td class='n'>${sum(f['dollars'] for f in v):,.0f}</td></tr>"
        for k, v in sorted(by_type.items())
    )
    top_entities: dict[str, float] = {}
    for f in flags:
        top_entities[f["entity"]] = top_entities.get(f["entity"], 0) + f["dollars"]
    entities = {e["id"]: e for e in sample["entities"]}
    tops = "".join(
        f"<li>{html.escape(entities[e]['name'])}: ${v:,.0f} across flagged claims</li>"
        for e, v in sorted(top_entities.items(), key=lambda kv: -kv[1])[:5]
    )
    body = f"""<p><a href='/pilot'>Pilot home</a></p>
<h1>Minnesota (sample): what the record shows before payment</h1>
{_PILOT_BANNER}
<p>We loaded one state's sample of claims and patient records ({s['enrollees']} enrollees,
{s['claims']} claims, ${s['claims_dollars']:,.0f}) and ran deterministic checks only:
no models, no AI, same input and same answer every time. The checks compare each claim against
the patient's own record, against scope of practice, and against the Medicare fee schedule and
payer-filed rates (OpenPayer corpus, CMS 2026 RVU file).</p>
<h2>What surfaced</h2>
<p><strong>{s['flags']} flags, ${s['flagged_dollars']:,.0f} in flagged claims.</strong>
{s['gate_flagged']} enrollees score below the validation gate (8 of 10) and would route to
review before payment.</p>
<table><tr><th>Signal</th><th>Flags</th><th>Flagged dollars</th></tr>{rows}</table>
<h2>Where it concentrates</h2><ul>{tops}</ul>
<p>Each flag opens to the billing entity and its ownership web: parent LLC, sibling entities,
shared addresses, owners, and registered agents. In this sample the ghost-enrollee billing
($1,560, no record history at all) traces to a DME supplier sharing a parent, address, owner,
and agent with a home health agency and a hospice.</p>
<h2>What this is and is not</h2>
<p>Flags are review signals, not findings. A clinician and CMS make every call. The method is
zero-copy: scoring runs where the records already live and moves nothing.</p>
<h2>The ask</h2>
<p><strong>An ATO and a sandbox in a jurisdiction of CMS's choosing, for a defined pilot term:</strong>
one high-risk category, one region, ninety days. We check every held claim against the record,
report what the check caught that review missed and what it cleared that review would have
delayed, and CMS decides what scales.</p>
<p class='note'>MedTruth · Prepared for CMS Program Integrity · Demo generated {html.escape(sample['generated'])} from synthetic data</p>"""
    return _pilot_page(body, "Minnesota sample: what we found")


@app.get("/code/{code}", response_class=HTMLResponse)
def code_page(code: str, payer: str | None = None, rate: float | None = None) -> str:
    if not _has_data():
        return f"<html><body style='font-family:system-ui'><h1>{html.escape(code)}</h1><p>No data pulled yet.</p></body></html>"
    codes_cfg = {c.code: c for c in load_codes()}
    cfg = codes_cfg.get(code)
    bench_all = [r for r in summary_by_code_payer() if str(r["billing_code"]) == code]
    agg_all = [r for r in summary_all_payers() if str(r["billing_code"]) == code]
    bench = [r for r in bench_all if not payer or str(r["payer"]) == payer]
    rows = rates_for_code(code, payer=payer, limit=100000)
    dollar = [r for r in rows if r.get("negotiated_rate") is not None]
    vals_all = [float(r["negotiated_rate"]) for r in dollar]
    xmax_global = max(25.0, (int(max(vals_all) / 25) + 1) * 25) if vals_all else 100.0
    p99 = _percentile(sorted(vals_all), 0.99) if len(vals_all) >= 20 else (max(vals_all) if vals_all else 0.0)
    xmax_code = max(25.0, (int(p99 / 25) + 1) * 25) if vals_all else 100.0

    total_n = sum(int(r["n_rates"]) for r in bench)
    total_groups = sum(int(r["n_provider_groups"]) for r in bench)
    payer_count = len({str(r["payer"]) for r in bench})
    counts_line = (
        f"{total_n} observed dollar rates · {total_groups} provider groups · {payer_count} payer"
        + ("s" if payer_count != 1 else "")
        + (f" · showing {html.escape(payer)}" if payer else "")
    )

    band_rows = bench if payer else agg_all
    cells = []
    for rtype in ("negotiated", "fee schedule"):
        r = next((x for x in band_rows if str(x["negotiated_type"]) == rtype), None)
        if r is None:
            cells.append(
                f"<div class='cell'><span class='lab'>{html.escape(rtype)}</span><div class='med'>no rates yet</div>"
                "<span class='lab'>n=0 in the files pulled so far</span></div>"
            )
        elif int(r["n_rates"]) == 1:
            cells.append(
                f"<div class='cell'><span class='lab'>{html.escape(rtype)}</span><div class='med'>${float(r['median'] or 0):,.0f}</div>"
                "<span class='lab'>single observed rate · n=1 · no spread claimed</span></div>"
            )
        else:
            who = f"{r['n_payers']} payers" if not payer else html.escape(payer)
            pct = _pct_text(code, r["median"])
            mrate = reference.medicare_rate(code)
            medline = (
                f"<span class='lab'>Medicare national ${mrate:,.2f} · this median is {pct}</span>" if pct and mrate else ""
            )
            cells.append(
                f"<div class='cell'><span class='lab'>{html.escape(rtype)}</span><div class='med'>${float(r['median'] or 0):,.0f}</div>"
                f"<span class='lab'>median · middle half ${float(r['p25'] or 0):,.0f} to ${float(r['p75'] or 0):,.0f} · n={r['n_rates']} · {who}</span>{medline}</div>"
            )
    answer = "<div class='answerband'>" + "".join(cells) + "</div>"

    whiskers = _code_whiskers(bench, xmax_code) if bench else ""
    scale_note = (
        f"<p class='note'>Chart scale $0 to ${xmax_code:,.0f} covers the middle 99 percent of this code's observed rates. "
        f"The site-wide scale is $0 to ${xmax_global:,.0f}; this page tightens position only, never the counts.</p>"
        if xmax_code < xmax_global else ""
    )
    by_type: dict[str, list[dict]] = {}
    for r in dollar:
        by_type.setdefault(str(r["negotiated_type"]), []).append(r)
    facets = _distribution_facets(by_type, xmax_code)

    payer_links = "".join(
        f"<a class='chip' href='/code/{html.escape(code)}?payer={html.escape(str(p))}'>{html.escape(str(p))}</a>"
        for p in sorted({str(r["payer"]) for r in bench_all})
    )
    scope = (
        f"<p class='coverage'>Showing {html.escape(payer)} only. <a href='/code/{html.escape(code)}'>Show all payers</a></p>"
        if payer else (f"<p class='coverage'>Filter by payer: <span class='chips'>{payer_links}</span></p>" if payer_links else "")
    )
    breakdown = ""
    if bench:
        breakdown = (
            "<h2>Median by payer</h2><div class='table-wrap'><table><tr><th>Payer</th><th>Rate type</th><th>Rates</th><th>p25</th><th>Median</th><th>p75</th><th>% of Medicare</th></tr>"
            + "".join(
                "<tr><td>{p}</td><td>{t}</td><td class='n'>{n}</td><td class='n'>${a:,.2f}</td><td class='n'>${m:,.2f}</td><td class='n'>${b:,.2f}</td><td class='n'>{pct}</td></tr>".format(
                    p=html.escape(str(r["payer"])), t=html.escape(str(r["negotiated_type"])), n=r["n_rates"],
                    a=r["p25"] or 0, m=r["median"] or 0, b=r["p75"] or 0,
                    pct=html.escape(_pct_text(code, r["median"])),
                )
                for r in bench
            )
            + "</table></div>"
        )
    table_rows = rows
    rate_note = ""
    if rate is not None:
        table_rows = [
            r for r in rows
            if r.get("negotiated_rate") is not None and abs(float(r["negotiated_rate"]) - rate) < 0.005
        ]
        clear_q = f"?payer={html.escape(payer)}" if payer else ""
        rate_note = (
            f"<p class='coverage'>Only rates of exactly ${rate:,.2f} are listed below "
            f"({len(table_rows):,} of {len(rows):,} rates for this code). "
            f"<a href='/code/{html.escape(code)}{clear_q}'>Show every rate for this code</a>.</p>"
        )
    trs = "".join(
        "<tr><td>{p}</td><td>${v:,.2f}</td><td>{t}</td><td>{prov}</td><td>{tin}</td><td><a href='{src}'>source file</a></td></tr>".format(
            p=html.escape(str(r["payer"])), v=r["negotiated_rate"] or 0, t=html.escape(str(r["negotiated_type"])),
            prov=html.escape(str(r["provider_name"])), tin=html.escape(str(r["tin"])), src=html.escape(str(r["source_url"])),
        )
        for r in table_rows[:200]
    )
    table = "<div class='table-wrap'><table><tr><th>Payer</th><th>Rate</th><th>Type</th><th>Provider</th><th>TIN</th><th>Lineage</th></tr>" + trs + "</table></div>"
    csv_link = f"/api/rates/{html.escape(code)}.csv" + (f"?payer={html.escape(payer)}" if payer else "")
    shown = payer if payer else "all payers"
    return (
        f"<html><head><title>{html.escape(code)} rates</title>{og_head()}<style>{STYLE}</style></head><body><div class='wrap'>"
        f"<p><a href='/'>All codes</a></p><div class='code-head'><h1><span class='cnum'>{html.escape(code)}</span></h1>"
        f"<p class='lede-sm'>{html.escape(cfg.note if cfg else '')} · {html.escape(cfg.code_system if cfg else '')}</p>"
        f"<p class='coverage'>{counts_line}</p></div>{scope}{answer}"
        f"<h2>By payer</h2>{whiskers}{scale_note}"
        f"<h2>The rates themselves</h2>{facets}"
        f"{breakdown}"
        f"<h2>See the numbers ({shown})</h2>{rate_note}{table}"
        f"<p class='note'>Rates are sorted low to high as stored. Each rate links to the payer file it came from. "
        f"Download: <a href='{csv_link}'>these rates as CSV</a> · <a href='/api/rates/{html.escape(code)}'>JSON</a>. First 200 rows shown; the CSV and JSON carry up to 500.</p>"
        + '<div id="tip" role="status"></div>' + _EXPLORE_SCRIPT + "</div></body></html>"
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


@app.get("/api/flags")
def api_flags():
    from . import flags as _flags

    if not _has_data():
        return JSONResponse({"detail": "no data yet"}, status_code=404)
    return _flags.compute_flags(flags_input())


@app.get("/api/flags.csv")
def api_flags_csv():
    import json as _json

    from . import flags as _flags

    if not _has_data():
        return JSONResponse({"detail": "no data yet"}, status_code=404)
    computed = _flags.compute_flags(flags_input())
    flat = [{**f, "evidence": _json.dumps(f["evidence"])} for f in computed]
    return _csv_response(
        flat,
        ["severity", "payer", "billing_code", "kind", "medicare_rate", "evidence", "clears_if", "lever", "note"],
        "openpayer-flags.csv",
    )


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

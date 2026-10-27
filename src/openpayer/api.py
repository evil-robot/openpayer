from __future__ import annotations

import html

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import auth as authmod
from .benchmarks import data_inventory, rates_for_code, summary_by_code_payer
from .config import load_codes
from .store import DB_PATH

app = FastAPI(title="OpenPayer", description="Rate search and benchmarks from CMS price transparency files")

PUBLIC_PATHS = {"/health", "/sign-in", "/confirm", "/auth/verify"}


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    if not authmod.auth_enabled() or request.url.path in PUBLIC_PATHS:
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
        f"<html><head><title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><h1>OpenPayer</h1>{body}</body></html>"
    )


@app.get("/sign-in", response_class=HTMLResponse)
def sign_in_page():
    domains = ", ".join(sorted(authmod.allowed_domains()))
    return _bare(
        "Sign in",
        "<p>OpenPayer at this address is for the MedTruth team. "
        f"Sign-in is by email link for @{domains} addresses.</p>"
        '<form method="post" action="/sign-in"><label>Email <input type="email" name="email" required size="34"></label> '
        '<button type="submit">Email me a sign-in link</button></form>',
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
    return _bare("Check your email", "<p>If that address may sign in, a link is on its way. It expires in 7 days.</p>")


@app.get("/confirm", response_class=HTMLResponse)
def confirm_page(token: str = ""):
    # Scanner-proof relay: no link or form action points at the verify URL.
    # The button builds it in the browser on a real click.
    safe = html.escape(token)
    return _bare(
        "Confirm sign-in",
        "<p>Press the button to finish signing in.</p>"
        f'<button id="go" data-token="{safe}">Sign in to OpenPayer</button>'
        "<script>document.getElementById('go').addEventListener('click',function(){"
        "setTimeout(function(){location.href='/auth/verify?token='+encodeURIComponent("
        "document.getElementById('go').dataset.token);},350);});</script>",
    )


@app.get("/auth/verify")
def auth_verify(token: str = ""):
    email = authmod.verify_token(token)
    if not email:
        return _bare("Link expired", "<p>That link is spent or expired. <a href='/sign-in'>Request a new one</a>.</p>")
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
body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:980px;padding:0 1rem;color:#13151E;background:#F0EEEB}
table{border-collapse:collapse;width:100%;background:#fff}th,td{border:1px solid #ccc;padding:.4rem .6rem;text-align:right}
th:first-child,td:first-child{text-align:left}.note{color:#444;font-size:.9rem}
.dot{cursor:pointer}.dot:hover{stroke:#13151E;stroke-width:2.6}
#tip{position:fixed;z-index:10;pointer-events:none;background:#13151E;color:#F0EEEB;padding:.55rem .7rem;
font-size:.85rem;line-height:1.45;max-width:340px;display:none;box-shadow:0 2px 10px rgba(0,0,0,.35)}
#tip strong{font-size:1rem}#tip .src{color:#c9c6c0;font-size:.75rem;word-break:break-all}
"""


def _has_data() -> bool:
    return DB_PATH.exists()


def _dot_plot(rows: list[dict]) -> str:
    rates = sorted(r["negotiated_rate"] for r in rows if r.get("negotiated_rate") is not None)
    if not rates:
        return "<p>No negotiated dollar rates yet for this code.</p>"
    lo, hi = rates[0], rates[-1]
    span = (hi - lo) or 1.0
    width, height = 900, 160
    dots = []
    for i, v in enumerate(rates):
        x = 40 + (v - lo) / span * (width - 80)
        y = 30 + (i % 10) * 12
        dots.append(f'<circle cx="{x:.1f}" cy="{y}" r="3.5" fill="#13151E"><title>${v:,.2f}</title></circle>')
    median = rates[len(rates) // 2]
    mx = 40 + (median - lo) / span * (width - 80)
    return (
        f'<svg width="{width}" height="{height}" role="img" aria-label="Dot plot of negotiated rates">'
        + "".join(dots)
        + f'<line x1="{mx:.1f}" y1="15" x2="{mx:.1f}" y2="{height - 15}" stroke="#888" stroke-dasharray="4"/>'
        + f'<text x="40" y="{height - 2}" font-size="11">${lo:,.0f} min</text>'
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
<li><strong>Sample depth today is one payer.</strong> The status and benchmark table at the top of this page always say exactly which codes, payers, and how many rates are live. Widen the code list to about 15 and add payer URLs to grow it; no code changes needed.</li>
<li><strong>Provider details and geography:</strong> NPPES (NPI registry) wiring is stubbed in <code>reference.py</code>. Provider practice city, state, ZIP, and specialty, and any map view, wait on that loader. It is designed to join only providers already in the pulled rates, so it stays small.</li>
<li><strong>Percent of Medicare:</strong> Medicare fee schedule wiring is stubbed the same way. No percent-of-Medicare figure is shown until real fee schedule data is loaded. The system shows nothing rather than a placeholder number.</li>
<li><strong>Hospital files:</strong> only payer Transparency in Coverage in-network files are parsed today. Hospital MRFs use a different schema and are a later source type.</li>
<li><strong>No automatic refresh yet:</strong> pulls are run by hand today. A scheduled quarterly refresh matches the new CMS cadence and is on the roadmap.</li>
<li><strong>Out of scope by decision:</strong> contract upload and modeling, and claims repricing for short pays. Those need private contracts and remits. This system is rate search and benchmarks from public data only.</li>
</ul>
"""


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    codes = load_codes()
    code_items = "".join(f"<li>{html.escape(c.code)} ({html.escape(c.code_system)}) {html.escape(c.note)}</li>" for c in codes) or "<li>None yet</li>"
    if not codes:
        status = "<p><strong>Current status: wired and waiting.</strong> No codes are configured, so no data has been pulled and no rates are shown. Add codes to <code>config/codes.json</code> and payer sources to <code>config/sources.json</code>, then pull.</p>"
        bench = ""
    elif not _has_data():
        status = f"<p><strong>Current status: codes configured, no pull yet.</strong></p><ul>{code_items}</ul>"
        bench = ""
    else:
        rows = summary_by_code_payer()
        trs = "".join(
            "<tr><td><a href='/code/{code}'>{code}</a></td><td>{payer}</td><td>{rtype}</td><td>{n}</td><td>{groups}</td><td>${p25:,.2f}</td><td>${med:,.2f}</td><td>${p75:,.2f}</td></tr>".format(
                code=html.escape(str(r["billing_code"])), payer=html.escape(str(r["payer"])), rtype=html.escape(str(r["negotiated_type"])), n=r["n_rates"],
                groups=r["n_provider_groups"], p25=r["p25"] or 0, med=r["median"] or 0, p75=r["p75"] or 0,
            )
            for r in rows
        )
        status = f"<p><strong>Current status: live with pulled data.</strong> Configured codes:</p><ul>{code_items}</ul>"
        inv = data_inventory()
        payer_rows = "".join(
            f"<li>{html.escape(str(p['payer']))}: {p['rows']} rate rows from {p['files']} source files</li>" for p in inv["by_payer"]
        )
        code_rows = "".join(
            f"<li>{html.escape(str(c['billing_code']))} ({html.escape(str(c['billing_code_type']))}): {c['rows']} rows</li>" for c in inv["by_code"]
        )
        type_rows = "".join(f"<li>{html.escape(str(t['negotiated_type'] or 'blank'))}: {t['rows']} rows</li>" for t in inv["by_type"])
        src_rows = "".join(
            f"<li><a href='{html.escape(str(s))}'>{html.escape(str(s).rsplit('/', 1)[-1])}</a></li>" for s in inv["sources"][:25]
        )
        extra_src = f"<li>Plus {len(inv['sources']) - 25} more source files, all listed in the database.</li>" if len(inv["sources"]) > 25 else ""
        inventory = (
            "<h2>Data in the demo today</h2>"
            "<p>This section is a live query of the demo database, not typed copy. It changes the moment a pull or load runs.</p>"
            f"<ul><li><strong>Total rate rows stored:</strong> {inv['total_rows']} (only the configured codes; everything else in each payer file was discarded during the pull)</li>"
            f"<li><strong>How much data that is:</strong> kept rate files take {inv['raw_size']} on disk (gzipped, {inv['raw_files_on_disk']} files); the searchable database is {inv['db_size']}. For scale, the payer files these rates were pulled from run about 9 MB each uncompressed before filtering, and a large national payer publishes files thousands of times bigger. The filter is why this demo stays megabytes, not terabytes.</li>"
            f"<li><strong>Source files kept from:</strong> {inv['source_files']} payer files; distinct NPIs on kept rates: {inv['distinct_npis']}</li>"
            f"<li><strong>Distinct provider groups (by tax ID):</strong> {inv['provider_groups']}; distinct named providers: {inv['providers_named']}"
            + (" Named providers are zero here because this payer cites providers by NPI without defining names in the file. The NPIs are kept on every rate; names join later from the NPI registry." if inv["providers_named"] == 0 and inv["total_rows"] else "")
            + "</li></ul>"
            f"<h3>By payer</h3><ul>{payer_rows}</ul>"
            f"<h3>By billing code</h3><ul>{code_rows}</ul>"
            f"<h3>By rate type (types are never blended in benchmarks)</h3><ul>{type_rows}</ul>"
            f"<h3>Source files (the audit trail; select one to open the payer original)</h3><ul>{src_rows}{extra_src}</ul>"
        )
        bench = inventory + (
            "<h2>Benchmarks (observed dollar rates by rate type, never interpolated, types never blended)</h2>"
            "<table><tr><th>Code</th><th>Payer</th><th>Rate type</th><th>Rates</th><th>Provider groups</th><th>p25</th><th>Median</th><th>p75</th></tr>"
            + trs + "</table><p class='note'>Select a code for the dot plot, the full rate table, and the source file behind every rate.</p>"
        ) + _market_strip()
    intro = "<p>OpenPayer is an open source rate search and benchmark tool. It takes the pricing files that payers must publish for free under federal price transparency law, keeps only the billing codes you choose, and lets anyone look up what payers actually reimburse, by code, payer, and provider, with the source file shown for every rate. Commercial tools sell access to this same public data. This one is open.</p>"
    return f"<html><head><title>OpenPayer</title><style>{STYLE}</style></head><body><h1>OpenPayer</h1>{intro}{status}{bench}{SYSTEM_DOES}<p class='note'>Source: payer machine-readable files published under CMS price transparency rules. Every rate traces to its source file URL in the code view. Counts are shown with each benchmark so a thin sample is never dressed up as a market.</p></body></html>"


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _market_strip() -> str:
    """Small multiples: every code on one shared dollar scale.

    One dot per observed dollar rate. Filled dot = negotiated, hollow dot = fee
    schedule (shape, not color alone). Grey band = middle half (p25 to p75),
    thick tick = median. Percentage rates are not dollars and are excluded,
    which the caption states. A code with no rates gets an explicit empty row.
    """
    codes = load_codes()
    per_code: dict[str, list[dict]] = {}
    all_vals: list[float] = []
    for c in codes:
        rows = [r for r in rates_for_code(c.code, limit=2000) if r.get("negotiated_rate") is not None]
        per_code[c.code] = rows
        all_vals.extend(float(r["negotiated_rate"]) for r in rows)
    if not codes:
        return ""
    xmax = max(all_vals) if all_vals else 100.0
    xmax = max(25.0, (int(xmax / 25) + 1) * 25)
    width, label_w, plot_w = 940, 110, 700
    row_h = 58
    height = 34 + row_h * len(codes) + 10
    x0 = label_w
    def X(v: float) -> float:
        return x0 + (v / xmax) * plot_w
    parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Market strip: for each billing code, one dot per observed dollar rate on a shared dollar scale, with the middle half and median marked">'
    ]
    tick = 0
    while tick <= xmax:
        parts.append(f'<line x1="{X(tick):.0f}" y1="22" x2="{X(tick):.0f}" y2="{height - 8}" stroke="#ddd"/>')
        parts.append(f'<text x="{X(tick):.0f}" y="14" font-size="10" fill="#444" text-anchor="middle">${tick:,.0f}</text>')
        tick += 25
    for i, c in enumerate(codes):
        top = 30 + i * row_h
        mid = top + 22
        rows = per_code[c.code]
        parts.append(f'<text x="0" y="{mid - 2}" font-size="13" font-weight="700">{html.escape(c.code)}</text>')
        parts.append(f'<text x="0" y="{mid + 13}" font-size="10" fill="#444">{html.escape(c.code_system)}</text>')
        vals = sorted(float(r["negotiated_rate"]) for r in rows)
        if not vals:
            parts.append(f'<text x="{x0 + 6}" y="{mid + 4}" font-size="11" fill="#666">No dollar rates found in the files pulled so far</text>')
            parts.append(f'<text x="{x0 + plot_w + 12}" y="{mid + 4}" font-size="11" fill="#444">n=0</text>')
            continue
        p25, med, p75 = _percentile(vals, 0.25), _percentile(vals, 0.5), _percentile(vals, 0.75)
        parts.append(f'<rect x="{X(p25):.1f}" y="{mid - 10}" width="{max(2.0, X(p75) - X(p25)):.1f}" height="20" fill="#d8d5cf"/>')
        for j, r in enumerate(rows):
            v = float(r["negotiated_rate"])
            y = mid - 6 + (j % 3) * 6
            who = r.get("provider_name") or ("NPI " + r["npi"] if r.get("npi") else "provider not named in file")
            title = html.escape(f"{r['payer']} | {r['negotiated_type']} | ${v:,.2f} | {who}")
            attrs = (
                f'class="dot" tabindex="0" data-code="{html.escape(c.code)}" data-rate="${v:,.2f}" '
                f'data-payer="{html.escape(str(r["payer"]))}" data-type="{html.escape(str(r["negotiated_type"]))}" '
                f'data-who="{html.escape(str(who))}" data-tin="{html.escape(str(r["tin"]))}" data-npi="{html.escape(str(r["npi"]))}" '
                f'data-src="{html.escape(str(r["source_url"]))}" '
                f'data-median="${med:,.2f}" data-band="${p25:,.2f} to ${p75:,.2f}"'
            )
            if r["negotiated_type"] == "negotiated":
                parts.append(f'<circle {attrs} cx="{X(v):.1f}" cy="{y}" r="4.5" fill="#13151E"><title>{title}</title></circle>')
            else:
                parts.append(f'<circle {attrs} cx="{X(v):.1f}" cy="{y}" r="4.5" fill="#F0EEEB" stroke="#13151E" stroke-width="1.4"><title>{title}</title></circle>')
        parts.append(f'<line x1="{X(med):.1f}" y1="{mid - 13}" x2="{X(med):.1f}" y2="{mid + 13}" stroke="#13151E" stroke-width="3"/>')
        parts.append(
            f'<text x="{x0 + plot_w + 12}" y="{mid - 2}" font-size="11">median ${med:,.0f}</text>'
            f'<text x="{x0 + plot_w + 12}" y="{mid + 12}" font-size="10" fill="#444">middle half ${p25:,.0f} to ${p75:,.0f} | n={len(vals)}</text>'
        )
    parts.append("</svg>")
    return (
        "<h2>The market at a glance</h2>"
        "<p>Each row is one billing code. Each dot is one real dollar rate from a payer file, on the same dollar scale for every row, so codes compare honestly. "
        "The grey band is the middle half of rates (p25 to p75). The thick tick is the median. "
        "Filled dots are negotiated rates. Hollow dots are fee schedule rates. Hover any dot for payer, rate type, amount, and provider. "
        "Percentage rates are not dollars and are left out. Exact values for every dot are in the benchmark table above and on each code page.</p>"
        + "".join(parts)
        + "<p class='note'>Source: Cox HealthPlans machine-readable files, index dated September 16, 2026, pulled live by this system. "
        "Counts (n) are printed on every row. A row with n=0 means no dollar rate for that code appeared in the files pulled so far, not a rate of zero. "
        "Hover or tab to any dot for its full detail panel.</p>"
        + '<div id="tip" role="status"></div>'
        + """<script>
(function(){
  var tip=document.getElementById('tip');
  function show(d){
    var pos='Market for this code: median '+d.median+', middle half '+d.band;
    tip.innerHTML='<strong>'+d.rate+'</strong> &nbsp;'+d.code+'<br>'+d.payer+' | '+d.type+
      '<br>'+d.who+(d.tin?'<br>TIN '+d.tin:'')+(d.npi && d.who.indexOf(d.npi)<0?'<br>NPI '+d.npi:'')+
      '<br>'+pos+'<br><span class="src">Source: '+d.src+'</span>';
    tip.style.display='block';
  }
  function move(e){tip.style.left=Math.min(e.clientX+14,innerWidth-360)+'px';tip.style.top=Math.min(e.clientY+14,innerHeight-170)+'px';}
  document.querySelectorAll('.dot').forEach(function(el){
    el.addEventListener('mouseenter',function(e){show(el.dataset);move(e);});
    el.addEventListener('mousemove',move);
    el.addEventListener('mouseleave',function(){tip.style.display='none';});
    el.addEventListener('focus',function(){show(el.dataset);var r=el.getBoundingClientRect();tip.style.left=Math.min(r.left+14,innerWidth-360)+'px';tip.style.top=(r.bottom+10)+'px';});
    el.addEventListener('blur',function(){tip.style.display='none';});
  });
})();
</script>"""
    )


@app.get("/code/{code}", response_class=HTMLResponse)
def code_page(code: str) -> str:
    if not _has_data():
        return f"<html><body style='font-family:system-ui'><h1>{html.escape(code)}</h1><p>No data pulled yet.</p></body></html>"
    rows = rates_for_code(code, limit=500)
    plot = _dot_plot(rows)
    trs = "".join(
        "<tr><td>{p}</td><td>${v:,.2f}</td><td>{t}</td><td>{prov}</td><td>{tin}</td><td><a href='{src}'>source file</a></td></tr>".format(
            p=html.escape(str(r["payer"])), v=r["negotiated_rate"] or 0, t=html.escape(str(r["negotiated_type"])),
            prov=html.escape(str(r["provider_name"])), tin=html.escape(str(r["tin"])), src=html.escape(str(r["source_url"])),
        )
        for r in rows[:200]
    )
    table = "<table><tr><th>Payer</th><th>Rate</th><th>Type</th><th>Provider</th><th>TIN</th><th>Lineage</th></tr>" + trs + "</table>"
    return (
        f"<html><head><title>{html.escape(code)} rates</title><style>{STYLE}</style></head><body>"
        f"<p><a href='/'>All codes</a></p><h1>Code {html.escape(code)}</h1>{plot}"
        f"<h2>See the numbers</h2>{table}"
        "<p class='note'>Each dot is one observed negotiated rate for one provider group. Dashed line is the median. Rates link to the payer file they came from.</p></body></html>"
    )


@app.get("/api/codes")
def api_codes():
    return [{"code": c.code, "code_system": c.code_system, "note": c.note} for c in load_codes()]


@app.get("/api/summary")
def api_summary():
    if not _has_data():
        return JSONResponse({"detail": "no data yet"}, status_code=404)
    return summary_by_code_payer()


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

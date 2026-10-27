# OpenPayer front-end design (Tufte + UX, paired review)

Briefed October 27, 2026 on the live sample (Cox HealthPlans, 179 rows, 8 codes). Where the seats disagree, Tufte decides evidence, UX decides interaction.

## Implementation status at brief time

- Tufte fix 1 (split the strip by rate type, never pooled) and fix 2 (zero baseline on the code page) were implemented the same day in src/openpayer/api.py.
- The remaining ranked items from both seats are the build list below, in their own words.

---

## Tufte seat (evidence design)

Verdict: The Market Strip makes the right big choice, one shared dollar scale with one dot per observed rate, but it pools negotiated and fee schedule rates into a single median and band in [api.py](/Users/jas/Projects/openpayer/src/openpayer/api.py:269), so the design must be rebuilt around that split before any polish, and the UX pass is still owed.

### The comparison each graphic exists to make

| Graphic | Comparison it must support |
|---|---|
| Market Strip (overview) | For the same dollars, how do the typical rate and spread for 99213 compare with 99446 to 99452 and G2212, for one payer in one period |
| Benchmark table | Exactly where a quoted rate sits, low, middle or high, within one code, one payer, one rate type |
| Code detail distribution | Within one code, how individual provider groups spread, and who is the outlier |
| Provider table | Which provider group was paid what, traceable to the payer file it came from |
| Future: percent of Medicare strip | How the paid rate compares with Medicare for the same code, shown as a ratio beside the dollars |
| Future: payer facets | The same code across payers, same scale, side by side |
| Future: quarterly sparkline | How the median for a code, payer and type moved between refresh dates, with n at each point |

If a graphic cannot state its comparison in one sentence like those, it does not go on the page.

### Page structure, top to bottom

1. Header. OpenPayer name, signed in address, sign out. No navigation that hides a page.
2. Sentence headline that states the finding, not a topic label. Example: 99213 pays a median of $93.73 at Cox HealthPlans, while the six 994xx codes pay $19.57 to $78.33. Under it, coverage in one line: One payer, index dated September 16, 2026, 23 files searched, 179 rate rows kept, 8 codes in scope. This line sits on the surface, not in a footer.
3. Controls. Payer picker, rate type control defaulting to separate (never pooled), provider search by name, NPI or TIN once NPPES joins. Every control shows its effect as a count: Showing X of Y rates.
4. Market Strip. All 8 codes on one shared dollar scale, split by rate type as paired rows or paired bands per code. This is the macro read.
5. Benchmark table. Exact numbers, one row per code, payer and rate type. This is the micro read and the primary screen reader surface.
6. Code detail. Clicking a code row opens its full distribution at a larger scale, the provider table, and the source file for every rate.
7. Methods and lineage. On each figure, source and period printed on the figure itself. Global note: public CMS price transparency files only, no AMA description text, backend on Databricks jobs and Lakebase Postgres in the future state, display built only from kept rows.

### Exact encodings and scales

Scale. One linear dollar scale for the whole strip, starting at zero, ending at the next $25 above the maximum observed rate. Today the maximum is $320.62, so the scale is $0 to $325 with ticks every $25, exactly as the current strip computes it. Position means dollars. No log scale, no truncated axis on the overview. The code detail view may zoom, and when it does it must print Scale differs from overview and keep a faint outline of the overview range.

Marks. One dot per observed dollar rate. Filled circle is negotiated, hollow circle with an ink stroke is fee schedule, shape carries the meaning, not colour alone, so it survives a grey photocopy. Dot radius 4.5 px. Vertical jitter inside a row is layout only and must be labelled as such, or replaced by stacking in dollar order.

Summary marks. A light grey band in #D8D5CF from p25 to p75, and a thick ink tick at the median. Band and median are computed within one code, one payer and one rate type only. The percentile method must be printed in the methods line, for example, percentiles use linear interpolation between closest ranks, which is what [api.py](/Users/jas/Projects/openpayer/src/openpayer/api.py:260) does today. Observed dots are never interpolated. Percentage rates are never plotted on the dollar scale, and the strip must say so.

Colour. Ink #13151E on cream #F0EEEB, greys only. No accent colour. Grid lines in light grey that recede, median and dots in ink that advance. Large areas stay muted cream and light grey per Imhof, only small marks carry full ink.

Labels. Every row carries code, median, middle half, and n at the right edge, in the same place for every row. Every figure repeats its source and period directly under it, for example, Source: Cox HealthPlans files, index September 16, 2026. Counts sit beside every benchmark, never in a separate panel.

### Interaction model

Hover and keyboard focus on a dot opens the same panel: rate, code, payer, rate type, provider or NPI not named in file, median and band for that slice, and the source file name as a link. The panel supplements the table. It never holds the only copy of a value.

Filter. Changing payer, rate type or provider recomputes median, band and n for the visible slice only, and prints the denominator, for example, 14 fee schedule rates from 23 files. Pooling rate types behind a single All types option is not offered. If a future pooled view is ever added for context, the split rows remain visible beside it.

Drill. Clicking a dot or a code label pins the slice and opens the code detail. The detail keeps the overview scale in view as a reference strip at the top, then the zoomed distribution, then the full See the numbers table. Back returns to the same filtered overview.

Search. Provider search results are a table first, not a map, until NPPES city, state and specialty are loaded. A map is a later small multiple, one per code, once geography is real data.

### What happens at n=1 and n=0

n=1. Show the single dot, no band, and a short median tick only if labelled Single observed rate, no spread. The table row shows the value in the median column and prints n=1 in the same row. It must not be drawn with the visual weight of a benchmark built on 34 rates. Today that is the one negotiated 99213 rate beside 34 fee schedule rates, and the page must make that imbalance impossible to miss.

n=0. Keep the row. Print No dollar rates found in the files pulled so far and n=0, as the current strip already does for G2212. The benchmark table must also keep a G2212 row stating searched and found none, because a missing row reads as not searched. Never render zero as $0.00. The current benchmark formatting in [api.py](/Users/jas/Projects/openpayer/src/openpayer/api.py:205), which substitutes 0 for a missing percentile, must not survive into the new build.

### How national scale changes the rendering without lying

Up to about 300 rates per slice, keep one dot per rate with ordered stacking. It stays honest because every rate is still a mark.

Above 300 rates per slice, switch that row to a binned strip. Fixed $5 bins on the overview, $10 bins if the maximum passes $500, the same bin width for every code on the page. Bar height is count, with a count axis. Individual dots remain for rates outside p1 to p99, each labelled as an observed outlier with its value. The switch threshold and bin width are printed on the figure. No smoothing curve, no kernel density, nothing that invents values between observed rates.

Above a few thousand rates, facet by payer before anything else. One small multiple per payer on the same dollar scale, each with its own n. Never pool national payers into one band and call it the market. The current silent caps, 2000 rows in the strip and 500 in the code page in [api.py](/Users/jas/Projects/openpayer/src/openpayer/api.py:269), must become visible statements: Showing first 2,000 of 8,431 rates, sorted by rate. Truncation without a label is omission.

Percent of Medicare joins only when the Medicare denominator for that code is loaded. It appears as a second strip sharing the code rows, scale 0 to 300 percent with a reference line at 100 percent labelled Medicare. Until then the cell prints Medicare rate not loaded, never a placeholder ratio.

### Tables and screen reader equivalents

Every SVG ships with the table that generated it on the same page, titled See the numbers, with payer, rate, rate type, provider, TIN, NPI and a source file link per row. The visual and the table sort the same way by default, by rate.

The SVG carries a text summary in its accessible name, for example, 99213, Cox HealthPlans, fee schedule, 34 rates, median $93.73, middle half $71.73 to $97.97, maximum $320.62. Dots are focusable in rate order, and the full table is reachable without a pointer. A screen reader user must be able to answer the same comparison, typical rate, spread and source, without seeing a single dot.

### Top 5 changes, ranked integrity first

1. Split the strip by rate type. The pooled median and band in the current Market Strip blend two populations that the benchmark table correctly keeps apart. Fix: paired rows per code, one negotiated, one fee schedule, each with its own band, median and n.
2. Hold the zero baseline and the shared scale. The code page dot plot in [api.py](/Users/jas/Projects/openpayer/src/openpayer/api.py:124) scales from minimum to maximum, which stretches small differences. Fix: overview always starts at zero, detail zoom always shows where it sits inside the overview, and missing values never render as $0.00.
3. Make n and coverage inseparable. Keep zero rows, print files searched beside rates kept, and surface the silent row caps. A benchmark without its denominator is a claim without evidence.
4. Print source, period and percentile method on every figure. Cox HealthPlans, index September 16, 2026 belongs under each strip and table, not only in a page footer. The reader should never have to hunt for provenance.
5. Earn the detail view. Raise dot density, direct labels instead of a legend, and whitespace in place of borders and grid ink. Erase non data ink until the rates are the loudest thing on the page, then stop before legibility suffers.

### What is good, specifically

The shared dollar scale across all codes is the correct foundation and should be kept exactly. Shape encoding of rate type, filled against hollow, is honest and photocopy safe. Printing n on every row and keeping an explicit empty row for G2212 already respects the reader. Every rate linking back to its payer source file is the audit trail this tool exists to provide.

### The single change that would improve this most

Unblend the Market Strip. Split every code row by rate type with its own band, median and n. Until that is done, the most prominent number on the page, the strip median for 99213, describes a pool that the tool itself elsewhere says must never be pooled.
---

## UX seat (interaction design)

OpenPayer UX design. MedTruth gated build at openpayer.medtruth.care.

Basis: live render of `/` and `/code/{code}` from [api.py](/Users/jas/Projects/openpayer/src/openpayer/api.py), plus [SPEC.md](/Users/jas/Projects/openpayer/SPEC.md) and [benchmarks.py](/Users/jas/Projects/openpayer/src/openpayer/benchmarks.py). Sample state checked live: 179 rows, Cox HealthPlans only, 23 files, index 16 Sep 2026. Tufte owns all evidence calls on the Market Strip (scale, band, median, ink). This ruling owns interface only. Where Tufte and this ruling would differ, Tufte decides the chart, this seat decides the interaction.

Verdict up top: the tool answers the right question and hides it. The landing page makes a contracting analyst scroll past a database inventory and a build log to reach the rates. Fix the order first. Everything else is cheaper after that.

### 1. Page and navigation structure

Current state: one long server page at `/`. In order: intro paragraph, status and code list, Data in the demo today, benchmark table, Market Strip, What this system does today, What it does not do yet, source note. Code page at `/code/{code}` is a dot plot plus a table with a single All codes link back. Sign in pages at `/sign-in` and `/confirm` are bare, with no header at all. The JSON API (`/api/codes`, `/api/summary`, `/api/rates/{code}`) is not linked from anywhere a person can find. Rule broken: no hidden pages, and one idea per surface.

Fix. Persistent header on every page, including sign in, in ink on cream. Left: OpenPayer wordmark, links home. Centre or right, words only, no icons: All codes, Data and sources, How it works, API. Far right: signed in email and Sign out when a session exists, Sign in when it does not. The current `POST /sign-out` needs a visible control. A person who lands signed out should never wonder how to get back in, and a person who is signed in should never hunt for the exit.

Landing `/` becomes the search surface and nothing else, in this order:
1. Freshness line (see section 8).
2. One sentence lede: what this is, whose files, what a rate here means.
3. Search and filter bar, sticky on scroll (section 2).
4. Market Strip, the glanceable answer.
5. Benchmark table, headed See the numbers, the same numbers in text for anyone who cannot or will not use the chart.
6. Data in the demo today, collapsed under a disclosure headed What is in here right now. It is provenance, not the answer, so it sits below the answer and opens on request.
7. Footer: source line, last pull, link to How it works.

Move What this system does today and What it does not do yet off the landing page entirely to `/about` (How it works), reachable from the header. It is good honest copy and it is currently taxing every lookup. Keep the gaps list there with the same plain wording, including NPPES geography and percent of Medicare as not yet loaded, with the reason on the surface.

Per code page `/code/{code}` keeps its job and gains a breadcrumb: All codes, then the code. Header block for the code: the code in large type, its short note from `codes.json`, its system (CPT or HCPCS), and the count line (n rates, n provider groups, payers present). Below that, the same filter bar narrowed to this code, then the dot plot, then the rate table, then a source note. Every rate row carries its own source link. That link is the product. It never moves into a footnote.

New route needed for one rate: `/code/{code}` with a rate selected stays on the code page and opens a detail panel (section 3). Do not add a separate rate page until a rate needs a stable shareable address for a client note, then add `/code/{code}/rate` keyed by source file and NPI.

### 2. Search and filter controls and their states

Today there are no search controls in the interface. The API accepts `?payer=` on `/api/rates/{code}` and nothing in the UI exposes it. With one payer that is survivable. With national payers coming it is not.

Controls, left to right in the filter bar, each with a visible label and one line of guidance under the bar in 0.9rem grey text. Guidance is part of the control, not a help page.

| Control | What it does | Guidance line |
|---|---|---|
| Code search | Type a code or word from the note, pick from the 8 configured codes | Search the 8 codes in this build. Codes not in the list have not been pulled. |
| Payer | Multi-select, today one option (Cox HealthPlans) plus disabled rows for payers with no URL yet | Rates are never averaged across payers. Pick one payer to read a clean market. |
| Rate type | Segmented: All, Negotiated only, Fee schedule only | Negotiated and fee schedule are different facts. All shows both, never blended into one median. |
| Provider | Text field for name, NPI or tax ID | Many Cox rows name no provider in the file. Search by NPI where a name is missing. |

Future controls appear disabled with the reason on the control, not hidden: Geography (State, ZIP) reads "Provider city and state arrive when the NPI registry joins. Not yet loaded." Percent of Medicare reads "Needs the Medicare fee schedule. Not yet loaded, so no percent is shown." Disabled is a state a person can read, not a grey mystery.

States for every control:
- Resting: label above, field below, cream background, ink border.
- Focus: 2px ink outline with offset. Never rely on colour alone. The current stylesheet has no focus rule at all.
- Active: chosen values become removable chips directly under the bar, each chip says what it filters and carries a clear control. A single Clear all sits at the end of the chip row.
- Loading: bar stays live, results area shows the skeleton in section 8. The control that caused the load shows a brief "Updating" text beside it.
- Empty after filtering: results area shows the filtered empty state in section 4, and the chips remain so the person can undo the exact filter that emptied the set.
- Error: if the API returns no data (the current 404 on `/api/summary` and `/api/rates`), the bar stays, the results area says what failed in plain English and offers Retry. Never a raw status or stack text.

Sort for the rate table: Rate low to high is the default and matches the dot order. Add Payer, then Provider as secondary sorts, chosen from a labelled select. Keep sort in the URL query so a filtered view can be pasted into a note and reopen the same view.

Density rule: the filter bar is one row on desktop, wraps to two. It never becomes a left rail. On a tool an analyst opens to answer one question, a rail is a second surface competing with the answer.

### 3. From all codes to one code to one rate and its source

The journey needs to be three deliberate steps, each reversible.

Step 1, all codes. On `/`, the Market Strip gives one row per code and the benchmark table gives the same codes as rows. Selecting a code name anywhere (strip row label, benchmark row, search result) goes to `/code/{code}`. The strip row label itself becomes a link. Today only the benchmark table links. A person reading the chart should not have to scroll up to a table to act on what the chart showed.

Step 2, one code. On `/code/{code}`, the dot plot shows that code alone, the rate table lists every observed dollar rate for the code sorted low to high, with payer, rate, type, provider or NPI, tax ID. Percentage rates stay out of the dollar plot and the caption says so on the page, as it does today.

Step 3, one rate and its source. Selecting a dot or a table row opens a detail panel pinned to the right on desktop, a sheet from the bottom on phone. The panel shows, in this order: the dollar amount in large type, the code, payer and rate type, provider name or "Provider not named in this payer file" with the NPI when there is one, tax ID when there is one, where this rate sits (the code median and the middle half, as text), and the source: the payer file name as a link that opens the original machine readable file, plus the pull date (Cox index 16 Sep 2026). A Copy link button copies the code page address with that rate selected, so the analyst can paste it into a client note and the recipient lands on the same rate. Close returns focus to the dot or row that opened it.

The hover panel that exists today (`#tip`) becomes the preview, the click or Enter becomes the commitment. Hover alone can never be the only path to the source link, which is the current gap: the source URL sits inside a `pointer-events: none` tooltip that vanishes on mouse leave and can never be selected, copied or tapped reliably.

### 4. Empty and thin data states

Four states, four different treatments. Conflating them is how a thin sample gets dressed as a market.

n=0, the code is configured and no dollar rate was found. G2212 today. The strip already renders "No dollar rates found in the files pulled so far" with `n=0`, which is the right instinct. Carry it everywhere: on the code page, replace the plot with that sentence in a bordered panel, plus why (this code is Medicare specific and this commercial payer does not publish it in the files pulled), plus what would change it (a Medicare Advantage payer or the Medicare fee schedule). The benchmark table omits the row rather than showing $0.00. A rate of zero is a claim. Absence is not.

n=1, one observed rate. 99213 negotiated at $45.00 today. Show the single dot, show the single table row, and suppress the band and the percentile language. There is no middle half of one. The summary line reads "One negotiated rate found: $45.00, Cox HealthPlans. One rate is not a market. Treat it as a single contract fact, not a benchmark." The panel for that rate says the same. Never print p25, median and p75 as three copies of the same number without that warning in the same visual block.

Thin, roughly n=2 to n=9. Show the dots and the numbers, and add a thin sample note directly under the code header: "Few rates so far (n=4). The median will move as more payers are pulled." Keep the median, drop the false precision of the band shading if Tufte agrees, and always print n beside any median.

Provider not named. In the Cox sample most rows carry an NPI and no name, and `providers_named` is 0. The table should show the NPI as the identifier and the words "Name not in payer file, NPI shown" once as a column note, not repeated as apologetic text in every cell. When NPPES joins, the name replaces the note and the geography appears in the same cell.

Percentage rates present but excluded. 60 of the 179 rows are percentage type. The code page note should say how many were set aside: "60 percentage rates for these codes are stored and left out of the dollar view because a percent is not a dollar." A person who knows the file should be able to account for every row.

### 5. Sign in flow friction

Current flow in [auth.py](/Users/jas/Projects/openpayer/src/openpayer/auth.py): `/sign-in` collects an email, always answers "If that address may sign in, a link is on its way," sends a Resend magic link to `/confirm?token=`, and `/confirm` shows a button that builds `/auth/verify` in the browser after a 350ms delay, specifically so mail scanners that pre fetch links do not spend the token. Sessions last 90 days, tokens 7 days. The scanner proof pattern is correct and stays.

Friction to remove:
- The sign in pages use `_bare`, no header, no way back, no statement of who this is for beyond one sentence. Give them the same header, the same measure and type scale, and the address in the title: Sign in to OpenPayer at openpayer.medtruth.care.
- The email field has no autocomplete, no input mode hint and no example. Add `autocomplete="email"` behaviour in words for the builder, a placeholder showing the expected form (name@medtruth.care), and guidance under the field: "Use your @medtruth.care address. The link arrives by email and works once."
- The check your email page gives no next step. It should say which address it was sent to (masked is fine), that it expires in 7 days, what to do if it does not arrive in a few minutes (check spam, then request a new link), and a Request a new link control that returns to the form with the email kept. Today a person whose link expires lands on "That link is spent or expired" with a single link and no context about why links die (already used, scanner spent it elsewhere, or 7 days passed). Name the likely cause in plain English and keep the new link request one tap away.
- The confirm page is the highest friction step and the easiest to misread as a second sign in. Head it "One more tap to finish" and explain in one line why: "Email scanners open links automatically. This tap proves it was you, so the link is not spent before you use it." The button label stays a verb: Sign in to OpenPayer. On a phone, a person will switch to mail, tap the link, land here, and tap again. That is acceptable because it is explained. Unexplained, it reads as a bug.
- Allowed versus not allowed must stay indistinguishable in the response, as it is today, for privacy. The guidance can still help without leaking: "If the address is on the MedTruth team list, the link is on its way. If nothing arrives, check the address ends in @medtruth.care."
- After verify, the redirect goes to `/` with no confirmation of who is signed in. Land on `/` with the header now showing the signed in email and a one line confirmation that dismisses: "Signed in as name@medtruth.care." A 90 day session means most visits skip sign in, which makes the rare sign in moment the one that must be unambiguous.
- No mailto anywhere in this flow. Help contact, if offered, is a real address rendered as text or a form, never a mailto link.

### 6. Phone layout with the chart

Current chart: fixed 940px wide SVG, 4.5px radius dots, a 340px fixed tooltip positioned from mouse coordinates, and a right aligned table. On a 390px phone that is horizontal scroll, dots too small to tap, and a tooltip that covers the row it describes.

Phone treatment:
- Header collapses to wordmark, All codes, and the account control. How it works and API move into a single Menu disclosure. Words, never a hamburger glyph alone without the word Menu beside it.
- Filter bar stacks: Code search full width, then Payer and Rate type as full width rows, chips wrap below. Every tap target at least 44px tall.
- Market Strip stops being one wide SVG on phone. Each code becomes its own block: code and note on one line, a compact strip at full phone width on the same shared dollar scale with fewer ticks ($0, $100, $200, $325), median and n as text under the strip, then the rate rows for that code. The shared scale is Tufte's call and it stays shared. The interface change is that the plot area uses the full width by moving the right hand median text below the strip instead of beside it, where it currently costs 130px.
- Dots keep a 4.5px visible mark with an invisible tap area of at least 24px, 44px where rows are sparse. Tap selects and opens the bottom sheet in section 3. The floating tooltip does not exist on touch. The sheet is dismissible, scrollable, and its source link is a real tappable link.
- Benchmark and rate tables become stacked cards per row on phone: code or rate as the heading, payer and type as a line, the numbers as labelled pairs (Rates, Median, Middle half). Right aligned numeric columns are a desktop affordance. On phone, labels travel with values.
- The code page dot plot scales to the container width with a viewBox, and the min, median and max labels stay inside the plot, never clipped at the edge as the current fixed width labels can be.

### 7. Keyboard and screen reader interaction for the chart

What exists: each dot is `tabindex="0"`, the SVG has `role="img"` with an aria label, each dot carries a `<title>`, and the tooltip is a `role="status"` div shown on focus. That is a real start and it has three problems. 179 tab stops is a keyboard trap in practice. A `role="status"` panel that rewrites its innerHTML on every focus will announce aggressively and unevenly across readers. And `role="img"` on the container tells a screen reader to treat the whole chart as one image, which fights the focusable children inside it.

Design:
- The chart is never the only path. The benchmark table above and the code table below carry every value in text. State that on the surface near the chart, as the caption already does, and keep it true.
- One tab stop for the chart. Arrow keys move between dots within a code row, up and down arrows move between code rows. Enter opens the detail panel, Escape closes it and returns focus to the dot. This is roving focus in interface terms: the chart behaves like one control with internal navigation, the way a person expects a grid to behave.
- Focus is visible: the focused dot gets a 2px ink ring drawn outside the mark, plus a slight size increase, never colour alone. The current hover stroke rule has no focus twin. Add one.
- The detail panel is a real labelled region. When it opens from the keyboard, focus moves into it, its heading is the rate and code, and it contains the source link as a normal link. When it opens from hover, it does not steal focus. The live announcement, if kept, is a polite single summary per selection (rate, code, payer), not the full panel contents re read on every arrow move. Arrow navigation updates the panel visually without announcing each intermediate dot, or the reader becomes unusable at 35 dots in the 99213 row.
- Screen reader text alternative beside the chart, visible to all: a short paragraph per code in text form, generated from the same numbers (for example "99213: 35 dollar rates from Cox HealthPlans, median $93, middle half $72 to $98, one negotiated rate at $45"). This doubles as the phone fallback and the print fallback. A visually hidden table is a second best. Visible text is the house pattern here and it serves sighted readers on small screens too.
- Skip link at the top of the page: Skip to rates. Reduced motion: nothing on this page needs motion. The tooltip fade, if any is added later, is removed under reduced motion and the panel appears without transition.

### 8. Loading and stale data states

The site is server rendered with no loading state today. A filter change, a payer pull in progress, or the move to Databricks and Lakebase will introduce waits. Design them now.

- First load: header and filter bar render immediately. The chart and table areas show skeleton rows in light grey blocks at the exact height of the finished rows, with the text "Loading rates" beside a count of codes expected. No spinner alone. A person should see the shape of the answer that is coming.
- Filter change: keep the previous results visible at reduced opacity with an Updating note, then swap. Never blank the chart to white on every keystroke in the code search. Search resolves on selection, not per character against the server.
- Freshness and stale data: every page carries one line under the header, in this form: "Cox HealthPlans, files dated 16 Sep 2026, pulled [date]. 179 rates for 8 codes." When a second payer joins, the line lists each payer with its own date, because a fresh national file and a stale regional file must never share one date. Stale is a stated threshold: once the newest file for a payer is older than one quarterly cycle (the CMS 9882 F cadence is quarterly), the line gains the words "This payer is past its quarterly refresh. Rates may have changed in the current files." in a bordered note, ink on cream, no accent colour. The fix is wording and placement, not a new hue.
- Percent of Medicare and geography, when they arrive, carry their own dates on the surface ("Medicare rates: 2026 fee schedule"). A benchmark that mixes a 2026 payer rate with a Medicare denominator must say both years where the number sits.
- Empty database and no pull yet: the current status copy ("codes configured, no pull yet") is honest. Restyle it into the empty state panel pattern from section 4, with the code list and a plain statement of what runs next. A person evaluating the tool should read that as a designed state, not a broken page.
- Error: if the store cannot be read, the page keeps the header, the freshness line reads "Rates unavailable right now," and the results area offers Retry. It never renders the capability list as a substitute for the data, which is the current risk on a long page where the build log sits below the failure.

### Top 5 interaction fixes, ranked

1. Reorder the landing page and move the capability log to How it works. Render: `/`. Element: the whole page order in `home()`. Rule: hierarchy, the eye lands on the answer, one idea per surface. Fix: freshness, lede, filters, Market Strip, See the numbers, collapsed inventory, footer. This single change makes every other fix discoverable.

2. Make one rate selectable, with a persistent source panel. Render: `/` Market Strip and `/code/{code}` dot plot. Element: the `pointer-events: none` hover tooltip (`#tip`) as the only home of the source URL. Rule: hover is an addition, never the only path. Fix: click, tap and Enter open a pinned panel (right on desktop, bottom sheet on phone) with the amount, position in market, provider or NPI, and a tappable source file link, plus Copy link. The audit trail is the reason this tool exists. It cannot live in a vanishing tooltip.

3. Add the search and filter bar with honest disabled states. Render: `/` and `/code/{code}`. Element: the missing payer, rate type and provider controls (the API already accepts `?payer=`). Rule: every control ships with plain English guidance. Fix: code search, payer multi select, a Negotiated and Fee schedule segmented control that never blends, provider search by name, NPI or tax ID, and geography and percent of Medicare shown disabled with the reason on the control. Without this, the second payer breaks the page.

4. Give empty and thin data their own designs. Render: `/` strip rows and `/code/{code}`. Element: the n=0 row (G2212) and the n=1 negotiated row (99213, $45.00). Rule: absence is never rendered as a rate, and a thin sample is never dressed as a market. Fix: n=0 gets a why and what would change it, with no zero in the table. n=1 loses the band and the percentile language and gains "one rate is not a market" in the same block as the number. Thin samples print n beside every median.

5. Make the chart work on a phone and by keyboard. Render: `/` Market Strip. Element: the fixed 940px SVG, 4.5px dots, mouse positioned tooltip, and 179 tab stops. Rule: thumb test and accessibility as part of done, focus states, reduced motion. Fix: per code blocks at full phone width with the median below the strip, 44px tap targets and a bottom sheet instead of a tooltip, one tab stop with arrow key navigation across dots and rows, a visible ink focus ring, and a visible text summary per code so the chart is never the only path to a number.

House rules check: ink, cream and greys only, no accent colour introduced anywhere in this design. Navigation in words, no emojis. No hidden pages, including the API, now linked from the header. No mailto. Every control carries its guidance line. Motion: none proposed, and the detail panel appears without animation under reduced motion.

Still owed: the Tufte pass on the same renders owns the shared scale, the band, the median mark, dot sizing as evidence, and any colour as information ruling. This design defers to it on all of those and will move the interface to match its findings where the two seats disagreed.
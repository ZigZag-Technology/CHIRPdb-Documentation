#!/usr/bin/env python3
"""Generate the costed sections of tranche-2/index.html from the data below.

Every day figure lives here once. Costs, section totals, bundle totals and
running totals are all computed, so the page cannot drift out of step with
itself. Only the region between the sentinel comments is rewritten; the head,
intro and scope-doc appendix are edited by hand in the HTML.

Usage:
  python3 scripts/gen_menu.py

Repo convention: plain hyphens, not em dashes. Standard library only.
"""
import os
import re
import sys

OUT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tranche-2", "index.html")

BEGIN = "      <!-- BEGIN gen_menu -->"
END = "      <!-- END gen_menu -->"

# --- Pricing basis ---------------------------------------------------------

DAY_RATE = 500
CONTINGENCY = 0.20
PM = 0.25  # on build days plus contingency
BUILD_RATE = DAY_RATE * (1 + CONTINGENCY) * (1 + PM)  # 750
BODY_RATE = DAY_RATE * (1 + CONTINGENCY)  # 600, contingency but no PM
BODY_DAYS_FULL = 5
BODY_DAYS_FAST = 2.5

BUILD_COST_HEAD = "Cost (£500/day + 20% contingency + 25% PM)"
BODY_TAG = "contingency, no PM"

PRIORITY_ORDER = ["Must", "Should", "Could", "Won't"]

# --- Menu data -------------------------------------------------------------
# (id, priority, text, days). Ids are referenced by the bundles. Days of None
# mean n/a (Won't items).

CHAT = [
    ("chat-answer", "Must", "Ask a question and get an answer drawn from verified reports (the tools the model can call, plus retrieval)", 11),
    ("chat-cite", "Must", "Every claim cited and checked, with a link to the report at the right PDF page", 4),
    ("chat-followup", "Must", "Follow-up questions within a conversation", 2),
    ("chat-refuse", "Must", "Refuses when there is no evidence or the question is off-topic; prompt-injection defence; safety disclaimer", 3),
    ("chat-stream", "Must", "Replies stream in; chat screen works on mobile and is accessible", 4),
    ("chat-english", "Must", "Answers in plain maritime English, tuned for task briefings and descriptions of a near miss", 4),
    ("chat-evals", "Must", "Quality test set, re-run after every change", 7),
    ("chat-tracing", "Must", "Tracing and cost per conversation", 2),
    ("chat-tables", "Should", "Tables in the reply", 2),
    ("chat-history", "Should", "Saved conversation history (needs sign-in)", 3),
    ("chat-toolbox", "Should", "Toolbox talk format", 3),
    ("chat-suggest", "Should", "Suggested follow-up and sample questions", 1),
    ("chat-summarise", "Should", "Long conversations: older turns summarised", 1),
    ("chat-export", "Should", "Copy, print and export an answer", 1),
    ("chat-charts", "Could", "Charts in the reply", 10),
    ("chat-upload", "Could", "Upload your own document and discuss it, deleted at session end, pattern record kept", 10),
    ("chat-maps", "Could", "Maps and heat maps", 8),
    ("chat-role", "Could", "Remembers your role and vessel type across chats", 3),
    ("chat-share", "Could", "Share link to a conversation", 2),
    ("chat-regen", "Could", "Regenerate an answer, or edit and resend a question", 1),
    (None, "Won't", "Web search (breaks the verified-data-only rule)", None),
    (None, "Won't", "Voice, image generation, native app", None),
    (None, "Won't", "Learning from user questions into the database (Tranche 3)", None),
]

ANALYST = [
    ("analyst-patterns", "Must", "Pattern finding for CHIRP analysts: ask what keeps recurring across all reports (for example, what keeps causing enclosed-space deaths), see the supporting cases, and get a first-draft outline of a CHIRP write-up to edit", 8),
    ("analyst-coding", "Must", "Proposed coding and similar cases for incoming CHIRP reports, inside the review tool", 6),
    ("analyst-dashboards", "Should", "Dashboards filtered by vessel type, date, outcome and country (P6)", 12),
]

PLATFORM = [
    ("platform-access", "Must", "Public access kept separate from staff tools; anonymous sessions", 2),
    ("platform-limits", "Must", "Rate limits, a spending cap that degrades gracefully, abuse and scraping protection", 4),
    ("platform-watch", "Must", "Watching answers, a “report a wrong answer” route, withdrawing an answer or record", 4),
    ("platform-deploy", "Must", "Deployment, load testing, backups, cost per conversation", 4),
    ("platform-landing", "Must", "Landing page, first-time walkthrough, sample questions, accessibility (WCAG)", 5),
    ("platform-terms", "Must", "Terms, privacy notice and disclaimers built in (CHIRP writes the wording)", 1.5),
    ("platform-beta", "Must", "Closed beta with real seafarers, then a round of fixes", 6),
    ("platform-docs", "Must", "User and developer documentation", 3),
]

SOURCES = [
    ("src-chirp", "Must", "CHIRP Maritime published reports", 3),
    ("src-digests", "Must", "MAIB Safety Digests", 2),
    ("src-link-official", "Must", "Accident linking, official reports: a report on an accident we already hold is kept and linked to that accident, never rejected (several countries’ reports on one accident, digests to the report they summarise; duplicate PDFs are already caught)", 2),
    ("src-freetext", "Should", "Generic free-text ingestion", 4),
    ("src-gisis", "Should", "IMO GISIS casualty module", 4),
    ("src-imo-lessons", "Should", "IMO Lessons Learned", 2.5),
    ("src-mars", "Should", "Nautical Institute MARS", 2.5),
    ("src-s4s", "Should", "SAFETY4SEA", 2.5),
    ("src-imca", "Should", "IMCA safety flashes", 2.5),
    ("src-uscg", "Should", "USCG Marine Safety Alerts", 2.5),
    ("src-msf", "Should", "Marine Safety Forum alerts", 2.5),
    ("src-legislation", "Should", "Legislation: UK/MCA, MLC, IMO references, AI-proposed links, recurring findings listed by law", 12),
    ("src-link-derivative", "Should", "Accident linking, derivative sources: MARS, SAFETY4SEA, GISIS and IMO lessons matched to the accident they retell, on looser clues", 3),
    ("src-scanned", "Could", "Pre-2005 scanned reports (the pipeline already reads page images)", 3),
    ("src-pandi", "Could", "P&amp;I club loss prevention publications", 4),
    ("src-copernicus", "Could", "Copernicus metocean data", 5),
    (None, "Won't", "Paris and Tokyo MoU detentions", None),
    (None, "Won't", "Other news and trade press", None),
    (None, "Won't", "Non-English reports via translation", None),
]

# (country, body, status, billable). Billable bodies are priced at the full
# and fast rates; the rest show their status only.
BODIES = [
    ("United Kingdom", "MAIB", "Done (Tranche 1)", False),
    ("United States", "NTSB", "Done (Tranche 1)", False),
    ("Australia", "ATSB", "To survey", True),
    ("Bahamas", "Bahamas Maritime Authority", "To survey", True),
    ("Belgium", "FPS Mobility, Shipping", "To survey, check English", True),
    ("Canada", "TSB", "To survey", True),
    ("Cyprus", "MAIC", "To survey", True),
    ("Denmark", "DMAIB", "To survey", True),
    ("Estonia", "Safety Investigation Bureau", "To survey", True),
    ("Finland", "Safety Investigation Authority", "To survey", True),
    ("France", "BEAmer", "To survey, check English", True),
    ("Germany", "BSU", "To survey, check English", True),
    ("Greece", "HBMCI", "To survey", True),
    ("Hong Kong", "MAIB HK", "To survey, summaries only", True),
    ("Isle of Man", "Ship Registry", "To survey, annual casualty reports", True),
    ("Japan", "JTSB", "To survey, check English", True),
    ("Malta", "MSIU", "To survey", True),
    ("Marshall Islands", "IRI", "To survey", True),
    ("Netherlands", "Dutch Safety Board", "To survey, check English", True),
    ("New Zealand", "TAIC", "To survey", True),
    ("Norway", "NSIA", "To survey", True),
    ("Singapore", "Ministry of Transport", "To survey", True),
    ("South Africa", "SAMSA", "To survey", True),
    ("Sweden", "SHK", "To survey", True),
    ("Turkey", "TSIC", "To survey, check English", True),
    ("Latvia", "TAIIB", "Won't (published in Latvian)", False),
]

CALIBRATION = [
    ("MVP", "19.5", "19.34", "on estimate"),
    ("P1 Foundation", "35", "50.5", "+44%"),
    ("P1.5 Foundation extension", "3", "4.1", "+37%"),
    ("US (NTSB) jurisdiction, first non-UK, generalised the pipeline", "n/a", "~12 working days", "sets the per-country seam"),
    ("NTSB corpus AI processing, 587 reports, including narrative-entity extraction", "n/a", "~$40-50", "AI processing cost is negligible"),
]

DECISIONS = [
    ("Survey each investigation body's site to replace the 5-day average with a per-body estimate", "Jack, Max"),
    ("Build or buy for chat features (open-source chat front end, OpenAI's hosted conversation state and tools)", "Max"),
    ("Confirm the MoSCoW priorities for chat features", "Adam"),
]

# Bundle contents: (label HTML, ids). A label of "chat:<priority>" sums that
# chat tier. Order within a bundle is by days, largest first.
BUNDLES = [
    ("Bronze", "Baseline plus every other Must", [
        ("Chat Musts (<a href=\"#chat\">section A</a>)", ["chat:Must"]),
        ("Public launch platform (<a href=\"#platform\">section C</a>)", [i[0] for i in PLATFORM]),
        ("Analyst tool: find what keeps recurring across all reports, with the supporting cases, and a first-draft outline of a write-up (<a href=\"#analyst\">section B</a>)", ["analyst-patterns"]),
        ("Analyst tool: proposed coding and similar cases for each report CHIRP receives (<a href=\"#analyst\">section B</a>)", ["analyst-coding"]),
        ("Ingest CHIRP Maritime’s own published reports, a new report format (<a href=\"#sources\">section D</a>)", ["src-chirp"]),
        ("Ingest MAIB Safety Digests, a new report format (<a href=\"#sources\">section D</a>)", ["src-digests"]),
        ("Link reports that describe the same accident, across countries and digests (<a href=\"#sources\">section D</a>)", ["src-link-official"]),
    ]),
    ("Silver", "Bronze plus every Should", [
        ("Ingest six short-form sources: IMO lessons, MARS, SAFETY4SEA, IMCA, USCG, Marine Safety Forum (<a href=\"#sources\">section D</a>)", ["src-imo-lessons", "src-mars", "src-s4s", "src-imca", "src-uscg", "src-msf"]),
        ("Dashboards filtered by vessel type, date, outcome and country (<a href=\"#analyst\">section B</a>)", ["analyst-dashboards"]),
        ("Link findings to the laws they relate to: UK/MCA, MLC, IMO conventions (<a href=\"#sources\">section D</a>)", ["src-legislation"]),
        ("Chat Shoulds (<a href=\"#chat\">section A</a>)", ["chat:Should"]),
        ("Ingest free-text accounts, such as a seafarer’s own description (<a href=\"#sources\">section D</a>)", ["src-freetext"]),
        ("Ingest investigation reports submitted to IMO GISIS, filling gaps for countries without their own site (<a href=\"#sources\">section D</a>)", ["src-gisis"]),
        ("Link short-form retellings to the accident report they came from (<a href=\"#sources\">section D</a>)", ["src-link-derivative"]),
    ]),
    ("Gold", "Silver plus every Could", [
        ("Chat Coulds (<a href=\"#chat\">section A</a>)", ["chat:Could"]),
        ("Add historical weather and sea state at each accident’s time and place, from Copernicus (<a href=\"#sources\">section D</a>)", ["src-copernicus"]),
        ("Ingest P&amp;I club loss prevention publications (<a href=\"#sources\">section D</a>)", ["src-pandi"]),
        ("Ingest scanned pre-2005 reports (<a href=\"#sources\">section D</a>)", ["src-scanned"]),
    ]),
]

# --- Helpers ---------------------------------------------------------------

ITEMS = {i[0]: i for i in CHAT + ANALYST + PLATFORM + SOURCES if i[0]}


def fmt_days(d):
    return f"{d:g}"


def money(x):
    return f"£{round(x):,}"


def pill(priority):
    cls = {"Must": "must", "Should": "should", "Could": "could", "Won't": "wont"}[priority]
    return f'<span class="pill pill--{cls}">{priority}</span>'


def days_for(ref):
    if ref.startswith("chat:"):
        tier = ref.split(":", 1)[1]
        return sum(i[3] for i in CHAT if i[1] == tier)
    return ITEMS[ref][3]


def billable_bodies():
    return [b for b in BODIES if b[3]]


def table(cls, heads, rows):
    """heads: list of (label, is_num). rows: list of (tr_class, [cells])
    where each cell is (html, is_num)."""
    out = ['        <div class="table-wrap">', f'          <table class="{cls}">',
           "            <thead>", "              <tr>"]
    for label, is_num in heads:
        attr = ' class="num"' if is_num else ""
        out.append(f"                <th{attr}>{label}</th>")
    out += ["              </tr>", "            </thead>", "            <tbody>"]
    for tr_cls, cells in rows:
        attr = f' class="{tr_cls}"' if tr_cls else ""
        out.append(f"              <tr{attr}>")
        for html, is_num in cells:
            cattr = ' class="num"' if is_num else ""
            out.append(f"                <td{cattr}>{html}</td>")
        out.append("              </tr>")
    out += ["            </tbody>", "          </table>", "        </div>"]
    return out


def section(sid, title, body, note=None):
    out = [f'      <section class="block" id="{sid}">', f"        <h2>{title}</h2>"]
    if note:
        out.append(f'        <p class="note">{note}</p>')
    return out + body + ["      </section>"]


def sorted_items(items):
    """Priority order, then largest first within a priority (stable)."""
    return sorted(items, key=lambda i: (PRIORITY_ORDER.index(i[1]), -(i[3] or 0)))


def items_table(items, label="Feature", tier_totals=True, extra_rows=()):
    rows = list(extra_rows)
    items = sorted_items(items)
    for idx, (_, pri, text, days) in enumerate(items):
        if days is None:
            rows.append((None, [(pill(pri), False), (text, False), ("n/a", True), ("n/a", True)]))
        else:
            rows.append((None, [(pill(pri), False), (text, False),
                                (fmt_days(days), True), (money(days * BUILD_RATE), True)]))
        last_of_tier = idx + 1 == len(items) or items[idx + 1][1] != pri
        if tier_totals and last_of_tier and pri != "Won't":
            total = sum(i[3] for i in items if i[1] == pri)
            rows.append(("total", [(f"<strong>{pri} total</strong>", False), ("", False),
                                   (f"<strong>{fmt_days(total)}</strong>", True),
                                   (f"<strong>{money(total * BUILD_RATE)}</strong>", True)]))
    return table("items", [("Priority", False), (label, False), ("Build days", True),
                           (BUILD_COST_HEAD, True)], rows)


# --- Sections --------------------------------------------------------------

def basis():
    rows = [
        (None, [("Day rate", False), ("£500", False)]),
        (None, [("Contingency", False), ("20% on build days", False)]),
        (None, [("Project management", False), ("25% on build days plus contingency", False)]),
        (None, [("Investigation bodies", False), ("Billed at £500 a day plus 20% contingency, no project management", False)]),
        (None, [("Excluded", False), ("Running costs (hosting and AI usage), paid by CHIRP", False)]),
    ]
    return section("basis", "Basis", table("kv", [("Item", False), ("Value", False)], rows))


def bundles():
    n = len(billable_bodies())
    base_days = n * BODY_DAYS_FULL
    base_cost = base_days * BODY_RATE
    running = base_cost

    def head(tier, sub, days, cost, running):
        key = tier.lower()
        return (f"bundle-head tier--{key}", [
            (f'<span class="medal medal--{key}"></span><strong>{tier}</strong><span class="sub">{sub}</span>', False),
            (f"<strong>{fmt_days(days)}</strong>", True),
            (f"<strong>{money(cost)}</strong>", True),
            (f"<strong>{money(running)}</strong>", True)])

    def item(label, days, cost):
        return ("bundle-item", [(label, False), (fmt_days(days), True), (money(cost), True), ("", True)])

    rows = [head("Baseline", "Official investigation bodies", base_days, base_cost, running),
            item(f'Ingest reports from {n} more national investigation bodies, full ingestion at {fmt_days(BODY_DAYS_FULL)} days each (<a href="#bodies">section E</a>) <span class="tag">{BODY_TAG}</span>',
                 base_days, base_cost)]
    for tier, sub, contents in BUNDLES:
        lines = [(label, sum(days_for(r) for r in refs)) for label, refs in contents]
        lines.sort(key=lambda l: -l[1])
        days = sum(d for _, d in lines)
        cost = days * BUILD_RATE
        running += cost
        rows.append(head(tier, sub, days, cost, running))
        rows += [item(label, d, d * BUILD_RATE) for label, d in lines]

    body = [
        '        <p class="note">Baseline is the official investigation bodies at full ingestion. Bronze adds every other Must, Silver adds every Should, Gold adds every Could. Each includes the one above it.</p>',
        '        <div class="callout">',
        '          <div class="callout__label">What the costs include</div>',
        "          <p>£500 a day plus <strong>20% contingency</strong> and <strong>25% project management</strong>. The investigation bodies are the exception: £500 a day plus 20% contingency, with no project management.</p>",
        "        </div>",
    ] + table("bundles", [("Bundle and contents", False), ("Build days", True), ("Cost", True), ("Running total", True)], rows)
    return section("bundles", "Bundles", body)


def sources():
    body_row = (None, [(pill("Must"), False),
                       (f'Official investigation bodies (<a href="#bodies">section E</a>) <span class="tag">{BODY_TAG}</span>', False),
                       (f"{fmt_days(BODY_DAYS_FULL)} each, {fmt_days(BODY_DAYS_FAST)} fast", True),
                       (f"{money(BODY_DAYS_FULL * BODY_RATE)} each, {money(BODY_DAYS_FAST * BODY_RATE)} fast", True)])
    return section("sources", "D. Sources", items_table(SOURCES, "Source", tier_totals=False, extra_rows=[body_row]))


def bodies():
    rows = []
    for country, body, status, billable in BODIES:
        if billable:
            rows.append((None, [(country, False), (body, False), (status, False),
                                (money(BODY_DAYS_FULL * BODY_RATE), True),
                                (money(BODY_DAYS_FAST * BODY_RATE), True)]))
        elif status.startswith("Done"):
            rows.append(("done", [(country, False), (body, False), (status, False), ("", True), ("", True)]))
        else:
            rows.append(("muted", [(country, False), (body, False), (status, False), ("n/a", True), ("n/a", True)]))
    n = len(billable_bodies())
    full, fast = n * BODY_DAYS_FULL, n * BODY_DAYS_FAST
    rows.append(("total", [(f"<strong>Total, {n} bodies</strong>", False), ("", False), ("", False),
                           (f"<strong>{money(full * BODY_RATE)}</strong><span class=\"sub\">{fmt_days(full)} days</span>", True),
                           (f"<strong>{money(fast * BODY_RATE)}</strong><span class=\"sub\">{fmt_days(fast)} days</span>", True)]))
    note = (f"Billed at £500 a day plus 20% contingency, with no project management. "
            f"<strong>Full ingestion</strong> ({fmt_days(BODY_DAYS_FULL)} days) encodes each jurisdiction’s rules. "
            f"<strong>Fast</strong> ({fmt_days(BODY_DAYS_FAST)} days) is quicker with less reliable data: halfway between full ingestion and ingesting the reports with no jurisdiction rules encoded. The Baseline bundle uses full ingestion.")
    heads = [("Country", False), ("Body", False), ("Status", False),
             (f"Full, {fmt_days(BODY_DAYS_FULL)} days", True), (f"Fast, {fmt_days(BODY_DAYS_FAST)} days", True)]
    return section("bodies", "E. Official investigation bodies", table("bodies", heads, rows), note=note)


def calibration():
    rows = [(None, [(p, False), (e, True), (a, True), (v, False)]) for p, e, a, v in CALIBRATION]
    heads = [("Phase", False), ("Estimate (days)", False), ("Actual (days)", False), ("Variance", False)]
    return section("calibration", "Calibration from Tranche 1", table("cal", heads, rows))


def decisions():
    rows = [(None, [(d, False), (o, False)]) for d, o in DECISIONS]
    return section("decisions", "Open decisions", table("kv", [("Decision", False), ("Owner", False)], rows))


def render():
    parts = [basis(), bundles(),
             section("chat", "A. Chat (P7)", items_table(CHAT)),
             section("analyst", "B. Analyst tools and dashboards", items_table(ANALYST, tier_totals=False)),
             section("platform", "C. Public launch platform (rest of P5)", items_table(PLATFORM, "Item")),
             sources(), bodies(), calibration(), decisions()]
    return "\n".join(line for part in parts for line in part)


def main():
    with open(OUT, encoding="utf-8") as f:
        html = f.read()
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not pattern.search(html):
        sys.exit(f"sentinels not found in {OUT}")
    html = pattern.sub(lambda _: f"{BEGIN}\n{render()}\n{END}", html)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

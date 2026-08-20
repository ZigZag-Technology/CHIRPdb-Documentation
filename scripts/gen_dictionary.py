#!/usr/bin/env python3
"""Render the DSG data dictionary markdown into the styled dictionary.html page.

Deterministic, dependency-free GFM-subset parser (headings, tables, lists,
paragraphs, blockquotes, inline code/bold/italic/links). Source-column cells get
colour-coded provenance badges; a `<!-- SHIELD-ICEBERG -->` sentinel expands to
the SHIELD iceberg diagram. Repo convention: plain hyphens, not em dashes.

Usage:
  python3 scripts/gen_dictionary.py <path/to/DATA_DICTIONARY.md> dataset/dictionary.html

The markdown source of truth lives in the CHIRPdb backend repo
(docs/dsg/DATA_DICTIONARY.md). Re-run this whenever it changes.
"""
import html
import re
import sys

SRC = sys.argv[1]
OUT = sys.argv[2]

with open(SRC) as f:
    _raw = f.read()

# The markdown lives beside a README.md in the backend repo, but the published
# dictionary page has no such sibling - point readers at the overview instead.
_raw = _raw.replace("the accompanying `README.md`",
                    "the [dataset overview](index.html)")

lines = _raw.split("\n")

# ---- inline formatting -----------------------------------------------------


def inline(text):
    # protect `code` spans as placeholders so their underscores/asterisks
    # never trip the bold/italic passes
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return "\x00%d\x00" % (len(codes) - 1)
    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)

    def restore(m):
        return "<code>%s</code>" % html.escape(codes[int(m.group(1))], quote=False)
    return re.sub(r"\x00(\d+)\x00", restore, text)


SRC_TOKENS = ["Source", "MAIB", "Pipeline",
              "AI-U", "AI-V", "System", "UNCLEAR"]
BADGE_CLASS = {"Source": "source", "MAIB": "maib", "Pipeline": "pipe",
               "AI-U": "aiu", "AI-V": "aiv", "System": "sys", "UNCLEAR": "unc"}


def _leading_token(text):
    return next((t for t in SRC_TOKENS
                 if text == t or text.startswith(t + " ") or text.startswith(t + " -")), None)


def source_cell(raw):
    """Badge the leading label(s); a slashed pair (Pipeline / AI-U) badges both."""
    rest = raw.strip()
    toks = []
    while True:
        tok = _leading_token(rest)
        if tok is None:
            break
        toks.append(tok)
        rest = rest[len(tok):].strip()
        if not rest.startswith("/"):
            break
        rest = rest[1:].strip()
    if not toks:
        return inline(raw.strip())
    badges = " / ".join('<span class="src src--%s">%s</span>' % (BADGE_CLASS[t], t)
                        for t in toks)
    return badges + (" " + inline(rest) if rest else "")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---- SHIELD iceberg diagram ------------------------------------------------
# Seeded taxonomy: 3 groups, 20 categories (name, code-count), rendered as an
# iceberg - acts at the tip, preconditions below the waterline, leadership deep.
_ICEBERG_TIERS = [
    ("tip", "1 / 4", "A &middot; ACTS", "Active failures - the visible tip", [
        ("Perception", 4), ("Planning &amp; Decision Making", 3),
        ("Intentional Deviation", 4), ("Response Execution", 6), ("Communicating", 2)]),
    ("mid", "2 / 4", "P &middot; PRECONDITIONS", "Conditions that set the stage - below the waterline", [
        ("Physical Environment", 9), ("Equipment &amp; Workplace", 6),
        ("Interpersonal Communication", 4), ("Team / Group", 6), ("Misperception", 4),
        ("Awareness", 7), ("Memory", 3), ("Mental Workload",
                                          4), ("Personal Factors", 7),
        ("Physiological Condition", 5), ("Drugs &amp; Nutrition", 3),
        ("Competence, Skills &amp; Capability", 4)]),
    ("deep", "3 / 4", "L &middot; OPERATIONAL LEADERSHIP", "Leadership decisions affecting safety - deeper still", [
        ("Personnel Leadership", 4), ("Operations Planning", 6), ("Task Leadership", 5)]),
    ("floor", "4 / 4", "O &middot; ORGANISATION", "Decisions and policies at organisational level - the base", [
        ("Culture", 2), ("Safety Management", 5), ("Resources", 6),
        ("Economy &amp; Business", 4)]),
]


def _build_iceberg():
    parts = ['<div class="iceberg" role="img" aria-label="SHIELD taxonomy iceberg: '
             'Acts above the waterline, Preconditions, Operational Leadership and Organisation below.">']
    for cls, frac, title, note, cats in _ICEBERG_TIERS:
        parts.append('<div class="ice ice--%s">' % cls)
        parts.append('<div class="ice__bar"><span class="ice__frac">%s</span>'
                     '<span class="ice__title">%s</span>'
                     '<span class="ice__note">%s</span></div>' % (frac, title, note))
        parts.append('<div class="ice__cats">')
        for name, cnt in cats:
            parts.append(
                '<span class="ice__cat">%s<span class="ice__n">%d</span></span>' % (name, cnt))
        parts.append('</div></div>')
    parts.append('</div>')
    return "".join(parts)


SHIELD_ICEBERG = _build_iceberg()

# ---- block parse -----------------------------------------------------------

out = []
toc = []            # (level, text, id) for ## and ###
i = 0
n = len(lines)


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


first_h1_skipped = False

while i < n:
    line = lines[i]

    # HTML-comment sentinels ----------------------------------------------
    if line.strip().startswith("<!--"):
        if line.strip() == "<!-- SHIELD-ICEBERG -->":
            out.append(SHIELD_ICEBERG)
        i += 1
        continue

    # tables ---------------------------------------------------------------
    if line.strip().startswith("|") and i + 1 < n and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
        header = split_row(line)
        i += 2  # skip header + separator
        rows = []
        while i < n and lines[i].strip().startswith("|"):
            rows.append(split_row(lines[i]))
            i += 1
        src_idx = next((k for k, h in enumerate(header)
                       if h.strip() == "Source"), None)
        t = ['<div class="dict-wrap"><table class="dict"><thead><tr>']
        for h in header:
            t.append("<th>%s</th>" % inline(h))
        t.append("</tr></thead><tbody>")
        for r in rows:
            t.append("<tr>")
            for k, c in enumerate(r):
                cell = source_cell(c) if k == src_idx else inline(c)
                t.append("<td>%s</td>" % cell)
            for _ in range(len(header) - len(r)):
                t.append("<td></td>")
            t.append("</tr>")
        t.append("</tbody></table></div>")
        out.append("".join(t))
        continue

    # headings -------------------------------------------------------------
    m = re.match(r"^(#{1,4})\s+(.*)$", line)
    if m:
        level = len(m.group(1))
        text = m.group(2).strip()
        if level == 1 and not first_h1_skipped:
            first_h1_skipped = True
            i += 1
            continue
        sid = slug(text)
        if level == 2:
            toc.append((2, text, sid))
            out.append('<h2 id="%s">%s</h2>' % (sid, inline(text)))
        elif level == 3:
            toc.append((3, text, sid))
            out.append('<h3 id="%s">%s</h3>' % (sid, inline(text)))
        else:
            out.append("<h4>%s</h4>" % inline(text))
        i += 1
        continue

    # horizontal rule ------------------------------------------------------
    if line.strip() == "---":
        out.append("<hr />")
        i += 1
        continue

    # blockquote -----------------------------------------------------------
    if line.strip().startswith(">"):
        buf = []
        while i < n and lines[i].strip().startswith(">"):
            buf.append(lines[i].strip()[1:].strip())
            i += 1
        out.append('<div class="callout callout--warn">%s</div>' %
                   inline(" ".join(buf).strip()))
        continue

    # lists (ordered / unordered, with nested continuation) ----------------
    if re.match(r"^\s*([-*]|\d+\.)\s+", line):
        ordered = bool(re.match(r"^\s*\d+\.\s+", line))
        tag = "ol" if ordered else "ul"
        items = []
        while i < n and (re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]) or (lines[i].startswith("   ") and lines[i].strip())):
            if re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i]))
            else:
                items[-1] += " " + lines[i].strip()
            i += 1
        out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" %
                   inline(x) for x in items), tag))
        continue

    # blank ----------------------------------------------------------------
    if not line.strip():
        i += 1
        continue

    # paragraph ------------------------------------------------------------
    buf = [line]
    i += 1
    while i < n and lines[i].strip() and not re.match(r"^(#{1,4}\s|\||>|\s*[-*]\s|\s*\d+\.\s|---|<!--)", lines[i]):
        buf.append(lines[i])
        i += 1
    out.append("<p>%s</p>" % inline(" ".join(x.strip() for x in buf)))

# ---- table-of-contents -----------------------------------------------------

toc_html = [
    '<nav class="toc"><div class="toc__title">Tables &amp; sections</div>']
for level, text, sid in toc:
    cls = "toc__h2" if level == 2 else "toc__h3"
    toc_html.append('<a class="%s" href="#%s">%s</a>' %
                    (cls, sid, html.escape(text)))
toc_html.append("</nav>")
toc_html = "".join(toc_html)

body = "\n".join(out)

PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>CHIRPdb Data Dictionary - DSG dataset</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="../css/chirp.css" />
    <style>
      :root { --navy-soft-tint: #eef2f8; }
      body { background: var(--bg-soft); color: var(--text); line-height: 1.6; }
      .intro-wide { background: var(--bg-card); border-bottom: 1px solid var(--border); }
      .intro-wide__inner { max-width: 1100px; margin: 0 auto; padding: 40px 24px 32px; }
      .eyebrow { font-size: 13px; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; color: var(--orange); margin-bottom: 12px; }
      .intro-wide h1 { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.2; margin-bottom: 14px; color: var(--navy-deep); }
      .lede { font-size: 16px; color: var(--text-soft); max-width: 760px; }
      .layout { max-width: 1180px; margin: 0 auto; padding: 8px 24px 80px; display: grid; grid-template-columns: 240px 1fr; gap: 40px; align-items: start; }
      .toc { position: sticky; top: 16px; font-size: 13px; max-height: calc(100vh - 32px); overflow: auto; padding: 16px 0; border-right: 1px solid var(--border); }
      .toc__title { font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: var(--text-mute); margin-bottom: 10px; }
      .toc a { display: block; text-decoration: none; color: var(--text-soft); padding: 2px 0; }
      .toc a:hover { color: var(--orange); }
      .toc__h2 { font-weight: 700; color: var(--navy-deep); margin-top: 12px; }
      .toc__h3 { padding-left: 12px !important; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }
      .content { min-width: 0; }
      .content h2 { font-size: 23px; font-weight: 800; letter-spacing: -0.015em; color: var(--navy-deep); margin: 44px 0 10px; padding-top: 22px; border-top: 1px solid var(--border); scroll-margin-top: 84px; }
      .content h3 { font-size: 17px; margin: 30px 0 6px; color: var(--navy); font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; scroll-margin-top: 84px; }
      .content h4 { font-size: 14px; margin: 18px 0 6px; color: var(--navy-deep); }
      .content p { margin-bottom: 12px; font-size: 15px; }
      .content ul, .content ol { margin: 0 0 14px 22px; font-size: 15px; }
      .content li { margin: 4px 0; }
      .content li > ul, .content li > ol { margin-top: 4px; }
      strong { color: var(--navy); }
      a { color: var(--orange-deep); }
      code { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 0.86em; background: var(--bg-soft); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; color: var(--navy); }
      hr { border: none; border-top: 1px solid var(--border); margin: 8px 0; }
      .dict-wrap { overflow-x: auto; margin: 12px 0 20px; border: 1px solid var(--border); border-radius: 10px; }
      table.dict { border-collapse: collapse; width: 100%; font-size: 13px; background: var(--bg-card); }
      table.dict th { text-align: left; font-size: 11px; letter-spacing: 0.5px; text-transform: uppercase; color: var(--text-soft); background: var(--bg-soft); padding: 8px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; position: sticky; top: 0; }
      table.dict td { padding: 7px 12px; border-bottom: 1px solid var(--border-soft); vertical-align: top; color: var(--text); }
      table.dict tr:last-child td { border-bottom: none; }
      table.dict td:first-child { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; color: var(--navy); font-weight: 600; white-space: nowrap; }
      .src { display: inline-block; font-size: 10.5px; font-weight: 700; letter-spacing: 0.4px; border-radius: 4px; padding: 1px 6px; white-space: nowrap; }
      .src--source { background: #e7eef7; color: #15375e; }
      .src--maib { background: #dde7f4; color: #0f2a4a; }
      .src--pipe { background: #e6f0ee; color: #1c5c50; }
      .src--aiu  { background: #fdeede; color: #b45f06; }
      .src--aiv  { background: #e4f3e7; color: #1f7a3d; }
      .src--sys  { background: #eceef2; color: #5a6478; }
      .src--unc  { background: #fbe6e6; color: #b3261e; }
      .callout { background: var(--navy-soft-tint); border-left: 4px solid var(--navy-soft); border-radius: 0 8px 8px 0; padding: 14px 18px; font-size: 14px; margin: 18px 0; }
      .callout--warn { background: var(--orange-soft); border-left-color: var(--orange); }
      .backlink { display: inline-block; margin: 20px 0 0; font-size: 14px; }
      /* SHIELD iceberg */
      .iceberg { margin: 20px 0 26px; border-radius: 12px; overflow: hidden; border: 1px solid var(--border); background: linear-gradient(180deg, #dbe6f2 0%, #b9d0e6 12%, #6f9dc4 24%, #2f6394 42%, #1a3f6b 66%, #0c2547 100%); }
      .ice { padding: 14px 16px 18px; }
      .ice--tip { background: linear-gradient(180deg, rgba(255,255,255,0.30), rgba(255,255,255,0.05)); }
      .ice--mid { border-top: 2px solid rgba(255,255,255,0.65); box-shadow: inset 0 3px 10px rgba(0,0,0,0.15); }
      .ice--floor .ice__cat { background: rgba(10,30,58,0.72); }
      .ice__bar { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; background: rgba(255,255,255,0.92); border-radius: 7px; padding: 8px 14px; margin-bottom: 12px; }
      .ice__frac { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; font-weight: 700; color: var(--text-mute); }
      .ice__title { font-size: 15px; font-weight: 800; letter-spacing: 0.02em; color: var(--navy-deep); }
      .ice__note { font-size: 12.5px; color: var(--text-soft); }
      .ice__cats { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
      .ice__cat { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 600; color: #fff; background: rgba(21,55,94,0.62); border: 1px solid rgba(255,255,255,0.28); border-radius: 6px; padding: 5px 10px; backdrop-filter: blur(2px); }
      .ice--tip .ice__cat { background: rgba(21,55,94,0.82); }
      .ice__n { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 10.5px; font-weight: 700; background: rgba(255,255,255,0.24); border-radius: 10px; padding: 0 6px; }
      @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .toc { position: static; border-right: none; border-bottom: 1px solid var(--border); max-height: none; } }
    </style>
  </head>
  <body>
    <header class="site-header">
      <div class="site-header__inner">
        <a href="../index.html" class="logo">
          <img src="https://chirp.co.uk/app/uploads/2024/07/chirp-logo-blue.svg" alt="CHIRP" class="logo__img" />
        </a>
        <div class="header__spacer"></div>
        <span class="header__tag">CHIRPdb Dataset &middot; DSG</span>
      </div>
    </header>
    <div class="intro-wide">
      <div class="intro-wide__inner">
        <p class="eyebrow">Alan Turing Institute &middot; Data Study Group</p>
        <h1>CHIRPdb Data Dictionary</h1>
        <p class="lede">Every table and column in the CHIRPdb database - with, for each field, whether it came from a source report (MAIB or NTSB), from the MAIB Data Portal spreadsheet, was derived by the pipeline, or was generated by AI, and whether a human has verified it. A reference to dip into, not read cover to cover. See the <a href="index.html">dataset overview</a> for orientation and the schema diagram.</p>
      </div>
    </div>
    <div class="layout">
      __TOC__
      <main class="content">
        __BODY__
        <a class="backlink" href="index.html">&larr; Back to the dataset overview</a>
      </main>
    </div>
  </body>
</html>
"""

PAGE = PAGE.replace("__TOC__", toc_html).replace("__BODY__", body)
# Repo convention: plain hyphens, not em dashes.
PAGE = PAGE.replace("—", "-")
with open(OUT, "w") as f:
    f.write(PAGE)
print("wrote", OUT, "-", len(toc), "toc entries")

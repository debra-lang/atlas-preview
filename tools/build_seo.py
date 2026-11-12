#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tinnitus Evidence — static SEO prerender.

Generates crawlable, canonical, self-contained HTML pages from the verified research database:
  /treatments/            directory landing + one page per treatment
  /trials/                directory landing + one page per registry trial
  /research/              directory landing + one page per research record
  /guides/                five evergreen evidence guides (database-driven, no invented claims)
  /claims/                Tinnitus Claims: Fact vs. Evidence (authored, human-approved data/claims.json; static pages)
  sitemap.xml             all canonical indexable URLs (production domain)
  robots-production.txt   the robots.txt to deploy AT LAUNCH (current robots.txt keeps the block)
  docs/redirect-map.md    old URL -> new URL documentation

Principles: content comes ONLY from data/*.json (no new research claims); loudness vs distress
always separate; conservative wording (a claim scrubber guards generated metadata); pages carry
self-referencing canonicals on https://tinnitusevidence.com/ and are usable with JavaScript
disabled (app.js only enhances chrome). Rerun after every data update (wired into the weekly
workflow) so static pages never drift from the database.
"""
import html, json, os, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD = "https://tinnitusevidence.com"
TODAY = date.today().isoformat()
YEAR = date.today().year

def load(rel):
    d = json.loads((ROOT / "data" / rel).read_text(encoding="utf-8"))
    return d

meta = load("meta.json")
cats = {c["id"]: c for c in load("categories.json")}
treatments = load("treatments.json")
if isinstance(treatments, dict): treatments = treatments["treatments"]
studies = load("studies.json")
if isinstance(studies, dict): studies = studies["studies"]
trials = load("trials.json")
rankings = load("rankings.json")
S = {s["id"]: s for s in studies}
T = {t["id"]: t for t in treatments}
RANK = {r["id"]: r for r in rankings.get("top", [])}
# reverse index: study id -> treatments citing it
CITED_BY = {}
for t in treatments:
    for sid in t.get("studies", []):
        CITED_BY.setdefault(sid, []).append(t["id"])

E = html.escape

# Evidence-status notices on treatment pages (provisional rating after a retraction notice; newer listed records not yet assessed; assessment older than a year).
# Without data/listings.json (listings off) only the provisional and out-of-date notices can appear, and only when their conditions hold today.
sys.path.insert(0, str(ROOT / "tools"))
import evidence_status
import guide_art
_LP = ROOT / "data" / "listings.json"
LISTINGS = json.loads(_LP.read_text(encoding="utf-8")) if _LP.exists() else None

# Claims: Fact vs. Evidence (data/claims.json is authored content, never produced by the research pipeline)
_CLP = ROOT / "data" / "claims.json"
CL = json.loads(_CLP.read_text(encoding="utf-8")) if _CLP.exists() else None
EU = json.loads((ROOT / "data" / "emerging-unproven.json").read_text(encoding="utf-8"))
EU_BY = {t["id"]: t for t in EU["T"]}
VCLS = {v["name"]: v["cls"] for v in CL["verdicts"]} if CL else {}
VSYM = {"supported": "\u2713", "partly": "\u25d0", "misleading": "!", "unsupported": "\u2715", "insufficient": "?"}
LASTMOD = {}   # per-URL <lastmod> overrides for the sitemap (claims pages carry their review date, not the build date)

def _long_date(iso):
    y, m, d = iso.split("-")
    months = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    return f"{int(d)} {months[int(m)]} {y}"

def vchip(name):
    cls = VCLS.get(name, "insufficient")
    return f'<span class="cl-chip cl-{cls}"><span aria-hidden="true">{VSYM[cls]}</span> {E(name)}</span>'


def claims_xlink(kind, tid):
    """Compact 'claim checks that mention this page' block for static treatment pages (empty when none)."""
    if not CL: return ""
    hits = [c for c in CL["claims"] if tid in c.get("related", {}).get(kind, [])]
    if not hits: return ""
    items = "".join(f'<li><a href="claims/{E(c["slug"])}/">{E(c["question"])}</a> {vchip(c["verdict"])}</li>' for c in hits)
    return (f'<section class="card sec-card cl-xlink" id="claim-checks"><h2>Claim checks that mention this treatment</h2><ul>{items}</ul>'
            '<p class="small muted">From <a href="claims/">Tinnitus Claims: Fact vs. Evidence</a>, which checks popular claims against the research. '
            'It does not change this treatment\u2019s evidence rating.</p></section>\n')
# Practical guides (Living with tinnitus): which treatment pages point to which guide. One map in data/patient-guides.json.
_PGP = ROOT / "data" / "patient-guides.json"
PGX = json.loads(_PGP.read_text(encoding="utf-8")) if _PGP.exists() else {}
def pg_href(ref):
    gid, _, anchor = ref.partition("#")
    base = "urgent/" if gid == "urgent" else PGX.get("guides", {}).get(gid, {}).get("path")
    assert base, f"practical-guide link to an unknown guide: {ref}"
    return base + ("#" + anchor if anchor else "")
def pg_title(ref):
    gid = ref.split("#")[0]
    return "When to get help quickly" if gid == "urgent" else PGX["guides"][gid]["title"]
def guide_xlink(tid):
    """Compact 'Practical help' block for static treatment pages (empty when no guide is linked)."""
    links = PGX.get("treatmentLinks", {}).get(tid)
    if not links: return ""
    items = "".join(f'<li><a href="{E(pg_href(r))}">{E(lbl)}</a>' + (f' <span class="small muted">· {E(pg_title(r))}</span>' if lbl != pg_title(r) else "") + "</li>"
                    for r, lbl in links)
    return (f'<section class="card sec-card pg-xlink" id="practical-help"><h2>Practical help</h2><ul>{items}</ul>'
            '<p class="small muted">From <a href="living/">Living with tinnitus</a>, our practical guides. They don\u2019t change this treatment\u2019s evidence rating.</p></section>\n')
RISKY = re.compile(r"\b(cure[sd]?|guaranteed|clinically proven|miracle|breakthrough cure|works for everyone)\b", re.I)

def scrub(text, fallback):
    """Generated metadata must never carry risky claim wording."""
    return fallback if RISKY.search(text or "") else text

def trunc(s, n=160):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    if len(s) <= n: return s
    return s[:n - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"

LV = {"none": "None shown", "limited": "Limited", "moderate": "Moderate", "strong": "Strong"}
def lv_label(o):
    """Outcome label. 'notMeasured' marks an outcome the human evidence never assessed (approved 26 Oct 2026): same rating level, clearer label."""
    return "Not measured" if o.get("notMeasured") else LV.get(o.get("level"), "Not assessed")
REP = {"none": "None yet", "same-group": "Same group/sponsor only", "limited-independent": "Limited independent",
       "strong-independent": "Strong independent", "conflicting": "Conflicting results"}
IND = {"primarily-independent": "Primarily independent", "mixed": "Mixed",
       "primarily-sponsor": "Primarily sponsor-supported", "unclear": "Independence unclear"}
SCORE_WORDS = {1: "Weak", 2: "Limited", 3: "Moderate", 4: "Good", 5: "Strong"}
TIERS = {1: "Tier 1 — strongest current evidence", 2: "Tier 2 — promising", 3: "Tier 3 — experimental/emerging",
         4: "Tier 4 — supportive/symptom-management (limited treatment-specific evidence)", 5: "Tier 5 — weak or unsupported"}

FOOTER_LINKS = [
    ("treatments/", "Tinnitus treatments"), ("trials/", "Clinical trials"), ("research/", "Research records"),
    ("ask/", "Ask Tinnitus Evidence"), ("research-questions/", "Research questions"),
    ("guides/tinnitus-treatments/", "What has the strongest evidence?"),
    ("guides/tinnitus-loudness-vs-distress/", "Loudness vs distress"),
    ("emerging-unproven/", "Emerging, experimental & unproven treatments"),
    ("claims/", "Tinnitus claims: fact vs. evidence"),
    ("research.html", "Latest tinnitus research updates"),
    ("about.html", "About & methodology"), ("about.html#limitations", "Research limitations"),
    ("about.html#corrections", "Corrections & editorial integrity"), ("about.html#disclaimer", "Medical disclaimer"),
    ("urgent/", "When to get help quickly"), ("support/", "Support & crisis lines"), ("living/", "Living with tinnitus"),
]

def footer_html(depth):
    up = "../" * depth
    links = " · ".join(f'<a href="{up}{h}">{E(n)}</a>' for h, n in FOOTER_LINKS)
    return f"""<footer class="footer-links"><div class="wrap"><p class="small">{links}</p>
<p class="small muted">Tinnitus Evidence is an educational evidence-navigation resource — not medical advice.
It does not diagnose, and never replaces an ENT physician, audiologist or other qualified professional.</p></div></footer>"""

def page(path_rel, title, desc, h1, crumbs, body, jsonld_extra=None, article=None, modified=None, main_cls="", extra_css="", crumb_extra=""):
    """path_rel like 'treatments/lenire/index.html' — canonical derives from it."""
    depth = path_rel.count("/")
    canon = PROD + "/" + path_rel.replace("index.html", "")
    up = "../" * depth
    crumb_html = ""
    crumb_ld = None
    if crumbs:
        items = []
        for i, (href, name) in enumerate(crumbs):
            if href is None:
                items.append(f'<span aria-current="page">{E(name)}</span>')
            else:
                # hrefs are site-root-relative; the page's <base> tag resolves them (never prepend up)
                items.append(f'<a href="{href if href else "./"}">{E(name)}</a>')
        crumb_html = '<nav class="crumbs small" aria-label="Breadcrumb" style="margin:14px 0 0">' + " › ".join(items) + "</nav>"
        if crumb_extra:   # phones: the page name (the title just below) gives way to a support link on the same row
            cur = f'<span class="crumb-cur"> › {items[-1]}</span>'
            crumb_html = f'<div class="crumb-row"><nav class="crumbs small" aria-label="Breadcrumb">{" › ".join(items[:-1])}{cur}</nav>{crumb_extra}</div>'
        crumb_ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name,
             **({"item": PROD + "/" + href} if href is not None else {})}
            for i, (href, name) in enumerate(crumbs)]}
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": title.split(" | ")[0],
           "url": canon, "description": desc, "isPartOf": {"@type": "WebSite", "name": "Tinnitus Evidence", "url": PROD + "/"},
           "dateModified": modified or TODAY}]
    if article:
        ld = [{"@context": "https://schema.org", "@type": "Article", "headline": article["headline"],
               "url": canon, "description": desc, "datePublished": article.get("published", TODAY), "dateModified": article.get("modified", TODAY),
               "author": {"@type": "Organization", "name": "Tinnitus Evidence"},
               "publisher": {"@type": "Organization", "name": "Tinnitus Evidence", "url": PROD + "/"}}]
    if article and article.get("published", TODAY) is None:
        ld[0].pop("datePublished", None)   # unreleased page: never represent a build date as a publication date
    if crumb_ld: ld.append(crumb_ld)
    if jsonld_extra: ld.append(jsonld_extra)
    ld_html = "\n".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
    sp = re.findall(r'<!--sprite:([a-z0-9 -]+)-->', body)   # icons used on the page, as one hidden SVG sprite
    body_pre = guide_art.sprite(sorted({n for x in sp for n in x.split()})) if sp else ""
    body = re.sub(r'<!--sprite:[a-z0-9 -]+-->', "", body)
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<base href="{up if up else './'}">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{canon}">
<meta property="og:site_name" content="Tinnitus Evidence">
<meta property="og:type" content="website">
<meta property="og:title" content="{E(title.split(' | ')[0])}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{canon}">
<meta property="og:image" content="{PROD}/icons/share.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{E(title.split(' | ')[0])}">
<meta name="twitter:description" content="{E(desc)}">
<meta name="twitter:image" content="{PROD}/icons/share.png">
<meta name="theme-color" content="#0c1120">
<link rel="icon" href="icons/icon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="css/styles.css">{extra_css}
{ld_html}
</head>
<body data-page="">{body_pre}
<a class="skip-link" href="#content">Skip to content</a>
<main id="content" class="wrap prose{main_cls}">
{crumb_html}
<h1 style="margin-top:14px">{h1}</h1>
{body}
</main>
{footer_html(0)}
<script src="js/app.js"></script>
</body>
</html>"""
    out = ROOT / path_rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return canon

def study_block(sid):
    s = S.get(sid)
    if not s: return ""
    res = s.get("results", {})
    links = []
    if s.get("pmid"): links.append(f'<a href="https://pubmed.ncbi.nlm.nih.gov/{E(str(s["pmid"]))}/" rel="noopener">PubMed {E(str(s["pmid"]))}</a>')
    if s.get("doi"): links.append(f'<a href="https://doi.org/{E(s["doi"])}" rel="noopener">DOI {E(s["doi"])}</a>')
    if s.get("url") and not s.get("pmid") and not s.get("doi"): links.append(f'<a href="{E(s["url"])}" rel="noopener">Source</a>')
    integ = ""
    if s.get("integrityNotice"):
        integ = f'<p class="small"><strong>⚠️ Research-integrity notice:</strong> {E(s["integrityNotice"].get("text", ""))}</p>'
    return f"""<section>
<h3><a href="research/{E(s['id'])}/">{E(s['title'])}</a></h3>
{integ}
<p class="small muted">{E(s.get('authors', ''))} · {E(str(s.get('journal', '')))} · {E(str(s.get('year', '')))}{(' · N=' + E(str(s['n']))) if s.get('n') else ''}{(' · ' + E(s['design'])) if s.get('design') else ''}</p>
<p>{E(res.get('summary', ''))}</p>
{f'<p class="small muted">{E(res["detail"])}</p>' if res.get('detail') else ''}
<p class="small">{' · '.join(links)}</p>
</section>"""

# ---------------- treatment pages ----------------
sitemap_urls = [PROD + "/", PROD + "/research.html", PROD + "/about.html", PROD + "/institutions.html",
                PROD + "/emerging-unproven/"]   # hand-authored page (generated by unproven/migrate/make_prod.py); published 2026-09-26

def t_title(t):
    n = t["name"]
    base = f"{n}: Research & Evidence" if "tinnitus" in n.lower() else f"{n} for Tinnitus: Research, Results & Evidence"
    return base + " | Tinnitus Evidence"

def t_h1(t):
    n = t["name"]
    return E(f"{n}: What Does the Evidence Show?" if "tinnitus" in n.lower() else f"{n} for Tinnitus: What Does the Evidence Show?")

for t in treatments:
    tid = t["id"]
    cat = cats.get(t.get("category"), {})
    av = t.get("availability", {})
    reg = t.get("regulatory", {})
    lo, di = t.get("loudness", {}), t.get("distress", {})
    score = t.get("evidenceScore", 0)
    desc = trunc(scrub(
        f"Current evidence for {t['name']} and tinnitus: {t.get('oneLiner', '')} Loudness vs distress outcomes, replication, safety, limitations and availability.",
        f"Review the clinical evidence for {t['name']} and tinnitus: study results, loudness vs distress outcomes, replication, safety, limitations and availability."), 165)
    related = [x for x in treatments if x.get("category") == t.get("category") and x["id"] != tid][:5]
    rel_trials = [x for x in trials if x.get("treatment") == tid]
    rk = RANK.get(tid)
    warn = ""
    if t.get("scopeNote"):
        _sn = t["scopeNote"]
        warn += ('<div class="notice" role="note" aria-label="Scope of this assessment"><strong>Scope of this assessment.</strong> ' + E(_sn["text"]) +
                 (' <span class="small">Sources: ' + " · ".join(f'<a href="{E(l[1])}" rel="noopener">{E(l[0])}</a>' for l in _sn.get("links", [])) + "</span>" if _sn.get("links") else "") + "</div>")
    if t.get("narrowPopulation"):
        warn += f'<div class="notice">🎯 <strong>Applies only to a specific diagnosed tinnitus population.</strong> {E(t.get("narrowNote", ""))}</div>'
    if t.get("underReevaluation"):
        warn += f'<div class="notice">🔎 <strong>Evidence rating under re-evaluation.</strong> {E(t["underReevaluation"].get("reason", ""))}</div>'
    warn += evidence_status.status_html(t, S, LISTINGS)
    # Section order = the site-wide treatment-page hierarchy: what it is → evidence → loudness →
    # distress → strength → key studies → limitations → replication → safety / regulatory /
    # availability → related → methodology & citations. Wording unchanged.
    toc = [("evidence", "Current evidence"), ("loud", "🔉 Loudness"), ("distress", "🧠 Distress"), ("strength", "How strong?"),
           ("studies", "Key studies"), ("limits", "Limitations"), ("replication", "Replication"), ("safety", "Safety"),
           ("availability", "Availability")]
    toc_html = '<nav class="toc" aria-label="On this page">' + "".join(f'<a href="treatments/{E(tid)}/#{a}">{E(l)}</a>' for a, l in toc) + "</nav>"
    body = f"""
<p class="small muted">{E(cat.get('name', ''))}{f" · Ranked #{rk['rank']} on our Top 10 ({E(rk.get('stability', ''))})" if rk else ''}</p>
{warn}
{toc_html}
<section class="card sec-card" id="evidence">
<h2>Current evidence</h2>
<p><strong>{E(t.get('oneLiner', ''))}</strong></p>
<p>Evidence strength: <strong>{SCORE_WORDS.get(score, '?')} ({score}/5)</strong> · {E(TIERS.get(t.get('tier'), ''))} ·
Evidence independence: <strong>{E(IND.get(t.get('independence'), 'Not assessed'))}</strong>.</p>
<p>{E(t.get('whatItIs', ''))}</p>
</section>
<section class="card sec-card sec-indigo" id="outcomes"><h2>Did tinnitus loudness or distress improve?</h2>
<div class="duo ld-full">
<div class="cell" id="loud"><div class="k">🔉 Did tinnitus loudness improve?</div>
<div class="v lv-{E(lo.get('level', 'none'))}">{E(lv_label(lo))}.</div><p class="small">{E(lo.get('summary', ''))}</p></div>
<div class="cell" id="distress"><div class="k">🧠 Did tinnitus distress improve?</div>
<div class="v lv-{E(di.get('level', 'none'))}">{E(lv_label(di))}.</div><p class="small">{E(di.get('summary', ''))}</p></div>
</div>
<p class="small muted">Loudness means the tinnitus percept itself became quieter (psychoacoustic matching or loudness
ratings). Distress means questionnaire scores such as THI/TFI, sleep, anxiety or quality of life improved — the sound
may be unchanged. A THI/TFI improvement is never evidence the tinnitus got quieter.</p></section>
<section class="card sec-card" id="strength"><h2>How strong is the evidence?</h2>
<p>{E(t.get('scoreRationale', ''))}</p></section>
<details class="sec" id="studies"><summary>What the studies found <span class="small">{len(t.get('studies', []))} tracked</span></summary>
{''.join(study_block(sid) for sid in t.get('studies', [])) or '<p class="muted">No individual study records yet.</p>'}</details>
<section class="card sec-card" id="limits"><h2>What are the limitations?</h2>
<ul>{''.join(f'<li>{E(l)}</li>' for l in t.get('limitations', []))}</ul>
{f'<p><strong>Conflicts of interest:</strong> {E(t["conflicts"])}</p>' if t.get('conflicts') else ''}</section>
<section class="card sec-card" id="replication"><h2>Has the result been independently replicated?</h2>
<p><strong>{E(REP.get(t.get('replication'), 'Not assessed'))}.</strong> {E(t.get('replicationNote', ''))}</p>
{f'<p class="small muted">Independence: {E(t.get("independenceNote", ""))}</p>' if t.get('independenceNote') else ''}</section>
<section class="card sec-card" id="safety"><h2>What should patients know about safety?</h2>
<p><strong>Safety evidence: {E((t.get('safetyLevel') or 'not yet assessed').capitalize())}.</strong> {E(t.get('safety', ''))}</p>
<h3 id="availability">Is it available?</h3>
<p><strong>Regulatory status:</strong> {E(reg.get('status', ''))}. {E(reg.get('detail', ''))}</p>
<p><strong>Availability:</strong> {E(av.get('usa', ''))}{(' · Europe: ' + E(av['europe'])) if av.get('europe') else ''}{(' · Cost (approx.): ' + E(av['cost'])) if av.get('cost') else ''}</p></section>
{f'''<details class="sec"><summary>Related clinical trials <span class="small">{len(rel_trials)}</span></summary><ul>{''.join(f'<li><a href="trials/{E(x["nctId"])}/">{E(x["title"])}</a> — {E(x.get("status", ""))}</li>' for x in rel_trials)}</ul>
<p class="small muted">Tracked trials are research in progress, not recommended treatments.</p></details>''' if rel_trials else ''}
{f'''<details class="sec"><summary>Related treatments <span class="small">{len(related)}</span></summary><ul>{''.join(f'<li><a href="treatments/{E(x["id"])}/">{E(x["name"])}</a> — {E(trunc(x.get("oneLiner", ""), 110))}</li>' for x in related)}</ul></details>''' if related else ''}
{guide_xlink(tid)}{claims_xlink("treatments", tid)}<p class="small muted">Evidence last reviewed: {E(t.get('lastReviewed', ''))} · Evidence included through: {E(t.get('evidenceThrough', ''))} ·
Confidence: {E(t.get('confidence', ''))}. <a href="treatment.html?id={E(tid)}">Open the interactive evidence profile</a> ·
<a href="about.html#methodology">How we rate evidence</a>.</p>
<p class="small muted">This page summarizes published research for education. It is not medical advice; it cannot say
what will work for any individual. Discuss treatment decisions with a qualified clinician.</p>"""
    canon = page(f"treatments/{tid}/index.html", t_title(t), desc, t_h1(t),
                 [("", "Home"), ("treatments/", "Treatments"), (None, t["name"])], body)
    sitemap_urls.append(canon)

# ---------------- treatments directory ----------------
by_tier = {}
for t in treatments: by_tier.setdefault(t.get("tier", 5), []).append(t)
dir_body = f"""
<p class="lead">Tinnitus treatments can affect different outcomes — <strong>tinnitus loudness</strong> (the sound itself),
<strong>tinnitus distress and severity</strong> (THI/TFI questionnaires), sleep, anxiety and quality of life, underlying
conditions, or hearing itself. Most treatments with good evidence improve distress rather than loudness, which is why every
treatment here is rated on <strong>loudness and distress separately</strong> — we never blur the two.</p>
<p>Currently tracking <strong>{len(treatments)} treatments</strong> across {len(cats)} categories, each with evidence scores,
replication and independence status, safety, availability and full primary-source citations.
<a href="treatments.html">Prefer filters and search? Open the interactive browser.</a></p>
""" + "".join(
    f"""<section><h2>{E(TIERS[tier])}</h2><ul>""" +
    "".join(f'<li><a href="treatments/{E(t["id"])}/">{E(t["name"])}</a> — {E(trunc(scrub(t.get("oneLiner", ""), "see the evidence page"), 140))}</li>'
            for t in sorted(ts, key=lambda x: -x.get("evidenceScore", 0))) + "</ul></section>"
    for tier, ts in sorted(by_tier.items()))
canon = page("treatments/index.html",
             "Tinnitus Treatments: Compare the Evidence | Tinnitus Evidence",
             "Compare the clinical evidence for major tinnitus treatments and emerging approaches — evidence scores, loudness vs distress outcomes, replication, safety, availability and primary sources.",
             "Tinnitus Treatments: What Does the Evidence Show?",
             [("", "Home"), (None, "Treatments")], dir_body)
sitemap_urls.append(canon)

# ---------------- trial pages ----------------
for x in trials:
    nct = x["nctId"]
    t = T.get(x.get("treatment"))
    desc = trunc(f"{x['title']} — {x.get('phase', '')}, status: {x.get('status', '')}. Sponsor: {x.get('sponsor', '')}. Registry record {nct} tracked by Tinnitus Evidence.", 165)
    body = f"""
<section><h2>Trial details</h2>
<ul>
<li><strong>Registry identifier:</strong> <a href="https://clinicaltrials.gov/study/{E(nct)}" rel="noopener">{E(nct)} on ClinicalTrials.gov</a></li>
<li><strong>Phase:</strong> {E(str(x.get('phase', '—')))}</li>
<li><strong>Status:</strong> {E(str(x.get('status', '—')))}</li>
<li><strong>Sponsor:</strong> {E(str(x.get('sponsor', '—')))}</li>
<li><strong>Planned enrollment:</strong> {E(str(x.get('n', '—')))}</li>
<li><strong>Estimated completion:</strong> {E(str(x.get('completionEst', '—')))}</li>
{f'<li><strong>Country:</strong> {E(str(x["country"]))}</li>' if x.get('country') else ''}
</ul></section>
<section><h2>Why this trial matters</h2><p>{E(x.get('whyItMatters', ''))}</p></section>
{f'<section><h2>Related treatment evidence</h2><p><a href="treatments/{E(t["id"])}/">See the current evidence for {E(t["name"])}</a>.</p></section>' if t else ''}
<p class="small muted">Trial statuses are verified against the ClinicalTrials.gov registry by our twice-monthly automated check.
A tracked trial is research in progress — inclusion is not a treatment recommendation, and only the study team can
determine eligibility.</p>"""
    canon = page(f"trials/{nct}/index.html",
                 trunc(f"{x['title']} ({nct})", 60) + " | Tinnitus Clinical Trial",
                 desc, E(x["title"]),
                 [("", "Home"), ("trials/", "Clinical trials"), (None, nct)], body)
    sitemap_urls.append(canon)

trials_body = f"""
<p class="lead">Tinnitus Evidence tracks <strong>{len(trials)} registered clinical trials</strong> — current drug,
device and therapy studies that may add to or change the evidence picture. Statuses are verified directly against
the ClinicalTrials.gov registry twice a month; tracked trials are research in progress, not recommended treatments.</p>
<p><a href="trials.html">Prefer filters and the watch feature? Open the interactive trials browser.</a></p>
<ul>""" + "".join(
    f'<li><a href="trials/{E(x["nctId"])}/">{E(x["title"])}</a> — {E(str(x.get("phase", "")))} · {E(str(x.get("status", "")))}</li>'
    for x in trials) + "</ul>"
canon = page("trials/index.html",
             "Tinnitus Clinical Trials: Current and Emerging Research | Tinnitus Evidence",
             "The registered clinical trials that could change tinnitus treatment — drug, device and therapy studies with phases, statuses and registry links, verified twice a month.",
             "Current Tinnitus Clinical Trials", [("", "Home"), (None, "Clinical trials")], trials_body)
sitemap_urls.append(canon)

# ---------------- research record pages ----------------
for s in studies:
    sid = s["id"]
    res = s.get("results", {})
    cited = [T[tid] for tid in CITED_BY.get(sid, []) if tid in T]
    links = []
    if s.get("pmid"): links.append(f'<li><a href="https://pubmed.ncbi.nlm.nih.gov/{E(str(s["pmid"]))}/" rel="noopener">PubMed record ({E(str(s["pmid"]))})</a></li>')
    if s.get("doi"): links.append(f'<li><a href="https://doi.org/{E(s["doi"])}" rel="noopener">Publisher (DOI {E(s["doi"])})</a></li>')
    if s.get("url"): links.append(f'<li><a href="{E(s["url"])}" rel="noopener">Source link</a></li>')
    hist = s.get("history", [])
    corr = [h for h in hist if "correct" in (h.get("change", "") + h.get("reason", "")).lower()]
    integ = ""
    if s.get("integrityNotice"):
        integ = f'<div class="notice">⚠️ <strong>Research-integrity notice ({E(s["integrityNotice"]["severity"])}).</strong> {E(s["integrityNotice"].get("text", ""))}</div>'
    desc = trunc(scrub(f"{s['title']} ({s.get('year', '')}): {res.get('summary', '')}",
                       f"Verified research record: {s['title']} ({s.get('year', '')}). Design, results, limitations and primary-source links."), 165)
    body = f"""
{integ}
<section><h2>Record details</h2>
<ul>
<li><strong>Authors:</strong> {E(s.get('authors', '—'))}</li>
<li><strong>Journal / source:</strong> {E(str(s.get('journal', '—')))} ({E(str(s.get('year', '')))})</li>
<li><strong>Design:</strong> {E(s.get('design', '—'))}</li>
<li><strong>Sample:</strong> {E(str(s.get('n', '—')))}</li>
<li><strong>Primary endpoint:</strong> {E(s.get('primaryOutcome', '—'))}</li>
<li><strong>Randomized:</strong> {'Yes' if s.get('randomized') else 'No'} · <strong>Sham/placebo-controlled:</strong> {'Yes' if s.get('sham') else 'No'} · <strong>Independent of the manufacturer:</strong> {'Yes' if s.get('independent') else 'No' + (' (' + E(s['independenceTag'].lower()) + '; see Funding / conflicts)' if s.get('independenceTag') else '')}</li>
</ul></section>
<section><h2>What this research found</h2>
<p>{E(res.get('summary', ''))}</p>
{f'<p class="small muted">{E(res["detail"])}</p>' if res.get('detail') else ''}</section>
<section><h2>Limitations and conflicts of interest</h2>
<p>{E(s.get('limitations') or 'See the record summary above.')}</p>
<p><strong>Funding / conflicts:</strong> {E(s.get('coi', '—'))}</p></section>
{f'''<section><h2>Corrections to this record</h2><ul>{''.join(f'<li>{E(h.get("date", ""))}: {E(h.get("change", ""))}</li>' for h in corr)}</ul></section>''' if corr else ''}
<section><h2>Primary sources</h2><ul>{''.join(links) or '<li>No public identifier exists for this record (labeled company/registry-only material).</li>'}</ul></section>
{f'''<section><h2>Used as evidence for</h2><ul>{''.join(f'<li><a href="treatments/{E(t["id"])}/">{E(t["name"])}</a></li>' for t in cited)}</ul></section>''' if cited else '<p class="small muted">Context record — informs the platform without serving as treatment evidence.</p>'}
<p class="small muted">This is an original summary from the Tinnitus Evidence verified database, checked against the
primary source — not a reproduction of the publisher's abstract.</p>"""
    canon = page(f"research/{sid}/index.html",
                 trunc(f"{s['title']} ({s.get('year', '')})", 62) + " | Research Record",
                 desc, E(s["title"]),
                 [("", "Home"), ("research/", "Research records"), (None, trunc(s["title"], 40))], body)
    sitemap_urls.append(canon)

def _rec_group(s):
    """Deterministic grouping from STRUCTURED fields only (design string + linkage), never guessed from titles."""
    d = (s.get("design") or "").lower()
    res = ((s.get("results") or {}).get("summary") or "").lower()
    if "guideline" in d: return "Clinical guidelines"
    if "cochrane" in d or "systematic review" in d or "meta-analysis" in d or "umbrella" in d or "pooled" in d:
        return "Systematic reviews & meta-analyses"
    if "measurement-standard" in d or "consensus criteria" in d or "epidemiology" in d or "context record" in d or "cross-sectional population" in d:
        return "Measurement standards & context records"
    if "company" in d or "program" in d or "registry" in d or "announcement" in (s.get("journal") or "").lower():
        return "Company programs & registry records"
    if s.get("randomized") or "rct" in d or "randomi" in d or "controlled" in d or "phase" in d or "crossover" in d:
        return "Randomized & controlled trials"
    return "Observational & other designs"
_ORDER = ["Randomized & controlled trials", "Systematic reviews & meta-analyses",
          "Clinical guidelines", "Company programs & registry records", "Measurement standards & context records", "Observational & other designs"]
_groups = {}
for s in studies: _groups.setdefault(_rec_group(s), []).append(s)
res_dir = """
<p class="lead">Every research record in the Tinnitus Evidence database — trials, systematic reviews, guidelines and
regulatory records — each verified against its primary source, with design, results, limitations and conflicts of
interest. Negative and failed results are first-class records here, not footnotes.</p>
<nav class="small muted" aria-label="Record types">Jump to: """ + " · ".join(
    f'<a href="research/#{E(g.lower().replace(" ", "-").replace("&", "and"))}">{E(g)}</a> ({len(_groups[g])})'
    for g in _ORDER if g in _groups) + "</nav>" + "".join(
    f'<section id="{E(g.lower().replace(" ", "-").replace("&", "and"))}"><h2>{E(g)} ({len(_groups[g])})</h2><ul>' +
    "".join(f'<li><a href="research/{E(s["id"])}/">{E(s["title"])}</a> <span class="muted">({E(str(s.get("year", "")))})</span></li>'
            for s in sorted(_groups[g], key=lambda x: (-int(x.get("year") or 0), x["id"]))) + "</ul></section>"
    for g in _ORDER if g in _groups)
canon = page("research/index.html",
             f"Tinnitus Research Records: {len(studies)} Verified Studies & Reviews | Tinnitus Evidence",
             "Browse every verified research record behind Tinnitus Evidence — trials, systematic reviews, guidelines and regulatory records with results, limitations and primary sources.",
             "The Research Behind Tinnitus Evidence", [("", "Home"), (None, "Research records")], res_dir)
sitemap_urls.append(canon)

# ---------------- guides ----------------
def guide(slug, title, h1, desc, body, extra_css="", main_cls=""):
    canon = page(f"guides/{slug}/index.html", title, desc, h1,
                 [("", "Home"), ("guides/", "Guides"), (None, h1.split(":")[0])], body,
                 article={"headline": h1, "published": "2026-09-04"}, extra_css=extra_css, main_cls=main_cls)
    sitemap_urls.append(canon)

top5 = [(r, T[r["id"]]) for r in rankings.get("top", [])[:5] if r["id"] in T]
def evidence_brief_body():
    """Approved 26 Oct 2026: plain-language treatment cards. Ranks, ratings, tiers, stability and caveats are read from
    data/rankings.json and data/treatments.json; nothing here sets or changes a rating."""
    ic = guide_art.icon; used = {"research", "speaker-low", "heart", "spark", "waves", "check-list", "tag-off", "focus"}
    SEG = {"none": 0, "limited": 1, "moderate": 2, "strong": 3}
    EW = {1: "Weak", 2: "Limited", 3: "Moderate", 4: "Strong", 5: "Very strong"}
    TIERW = {1: "Strongest evidence", 2: "Promising", 3: "Experimental", 4: "Supportive", 5: "Weak / unsupported"}
    POS = {"stable-top": "Stable position", "stable": "Stable position", "weighting-sensitive": "Position could change"}
    def meter(kind, o):
        segs = "".join(f'<i class="{"on" if i < SEG.get(o["level"], 0) else ""}"></i>' for i in range(3))
        q = ("Quieter sound?", "speaker-low", "Loudness") if kind == "l" else ("Less bothered?", "heart", "Distress")
        lvl = "nm" if o.get("notMeasured") else o["level"]
        return (f'<div class="v-m v-{kind}"><span class="v-mk">{ic(q[1])}{q[2]}</span><span class="v-mq">{q[0]}</span>'
                f'<span class="v-mv lv-{E(lvl)}"><span class="v-segs" aria-hidden="true">{segs}</span>{E(lv_label(o))}</span></div>')
    def card(r, t, featured):
        href = f'treatments/{E(r["id"])}/'; avail = t.get("availability", {}).get("availableNow"); sc = t["evidenceScore"]
        dots = "".join(f'<i class="{"on" if i <= sc else ""}"></i>' for i in range(1, 6))
        pos = POS.get(r.get("stability"), "")
        note = f'<p class="v-posnote">{E(r["stabilityNote"])}</p>' if featured and r.get("stabilityNote") else ""
        why = E(scrub(r.get("whyPlain", t.get("oneLiner", "")), t.get("oneLiner", "")))
        return (f'<li class="v-card{" v-feat" if featured else ""}"><div class="v-top"><span class="v-rank">Ranked #{r["rank"]}</span>'
                + (f'<span class="v-pos v-{"ok" if pos.startswith("Stable") else "move"}">{pos}</span>' if pos else "")
                + f'<span class="v-av v-{"yes" if avail else "no"}">{"Available now" if avail else "Not currently available"}</span></div>'
                f'<h3><a href="{href}">{E(t["name"])}</a></h3>{note}<p class="v-why">{why}</p>'
                f'<div class="v-meters">{meter("l", t["loudness"])}{meter("d", t["distress"])}</div>'
                f'<p class="v-sure"><span class="v-sk">How sure are we?</span><span class="emeter v-dots" role="img" aria-label="Evidence score {sc} out of 5, {EW[sc]}">{dots}</span>'
                f'<span class="v-sv">{EW[sc]} ({sc}/5) · {TIERW[t["tier"]]}</span></p>'
                + (f'<p class="v-for"><span class="v-sk">Best suited for</span>{E(t["bestSuitedFor"])}</p>' if t.get("bestSuitedFor") else "") + "</li>")
    principles = ["We rate loudness and distress separately (most good evidence is for distress)", "Require independent replication before calling anything established",
                  "Show who funded the research", "And label ranking positions that are sensitive to how you weigh the evidence"]
    return (f"""
<nav class="e-start" aria-label="Start here"><span class="e-start-h">Start here</span><ul>
<li><a href="guides/tinnitus-loudness-vs-distress/">Loudness vs distress</a><span class="small muted">: how to read our ratings</span></li>
<li><a href="treatments.html?flag=avail">Treatments you can try now</a><span class="small muted">, with clear evidence labels</span></li>
<li><a href="trials.html">Clinical trials to watch</a></li>
<li><a href="claims/">Check a claim</a><span class="small muted"> before you spend money</span></li></ul>
<p class="small">Looking for practical help rather than research? <a href="living/">Living with tinnitus</a></p></nav>
<section class="v-answer" aria-labelledby="v-ans-h"><p class="v-kicker">{ic("research")}Key message</p><h2 id="v-ans-h">The short answer</h2>
<p class="v-lead"><strong>Cognitive behavioral therapy (CBT) has the strongest evidence of any tinnitus treatment</strong> — for reducing
distress and improving quality of life, not for making the sound quieter. No treatment has been established as a universal
cure for tinnitus. Beyond CBT, the best-supported options depend on your situation — hearing loss, sleep problems, and
tinnitus subtype all change the picture.</p></section>
<section class="v-two" aria-labelledby="v-two-h"><h2 id="v-two-h">Two different questions</h2><div class="v-two-grid">
<div class="v-q v-l"><span class="v-qi">{ic("speaker-low")}</span><div><p class="v-qk">Loudness</p><p class="v-qq">Did the sound itself get quieter?</p></div></div>
<div class="v-q v-d"><span class="v-qi">{ic("heart")}</span><div><p class="v-qk">Distress</p><p class="v-qq">Did it bother people less, even if the sound stayed?</p></div></div></div></section>
<section class="v-top5" aria-labelledby="v-top-h"><h2 id="v-top-h">The current top-ranked treatments</h2>
<p class="v-order">{ic("spark")}<span>{E(rankings.get('uncertaintyNote', ''))}</span></p>
<ol class="v-cards">{''.join(card(r, t, i == 0) for i, (r, t) in enumerate(top5))}</ol>
<p class="v-all"><a href="treatments/">See all {len(treatments)} treatments ranked by evidence tier</a> — including the ones that have
failed their trials, because negative evidence protects people from wasting money and hope.</p></section>
<section class="v-how" aria-labelledby="v-how-h"><h2 id="v-how-h">How to read "strongest evidence"</h2><ul class="v-principles">"""
      + "".join(f'<li><span class="c-ic">{ic(n)}</span><span>{E(p)}</span></li>' for p, n in zip(principles, ["waves", "check-list", "tag-off", "focus"]))
      + f"""</ul><p><a href="about.html#methodology">Read the full methodology</a>.</p></section><!--sprite:{" ".join(sorted(used))}-->""")
guide("tinnitus-treatments",
      "Tinnitus Treatments: What Has the Strongest Evidence? | Tinnitus Evidence",
      "Tinnitus Treatments: What Has the Strongest Evidence?",
      "Which tinnitus treatments have the strongest clinical evidence? A conservative, source-linked answer based on evidence scores, replication, and loudness vs distress outcomes.",
      evidence_brief_body(), extra_css='\n<link rel="stylesheet" href="css/evidence-brief.css">', main_cls=" v-page")

recent = []
for t in treatments:
    for ev in t.get("timeline", []):
        if isinstance(ev.get("year"), int) and ev["year"] >= YEAR - 2:
            recent.append((ev["year"], t, ev.get("event", "")))
recent.sort(key=lambda x: -x[0])
guide("new-tinnitus-treatments",
      "New Tinnitus Treatments and Research: What's Actually Emerging | Tinnitus Evidence",
      "New Tinnitus Treatments and Research",
      "What genuinely new tinnitus treatments and research are emerging — bimodal neuromodulation, drug programs and major trials — with conservative evidence context, updated twice a month.",
      f"""
<section><h2>The short answer</h2>
<p>The most consequential recent developments are <strong>bimodal neuromodulation devices</strong> (Lenire's FDA De Novo
authorization; the Shore/Auricle device, investigational and not commercially available, with its regulatory status not publicly verified), large head-to-head and sound-therapy trials
(UNITI; the MOST trial, N=440), and a small pipeline of drug programs. "New" does not mean "better" — several heavily
promoted approaches have failed their trials, and this page reflects the evidence as of our latest review.</p></section>
<section><h2>Recent developments from the evidence timeline ({YEAR - 2}–{YEAR})</h2>
<ul>{''.join(f'<li><strong>{y}</strong> — <a href="treatments/{E(t["id"])}/">{E(t["name"])}</a>: {E(ev)}</li>' for y, t, ev in recent[:20])}</ul></section>
<section><h2>What's in trials now</h2>
<p><a href="trials/">See the {len(trials)} registered clinical trials we track</a>, verified twice a month against
ClinicalTrials.gov. For research updates, see <a href="research.html">Latest Tinnitus Research</a>.</p></section>""")

loud_t = sorted([t for t in treatments if t.get("loudness", {}).get("level") in ("moderate", "strong")], key=lambda x: -x.get("evidenceScore", 0))
guide("tinnitus-loudness-vs-distress",
      "Can Tinnitus Treatments Reduce Loudness, Distress, or Both? | Tinnitus Evidence",
      "Can Tinnitus Treatments Reduce Loudness, Distress, or Both?",
      "The single most important distinction in tinnitus research: treatments that change the sound itself vs treatments that reduce distress and impact. What the evidence supports for each.",
      f"""
<section><h2>The short answer</h2>
<p><strong>Most tinnitus treatments with good evidence reduce distress — how much tinnitus bothers you — rather than the
loudness of the sound itself.</strong> The questionnaires used in most trials (THI, TFI) measure impact on your life, not
volume. A treatment can meaningfully improve your life while the sound stays the same — and a questionnaire improvement is
never proof the sound got quieter.</p></section>
<section><h2>Treatments with at least moderate loudness evidence</h2>
<ul>{''.join(f'<li><a href="treatments/{E(t["id"])}/">{E(t["name"])}</a> — {E(t["loudness"].get("summary", ""))}</li>' for t in loud_t)}</ul>
<p class="small muted">Note how short this list is, and how population-specific its entries are — that is the honest state
of the science.</p></section>
<section><h2>Why we never blur the two</h2>
<p>Distress improvements are real and valuable — better sleep, less anxiety, a life that feels normal again. But telling
someone a treatment "reduces tinnitus" when trials only measured questionnaires misleads them about what to expect.
Every treatment page on this site rates <strong>loudness evidence and distress evidence separately</strong>.
The measurement standards behind this — TFI, THI, and the COMiT'ID core outcome consensus — are
<a href="about.html#measures">documented in our methodology</a>.</p></section>""")

lenire, shore = T.get("lenire"), T.get("shore-bimodal")
guide("bimodal-neuromodulation",
      "Bimodal Neuromodulation for Tinnitus: What the Evidence Shows | Tinnitus Evidence",
      "Bimodal Neuromodulation for Tinnitus: What the Evidence Shows",
      "Bimodal neuromodulation for tinnitus — Lenire and the Shore/Auricle device: trial results, FDA status, replication and independence, limitations and what patients should know.",
      f"""
<section><h2>The short answer</h2>
<p>Bimodal neuromodulation pairs sound with electrical stimulation (tongue or skin) to target the brain circuits behind
tinnitus. Two device programs lead the field: <strong>Lenire</strong> (FDA De Novo authorized, available now) and the
<strong>Shore/Auricle device</strong> (positive academic trial; investigational, not commercially available; regulatory-submission status not publicly verified). Trials report meaningful distress
improvements; independent replication is still missing for both, and neither is established to make tinnitus quieter for
the typical patient.</p></section>
<section><h2>Lenire</h2>
<p>{E(lenire.get('oneLiner', ''))}</p>
<p>Replication: <strong>{E(REP.get(lenire.get('replication'), ''))}</strong>. Independence:
<strong>{E(IND.get(lenire.get('independence'), ''))}</strong>. {E(lenire.get('independenceNote', ''))}</p>
<p><a href="treatments/lenire/">Full Lenire evidence review</a></p></section>
<section><h2>Shore / Auricle bisensory device</h2>
<p>{E(shore.get('oneLiner', ''))}</p>
<p>Replication: <strong>{E(REP.get(shore.get('replication'), ''))}</strong>. Independence:
<strong>{E(IND.get(shore.get('independence'), ''))}</strong>. {E(shore.get('independenceNote', ''))}</p>
<p><a href="treatments/shore-bimodal/">Full Shore-device evidence review</a></p></section>
<section><h2>How to think about the difference</h2>
<p>Lenire's evidence is larger but entirely sponsor-run; the Shore trials are NIH-funded but inventor-led and used a
psychoacoustic loudness co-primary that missed statistical significance in the main analysis at week 6. Both are honest
reasons for caution, not dismissal. See each page's limitations and study records for the full picture.</p></section>""")

guide("tinnitus-clinical-trials",
      "Tinnitus Clinical Trials: How to Understand Emerging Research | Tinnitus Evidence",
      "Tinnitus Clinical Trials: How to Understand Emerging Research",
      "How to read tinnitus clinical trials without being misled: phases, endpoints, placebo response, press releases vs published results — plus the current tracked trials.",
      f"""
<section><h2>The short answer</h2>
<p>A registered clinical trial means a treatment is being <em>tested</em>, not that it works. Most tinnitus drug candidates
that reached Phase 2 or 3 have failed, and company press releases routinely sound stronger than the eventual published
data. The tools below help you read trial news without being misled.</p></section>
<section><h2>Five things to check in any tinnitus trial</h2>
<ul>
<li><strong>The primary endpoint</strong> — was it met? A trial that failed its primary endpoint but reports a positive
subgroup is a negative trial with a lead for future research.</li>
<li><strong>Loudness or distress?</strong> THI/TFI questionnaires measure impact, not volume.</li>
<li><strong>The control group</strong> — tinnitus improves substantially on placebo/waitlist; uncontrolled improvement
proves little. In one gabapentin trial both arms improved ~11 points equally.</li>
<li><strong>Who ran it</strong> — sponsor-run results await independent replication.</li>
<li><strong>Published or press-released?</strong> Toplines can precede (or replace) peer-reviewed data by years —
some failed programs never published their results at all.</li>
</ul></section>
<section><h2>Trials we track now</h2>
<p><a href="trials/">All {len(trials)} tracked trials with statuses verified twice a month against ClinicalTrials.gov</a>.
Only a study's research team can determine whether anyone is eligible.</p></section>""")

guides_dir = """
<p class="lead">Evidence guides answering the questions people actually ask — built from the verified research database,
with the same conservative standards as every treatment page.</p>
<ul>
<li><a href="guides/tinnitus-treatments/">Tinnitus Treatments: What Has the Strongest Evidence?</a></li>
<li><a href="guides/new-tinnitus-treatments/">New Tinnitus Treatments and Research</a></li>
<li><a href="guides/tinnitus-loudness-vs-distress/">Can Tinnitus Treatments Reduce Loudness, Distress, or Both?</a></li>
<li><a href="guides/bimodal-neuromodulation/">Bimodal Neuromodulation for Tinnitus: What the Evidence Shows</a></li>
<li><a href="guides/tinnitus-clinical-trials/">Tinnitus Clinical Trials: How to Understand Emerging Research</a></li>
</ul>"""
canon = page("guides/index.html", "Tinnitus Evidence Guides: Research Questions Answered | Tinnitus Evidence",
             "Evergreen evidence guides on tinnitus treatments, new research, loudness vs distress, bimodal neuromodulation and clinical trials — from the verified database.",
             "Tinnitus Evidence Guides", [("", "Home"), (None, "Guides")], guides_dir)
sitemap_urls.append(canon)

# ---------------- Claims: Fact vs. Evidence (V14) ----------------
# CONTENT POLICY: data/claims.json is authored and human-approved, never generated from the research pipeline and
# never writable by the weekly workflow. Pages are fully static (no JavaScript rendering), so crawlers and
# no-JS readers see exactly what everyone else sees. Every verdict is one of the five defined terms.
def label_tables(h):
    """Give every body cell a data-label from its column header so tables stack readably on phones."""
    def fix(m):
        t = m.group(0)
        heads = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r'<th scope="col">(.*?)</th>', t, re.S)]
        i0 = t.find("<tbody>")
        def row(rm):
            idx = [0]
            def td(tm):
                i = idx[0]; idx[0] += 1
                lab = heads[i + 1] if i + 1 < len(heads) else ""
                return f'<td data-label="{E(lab)}"{tm.group(1)}>'
            return re.sub(r"<td([^>]*)>", td, rm.group(0))
        return t[:i0] + re.sub(r"<tr>.*?</tr>", row, t[i0:], flags=re.S)
    return re.sub(r'<table class="cl-table">.*?</table>', fix, h, flags=re.S)

GUIDE_NAMES = {"tinnitus-treatments": "Tinnitus Treatments: What Has the Strongest Evidence?",
               "new-tinnitus-treatments": "New Tinnitus Treatments and Research",
               "tinnitus-loudness-vs-distress": "Can Tinnitus Treatments Reduce Loudness, Distress, or Both?",
               "bimodal-neuromodulation": "Bimodal Neuromodulation for Tinnitus: What the Evidence Shows",
               "tinnitus-clinical-trials": "Tinnitus Clinical Trials: How to Understand Emerging Research"}

def cl_ref_li(r):
    links = " · ".join(f'<a href="{E(u)}" rel="noopener">{E(lab)}</a>' for lab, u in r["links"])
    return f'<li id="ref-{r["n"]}">{E(r["cite"])} <span class="small muted">[{E(r["kind"])}]</span> <span class="small">{links}</span></li>'

def claim_body(c):
    cls = VCLS[c["verdict"]]
    r = c.get("related", {})
    rel = []
    for tid in r.get("treatments", []):
        if tid in T: rel.append(f'<li><a href="treatments/{E(tid)}/">{E(T[tid]["name"])}</a> <span class="muted">— treatment evidence review</span></li>')
    for eid in r.get("emerging", []):
        if eid in EU_BY: rel.append(f'<li><a href="emerging-unproven/#{E(eid)}">{E(EU_BY[eid]["name"])}</a> <span class="muted">— Emerging &amp; Unproven</span></li>')
    for g in r.get("guides", []):
        if g in GUIDE_NAMES: rel.append(f'<li><a href="guides/{E(g)}/">{E(GUIDE_NAMES[g])}</a> <span class="muted">— guide</span></li>')
    tocs = [("claim", "The claim"), ("answer", "Short answer"), ("verdicts", "Claim by claim"), ("circulates", "Where it circulates"),
            ("research", "What the research shows")]
    tops = [s for s in c["sections"] if len(s) > 2]
    inner = [s for s in c["sections"] if len(s) <= 2]
    for i, s in enumerate(tops): tocs.append((f"top{i}", s[0].split(":")[0] if len(s[0]) > 40 else s[0]))
    tocs += [("terms", "Loudness, distress, relief, cure"), ("limits", "Limits and conflicts"), ("practical", "What you can do"),
             ("related", "Related pages"), ("references", "References")]
    toc = '<nav class="toc" aria-label="On this page">' + "".join(f'<a href="claims/{E(c["slug"])}/#{a}">{E(l)}</a>' for a, l in tocs) + "</nav>"
    sv = "".join(f'<tr><th scope="row">{claim}</th><td>{vchip(v)}</td><td>{E(why)}</td></tr>' for claim, v, why in c["subverdicts"])
    circ = "".join(f'<li><strong>{t}</strong> <span class="muted">({n})</span></li>' for t, n in c["circulation"])
    terms = "".join(f'<tr><th scope="row">{E(a)}</th><td>{E(b)}</td><td>{d}</td></tr>' for a, b, d in c["distinctions"])
    research = "".join(f"<h3>{s[0]}</h3>{s[1]}" for s in inner)
    tops_html = "".join(f'<section id="top{i}"><h2>{s[0]}</h2>{s[1]}</section>' for i, s in enumerate(tops))
    publine = f'First published <time datetime="{E(CL["meta"]["published"])}">{_long_date(CL["meta"]["published"])}</time> · ' if CL["meta"].get("published") else ""
    safety = f'<aside class="cl-safety" role="note" aria-label="Safety note"><p class="cl-safety-h"><span aria-hidden="true">⚠</span> Safety note</p>{c["safety"]}</aside>' if c.get("safety") else ""
    _dl, _dr = CL["meta"]["disclaimer"].split(":", 1)
    disclaimer = f'<aside class="cl-disclaimer" role="note" aria-label="Medical disclaimer"><p><strong>{E(_dl)}:</strong>{E(_dr)}</p></aside>'
    body = f"""
<div class="cl-verdict cl-v-{cls}" role="note" aria-label="Evidence verdict">
<p class="cl-kicker small"><a href="claims/">Tinnitus Claims: Fact vs. Evidence</a></p>
<p class="cl-vline">{vchip(c['verdict'])} <span class="cl-vtext">Evidence verdict</span></p>
<p class="cl-vexp">{E(c['verdictLine'])}</p>
<p class="cl-meta small muted">{publine}Evidence through <time datetime="{E(c['evidenceThrough'])}">{_long_date(c['evidenceThrough'])}</time> ·
Last reviewed <time datetime="{E(c['lastReviewed'])}">{_long_date(c['lastReviewed'])}</time> ·
<a href="claims/verdicts/">What the verdicts mean</a> · “Unsupported” does not necessarily mean disproven.</p>
</div>
{safety}
{disclaimer}
{toc}
<section id="claim"><h2>The claim</h2><blockquote class="cl-q">{c['claim']}</blockquote></section>
<section id="answer"><h2>The short answer</h2>{c['answer']}</section>
<section id="verdicts"><h2>Claim by claim</h2>
<div class="cl-tablewrap"><table class="cl-table"><caption class="sr-only">Verdict for each version of the claim</caption>
<thead><tr><th scope="col">Version of the claim</th><th scope="col">Verdict</th><th scope="col">Why</th></tr></thead><tbody>{sv}</tbody></table></div></section>
<section id="circulates"><h2>Where this claim circulates</h2><p>{E(c['circulation_intro'])}</p><ul class="cl-circ">{circ}</ul></section>
<section id="research"><h2>What the research shows</h2>{research}</section>
{tops_html}
<section id="terms"><h2>Loudness, distress, relief or cure: what is being claimed?</h2>
<p>Claims often blur these. Here is what the evidence supports for each. <a href="claims/verdicts/#terms">Definitions</a>.</p>
<div class="cl-tablewrap"><table class="cl-table"><caption class="sr-only">What the evidence shows for each kind of benefit</caption>
<thead><tr><th scope="col">What is claimed</th><th scope="col">What it means</th><th scope="col">What the evidence shows</th></tr></thead><tbody>{terms}</tbody></table></div></section>
<section id="limits"><h2>Limitations and conflicts of interest</h2>{c['limits']}{c['coi']}</section>
<section id="practical"><h2>What you can do</h2>{c['practical']}</section>
<section id="related"><h2>Related pages on this site</h2>
<ul class="cl-rel">{''.join(rel)}</ul>
<p class="small muted">These pages are the full evidence reviews. Claim checks do not change any treatment’s evidence score or ranking.</p></section>
<section id="references"><h2>References</h2>
<ol class="cl-refs">{''.join(cl_ref_li(x) for x in c['references'])}</ol>
<p class="small muted">Primary sources were opened and read for this page; the links go to PubMed, publisher DOIs, guideline texts, regulator or registry records. Evidence through {_long_date(c['evidenceThrough'])}. Last reviewed {_long_date(c['lastReviewed'])}.</p></section>
<p class="small muted">This page evaluates a public claim against published research for education. It is not medical advice and cannot say what will work for any individual. See a qualified clinician for diagnosis and treatment. <a href="about.html#disclaimer">Medical disclaimer</a> · <a href="about.html#corrections">Corrections</a>.</p>"""
    # <base href> is set on every page, so same-page fragment links must carry the full page path
    body = body.replace('href="#ref-', f'href="claims/{c["slug"]}/#ref-')
    return label_tables(body)

if CL:
    for c in CL["claims"]:
        canon = page(f"claims/{c['slug']}/index.html", c["metaTitle"], c["metaDesc"], E(c["question"]),
                     [("", "Home"), ("claims/", "Tinnitus Claims"), (None, c["short"])], claim_body(c),
                     article={"headline": c["question"], "published": CL["meta"]["published"], "modified": c["lastReviewed"]}, main_cls=" cl-page")
        sitemap_urls.append(canon); LASTMOD[canon] = c["lastReviewed"]
    cards = "".join(f"""<article class="card cl-card cl-v-{VCLS[c['verdict']]}">
<p class="cl-cardv">{vchip(c['verdict'])}</p>
<h2><a href="claims/{E(c['slug'])}/">{E(c['question'])}</a></h2>
<p class="cl-claimq">{c['claim']}</p>
<p class="small">{E(c['verdictLine'])}</p>
<p class="small"><a href="claims/{E(c['slug'])}/">Read the evidence →</a></p></article>""" for c in CL["claims"])
    vdefs = "".join(f"<li>{vchip(v['name'])} {v['meaning']}</li>" for v in CL["verdicts"])
    land = f"""
<p class="lead">{E(CL['landing']['lead'])}</p>
<p><span class="cl-intro-lead">{E(CL['landing']['intro'].split(':', 1)[0])}:</span>{E(CL['landing']['intro'].split(':', 1)[1])}</p>
<aside class="cl-disclaimer" role="note" aria-label="About these articles"><p><strong>{E(CL['meta']['landingDisclosure'].split(':', 1)[0])}:</strong>{E(CL['meta']['landingDisclosure'].split(':', 1)[1])}</p></aside>
<p class="cl-meta small muted">{('First published ' + _long_date(CL['meta']['published']) + ' · ') if CL['meta'].get('published') else ''}Evidence through {_long_date(CL['meta']['evidenceThrough'])} · Last reviewed {_long_date(CL['meta']['lastReviewed'])}</p>
<div class="grid grid-2 cl-grid">{cards}</div>
<section id="how"><h2>How to read a verdict</h2>
<ul class="cl-vdefs">{vdefs}</ul>
<p><strong>Unsupported does not necessarily mean disproven.</strong> It can mean a claim was tested and did not show a benefit, or that it has not been tested well enough to know. <a href="claims/verdicts/">Read the full explanation of the verdicts</a>.</p></section>
<section><h2>How we check a claim</h2><ul>{''.join(f'<li>{E(x)}</li>' for x in CL['how'])}</ul>
<p class="small muted">Tinnitus Evidence is independently operated and carries no advertising or affiliate links. This section is education, not medical advice. <a href="about.html#disclaimer">Medical disclaimer</a>.</p></section>"""
    canon = page("claims/index.html", CL["landing"]["metaTitle"], CL["landing"]["metaDesc"], "Tinnitus Claims: Fact vs. Evidence",
                 [("", "Home"), (None, "Tinnitus Claims")], land, modified=CL["meta"]["lastReviewed"], main_cls=" cl-page")
    sitemap_urls.append(canon); LASTMOD[canon] = CL["meta"]["lastReviewed"]
    vrows = "".join(f"""<section id="{E(v['cls'])}"><h2>{vchip(v['name'])}</h2><p>{v['meaning']}</p><p class="muted"><strong>What it does not mean.</strong> {v['notmean']}</p></section>""" for v in CL["verdicts"])
    trows = "".join(f'<tr><th scope="row">{E(a)}</th><td>{E(b)}</td></tr>' for a, b in CL["terms"])
    vpage = f"""
<p class="lead">Every claim page ends with one of five verdicts. They describe the <em>evidence</em>, not the people making a claim.</p>
{vrows}
<section id="terms"><h2>Six outcomes that claims blur together</h2>
<p>A claim can be true about one of these and misleading about another. Each claim page shows which applies.</p>
<div class="cl-tablewrap"><table class="cl-table"><caption class="sr-only">Definitions of outcomes used on claim pages</caption>
<thead><tr><th scope="col">Outcome</th><th scope="col">What it means</th></tr></thead><tbody>{trows}</tbody></table></div></section>
<section><h2>How we assign a verdict</h2><ul>{''.join(f'<li>{E(x)}</li>' for x in CL['how'])}</ul>
<p><a href="claims/">Back to Tinnitus Claims: Fact vs. Evidence</a> · <a href="about.html#methodology">Our evidence methodology</a> · <a href="about.html#corrections">Corrections</a></p></section>"""
    canon = page("claims/verdicts/index.html", CL["verdictsPage"]["metaTitle"], CL["verdictsPage"]["metaDesc"],
                 "How We Judge Tinnitus Claims: Evidence Verdicts",
                 [("", "Home"), ("claims/", "Tinnitus Claims"), (None, "Verdicts")], label_tables(vpage), modified=CL["meta"]["lastReviewed"], main_cls=" cl-page")
    sitemap_urls.append(canon); LASTMOD[canon] = CL["meta"]["lastReviewed"]

# ---------------- Safety pages (Phase 1): /urgent/ and /support/ from data/safety.json ----------------
# One source for urgent-care tiers and crisis lines; the same file feeds the Profile (js/app.js) and is mirrored by the
# Ask worker (checked by tools/ask_core_test.mjs). Wording is calm and specific; NICE wording is marked as a secondary
# summary until checked against the original.
SAF = json.load(open(os.path.join(ROOT, "data", "safety.json"), encoding="utf-8"))
TIER_COLOR = {"emergency": "var(--c-watch)", "today": "var(--c-emerging)", "soon": "var(--c-promising)"}

def crisis_list_html():
    rows = []
    for l in SAF["crisis"]["lines"]:
        svc = "".join(f'<li><strong>{E(sv["name"])}</strong>: {E(sv["contact"])} ({E(sv["hours"])}). '
                      f'<a href="{E(sv["url"])}" rel="noopener">Website</a>'
                      + (f' <span class="small muted">{E(sv["note"])}</span>' if sv.get("note") else "") + '</li>'
                      for sv in l["services"])
        rows.append(f'<div class="card" style="padding:12px 16px;margin:10px 0"><h3 style="margin:0 0 6px;font-size:1rem">{E(l["country"])}</h3><ul style="margin:0">{svc}</ul></div>')
    d = SAF["crisis"]["directory"]
    rows.append(f'<div class="card" style="padding:12px 16px;margin:10px 0"><h3 style="margin:0 0 6px;font-size:1rem">Anywhere else</h3>'
                f'<p style="margin:0"><a href="{E(d["url"])}" rel="noopener"><strong>{E(d["name"])}</strong></a>: {E(d["contact"])}. <span class="small muted">{E(d["note"])}.</span></p></div>')
    return "".join(rows)

U = SAF["urgent"]
tiers_html = "".join(
    f'<section class="card" style="padding:14px 18px;margin:14px 0;border-left:4px solid {TIER_COLOR[t["id"]]}" aria-labelledby="tier-{t["id"]}">'
    f'<h2 id="tier-{t["id"]}" style="margin:0 0 6px;font-size:1.2rem">{E(t["label"])}</h2><p style="margin:0 0 6px">{E(t["lead"])}</p>'
    f'<ul style="margin:0">{"".join("<li>" + E(i) + "</li>" for i in t["items"])}</ul></section>'
    for t in U["tiers"])
nums_src_html = " · ".join(f'<a href="{E(sv["url"])}" rel="noopener">{E(sv["label"])}</a>' for n in U["emergencyNumbers"] for sv in n.get("sources", []))
nums_html = " · ".join(f'{E(n["where"])}: <strong>{E(n["number"])}</strong>' for n in U["emergencyNumbers"])
basis_html = "".join(f'<li><a href="{E(b["url"])}" rel="noopener">{E(b["label"])}</a>'
                     + (' <span class="small muted">(our summary, not an official quotation)</span>' if b.get("summary") else "") + '</li>'
                     for b in U["basis"])
urgent_body = f"""
<p class="lead">{E(U["intro"])}</p>
<p class="small muted">Emergency numbers: {nums_html}.</p>
{tiers_html}
<section class="notice" style="margin:18px 0" aria-labelledby="urgent-crisis-h">
  <h2 id="urgent-crisis-h" style="margin:0 0 6px;font-size:1.1rem">If you feel you can't cope</h2>
  <p style="margin:0">{E(U["crisisLine"])} <a href="support/#crisis"><strong>Crisis lines by country</strong></a></p>
</section>
<h2>Where this guidance comes from</h2>
<ul class="small">{basis_html}</ul>
<p class="small muted">Emergency numbers checked {E(SAF["lastVerified"])} on official sources: {nums_src_html}.</p>
<p class="small muted">Last checked {E(SAF["lastVerified"])}. Educational information, not a diagnosis and not medical advice; it has not been reviewed by a clinician.
If you are unsure how urgent something is, contact a doctor, a nurse advice line or an emergency service.</p>
"""
canon = page("urgent/index.html", "When to Get Help Quickly for Tinnitus | Tinnitus Evidence",
             "Which tinnitus symptoms need emergency care, same-day medical help or a routine appointment, explained calmly and with sources.",
             E(U["title"]), [("", "Home"), (None, U["title"])], urgent_body, modified=SAF["lastVerified"])
sitemap_urls.append(canon); LASTMOD[canon] = SAF["lastVerified"]

C = SAF["crisis"]
orgs_html = "".join(f'<li><a href="{E(o["url"])}" rel="noopener"><strong>{E(o["name"])}</strong></a> ({E(o["country"])}): {E(o["offers"])}.</li>'
                    for o in SAF["organizations"])
support_body = f"""
<p class="lead">Living with tinnitus can be hard, and you don't have to manage it alone. This page lists crisis lines for
anyone who needs to talk to someone now, and organizations that support people with tinnitus.</p>
<section id="crisis" aria-labelledby="crisis-h">
  <h2 id="crisis-h">If you need help now</h2>
  <p>{E(C["intro"])} <strong>{E(C["danger"])}</strong></p>
  {crisis_list_html()}
  <p class="small muted">{E(C["limits"])}</p>
</section>
<section id="organizations" aria-labelledby="orgs-h">
  <h2 id="orgs-h">Tinnitus support organizations</h2>
  <p>These charities and associations offer information, helplines and support groups for people with tinnitus.</p>
  <ul>{orgs_html}</ul>
  <p class="small muted">We list organizations whose contact details we could check on their own websites. Inclusion is not an endorsement, and
  Tinnitus Evidence has no connection with any of them.</p>
</section>
<section id="professional" aria-labelledby="pro-h">
  <h2 id="pro-h">Professional support for tinnitus distress</h2>
  <p>Talking therapies, especially <a href="treatments/cbt/">cognitive behavioural therapy (CBT)</a>, have the strongest evidence for
  reducing how much tinnitus affects daily life. They don't make the sound quieter, but they help many people sleep, cope and feel
  better. Ask your doctor or audiologist what is available where you live. If sleep is the main problem, ask about
  <a href="treatments/cbt-i/">CBT for insomnia</a>.</p>
  <p>Worried about a symptom? See <a href="urgent/">When to get help quickly</a>.</p>
</section>
<p class="small muted">Contact details last checked {E(SAF["lastVerified"])}. If a number has changed, please tell us through the corrections process on
<a href="about.html#corrections">About</a>.</p>
"""
canon = page("support/index.html", "Tinnitus Support and Crisis Lines | Tinnitus Evidence",
             "Crisis lines by country for anyone who needs to talk to someone now, and tinnitus support organizations, with contact details checked on their own websites.",
             "Support and crisis lines", [("", "Home"), (None, "Support and crisis lines")], support_body, modified=SAF["lastVerified"])
sitemap_urls.append(canon); LASTMOD[canon] = SAF["lastVerified"]

# ---------------- Patient experience (Phase 2): "What would help you today?" + /living/ hub ----------------
# One source (data/patient-guides.json) for the homepage section and the hub. A choice links to its guide once the guide is
# published; until then to its short card on /living/. Plain links: no JavaScript, no questions, nothing stored.
PG = json.load(open(os.path.join(ROOT, "data", "patient-guides.json"), encoding="utf-8"))
PG_NEEDS = PG["needs"]
PG_GUIDES = PG.get("guides", {})
NEED_IDS = {n["id"] for n in PG_NEEDS}
def tile_items(ids):
    """Choice tiles, in the order given: a homepage choice, or another published guide from the library (Phase 4)."""
    out = []
    for i in ids:
        n = next((x for x in PG_NEEDS if x["id"] == i), None)
        if n:
            out.append((need_href(n), n["icon"], n["label"], n["short"], n["desc"]))
        elif i in PG_GUIDES:
            g = PG_GUIDES[i]; out.append((g["path"], g["icon"], g["tileLabel"], g["tileShort"], g["tileDesc"]))
    return "".join(f'<li><a href="{E(h)}"><span class="hi" aria-hidden="true">{ic}</span><span><b><span class="lf">{E(l)}</span><span class="ls">{E(sh)}</span></b>'
                   f'<span class="d">{E(d)}</span></span></a></li>' for h, ic, l, sh, d in out)
def need_href(n):
    return n["guide"]

def chooser_html(hid, with_intro=True):
    C = PG["chooser"]
    tiles = "".join(
        f'<li><a href="{E(need_href(n))}"><span class="hi" aria-hidden="true">{n["icon"]}</span><span>'
        f'<b><span class="lf">{E(n["label"])}</span><span class="ls">{E(n["short"])}</span></b>'
        f'<span class="d">{E(n["desc"])}</span></span></a></li>' for n in PG_NEEDS)
    intro = (f'<h2 id="{hid}-h">{E(C["title"])}</h2>\n  <p class="help-sub">{E(C["sub"])}</p>\n  '
             f'<p class="help-q" id="{hid}-q">{E(C["question"])}</p>') if with_intro else f'<h2 class="help-q" id="{hid}-q">{E(C["question"])}</h2>'
    explore = " · ".join(f'<a href="{E(h)}">{E(t)}</a>' for h, t in PG["explore"])
    shield = f'<svg class="vi" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{guide_art.ICONS["shield"]}</svg>'   # approved 26 Oct 2026
    return (f'<section class="help-entry{" f-help" if with_intro else ""}" aria-labelledby="{hid}-{"h" if with_intro else "q"}">\n  {intro}\n'
            f'  <ul class="help-grid" aria-labelledby="{hid}-q">{tiles}</ul>\n'
            f'  <p class="help-urgent f-urgent">{shield}<span>{PG["urgentLine"]}</span></p>\n'
            + (f'  <p class="help-explore">Explore the research: {explore}</p>\n' if with_intro else "")
            + '</section>')

# homepage: the section sits in the hero, after the lead (replaces the three research path cards; their destinations are the
# "Explore the research" row). Rewritten between markers on every build, so the hand-authored page stays in sync with the data.
_ip = ROOT / "index.html"
_ih = _ip.read_text(encoding="utf-8")
_m = re.search(r"(<!-- help-entry:start[^>]*-->\n)[\s\S]*?(\s*<!-- help-entry:end -->)", _ih)
assert _m, "index.html: help-entry markers missing"
_new = _ih[:_m.end(1)] + "    " + chooser_html("help") + _ih[_m.start(2):]
if _new != _ih:
    _ip.write_text(_new, encoding="utf-8")

living_body = f"""
<p class="lead">Practical help for everyday life with tinnitus. Choose what's closest to how you feel today, or browse all the guides.</p>
{chooser_html("lw", with_intro=False)}
{('<section class="help-entry g-related lw-more-guides" aria-labelledby="lw-more-h"><h2 class="help-q" id="lw-more-h">More practical guides</h2><ul class="help-grid">'
  + tile_items([k for k in PG_GUIDES if k not in NEED_IDS]) + '</ul></section>') if any(k not in NEED_IDS for k in PG_GUIDES) else ""}
<p class="small muted lw-note">Not sure where to start? Begin with <a href="{E(need_href(PG_NEEDS[0]))}">New to tinnitus? Start here</a>.</p>
<section class="card lw-evidence" aria-labelledby="lw-ev-h"><h2 id="lw-ev-h">The research behind the guides</h2>
<p>Every guide links to its sources, and to our evidence pages. To explore the research on treatments:</p>
<ul><li><a href="guides/tinnitus-treatments/">What has the strongest evidence?</a></li>
<li><a href="guides/tinnitus-loudness-vs-distress/">Loudness vs distress: how to read our ratings</a></li>
<li><a href="treatments.html">All treatments, ranked by evidence</a></li>
<li><a href="claims/">Check a claim</a></li></ul></section>
<p class="small muted">Last reviewed {E(PG["lastReviewed"])}. Educational information, not a diagnosis and not medical advice; it has not been reviewed
by a clinician. Worried about a symptom? See <a href="urgent/">When to get help quickly</a>.</p>
"""
# ---- Patient guides (Phase 3): one template, content in data/patient-guides.json "guides" ----
# Order on the page: reassurance, "Right now" box, On this page, sections (urgent block from data/safety.json where asked),
# checklist or worksheet (tick or type; nothing is stored or sent; print or save as PDF), what the research says, related
# choices, numbered sources. Citations are written [[key]] in the content and become numbered links to the source list.
def crisis_links(contact):
    """'call 116 123' -> a 'call 116 123' button (tel:); numbers in a 'text ...' clause become sms: links. The verb right before a number
    joins the button only when it matches the action; the accessible label always names it. Short codes are dialled as written.
    Digits come from data/safety.json unchanged (approved 26 Oct 2026)."""
    out, pos = "", 0
    for m in re.finditer(r"\b\d[\d -]*\d\b", contact):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) < 3: continue
        clause = contact[:m.start()].split(", ")[-1]
        sms = "text" in clause.lower() and "call" not in clause.lower()
        v = re.search(r"\b(call|dial|text)\s+$", contact[pos:m.start()], re.I)
        if v and (v.group(1).lower() == "text") != sms: v = None   # "call or text 1737": the button calls, so it shows just the number
        start = pos + v.start() if v else m.start()
        if v: label = v.group(1).capitalize() + " " + m.group(0)
        elif sms: label = clause.strip()[:1].upper() + clause.strip()[1:] + " " + m.group(0)   # "Text SHOUT to 85258"
        else: label = "Call " + m.group(0)
        out += E(contact[pos:start]) + f'<a class="o-num" href="{"sms:" if sms else "tel:"}{digits}" aria-label="{E(label)}">{E(contact[start:m.end()])}</a>'
        pos = m.end()
    return out + E(contact[pos:])

def harbour_crisis(gid, G, sec, cite):
    """Compact crisis support beneath the practical help: every verified contact visible, tap to call or text, country links on phones."""
    C = SAF["crisis"]; d = C["directory"]; lc = lambda t: t[:1].lower() + t[1:]
    cid = lambda name: "crisis-" + re.sub(r"[^a-z]+", "-", name.lower()).strip("-")
    index = ('<nav class="o-index" aria-label="Crisis lines by country">' + "".join(f'<a href="{G["path"]}#{cid(l["country"])}">{E(l["country"])}</a>' for l in C["lines"])
             + f'<a href="{G["path"]}#crisis-anywhere">Anywhere else</a></nav>')
    cells = "".join(f'<li id="{cid(l["country"])}"><strong class="o-country">{E(l["country"])}</strong>' + "".join(
        f'<span class="g-svc"><span class="o-svc">{E(sv["name"])}</span>: {crisis_links(lc(sv["contact"]))}</span>' for sv in l["services"]) + "</li>" for l in C["lines"])
    cells += (f'<li class="o-any" id="crisis-anywhere"><strong class="o-country">Anywhere else</strong><span class="g-svc"><a href="{E(d["url"])}" rel="noopener">{E(d["name"])}</a>: '
              f'{E(lc(d["contact"]))}</span></li>')
    return (f'<section class="g-sec g-crisis o-crisis" id="{sec["id"]}" aria-labelledby="{gid}-{sec["id"]}-h">'
            f'<header class="o-crisis-h"><h2 id="{gid}-{sec["id"]}-h"><span class="o-badge">{guide_art.icon("support")}</span>{E(sec["title"])}</h2>'
            f'<p class="o-intro">{cite(sec["intro"])}</p></header>'
            f'<p class="o-danger">{guide_art.icon("siren")}<strong>{E(C["danger"])}</strong></p>{index}'
            f'<ul class="g-lines o-grid">{cells}</ul>'
            f'<p class="small muted o-limits">{E(C["limits"])} <a href="support/#crisis">All support and crisis lines</a></p></section>')

STEP_ART = {"lighthouse": 0, "headphones": 1, "moon-waves": 2, "leaf": 3, "tag": 4}
def now_section(gid, G, L, cite):
    """Approved 26 Oct 2026. 'steps': numbered cards with a small illustration (Start here). 'routine': Right now / Still awake? /
    Tomorrow cards with a night-to-dawn tint (Sleep). Same words and citations as the plain list; nothing is hidden behind a tap."""
    ic = guide_art.icon; used = set()
    def icon(n): used.add(n); return ic(n)
    secs = {x["id"]: x for x in G["sections"]}
    def lis(sid): return re.findall(r"<li>(.*?)</li>", secs[sid]["html"], re.S)
    def src(ref): return G["now"][ref[1]] if ref[0] == "now" else lis(ref[0])[ref[1]]
    foot = lambda n: (f'<p class="g-now-foot f-foot">{icon(n)}<span>{cite(G["nowFoot"])}</span></p>' if G.get("nowFoot") else "")
    if L["style"] == "groups":
        # Approved 26 Oct 2026 (Concentration): the steps grouped by what you can change, each group with a small scene
        cards = "".join(f'<li class="c-group"><span class="c-art" aria-hidden="true">{guide_art.conc_art(gr["art"])}</span><h3>{E(gr["title"])}</h3><ul class="c-tips">'
                        + "".join(f'<li><span class="c-ic">{icon(ic)}</span><div>{cite(G["now"][i])}</div></li>' for i, ic in gr["items"]) + "</ul></li>"
                        for gr in L["groups"])
        assert sorted(i for gr in L["groups"] for i, _ in gr["items"]) == list(range(len(G["now"]))), f"{gid}: every step in exactly one group"
        hint = (f'<p class="g-now-foot c-hint">{icon(L.get("hintIcon", "spark"))}<span>{cite(G["nowFoot"])}</span></p>' if G.get("nowFoot") else "")
        html = (f'<section class="g-now c-now" aria-labelledby="{gid}-now-h"><h2 id="{gid}-now-h">{E(G["nowTitle"])}</h2>'
                f'<ul class="c-groups">{cards}</ul>{hint}</section>')
        return html + f'<!--sprite:{" ".join(sorted(used))}-->'
    if L["style"] == "stages":
        # Approved 26 Oct 2026 (Appointment): stage 1's box; the stages themselves are assembled in guide_page
        items = "".join(f'<li><span class="a-tick" aria-hidden="true">{icon("check-list")}</span><div>{cite(x)}</div></li>' for x in G["now"])
        alert = (f'<p class="g-now-foot a-alert">{icon("siren")}<span>{cite(G["nowFoot"])}</span></p>' if G.get("nowFoot") else "")
        html = (f'<section class="g-now a-before" id="before" aria-labelledby="{gid}-now-h"><h2 id="{gid}-now-h">{E(G["nowTitle"])}</h2>'
                f'<ol class="g-now-list a-list">{items}</ol>{alert}</section>')
        return html + f'<!--sprite:{" ".join(sorted(used))}-->'
    if L["style"] == "harbour":
        # Approved 26 Oct 2026 ("When it feels like too much"): practical help first, the urgent lines at its top, compact crisis support beneath
        used.update(["support", "siren"])
        safe = (f'<li class="o-safe"><p class="o-safe-danger">{icon("siren")}<span>{E(SAF["crisis"]["danger"])}</span></p>'
                f'<span class="o-safe-ic">{icon("support")}</span><div>{cite(G["now"][0])}</div></li>')
        tiles = "".join(f'<li class="o-act"><span class="o-act-art" aria-hidden="true">{guide_art.tile_art(k)}</span><span class="o-act-n" aria-hidden="true">{i + 2}</span>'
                        f'<div>{cite(t)}</div></li>' for i, (t, k) in enumerate(zip(G["now"][1:], L["art"])))
        now = (f'<section class="g-now o-now" aria-labelledby="{gid}-now-h"><header class="o-now-h"><h2 id="{gid}-now-h">{E(G["nowTitle"])}</h2>'
               f'<span class="o-art" aria-hidden="true">{guide_art.harbour_art()}</span></header>'
               f'<ol class="g-now-list o-list">{safe}<li class="o-then" aria-hidden="true">{E(L["then"])}</li>{tiles}</ol>'
               + (f'<p class="g-now-foot o-foot">{icon("leaf")}<span>{cite(G["nowFoot"])}</span></p>' if G.get("nowFoot") else "") + "</section>")
        html = f'<div class="o-top">{now}{harbour_crisis(gid, G, secs[L["crisis"]], cite)}</div>'
        return html + f'<!--sprite:{" ".join(sorted(used))}-->'
    if L["style"] == "steps":
        out = ""
        for i, li in enumerate(G["now"]):
            m = re.match(r"\s*<strong>(.*?)</strong>(.*)", li, re.S); short, rest = m.group(1), m.group(2).lstrip()
            more = L["more"][i]
            more = f' <a class="f-more" href="{G["path"]}#{more}">{E(secs[more]["title"])}</a>' if more else ""
            out += (f'<li class="f-step" id="step-{i + 1}"><span class="f-step-art" aria-hidden="true">{guide_art.step_art(STEP_ART[L["art"][i]])}</span>'
                    f'<span class="f-num" aria-hidden="true">{i + 1}</span><h3>{cite(short)}</h3><p>{cite(rest)}{more}</p></li>')
        html = (f'<section class="g-now f-start" aria-labelledby="{gid}-now-h"><h2 id="{gid}-now-h">{E(G["nowTitle"])}</h2>'
                f'<ol class="g-now-list f-steps">{out}</ol>{foot("support")}</section>')
    else:
        loop = (f'<span class="f-loop" aria-hidden="true">' + f'{icon("arrow")}'.join(f'<span>{icon(n)}{E(t)}</span>' for n, t in L["loop"]) + "</span>")
        def item(ref):
            when = f'<span class="f-when">{E(ref[3])}</span>' if len(ref) > 3 and ref[3] != "loop" else ""
            extra = loop if len(ref) > 3 and ref[3] == "loop" else ""
            return f'<li><span class="f-li-ic">{icon(ref[2])}</span><div>{when}{cite(src(ref))}{extra}</div></li>'
        cards = ""
        for k, c in enumerate(L["cards"]):
            inner = f'<ul class="f-items">{"".join(item(r) for r in c["items"])}</ul>'
            if c.get("group"):
                inner += f'<h4 class="f-h4">{E(secs[c["group"]]["title"])}</h4><ul class="f-items">{"".join(item(r) for r in c["groupItems"])}</ul>'
            if c.get("support"):
                inner += f'<p class="f-support">{icon("support")}<span>{cite(src(c["support"]))}</span></p>'
            cards += (f'<section class="f-card f-c{k + 1}" id="{c["id"]}" aria-labelledby="{gid}-card-{c["id"]}-h"><header class="f-card-h">'
                      f'<span class="f-card-art" aria-hidden="true">{guide_art.card_art(c["art"])}</span><div><p class="f-kicker">{E(c["kicker"])}</p>'
                      f'<h3 id="{gid}-card-{c["id"]}-h">{E(c["title"])}</h3><p class="f-sub">{E(c["sub"])}</p></div></header>{inner}</section>')
        html = (f'<section class="g-now f-night" aria-labelledby="{gid}-now-h"><h2 id="{gid}-now-h">{E(G["nowTitle"])}</h2>'
                f'<div class="f-cards">{cards}</div>{foot("leaf")}</section>')
    return html + f'<!--sprite:{" ".join(sorted(used))}-->'

def guide_page(gid, G):
    path = G["path"]
    src_keys = [x["key"] for x in G["sources"]]
    def cite(html_text):
        def one(m):
            keys = [k.strip() for k in m.group(1).split(",")]
            for k in keys: assert k in src_keys, f"guide {gid}: unknown source [[{k}]]"
            keys.sort(key=src_keys.index)
            return '<sup class="g-cite">' + ", ".join(f'<a href="{path}#src-{k}" aria-label="Source {src_keys.index(k) + 1}">{src_keys.index(k) + 1}</a>' for k in keys) + "</sup>"
        return re.sub(r"\[\[([a-z0-9_, -]+)\]\]", one, html_text)
    toc, body, tile_icons = [], [], set()
    body.append(f'<p class="lead">{cite(G["lead"])}</p>')
    L = G.get("nowLayout")
    body.append(now_section(gid, G, L, cite) if L else
                f'<section class="g-now" aria-labelledby="{gid}-now-h"><h2 id="{gid}-now-h">{E(G["nowTitle"])}</h2>'
                f'<ol class="g-now-list">{"".join("<li>" + cite(x) + "</li>" for x in G["now"])}</ol>'
                + (f'<p class="g-now-foot">{cite(G["nowFoot"])}</p>' if G.get("nowFoot") else "") + "</section>")
    sec_html, sec_ids = [], []
    for sec in G["sections"]:
        if sec.get("inNow"):   # shown inside the illustrated "Right now" layout (same id), not repeated here
            if sec.get("toc", True): toc.append((sec["id"], sec.get("short", sec["title"])))
            continue
        if sec.get("type") == "urgent":
            T = {t["id"]: t for t in SAF["urgent"]["tiers"]}
            rows = "".join(f'<li style="border-left-color:{TIER_COLOR[k]}"><strong>{E(T[k]["label"])}:</strong> {E(sec["summary"][k])}</li>' for k in ("emergency", "today", "soon"))
            sec_html.append(f'<section class="g-sec g-urgent{" " + sec["class"] if sec.get("class") else ""}" id="{sec["id"]}" aria-labelledby="{gid}-{sec["id"]}-h"><h2 id="{gid}-{sec["id"]}-h">{E(sec["title"])}</h2>'
                            f'<p>{cite(sec["intro"])}</p><ul class="g-tiers">{rows}</ul><p><a class="see" href="urgent/">All the signs, explained calmly</a></p></section>')
        elif sec.get("type") == "crisis":
            # crisis lines rendered from data/safety.json (the single source; drift-tested), never typed into a guide
            C = SAF["crisis"]; d = C["directory"]
            lc = lambda t: t[:1].lower() + t[1:]
            rows = "".join(f'<li><strong>{E(l["country"])}</strong>' + "".join(f'<span class="g-svc">{E(sv["name"])}: {E(lc(sv["contact"]))}</span>' for sv in l["services"]) + "</li>" for l in C["lines"])
            rows += f'<li><strong>Anywhere else</strong><span class="g-svc"><a href="{E(d["url"])}" rel="noopener">{E(d["name"])}</a>: {E(lc(d["contact"]))}</span></li>'
            sec_html.append(f'<section class="g-sec g-crisis" id="{sec["id"]}" aria-labelledby="{gid}-{sec["id"]}-h"><h2 id="{gid}-{sec["id"]}-h">{E(sec["title"])}</h2>'
                            f'<p>{cite(sec["intro"])}</p><ul class="g-lines">{rows}</ul><p><strong>{E(C["danger"])}</strong></p>'
                            f'<p class="small muted">{E(C["limits"])} <a href="support/#crisis">All support and crisis lines</a></p></section>')
        elif sec.get("type") == "checklist":
            items = "".join(f'<li><label><input type="checkbox"> <span>{cite(x)}</span></label></li>' for x in sec["items"])
            sec_html.append(f'<section class="g-sec g-print{" " + sec["class"] if sec.get("class") else ""}" id="{sec["id"]}" aria-labelledby="{gid}-{sec["id"]}-h"><h2 id="{gid}-{sec["id"]}-h">{E(sec["title"])}</h2>'
                            f'<p>{cite(sec["intro"])}</p><ul class="g-check">{items}</ul>'
                            f'<p class="g-tools"><button type="button" class="btn" data-print="{sec["id"]}">Print or save this checklist</button>'
                            f'<span class="small muted">Ticks are not saved or sent anywhere.</span></p></section>')
        elif sec.get("type") == "worksheet":
            fields = "".join(f'<div class="g-field"><label for="ws-{i}">{E(f["label"])}</label>'
                             + (f'<span class="small muted" id="ws-{i}-h">{E(f["hint"])}</span>' if f.get("hint") else "")
                             + f'<textarea id="ws-{i}" rows="{f.get("rows", 2)}" autocomplete="off"' + (f' aria-describedby="ws-{i}-h"' if f.get("hint") else "") + '></textarea></div>'
                             for i, f in enumerate(sec["fields"]))
            top = (f'<p class="a-print-top"><button type="button" class="btn btn-primary" data-print="{sec["id"]}">Print or save as PDF</button>'
                   f'<span class="small muted">{E(sec["printTop"])}</span></p>') if sec.get("printTop") else ""   # approved 26 Oct 2026
            sec_html.append(f'<section class="g-sec g-print g-sheet{" " + sec["class"] if sec.get("class") else ""}" id="{sec["id"]}" aria-labelledby="{gid}-{sec["id"]}-h"><h2 id="{gid}-{sec["id"]}-h">{E(sec["title"])}</h2>'
                            f'{top}<p>{cite(sec["intro"])}</p>{fields}'
                            f'<p class="g-tools"><button type="button" class="btn btn-primary" data-print="{sec["id"]}">Print or save as PDF</button>'
                            f'<span class="small muted">What you type stays on this page: it is not saved or sent, and it disappears when you leave.</span></p></section>')
        else:
            h = sec["html"]
            if sec.get("tiles"):   # approved 26 Oct 2026: the section's list as icon tiles (same items, same order)
                its = re.findall(r"<li>(.*?)</li>", h, re.S); assert len(its) == len(sec["tiles"]), sec["id"]
                h = re.sub(r"<ul>.*?</ul>", lambda _m: '<ul class="o-steps">' + "".join(f'<li><span class="o-step-ic">{guide_art.icon(n)}</span><div>{t}</div></li>'
                                                                                     for t, n in zip(its, sec["tiles"])) + "</ul>", h, count=1, flags=re.S)
                tile_icons.update(sec["tiles"])
            card, head_extra = sec.get("card"), ""
            if card:   # approved 26 Oct 2026: a small scene beside the heading; the first list as icon rows (same items, same order)
                m = re.search(r"<ul>(.*?)</ul>", h, re.S); its = re.findall(r"<li>(.*?)</li>", m.group(1), re.S); assert len(its) == len(card["icons"]), sec["id"]
                tag, lcls = ("ol", "c-path") if card.get("path") else ("ul", "c-tips")
                h = h[:m.start()] + f'<{tag} class="{lcls}">' + "".join(f'<li><span class="c-ic">{guide_art.icon(n)}</span><div>{t}</div></li>' for t, n in zip(its, card["icons"])) + f"</{tag}>" + h[m.end():]
                tile_icons.update(card["icons"])
            if sec.get("ticks"):   # approved 26 Oct 2026: tick the questions you want to ask (not saved or sent)
                m = re.search(r"<ul>(.*?)</ul>", h, re.S); its = re.findall(r"<li>(.*?)</li>", m.group(1), re.S)
                h = h[:m.start()] + '<ul class="a-qs">' + "".join(f'<li><label><input type="checkbox"> <span>{t}</span></label></li>' for t in its) + "</ul>" + h[m.end():]
                head_extra = f'<p class="small muted a-qhint">{sec["ticks"]}</p>'
            cls = " " + sec["class"] if sec.get("class") else ""
            if card:
                cls += " c-help" if card.get("path") else " c-sit" + (" c-wide" if card.get("wide") else "")
                sec_html.append(f'<section class="g-sec{cls}" id="{sec["id"]}" aria-labelledby="{gid}-{sec["id"]}-h"><header class="c-sit-h">'
                                f'<span class="c-art" aria-hidden="true">{guide_art.conc_art(card["art"])}</span><h2 id="{gid}-{sec["id"]}-h">{E(sec["title"])}</h2></header>{cite(h)}</section>')
            else:
                sec_html.append(f'<section class="g-sec{cls}" id="{sec["id"]}" aria-labelledby="{gid}-{sec["id"]}-h"><h2 id="{gid}-{sec["id"]}-h">{E(sec["title"])}</h2>{head_extra}{cite(h)}</section>')
        sec_ids.append(sec["id"])
        if sec.get("toc", True): toc.append((sec["id"], sec.get("short", sec["title"])))   # minor sections stay out of the chip row
    ev = "".join(f'<li><span class="g-lv g-lv-{E(x["kind"])}">{E(x["level"])}</span> {cite(x["text"])}</li>' for x in G["evidence"])
    sec_html.append(f'<section class="g-sec g-ev" id="research" aria-labelledby="{gid}-ev-h"><h2 id="{gid}-ev-h">What the research says</h2>'
                    f'<ul class="g-ev-list">{ev}</ul>' + (f'<p class="small muted">{cite(G["evidenceNote"])}</p>' if G.get("evidenceNote") else "") + "</section>")
    toc.append(("research", "The research")); sec_ids.append("research")
    groups = {x["id"]: x.get("group") for x in G["sections"]}
    merged, ids2 = [], []
    for sid, h in zip(sec_ids, sec_html):   # consecutive sections with the same "group" share one wrapper (Concentration: the situations)
        g = groups.get(sid)
        if g and ids2 and groups.get(ids2[-1]) == g: merged[-1] = merged[-1][:-len("</div>")] + h + "</div>"
        else: merged.append(f'<div class="c-where">{h}</div>' if g else h)
        ids2.append(sid)
    sec_html = merged
    if L and L["style"] == "stages":
        # Approved 26 Oct 2026: five stages in order, a step navigator that stays in view on desktop (with the print action),
        # and the stage the reader is in marked in the navigator (js). Everything stays on the page; nothing is collapsed.
        now_html = body.pop()                     # stage 1's box, built by now_section
        blocks = dict(zip(sec_ids, sec_html)); used_ids = set(); stages = ""
        for k, st in enumerate(L["stages"]):
            inner = ""
            for part in st["parts"]:
                inner += now_html if part == "now" else blocks[part]; used_ids.add(part)
            stages += (f'<div class="a-stage" id="stage-{k + 1}"><div class="a-stage-mark" aria-hidden="true"><span class="a-sn">{k + 1}</span><span class="a-line"></span></div>'
                       f'<div class="a-stage-body"><p class="a-kicker">{guide_art.icon(st["icon"])}Step {k + 1} · {E(st["label"])}</p>{inner}</div></div>')
            tile_icons.add(st["icon"])
        tops = {i: t for i, t in toc}
        rail = (f'<nav class="g-toc a-stages" aria-label="On this page"><span class="g-toc-h">{E(L["railTitle"])}</span><ol>'
                + "".join(f'<li><a href="{path}#{"before" if st["parts"][0] == "now" else st["parts"][0]}" data-stage="stage-{k + 1}"><span class="a-sn">{k + 1}</span><span class="a-sl">{E(st["label"])}</span></a></li>'
                          for k, st in enumerate(L["stages"]))
                + f'</ol><p class="a-rail-print"><button type="button" class="btn btn-primary" data-print="{L["print"]}">{guide_art.icon("check-list")}{E(L["printLabel"])}</button></p>'
                + '<p class="a-sub small">Also on this page: ' + " · ".join(f'<a href="{path}#{i}">{E(tops.get(i, i))}</a>' for i in L["also"]) + "</p></nav>")
        body.append(f'<div class="a-wrap">{rail}<div class="a-flow">{stages}</div></div>')
        sec_html = [h for sid, h in zip(ids2, sec_html) if sid not in used_ids]
    else:
        body.append('<nav class="g-toc" aria-label="On this page"><span class="g-toc-h">On this page</span><ul>'
                    + "".join(f'<li><a href="{path}#{i}">{E(t)}</a></li>' for i, t in toc) + "</ul></nav>")
    if L and L.get("later"): body.append(f'<p class="o-later"><span>{E(L["later"])}</span></p>')
    if tile_icons: body.append(f'<!--sprite:{" ".join(sorted(tile_icons))}-->')
    body.extend(sec_html)
    rel_tiles = tile_items(G.get("related", []))
    body.append(f'<section class="help-entry g-related" aria-labelledby="{gid}-rel-h"><h2 class="help-q" id="{gid}-rel-h">You might also find helpful</h2>'
                f'<ul class="help-grid">{rel_tiles}</ul><p class="help-urgent">{PG["urgentLine"]}</p></section>')
    srcs = "".join(f'<li id="src-{E(x["key"])}">{E(x["cite"])}' + (f' <a href="{E(x["url"])}" rel="noopener">{E(x.get("linkText", "Source"))}</a>' if x.get("url") else "") + "</li>" for x in G["sources"])
    body.append(f'<section class="g-sources" aria-labelledby="{gid}-src-h"><h2 id="{gid}-src-h">Sources</h2><ol class="small">{srcs}</ol>'
                f'<p class="small muted">Last reviewed {E(G["lastReviewed"])}. Educational information, not a diagnosis and not medical advice; it has not been reviewed by a clinician. '
                f'Spotted something wrong? Tell us through the <a href="about.html#corrections">corrections process</a>.</p></section>')
    canon = page(path + "index.html", G["metaTitle"], G["metaDesc"], E(G["title"]),
                 [("", "Home"), ("living/", "Living with tinnitus"), (None, G["crumb"])], "\n".join(body), modified=G["lastReviewed"],
                 main_cls=" g-page" + ({"harbour": " o-page", "groups": " c-page", "stages": " a-page"}.get(L["style"], "") if L else ""),
                 extra_css='\n<link rel="stylesheet" href="css/guides.css">' if L else "",
                 crumb_extra=(f'<a class="crumb-help" href="{path}#{L["crisis"]}">{E(L["crumbLink"])}</a>' if L and L.get("crumbLink") else ""))
    sitemap_urls.append(canon); LASTMOD[canon] = G["lastReviewed"]

for _gid, _G in PG.get("guides", {}).items():
    guide_page(_gid, _G)

canon = page("living/index.html", "Living with Tinnitus: Practical Help and Next Steps | Tinnitus Evidence",
             "Practical, evidence-based guides for living with tinnitus: new tinnitus, sleep, feeling overwhelmed, concentration, appointments, spikes, sound sensitivity, social life and travel, and family.",
             "Living with tinnitus", [("", "Home"), (None, "Living with tinnitus")], living_body, modified=PG["lastReviewed"], main_cls=" lw-hub")
sitemap_urls.append(canon); LASTMOD[canon] = PG["lastReviewed"]

# data/guide-index.json: a few KB the browser can fetch instead of the full guide data. Used by Search ("Guide" results),
# the Profile ("Practical guides for you") and the interactive treatment page (same "Practical help" block as static pages).
def _plain(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>|\[\[[^\]]+\]\]", "", x or ""))).strip()
_gi = {"_comment": "Generated by tools/build_seo.py from data/patient-guides.json. Do not edit.",
       "guides": [{"id": k, "path": g["path"], "title": g["title"], "desc": g.get("tileDesc") or next(n["desc"] for n in PG_NEEDS if n["id"] == k),
                   "terms": _plain(" ".join([g["metaTitle"], g["metaDesc"], g["lead"]] + [x.get("title", "") for x in g.get("sections", [])]))} for k, g in PG_GUIDES.items()],
       "treatmentLinks": {tid: [[pg_href(r), lbl, pg_title(r)] for r, lbl in v] for tid, v in sorted(PG.get("treatmentLinks", {}).items())}}
_gip = ROOT / "data" / "guide-index.json"
_gtxt = json.dumps(_gi, ensure_ascii=False, indent=1) + "\n"
if not _gip.exists() or _gip.read_text(encoding="utf-8") != _gtxt:
    _gip.write_text(_gtxt, encoding="utf-8", newline="\n")

# ---------------- Research Questions (hypotheses — NEVER data-driven) ----------------
# CONTENT POLICY: this section is authored and human-approved IN THIS SCRIPT, never generated
# from data/*.json and never writable by the weekly pipeline. The automation may flag candidate
# hypotheses into the held review queue, but nothing publishes here without a human editing this
# file. Every item carries the hypothesis banner — these are not evidence records.
HYPO_BANNER = """<div class="hypo-banner" role="note"><span class="tag">HYPOTHESIS</span>
<span>Research hypothesis — not established evidence</span></div>"""

rq_cites = """<section><h2>Sources</h2><ul class="small">
<li>van der Wal AC, et al. Prognostic indicators for positive treatment outcome after multidisciplinary orofacial treatment in patients with somatosensory tinnitus. Front Neurosci 2020. <a href="https://pubmed.ncbi.nlm.nih.gov/33041758/" rel="noopener">PMID 33041758</a></li>
<li>Spencer S, et al. Bimodal (auditory and electrical) stimulation for tinnitus — feasibility and predictor analysis. Front Neurosci 2022. <a href="https://pubmed.ncbi.nlm.nih.gov/36090280/" rel="noopener">PMID 36090280</a></li>
<li>Lee HY, et al. Retrospective analysis of somatic modulation and treatment outcome in a tinnitus clinic. J Int Adv Otol 2020. <a href="https://pubmed.ncbi.nlm.nih.gov/32784160/" rel="noopener">PMID 32784160</a></li>
<li>Low WK, et al. Electroacupuncture in somatic vs non-somatic tinnitus. Med Acupunct 2017. <a href="https://pubmed.ncbi.nlm.nih.gov/28736590/" rel="noopener">PMID 28736590</a></li>
<li>Vanneste S, et al. Transcutaneous electrical nerve stimulation (C2) in 240 patients selected for somatosensory modulation. Exp Brain Res 2010. <a href="https://pubmed.ncbi.nlm.nih.gov/20505927/" rel="noopener">PMID 20505927</a></li>
<li>Jones GR, …, Shore SE. Bisensory stimulation randomized clinical trial (incl. supplementary eFigure 7). JAMA Netw Open 2023. <a href="https://pubmed.ncbi.nlm.nih.gov/37266943/" rel="noopener">PMID 37266943</a></li>
<li>Rocha CB, Sanchez TG. Myofascial trigger-point deactivation RCT with modulation-direction analysis. Braz J Otorhinolaryngol 2012. <a href="https://pubmed.ncbi.nlm.nih.gov/23306563/" rel="noopener">PMID 23306563</a></li>
<li>D'Arcy S, et al. TENT-A1 trial protocol (prespecified somatic-subtype analysis). BMJ Open 2017. <a href="https://pubmed.ncbi.nlm.nih.gov/29074518/" rel="noopener">PMID 29074518</a></li>
<li>Levine RA, et al. Somatic testing and treatment-subgroup proposal. Prog Brain Res 2007. <a href="https://pubmed.ncbi.nlm.nih.gov/17956783/" rel="noopener">PMID 17956783</a></li>
<li>Won JY, et al. Modulation-characteristics candidate-selection proposal. Audiol Neurootol 2013. <a href="https://pubmed.ncbi.nlm.nih.gov/23881235/" rel="noopener">PMID 23881235</a></li>
</ul>
<p class="small muted">Summaries are original to Tinnitus Evidence, written from the sources above during an
adversarial precedent audit (September 2026); they are not publisher abstracts.</p></section>"""

rq_body = HYPO_BANNER + """
<section><h2>The question in plain language</h2>
<p>Many people can temporarily change their tinnitus — its loudness, pitch, or character — by moving or
tensing the jaw, neck, or head, or by pressing on certain muscles. This is common: studies report that
roughly 56–80% of people with tinnitus show some modulation on formal maneuver testing.</p>
<p>Researchers have already asked the obvious question: does simply HAVING this ability predict who will
respond to treatments that engage the body–hearing connection (bimodal stimulation devices, cervical or
jaw-focused physiotherapy, related neuromodulation)? So far, that simple yes/no characteristic has generally
<strong>not</strong> been a useful predictor.</p>
<p>A narrower possibility remains open: the <strong>number</strong> of maneuvers that change the tinnitus,
the <strong>direction</strong> of the change (louder vs quieter), the <strong>size</strong> of the change,
and how <strong>consistently</strong> the same response occurs may carry more information than mere presence.
This remains unproven.</p></section>

<section><h2>Evidence for the refined question</h2>
<ul>
<li><strong>Shore/Jones 2023 (bisensory device RCT):</strong> in a supplementary analysis, participants for whom
MORE maneuvers changed their tinnitus showed greater questionnaire (TFI) improvement during active treatment —
and not during control or washout phases. Important caveats: this was a post-hoc correlation (r ≈ 0.3), inside a
trial that only enrolled people who could modulate, so it cannot say anything about non-modulators.</li>
<li><strong>Rocha &amp; Sanchez 2012 (trigger-point therapy RCT):</strong> the DIRECTION of modulation at baseline
mattered — people whose tinnitus temporarily decreased when a trigger point was pressed were more likely to have
lasting relief after treatment (p=0.002).</li>
<li><strong>Related phenotype signals:</strong> in cervical physiotherapy studies, self-reported co-variation of
tinnitus with neck complaints — and history-based somatic-association scores — have predicted response better
than maneuver testing itself.</li>
</ul>
<p class="small muted">These are associations, not demonstrations of prediction. None comes from a study designed
and powered to test the question.</p></section>

<section><h2>Evidence against the simple version</h2>
<p>The binary form of this idea — "can modulate" vs "cannot" — has been tested directly and has generally not
held up:</p>
<ul>
<li><strong>van der Wal 2020</strong> (N=101, multidisciplinary orofacial treatment): explicitly expected stronger
somatic influence to mean larger treatment effects; ability to modulate was <em>not</em> identified as a prognostic
indicator. Shorter tinnitus duration, painful jaw-muscle palpation and other characteristics predicted outcome instead.</li>
<li><strong>Spencer 2022</strong> (N=29, bimodal auditory + electrical stimulation): baseline modulation ability did
not predict outcome — though with only six modulators, the test was severely underpowered.</li>
<li><strong>Lee 2020</strong> (N=81, retrospective clinic series): modulation status was unrelated to improvement;
only age predicted outcome.</li>
<li><strong>Low 2017</strong> (N=27, electroacupuncture): no overall outcome difference between somatic and
non-somatic groups (a post-hoc signal favored people whose maneuver responses were <em>consistent</em>).</li>
<li><strong>Vanneste 2010</strong> (N=240, electrical stimulation at C2): every participant was selected for
somatosensory modulation — yet only 17.9% responded. Being a modulator clearly does not guarantee response to a
somatosensory treatment.</li>
</ul>
<p>With modulation present in roughly 56–80% of patients, the simple yes/no trait appears too common and too
weakly discriminating to work as a biomarker by itself. That is a finding about the <em>simple</em> version — it
does not settle the refined, graded question above.</p></section>

<section><h2>An unanswered Lenire/TENT-A1 question</h2>
<p>The first large Lenire trial (TENT-A1, 326 participants) collected baseline somatic-modulation data using a
standardized 25-maneuver assessment performed by a physiotherapist, and its published protocol prespecified an
efficacy analysis by somatic-tinnitus status, to be reported in a subsequent publication. In our literature audit
(through September 2026), <strong>we did not identify a published report of the prespecified somatic-subgroup
analysis</strong>. The existing dataset may therefore contain information relevant to this question.</p></section>

<section><details><summary><strong>Refined hypothesis (technical wording)</strong></summary>
<p>In interventions engaging auditory–somatosensory integration, graded features of baseline somatic modulation —
including the number of effective maneuvers, direction of induced change, magnitude of change, and test–retest
consistency — may predict treatment response more effectively than the simple presence or absence of modulation.</p>
<p><strong>This has not yet been established in an adequately powered, prespecified prospective test.</strong></p>
</details></section>

<section><h2>How researchers could test this</h2>
<p><strong>Lowest-cost approach:</strong> analyze existing datasets that already collected standardized
somatic-modulation measurements — prioritizing TENT-A1, if the relevant baseline data and outcomes are available.</p>
<p><strong>Next step:</strong> add a standardized baseline modulation battery to ongoing bimodal or somatosensory
tinnitus trials, and prespecify the interaction analysis before outcomes are known.</p>
<p><strong>Definitive test:</strong> a prospective controlled study enrolling participants across the full
modulation spectrum, with a standardized baseline maneuver battery, a prespecified modulation × treatment
interaction, and a percept-level tinnitus outcome — not only distress/severity questionnaires.</p></section>

<section><h2>What would disprove this?</h2>
<p>The refined hypothesis would be weakened or rejected if: graded modulation features fail to predict response in
adequately powered studies; the same apparent relationship appears in matched control groups (indicating a
non-specific effect); test–retest modulation measurements prove too unreliable to carry a signal; stronger baseline
predictors fully account for the association; or independent datasets do not reproduce it. The hypothesis is
falsifiable, and several of these tests are inexpensive.</p></section>

<section><h2>Why this question matters</h2>
<p>If a simple baseline test could identify who is more likely to respond to a particular tinnitus treatment,
future trials could become more targeted and less likely to dilute subgroup effects. <strong>But current evidence
is not strong enough to use somatic modulation for clinical treatment selection.</strong></p>
<p>Somatic-modulation characteristics are being investigated as potential response predictors, but they are not
established tools for selecting tinnitus treatment. Nothing on this page is a treatment recommendation.</p></section>

<section><h2>Novelty and precedent</h2>
<p>This is not a new idea in its broad form. Researchers have proposed somatic testing for treatment selection
since at least 2007 (Levine; later Won 2013), and binary somatic-modulation predictors have been tested before,
with mostly null results. The remaining research question concerns whether more detailed, graded modulation
characteristics carry predictive information.</p></section>
""" + rq_cites

canon = page("research-questions/somatic-modulation-treatment-response/index.html",
             "Can Somatic Tinnitus Modulation Predict Treatment Response? | Tinnitus Evidence",
             "Review the evidence on whether jaw, neck and other somatic tinnitus modulation patterns may help predict treatment response, including supporting and contradictory studies.",
             "Could patterns of somatic tinnitus modulation help predict treatment response?",
             [("", "Home"), ("research-questions/", "Research questions"), (None, "Somatic modulation & treatment response")],
             rq_body, article={"headline": "Could patterns of somatic tinnitus modulation help predict treatment response?", "published": "2026-09-05"})
sitemap_urls.append(canon)

rq_dir = """
<p class="muted" style="margin-top:-8px;font-size:1.05rem">Patterns in the evidence that may deserve further investigation</p>
<p class="lead">Tinnitus Evidence reviews published research, but some important questions remain unresolved.
This section highlights patterns that emerge across multiple studies and may be worth testing further.
<strong>These are hypotheses, not treatment recommendations or established medical conclusions.</strong></p>
""" + HYPO_BANNER + """
<section class="card rq-card rq-open"><h2>Open questions</h2>
<ul>
<li><a href="research-questions/somatic-modulation-treatment-response/">Could patterns of somatic tinnitus
modulation help predict treatment response?</a> — the simple yes/no version has been tested (mostly null);
whether graded modulation features carry predictive information remains open.</li>
</ul></section>
<section class="card rq-card rq-process"><h2>How a research hypothesis earns a place here</h2>
<p class="small muted rq-distinction">Note the distinction: <a href="ask/">Ask Tinnitus Evidence</a> answers <em>your</em> questions
about the existing evidence. This section lists unresolved <em>scientific hypotheses</em> — patterns across studies
that may deserve formal investigation. They never affect treatment ratings, tiers, or rankings.</p>
<p>Every entry follows the same process before publication:</p>
<p class="small rq-flow"><strong><span class="step">Pattern identified</span> <span class="arrow">→</span> <span class="step">adversarial literature search</span> <span class="arrow">→</span> <span class="step">precedent check</span> <span class="arrow">→</span> <span class="step">contradictory-evidence
search</span> <span class="arrow">→</span> <span class="step">hypothesis refined or rejected</span> <span class="arrow">→</span> <span class="step">human approval</span> <span class="arrow">→</span> <span class="step">publication.</span></strong></p>
<p class="small muted">Hypotheses are never auto-published. The research automation may flag candidate
questions internally for review, but nothing appears in this section without an adversarial precedent audit and
explicit human approval — and being listed here never affects any treatment's evidence rating, tier, or ranking.
Unlike evidence records, entries here carry no evidence scores.</p></section>"""
canon = page("research-questions/index.html",
             "Research Questions in Tinnitus | Tinnitus Evidence",
             "Patterns in the tinnitus evidence that may deserve further investigation — clearly labeled research hypotheses, with supporting and contradictory studies, never treatment recommendations.",
             "Research Questions",
             [("", "Home"), (None, "Research questions")], rq_dir)
sitemap_urls.append(canon)

# ---------------- Ask Tinnitus Evidence (tool page; endpoint configured in /ask-config.js) ----------------
ask_body = """
<p class="lead"><strong>Ask a question about tinnitus treatments, studies, trials, evidence strength, safety,
or research findings.</strong> Answers are generated from the Tinnitus Evidence research database and linked sources.</p>
<p class="small muted">This tool provides research information, not diagnosis or personalized medical advice. Answers are generated automatically from this site's database. <a href="about.html#review">Who prepares this site</a></p>

<div class="card ask-panel">
  <form id="ask-form">
    <label for="ask-q" class="ask-label">Your question</label>
    <div class="ask-row-in">
      <input id="ask-q" class="ask-input" type="text" maxlength="350" placeholder="Ask a tinnitus research question…">
      <button class="btn btn-primary ask-submit" type="submit" id="ask-btn">Ask</button>
    </div>
  </form>
  <p class="small muted" style="margin:10px 0 0">Answers are generated with AI from Tinnitus Evidence's verified
  research database. AI does not determine treatment ratings or rankings. Evidence ratings, safety assessments,
  rankings, and major research conclusions remain subject to the site's human-review rules.
  Looking for a specific study or treatment? <a href="search.html">Search the database →</a></p>
  <p class="small" id="ask-help" style="margin:10px 0 0">Ask is an automated research tool and can’t recognise every urgent situation. Struggling right now? <a href="support/#crisis">Find support</a> · Worried about a symptom? <a href="urgent/">When to get help quickly</a></p>
</div>

<div id="ask-status" role="status" aria-live="polite" class="small muted" style="position:absolute;left:-9999px"></div>
<div id="ask-loading" class="ask-loading" hidden>
  <span class="ask-spin" aria-hidden="true"></span>
  <div style="flex:1;min-width:0">
    <div id="ask-loading-text" class="small" style="font-weight:600">Searching the evidence database…</div>
    <div class="bar" aria-hidden="true"><i></i></div>
  </div>
</div>
<div id="ask-answer" class="prose" hidden></div>
<div id="ask-sources" hidden></div>
<div id="ask-followups" hidden></div>

<div id="ask-examples">
<h2>Try a question</h2>
<ul class="ask-ex-grid">
  <li><button class="btn ask-ex" type="button">What tinnitus treatments currently have the strongest evidence?</button></li>
  <li><button class="btn ask-ex" type="button">What does the evidence say about Lenire?</button></li>
  <li><button class="btn ask-ex" type="button">Compare Lenire and the Michigan Shore treatment.</button></li>
  <li><button class="btn ask-ex" type="button">Which treatments have evidence for reducing tinnitus loudness?</button></li>
  <li><button class="btn ask-ex" type="button">Which tinnitus treatments have failed in controlled trials?</button></li>
  <li><button class="btn ask-ex" type="button">What are researchers currently investigating?</button></li>
</ul>
</div>

<script src="ask-config.js"></script>
<script>
(function(){
  var EP = window.ASK_ENDPOINT || "";
  var $ = function(s){ return document.querySelector(s); };
  var form=$("#ask-form"), q=$("#ask-q"), btn=$("#ask-btn"), st=$("#ask-status"),
      ans=$("#ask-answer"), src=$("#ask-sources"), fu=$("#ask-followups"), ex=$("#ask-examples"),
      ld=$("#ask-loading"), ldt=$("#ask-loading-text");
  var STAGES=["Searching the evidence database…","Reading the most relevant studies…",
              "Checking loudness vs distress outcomes…","Writing a sourced answer…","Validating citations…"];
  var stageTimer=null;
  function startLoading(){
    var i=0; ld.hidden=false; ldt.textContent=STAGES[0]; st.textContent=STAGES[0];
    stageTimer=setInterval(function(){ i=Math.min(i+1,STAGES.length-1); ldt.textContent=STAGES[i];
      if(i===STAGES.length-1) clearInterval(stageTimer); else st.textContent=STAGES[i]; },2600);
  }
  function stopLoading(){ if(stageTimer){clearInterval(stageTimer);stageTimer=null;} ld.hidden=true; st.textContent=""; }
  function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  function inline(s){ // links + bold only, on escaped text
    return esc(s)
      .replace(/\\[([^\\]]+)\\]\\(([^)\\s]+)\\)/g, function(m,t,u){
        var safe=/^(https:\\/\\/(pubmed\\.ncbi\\.nlm\\.nih\\.gov|doi\\.org|clinicaltrials\\.gov)\\/|treatments\\/|research\\/|trials\\/|guides\\/|research-questions\\/|about\\.html|search\\.html)/.test(u);
        return safe? '<a href="'+u+'"'+(u.indexOf("https:")===0?' rel="noopener"':'')+'>'+t+'</a>' : t; })
      .replace(/\\*\\*([^*]+)\\*\\*/g,"<strong>$1</strong>");
  }
  function md(text){ // minimal renderer: ###, lists, tables, paragraphs
    var out=[], lines=text.split(/\\r?\\n/), i=0;
    while(i<lines.length){
      var L=lines[i];
      if(/^###\\s+/.test(L)){ out.push("<h3>"+inline(L.replace(/^###\\s+/,""))+"</h3>"); i++; continue; }
      if(/^\\s*[-*]\\s+/.test(L)){ var items=[]; while(i<lines.length && /^\\s*[-*]\\s+/.test(lines[i])){ items.push("<li>"+inline(lines[i].replace(/^\\s*[-*]\\s+/,""))+"</li>"); i++; }
        out.push("<ul>"+items.join("")+"</ul>"); continue; }
      if(/^\\s*\\|/.test(L)){ var rows=[]; while(i<lines.length && /^\\s*\\|/.test(lines[i])){ rows.push(lines[i]); i++; }
        var html="<div style='overflow-x:auto'><table>"; rows.forEach(function(rw,ri){
          if(/^\\s*\\|[\\s:-]+\\|/.test(rw.replace(/[^|:\\s-]/g,"x"))&&/^[|\\s:-]+$/.test(rw)) return;
          var cells=rw.split("|").slice(1,-1); var tag=ri===0?"th":"td";
          html+="<tr>"+cells.map(function(c){return "<"+tag+">"+inline(c.trim())+"</"+tag+">";}).join("")+"</tr>"; });
        out.push(html+"</table></div>"); continue; }
      if(L.trim()==""){ i++; continue; }
      var para=[L]; i++;
      while(i<lines.length && lines[i].trim()!="" && !/^(###|\\s*[-*]\\s|\\s*\\|)/.test(lines[i])){ para.push(lines[i]); i++; }
      out.push("<p>"+inline(para.join(" "))+"</p>");
    }
    return out.join("");
  }
  function unavailable(){
    stopLoading();
    ans.hidden=false;
    ans.innerHTML="<div class='notice'>Ask Tinnitus Evidence is temporarily unavailable. You can still search "+
      "<a href='treatments/'>treatments</a>, <a href='research/'>studies</a> and <a href='trials/'>trials</a> directly.</div>";
  }
  // Distress tier (worker sets res.support): a calm panel above the answer. Lines mirror data/safety.json.
  var SUPPORT_PANEL="<div class='notice' role='note' style='margin:0 0 14px'><p style='margin:0 0 6px'><strong>If tinnitus feels overwhelming, you're not alone, and support can help.</strong> "+
    "Talking therapies such as cognitive behavioural therapy (CBT) have the strongest evidence for reducing tinnitus distress.</p>"+
    "<p class='small' style='margin:0'>If you're thinking about suicide, talk to someone now: US <strong>988</strong> · UK &amp; Ireland <strong>116 123</strong> · "+
    "Canada <strong>9-8-8</strong> · Australia <strong>13 11 14</strong> · New Zealand <strong>1737</strong> · elsewhere <a href='https://findahelpline.com/'>findahelpline.com</a>. "+
    "<a href='support/#crisis'>More support and crisis lines</a></p></div>";
  function render(res){
    stopLoading();
    ans.hidden=false; ans.innerHTML=(res.support? SUPPORT_PANEL : "")+md(res.answer||"");
    if(res.sources && res.sources.length){
      src.hidden=false;
      src.innerHTML="<h3 style='margin-top:18px'>Sources</h3><ul class='small'>"+res.sources.map(function(s){
        var extra=s.pmid? ' · <a rel="noopener" href="https://pubmed.ncbi.nlm.nih.gov/'+esc(s.pmid)+'/">PubMed '+esc(s.pmid)+"</a>":"";
        return "<li><a href='"+esc(s.href)+"'>"+esc(s.label)+"</a>"+extra+"</li>"; }).join("")+"</ul>"+
        "<p class='small muted'>Coverage in the database: "+esc(res.coverage||"")+".</p>";
    } else { src.hidden=true; }
    if(res.followups && res.followups.length){
      fu.hidden=false;
      fu.innerHTML="<h3>Follow-up questions</h3><div style='display:flex;flex-wrap:wrap;gap:8px'>"+
        res.followups.map(function(f){ return "<button type='button' class='btn ask-ex'>"+esc(f)+"</button>"; }).join("")+"</div>";
      wireExamples();
    } else { fu.hidden=true; }
    ans.scrollIntoView({behavior:"smooth",block:"start"});
  }
  function submit(question){
    if(!EP){ unavailable(); return; }
    btn.disabled=true; ex.hidden=true;
    ans.hidden=true; src.hidden=true; fu.hidden=true;
    startLoading();
    fetch(EP,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:question})})
      .then(function(r){ return r.json().then(function(j){ return {okStatus:r.ok, j:j}; }); })
      .then(function(x){
        if(x.j && x.j.answer){ render(x.j); }
        else if(x.j && x.j.message){ stopLoading(); ans.hidden=false; ans.innerHTML="<div class='notice'>"+esc(x.j.message)+"</div>"; }
        else unavailable();
      })
      .catch(unavailable)
      .finally(function(){ btn.disabled=false; });
  }
  form.addEventListener("submit",function(e){ e.preventDefault(); var v=q.value.trim(); if(v) submit(v); });
  function wireExamples(){
    document.querySelectorAll(".ask-ex").forEach(function(b){
      b.onclick=function(){ q.value=b.textContent; q.focus(); submit(b.textContent); };
    });
  }
  wireExamples();
})();
</script>"""

canon = page("ask/index.html",
             "Ask Tinnitus Evidence: Evidence-Based Answers About Tinnitus Research | Tinnitus Evidence",
             "Ask a question about tinnitus treatments, studies, trials, evidence strength or safety — answers generated from the verified Tinnitus Evidence research database, with sources.",
             "Ask Tinnitus Evidence",
             [("", "Home"), (None, "Ask")], ask_body)
sitemap_urls.append(canon)
# the page loads its endpoint from the root config (kept outside the generator so enabling
# the feature never requires regenerating pages); create a disabled default if absent
_cfg = ROOT / "ask-config.js"
if not _cfg.exists():
    _cfg.write_text('// Ask Tinnitus Evidence endpoint. Empty string = feature disabled (page shows a graceful\n'
                    '// unavailable message). Set to the deployed Cloudflare Worker URL to enable.\n'
                    'window.ASK_ENDPOINT = "";\n', encoding="utf-8")

# ---------------- static-stat sync (single source of truth: the database) ----------------
# Elements marked data-stat="…" in hand-authored pages (index.html, about.html) get their text
# refreshed from data/ on every build — the weekly workflow runs this, so visible counts can
# never drift from the database again, and crawlers/no-JS visitors see real values, not dashes.
def _fmt_date(iso):
    y, m, d = iso.split("-")
    months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[int(m)]} {int(d)}, {y}"

_weekly_idx = json.loads((ROOT / "data" / "weekly" / "index.json").read_text(encoding="utf-8"))
_last_scan = (_weekly_idx.get("reports") or [{}])[0].get("date") or meta.get("lastFullReview", TODAY)
STATS = {"treatments": str(len(treatments)), "records": str(len(studies)), "trials": str(len(trials)),
         "lastReview": _fmt_date(meta.get("lastFullReview", TODAY)),
         "lastScan": _fmt_date(_last_scan)}   # newest weekly report = last automated research scan
for fname in ("index.html", "about.html"):
    p = ROOT / fname
    h = p.read_text(encoding="utf-8")
    orig = h
    for key, val in STATS.items():
        h = re.sub(r'(data-stat="' + key + r'"[^>]*>)[^<]*(</)', r"\g<1>" + val + r"\g<2>", h)
    if h != orig:
        p.write_text(h, encoding="utf-8")
        print(f"stats synced into {fname}")

# ---------------- Emerging & Unproven: static fallback (single source of truth: data/emerging-unproven.json) ----------------
# The interactive page builds its cards from the data file at runtime. The same data file generates a compact,
# visible static list inside #eu-app — name, evidence situation, one-line summary, deep link — for crawlers and
# no-JS readers. js/emerging-unproven.js attaches a shadow root to #eu-app, which hides this light-DOM fallback the
# moment the interactive page mounts, so the two are never shown (or exposed to assistive tech) together.
# tools/check_seo.py verifies that the list and the data file agree (count, ids, names).
def sync_emerging_static():
    p = ROOT / "emerging-unproven" / "index.html"
    if not p.exists():
        return
    d = json.loads((ROOT / "data" / "emerging-unproven.json").read_text(encoding="utf-8"))
    h = p.read_text(encoding="utf-8")
    shell = re.search(r'<template id="eu-shell">([\s\S]*?)</template>', h)
    sh = shell.group(1) if shell else ""
    m1 = re.search(r"<h1>(.*?)</h1>", sh)
    h1 = m1.group(1) if m1 else "Emerging, Experimental &amp; Unproven Tinnitus Treatments"
    sub = re.search(r'<p class="sub">(.*?)</p>', sh)
    meta_line = re.search(r'<p class="meta">(.*?)</p>', sh)
    intro = "".join(re.findall(r'<p class="(?:intro|keyline)">[\s\S]*?</p>', sh))
    groups = []
    for cat in d["ORDER"]:
        sit = d["SIT"][cat]
        items = "".join(
            f'<li id="{E(t["id"])}"><strong><a href="#{E(t["id"])}">{E(t["name"])}</a></strong>'
            + (f' <span class="muted">— {E(t["alt"])}</span>' if t.get("alt") else "")
            + f'<br><small>Evidence situation: {E(sit["short"])}</small><br>{E(t["tells"])}</li>'
            for t in d["T"] if t["cat"] == cat)
        groups.append(f'<h2>{E(sit["label"])}</h2><p class="muted">{E(sit["mean"])}</p><ul>{items}</ul>')
    block = ('<!-- eu-static:start (generated by tools/build_seo.py from data/emerging-unproven.json — do not edit by hand) -->\n'
             f'<div class="eu-static wrap"><h1>{h1}</h1>'
             + (f'<p><strong>{sub.group(1)}</strong></p>' if sub else "")
             + (f'<p class="small muted">{meta_line.group(1)}</p>' if meta_line else "")
             + intro
             + f'<p>{len(d["T"])} treatments and claims, grouped by evidence situation. With JavaScript on, this page adds filters, search and the full evidence detail behind each entry.</p>'
             + "".join(groups) + "</div>\n<!-- eu-static:end -->")
    if "<!-- eu-static:start" not in h or "<!-- eu-static:end -->" not in h:
        raise SystemExit("emerging-unproven/index.html has no <!-- eu-static:start/end --> markers")
    new = re.sub(r"<!-- eu-static:start[\s\S]*?<!-- eu-static:end -->", lambda _m: block, h, count=1)
    if new != h:
        p.write_text(new, encoding="utf-8")
        print(f"emerging static fallback synced: {len(d['T'])} entries")
sync_emerging_static()

# ---------------- sitemap + production robots + redirect map ----------------
(ROOT / "sitemap.xml").write_text(
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    "\n".join(f"  <url><loc>{E(u)}</loc><lastmod>{LASTMOD.get(u, TODAY)}</lastmod></url>" for u in sorted(set(sitemap_urls))) +
    "\n</urlset>\n", encoding="utf-8")

(ROOT / "robots-production.txt").write_text(f"""# Tinnitus Evidence — PRODUCTION robots.txt
# Deploy as robots.txt ONLY as the final launch action, after the scientific launch gate
# (production AI benchmark) and the SEO gate both pass.
User-agent: *
Disallow: /admin.html
Disallow: /preview.html
Allow: /

Sitemap: {PROD}/sitemap.xml
""", encoding="utf-8")

docs = ROOT / "docs"; docs.mkdir(exist_ok=True)
(docs / "redirect-map.md").write_text(f"""# Redirect / canonical map (prepared {TODAY})

Preferred host: **{PROD}** (non-www). At DNS setup: configure `www.tinnitusevidence.com` -> 301 -> `tinnitusevidence.com`,
HTTP -> HTTPS (GitHub Pages custom-domain HTTPS enforcement), one hostname only.

| Old URL | New canonical | Mechanism |
|---|---|---|
| https://debra-lang.github.io/atlas-preview/* | {PROD}/* | GitHub Pages serves one site; after custom domain is set, github.io URLs 301 to the domain automatically |
| /treatment.html?id=&lt;id&gt; | /treatments/&lt;id&gt;/ | JS-injected rel=canonical (app.js) + internal links point to clean URLs |
| /treatments.html | /treatments/ | rel=canonical (interactive browser remains linked as a tool) |
| /trials.html | /trials/ | rel=canonical |
| /index.html | / | rel=canonical |
| trailing-slash variants /x/ vs /x/index.html | /x/ | rel=canonical on every generated page |
| Tinnitus Atlas-era URLs | none existed publicly (repo was always atlas-preview; only the github.io preview circulated) | covered by the github.io redirect row |

No redirect chains: every mapping is one hop. Never redirect unrelated missing pages to the homepage (404.html serves real 404s).
""", encoding="utf-8")

print(f"SEO build: {len(treatments)} treatment pages, {len(trials)} trial pages, {len(studies)} research pages, "
      f"6 guide/directory pages, {len(CL['claims']) + 2 if CL else 0} claims pages, sitemap {len(set(sitemap_urls))} URLs")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tinnitus Evidence — static SEO prerender.

Generates crawlable, canonical, self-contained HTML pages from the verified research database:
  /treatments/            directory landing + one page per treatment
  /trials/                directory landing + one page per registry trial
  /research/              directory landing + one page per research record
  /guides/                five evergreen evidence guides (database-driven, no invented claims)
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
RISKY = re.compile(r"\b(cure[sd]?|guaranteed|clinically proven|miracle|breakthrough cure|works for everyone)\b", re.I)

def scrub(text, fallback):
    """Generated metadata must never carry risky claim wording."""
    return fallback if RISKY.search(text or "") else text

def trunc(s, n=160):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    if len(s) <= n: return s
    return s[:n - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"

LV = {"none": "None shown", "limited": "Limited", "moderate": "Moderate", "strong": "Strong"}
REP = {"none": "None yet", "same-group": "Same group/sponsor only", "limited-independent": "Limited independent",
       "strong-independent": "Strong independent", "conflicting": "Conflicting results"}
IND = {"primarily-independent": "Primarily independent", "mixed": "Mixed",
       "primarily-sponsor": "Primarily sponsor-supported", "unclear": "Independence unclear"}
SCORE_WORDS = {1: "Weak", 2: "Limited", 3: "Moderate", 4: "Good", 5: "Strong"}
TIERS = {1: "Tier 1 — strongest current evidence", 2: "Tier 2 — promising", 3: "Tier 3 — experimental/emerging",
         4: "Tier 4 — symptom management/coping", 5: "Tier 5 — weak or unsupported"}

FOOTER_LINKS = [
    ("treatments/", "Tinnitus treatments"), ("trials/", "Clinical trials"), ("research/", "Research records"),
    ("research-questions/", "Research questions"),
    ("guides/tinnitus-treatments/", "What has the strongest evidence?"),
    ("guides/tinnitus-loudness-vs-distress/", "Loudness vs distress"),
    ("research.html", "This week in tinnitus research"),
    ("about.html", "About & methodology"), ("about.html#limitations", "Research limitations"),
    ("about.html#corrections", "Corrections & editorial integrity"), ("about.html#disclaimer", "Medical disclaimer"),
]

def footer_html(depth):
    up = "../" * depth
    links = " · ".join(f'<a href="{up}{h}">{E(n)}</a>' for h, n in FOOTER_LINKS)
    return f"""<footer class="footer-links"><div class="wrap"><p class="small">{links}</p>
<p class="small muted">Tinnitus Evidence is an educational evidence-navigation resource — not medical advice.
It does not diagnose, and never replaces an ENT physician, audiologist or other qualified professional.</p></div></footer>"""

def page(path_rel, title, desc, h1, crumbs, body, jsonld_extra=None, article=None):
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
        crumb_ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name,
             **({"item": PROD + "/" + href} if href is not None else {})}
            for i, (href, name) in enumerate(crumbs)]}
    ld = [{"@context": "https://schema.org", "@type": "WebPage", "name": title.split(" | ")[0],
           "url": canon, "description": desc, "isPartOf": {"@type": "WebSite", "name": "Tinnitus Evidence", "url": PROD + "/"},
           "dateModified": TODAY}]
    if article:
        ld = [{"@context": "https://schema.org", "@type": "Article", "headline": article["headline"],
               "url": canon, "description": desc, "datePublished": article.get("published", TODAY), "dateModified": TODAY,
               "author": {"@type": "Organization", "name": "Tinnitus Evidence"},
               "publisher": {"@type": "Organization", "name": "Tinnitus Evidence", "url": PROD + "/"}}]
    if crumb_ld: ld.append(crumb_ld)
    if jsonld_extra: ld.append(jsonld_extra)
    ld_html = "\n".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
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
<link rel="stylesheet" href="css/styles.css">
{ld_html}
</head>
<body data-page="">
<a class="skip-link" href="#content">Skip to content</a>
<main id="content" class="wrap prose">
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
sitemap_urls = [PROD + "/", PROD + "/research.html", PROD + "/about.html", PROD + "/institutions.html"]

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
    if t.get("narrowPopulation"):
        warn += f'<div class="notice">🎯 <strong>Applies only to a specific diagnosed tinnitus population.</strong> {E(t.get("narrowNote", ""))}</div>'
    if t.get("underReevaluation"):
        warn += f'<div class="notice">🔎 <strong>Evidence rating under re-evaluation.</strong> {E(t["underReevaluation"].get("reason", ""))}</div>'
    body = f"""
<p class="small muted">{E(cat.get('name', ''))}{f" · Ranked #{rk['rank']} on our Top 10 ({E(rk.get('stability', ''))})" if rk else ''}</p>
{warn}
<section>
<h2>Current evidence</h2>
<p><strong>{E(t.get('oneLiner', ''))}</strong></p>
<p>Evidence strength: <strong>{SCORE_WORDS.get(score, '?')} ({score}/5)</strong> · {E(TIERS.get(t.get('tier'), ''))} ·
Evidence independence: <strong>{E(IND.get(t.get('independence'), 'Not assessed'))}</strong>.</p>
<p>{E(t.get('whatItIs', ''))}</p>
</section>
<section><h2>Did tinnitus loudness improve?</h2>
<p><strong>{E(LV.get(lo.get('level'), 'Not assessed'))}.</strong> {E(lo.get('summary', ''))}</p></section>
<section><h2>Did tinnitus distress improve?</h2>
<p><strong>{E(LV.get(di.get('level'), 'Not assessed'))}.</strong> {E(di.get('summary', ''))}</p>
<p class="small muted">Loudness means the tinnitus percept itself became quieter (psychoacoustic matching or loudness
ratings). Distress means questionnaire scores such as THI/TFI, sleep, anxiety or quality of life improved — the sound
may be unchanged. A THI/TFI improvement is never evidence the tinnitus got quieter.</p></section>
<section><h2>How strong is the evidence?</h2>
<p>{E(t.get('scoreRationale', ''))}</p></section>
<section><h2>Has the result been independently replicated?</h2>
<p><strong>{E(REP.get(t.get('replication'), 'Not assessed'))}.</strong> {E(t.get('replicationNote', ''))}</p>
{f'<p class="small muted">Independence: {E(t.get("independenceNote", ""))}</p>' if t.get('independenceNote') else ''}</section>
<section><h2>What are the limitations?</h2>
<ul>{''.join(f'<li>{E(l)}</li>' for l in t.get('limitations', []))}</ul>
{f'<p><strong>Conflicts of interest:</strong> {E(t["conflicts"])}</p>' if t.get('conflicts') else ''}</section>
<section><h2>What should patients know about safety?</h2>
<p><strong>Safety evidence: {E((t.get('safetyLevel') or 'not yet assessed').capitalize())}.</strong> {E(t.get('safety', ''))}</p></section>
<section><h2>Is it available?</h2>
<p><strong>Regulatory status:</strong> {E(reg.get('status', ''))}. {E(reg.get('detail', ''))}</p>
<p><strong>Availability:</strong> {E(av.get('usa', ''))}{(' · Europe: ' + E(av['europe'])) if av.get('europe') else ''}{(' · Cost (approx.): ' + E(av['cost'])) if av.get('cost') else ''}</p></section>
<section><h2>What the studies found</h2>
{''.join(study_block(sid) for sid in t.get('studies', [])) or '<p class="muted">No individual study records yet.</p>'}</section>
{f'''<section><h2>Related clinical trials</h2><ul>{''.join(f'<li><a href="trials/{E(x["nctId"])}/">{E(x["title"])}</a> — {E(x.get("status", ""))}</li>' for x in rel_trials)}</ul>
<p class="small muted">Tracked trials are research in progress, not recommended treatments.</p></section>''' if rel_trials else ''}
{f'''<section><h2>Related treatments</h2><ul>{''.join(f'<li><a href="treatments/{E(x["id"])}/">{E(x["name"])}</a> — {E(trunc(x.get("oneLiner", ""), 110))}</li>' for x in related)}</ul></section>''' if related else ''}
<p class="small muted">Evidence last reviewed: {E(t.get('lastReviewed', ''))} · Evidence included through: {E(t.get('evidenceThrough', ''))} ·
Confidence: {E(t.get('confidence', ''))}. <a href="treatment.html?id={E(tid)}">Open the interactive evidence profile</a>.</p>
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
             "Compare the clinical evidence for every major tinnitus treatment — evidence scores, loudness vs distress outcomes, replication, safety, availability and primary sources.",
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
<p class="small muted">Trial statuses are verified against the ClinicalTrials.gov registry by our weekly automated check.
A tracked trial is research in progress — inclusion is not a treatment recommendation, and only the study team can
determine eligibility.</p>"""
    canon = page(f"trials/{nct}/index.html",
                 trunc(f"{x['title']} ({nct})", 60) + " | Tinnitus Clinical Trial",
                 desc, E(x["title"]),
                 [("", "Home"), ("trials/", "Clinical trials"), (None, nct)], body)
    sitemap_urls.append(canon)

trials_body = f"""
<p class="lead">Tinnitus Evidence tracks <strong>{len(trials)} registered clinical trials</strong> — the drug programs,
device studies and therapy trials that could change the tinnitus evidence picture. Statuses are verified directly against
the ClinicalTrials.gov registry every week; tracked trials are research in progress, not recommended treatments.</p>
<p><a href="trials.html">Prefer filters and the watch feature? Open the interactive trials browser.</a></p>
<ul>""" + "".join(
    f'<li><a href="trials/{E(x["nctId"])}/">{E(x["title"])}</a> — {E(str(x.get("phase", "")))} · {E(str(x.get("status", "")))}</li>'
    for x in trials) + "</ul>"
canon = page("trials/index.html",
             "Tinnitus Clinical Trials: Current and Emerging Research | Tinnitus Evidence",
             "The registered clinical trials that could change tinnitus treatment — drug, device and therapy studies with phases, statuses and registry links, verified weekly.",
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
<li><strong>Randomized:</strong> {'Yes' if s.get('randomized') else 'No'} · <strong>Sham/placebo-controlled:</strong> {'Yes' if s.get('sham') else 'No'} · <strong>Independent of the manufacturer:</strong> {'Yes' if s.get('independent') else 'No'}</li>
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

res_dir = """
<p class="lead">Every research record in the Tinnitus Evidence database — trials, systematic reviews, guidelines and
regulatory records — each verified against its primary source, with design, results, limitations and conflicts of
interest. Negative and failed results are first-class records here, not footnotes.</p>
<ul>""" + "".join(
    f'<li><a href="research/{E(s["id"])}/">{E(s["title"])}</a> <span class="muted">({E(str(s.get("year", "")))})</span></li>'
    for s in sorted(studies, key=lambda x: (-int(x.get("year") or 0), x["id"]))) + "</ul>"
canon = page("research/index.html",
             f"Tinnitus Research Records: {len(studies)} Verified Studies & Reviews | Tinnitus Evidence",
             "Browse every verified research record behind Tinnitus Evidence — trials, systematic reviews, guidelines and regulatory records with results, limitations and primary sources.",
             "The Research Behind Tinnitus Evidence", [("", "Home"), (None, "Research records")], res_dir)
sitemap_urls.append(canon)

# ---------------- guides ----------------
def guide(slug, title, h1, desc, body):
    canon = page(f"guides/{slug}/index.html", title, desc, h1,
                 [("", "Home"), ("guides/", "Guides"), (None, h1.split(":")[0])], body,
                 article={"headline": h1, "published": "2026-09-04"})
    sitemap_urls.append(canon)

top5 = [(r, T[r["id"]]) for r in rankings.get("top", [])[:5] if r["id"] in T]
guide("tinnitus-treatments",
      "Tinnitus Treatments: What Has the Strongest Evidence? | Tinnitus Evidence",
      "Tinnitus Treatments: What Has the Strongest Evidence?",
      "Which tinnitus treatments have the strongest clinical evidence? A conservative, source-linked answer based on evidence scores, replication, and loudness vs distress outcomes.",
      f"""
<section><h2>The short answer</h2>
<p><strong>Cognitive behavioral therapy (CBT) has the strongest evidence of any tinnitus treatment</strong> — for reducing
distress and improving quality of life, not for making the sound quieter. No treatment has been established as a universal
cure for tinnitus. Beyond CBT, the best-supported options depend on your situation — hearing loss, sleep problems, and
tinnitus subtype all change the picture.</p></section>
<section><h2>The current top-ranked treatments</h2>
<p class="small muted">{E(rankings.get('uncertaintyNote', ''))}</p>
<ul>{''.join(f'<li><strong>#{r["rank"]}: <a href="treatments/{E(r["id"])}/">{E(t["name"])}</a></strong> — {E(scrub(r.get("whyPlain", t.get("oneLiner", "")), t.get("oneLiner", "")))}</li>' for r, t in top5)}</ul>
<p><a href="treatments/">See all {len(treatments)} treatments ranked by evidence tier</a> — including the ones that have
failed their trials, because negative evidence protects people from wasting money and hope.</p></section>
<section><h2>How to read "strongest evidence"</h2>
<p>We rate loudness and distress separately (most good evidence is for distress), require independent replication before
calling anything established, show who funded the research, and label ranking positions that are sensitive to how you
weigh the evidence. <a href="about.html#methodology">Read the full methodology</a>.</p></section>""")

recent = []
for t in treatments:
    for ev in t.get("timeline", []):
        if isinstance(ev.get("year"), int) and ev["year"] >= YEAR - 2:
            recent.append((ev["year"], t, ev.get("event", "")))
recent.sort(key=lambda x: -x[0])
guide("new-tinnitus-treatments",
      "New Tinnitus Treatments and Research: What's Actually Emerging | Tinnitus Evidence",
      "New Tinnitus Treatments and Research",
      "What genuinely new tinnitus treatments and research are emerging — bimodal neuromodulation, drug programs and major trials — with conservative evidence context, updated weekly.",
      f"""
<section><h2>The short answer</h2>
<p>The most consequential recent developments are <strong>bimodal neuromodulation devices</strong> (Lenire's FDA De Novo
authorization; the Shore/Auricle device awaiting FDA review), large head-to-head and sound-therapy trials
(UNITI; the MOST trial, N=440), and a small pipeline of drug programs. "New" does not mean "better" — several heavily
promoted approaches have failed their trials, and this page reflects the evidence as of our latest weekly review.</p></section>
<section><h2>Recent developments from the evidence timeline ({YEAR - 2}–{YEAR})</h2>
<ul>{''.join(f'<li><strong>{y}</strong> — <a href="treatments/{E(t["id"])}/">{E(t["name"])}</a>: {E(ev)}</li>' for y, t, ev in recent[:20])}</ul></section>
<section><h2>What's in trials now</h2>
<p><a href="trials/">See the {len(trials)} registered clinical trials we track</a>, verified weekly against
ClinicalTrials.gov. For weekly research updates, see <a href="research.html">This Week in Tinnitus Research</a>.</p></section>""")

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
<strong>Shore/Auricle device</strong> (positive academic trial, awaiting FDA review). Trials report meaningful distress
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
<p><a href="trials/">All {len(trials)} tracked trials with statuses verified weekly against ClinicalTrials.gov</a>.
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
<section><h2>Open questions</h2>
<ul>
<li><a href="research-questions/somatic-modulation-treatment-response/">Could patterns of somatic tinnitus
modulation help predict treatment response?</a> — the simple yes/no version has been tested (mostly null);
whether graded modulation features carry predictive information remains open.</li>
</ul></section>
<section><h2>How a question earns a place here</h2>
<p>Every entry follows the same process before publication:</p>
<p class="small"><strong>Pattern identified → adversarial literature search → precedent check → contradictory-evidence
search → hypothesis refined or rejected → human approval → publication.</strong></p>
<p class="small muted">Hypotheses are never auto-published. The weekly research automation may flag candidate
questions internally for review, but nothing appears in this section without an adversarial precedent audit and
explicit human approval — and being listed here never affects any treatment's evidence rating, tier, or ranking.
Unlike evidence records, entries here carry no evidence scores.</p></section>"""
canon = page("research-questions/index.html",
             "Research Questions in Tinnitus | Tinnitus Evidence",
             "Patterns in the tinnitus evidence that may deserve further investigation — clearly labeled research hypotheses, with supporting and contradictory studies, never treatment recommendations.",
             "Research Questions",
             [("", "Home"), (None, "Research questions")], rq_dir)
sitemap_urls.append(canon)

# ---------------- sitemap + production robots + redirect map ----------------
(ROOT / "sitemap.xml").write_text(
    '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    "\n".join(f"  <url><loc>{E(u)}</loc><lastmod>{TODAY}</lastmod></url>" for u in sorted(set(sitemap_urls))) +
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
      f"6 guide/directory pages, sitemap {len(set(sitemap_urls))} URLs")

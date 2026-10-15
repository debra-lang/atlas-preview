#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tinnitus Evidence — lightweight SEO regression checks.

Run after every data update / SEO build (wired into the weekly workflow). Exit 1 on failure so
an automated update can never silently break SEO. Checks:
  * every public treatment in the database has a generated static page with a canonical
  * every indexable page: exactly one <title> (unique site-wide), non-empty meta description,
    exactly one <h1>, one canonical on the production domain
  * no canonical points at GitHub Pages / localhost
  * no indexable page carries noindex; utility pages DO carry noindex
  * sitemap parses, contains only production URLs, no admin/preview/noindexed pages,
    and matches the generated page set
  * Tinnitus Claims (data/claims.json): every claim has a static page; every verdict is one of the five
    defined terms; verdict, evidence-through and last-reviewed dates, references and the "unsupported does
    not mean disproven" explanation are present; every citation resolves to a reference; related links resolve
"""
import html, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD = "https://tinnitusevidence.com"
errors, warns = [], []

treatments = json.loads((ROOT / "data" / "treatments.json").read_text(encoding="utf-8"))
if isinstance(treatments, dict): treatments = treatments["treatments"]

# collect indexable pages: generated dirs + root indexable pages
gen = sorted(ROOT.glob("treatments/**/index.html")) + sorted(ROOT.glob("trials/**/index.html")) + \
      sorted(ROOT.glob("research/**/index.html")) + sorted(ROOT.glob("guides/**/index.html")) + \
      sorted(ROOT.glob("research-questions/**/index.html")) + sorted(ROOT.glob("ask/index.html")) +       sorted(ROOT.glob("claims/**/index.html"))

# Research Questions integrity: every page in the section MUST carry the hypothesis banner
# (they are hypotheses, never evidence) — and the section must never be empty once launched.
rq = sorted(ROOT.glob("research-questions/**/index.html"))
if not rq:
    errors.append("research-questions section missing (was launched 2026-09-05; must not disappear)")
for p in rq:
    if "hypo-banner" not in p.read_text(encoding="utf-8"):
        errors.append(f"{p.relative_to(ROOT).as_posix()}: missing hypothesis banner — research questions must be labeled as not-established-evidence")
root_indexable = [ROOT / f for f in ("index.html", "research.html", "about.html", "institutions.html")]
noindex_expected = [ROOT / f for f in ("admin.html", "compare.html", "search.html", "watchlist.html", "profile.html")]

for t in treatments:
    if not (ROOT / "treatments" / t["id"] / "index.html").exists():
        errors.append(f"treatment '{t['id']}' has no generated static page")

titles = {}
sitemap_expect = set()
for p in gen + root_indexable:
    h = p.read_text(encoding="utf-8")
    rel = p.relative_to(ROOT).as_posix()
    tt = re.findall(r"<title>(.*?)</title>", h)
    if len(tt) != 1 or not tt[0].strip():
        errors.append(f"{rel}: missing/multiple <title>")
    else:
        titles.setdefault(tt[0], []).append(rel)
    if not re.search(r'<meta name="description" content="[^"]{20,}"', h):
        errors.append(f"{rel}: missing/blank meta description")
    if len(re.findall(r"<h1[ >]", h)) != 1:
        errors.append(f"{rel}: h1 count != 1")
    canons = re.findall(r'<link rel="canonical" href="([^"]+)"', h)
    if p in root_indexable and rel == "index.html":
        pass
    if len(canons) != 1:
        errors.append(f"{rel}: canonical count {len(canons)} != 1")
    else:
        c = canons[0]
        if not c.startswith(PROD):
            errors.append(f"{rel}: canonical not on production domain: {c}")
        if "github.io" in c or "localhost" in c:
            errors.append(f"{rel}: canonical points at a preview host")
        sitemap_expect.add(c)
    if 'name="robots" content="noindex"' in h:
        errors.append(f"{rel}: indexable page carries noindex")

# treatments.html / trials.html canonicalize to their static directories (not self) — allowed, not in sitemap
for f in ("treatments.html", "trials.html"):
    h = (ROOT / f).read_text(encoding="utf-8")
    c = re.findall(r'<link rel="canonical" href="([^"]+)"', h)
    if not c or not c[0].startswith(PROD):
        errors.append(f"{f}: expected production canonical")

for p in noindex_expected:
    if p.exists() and not re.search(r'name="robots" content="noindex', p.read_text(encoding="utf-8")):
        errors.append(f"{p.name}: utility/internal page missing noindex")

dups = {t: v for t, v in titles.items() if len(v) > 1}
for t, v in dups.items():
    errors.append(f"duplicate title '{t[:60]}' on: {', '.join(v)}")

sm = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
sm_urls = set(re.findall(r"<loc>([^<]+)</loc>", sm))
for u in sm_urls:
    if not u.startswith(PROD):
        errors.append(f"sitemap URL not on production domain: {u}")
    if any(u.endswith(b) for b in ("admin.html", "preview.html", "compare.html", "/search.html", "watchlist.html", "profile.html")):
        errors.append(f"sitemap contains internal/noindex page: {u}")
missing = sitemap_expect - sm_urls
extra = sm_urls - sitemap_expect
if missing: errors.append(f"sitemap missing {len(missing)} canonical pages (e.g. {sorted(missing)[:3]})")
if extra: warns.append(f"sitemap has {len(extra)} URLs with no generated page counterpart: {sorted(extra)[:4]}")

# Emerging & Unproven: the static fallback list must mirror the data file (one source of truth)
eu_page = ROOT / "emerging-unproven" / "index.html"
if eu_page.exists():
    eu = json.loads((ROOT / "data" / "emerging-unproven.json").read_text(encoding="utf-8"))
    eh = eu_page.read_text(encoding="utf-8")
    m = re.search(r"<!-- eu-static:start[\s\S]*?-->([\s\S]*?)<!-- eu-static:end -->", eh)
    if not m:
        errors.append("emerging-unproven/index.html: static fallback block missing (run tools/build_seo.py)")
    else:
        found = re.findall(r'<li id="([^"]+)"><strong><a href="#[^"]+">(.*?)</a>', m.group(1))
        want = [(t["id"], html.escape(t["name"])) for t in eu["T"]]
        if len(found) != len(want) or sorted(found) != sorted(want):
            errors.append(f"emerging-unproven/index.html: static fallback has {len(found)} entries, data has {len(want)} (or ids/names differ) — run tools/build_seo.py")
        else:
            print(f"emerging static fallback: {len(found)} entries match data/emerging-unproven.json")

# Tinnitus Claims: Fact vs. Evidence — integrity of the static section and its data
cl_path = ROOT / "data" / "claims.json"
if cl_path.exists():
    CL = json.loads(cl_path.read_text(encoding="utf-8"))
    VER = {v["name"] for v in CL["verdicts"]}
    if VER != {"Supported", "Partly Supported", "Misleading", "Unsupported", "Insufficient Evidence"}:
        errors.append(f"claims: verdict vocabulary changed: {sorted(VER)}")
    t_ids = {t["id"] for t in treatments}
    eu_ids = {t["id"] for t in json.loads((ROOT / "data" / "emerging-unproven.json").read_text(encoding="utf-8"))["T"]}
    g_ids = {p.parent.name for p in ROOT.glob("guides/*/index.html")}
    land = ROOT / "claims" / "index.html"
    lh = land.read_text(encoding="utf-8") if land.exists() else ""
    if not land.exists(): errors.append("claims/index.html missing")
    if not (ROOT / "claims" / "verdicts" / "index.html").exists(): errors.append("claims/verdicts/index.html missing")
    for c in CL["claims"]:
        rel = f"claims/{c['slug']}/index.html"
        pp = ROOT / rel
        if not pp.exists():
            errors.append(f"{rel}: missing"); continue
        h = pp.read_text(encoding="utf-8")
        if c["verdict"] not in VER: errors.append(f"{rel}: undefined verdict {c['verdict']!r}")
        for sv in c["subverdicts"]:
            if sv[1] not in VER: errors.append(f"{rel}: undefined sub-verdict {sv[1]!r}")
        for need in ("Evidence through", "Last reviewed", 'id="references"', "Evidence verdict", "does not necessarily mean disproven"):
            if need not in h: errors.append(f"{rel}: missing '{need}'")
        if len(re.findall(r'class="cl-verdict ', h)) != 1: errors.append(f"{rel}: expected exactly one verdict block")
        refs = set(re.findall(r'<li id="ref-(\d+)">', h))
        cites = set(re.findall(r'<a href="claims/' + re.escape(c["slug"]) + r'/#ref-(\d+)" aria-label', h))
        if re.search(r'href="#(?!content")', h): errors.append(f"{rel}: bare '#' link (breaks under <base href>) — use the full page path")
        if len(refs) < 5: errors.append(f"{rel}: only {len(refs)} references listed")
        if not cites: errors.append(f"{rel}: no inline citations")
        if cites - refs: errors.append(f"{rel}: citations without reference entries: {sorted(cites - refs)[:5]}")
        if refs - cites: warns.append(f"{rel}: references never cited inline: {sorted(refs - cites)[:5]}")
        for r in c["references"]:
            if not r.get("links"): errors.append(f"{rel}: reference {r['n']} has no link")
        d = re.search(r'<meta name="description" content="([^"]*)"', h)
        if d and len(d.group(1)) > 200: warns.append(f"{rel}: meta description {len(d.group(1))} chars")
        rr = c.get("related", {})
        for tid in rr.get("treatments", []):
            if tid not in t_ids: errors.append(f"{rel}: unknown related treatment {tid}")
        for eid in rr.get("emerging", []):
            if eid not in eu_ids: errors.append(f"{rel}: unknown related Emerging id {eid}")
        for gid in rr.get("guides", []):
            if gid not in g_ids: errors.append(f"{rel}: unknown related guide {gid}")
        if f'href="claims/{c["slug"]}/"' not in lh: errors.append(f"claims/index.html does not link to {c['slug']}")
        if f"https://tinnitusevidence.com/claims/{c['slug']}/" not in sm_urls: errors.append(f"sitemap missing claims/{c['slug']}/")
        if c.get("safety") and "cl-safety" not in h: errors.append(f"{rel}: safety note not rendered")
    s5 = [c for c in CL["claims"] if c["slug"] == "does-tinnitus-go-away"]
    if s5 and "sudden hearing loss" not in (ROOT / "claims/does-tinnitus-go-away/index.html").read_text(encoding="utf-8").split('id="claim"')[0].lower():
        errors.append("does-tinnitus-go-away: sudden-hearing-loss safety note must appear before the article body")
    print(f"claims: {len(CL['claims'])} claim pages + landing + verdicts checked")

print(f"checked {len(gen) + len(root_indexable)} indexable pages, sitemap {len(sm_urls)} URLs")
for w in warns: print("WARN:", w)
if errors:
    for e in errors: print("FAIL:", e)
    sys.exit(1)
print("SEO CHECKS PASS")

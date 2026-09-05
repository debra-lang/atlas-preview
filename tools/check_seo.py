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
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD = "https://tinnitusevidence.com"
errors, warns = [], []

treatments = json.loads((ROOT / "data" / "treatments.json").read_text(encoding="utf-8"))
if isinstance(treatments, dict): treatments = treatments["treatments"]

# collect indexable pages: generated dirs + root indexable pages
gen = sorted(ROOT.glob("treatments/**/index.html")) + sorted(ROOT.glob("trials/**/index.html")) + \
      sorted(ROOT.glob("research/**/index.html")) + sorted(ROOT.glob("guides/**/index.html")) + \
      sorted(ROOT.glob("research-questions/**/index.html"))

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

print(f"checked {len(gen) + len(root_indexable)} indexable pages, sitemap {len(sm_urls)} URLs")
for w in warns: print("WARN:", w)
if errors:
    for e in errors: print("FAIL:", e)
    sys.exit(1)
print("SEO CHECKS PASS")

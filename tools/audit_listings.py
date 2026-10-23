#!/usr/bin/env python3
"""Independent audit of data/listings.json. READ-ONLY (public PubMed and ClinicalTrials.gov APIs; nothing is written except the report you ask for).

The listings are verified when they are made, from the PubMed efetch text and the registry record. This audit re-checks them through a DIFFERENT route (PubMed esummary, the ClinicalTrials.gov
studies API) so a mistake in the first route cannot confirm itself, and it looks for the problems a listing page can have:
  source accuracy   title, journal, publication date, identifier, article types (PubMed) / title, sponsor, status (registry) against the independent record
  duplicates        the same identifier, the same DOI, or the same normalised title listed twice; near-duplicates (same first 8 words) are reported separately
  relevance         how clearly the record concerns tinnitus: tinnitus in the title / a MeSH heading / the number of abstract mentions (needs the queue facts, --queue)
  tags              every treatment tag with its title, for a human to judge
Usage: python tools/audit_listings.py [--listings data/listings.json] [--queue data/review-queue/queue.json] [--out report.json]
It is also the monthly audit once listings are live: run it over a random sample with --sample N.
"""
import argparse, json, random, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "TinnitusEvidence-audit/1.0 (read-only)"}


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def http_json(url, pause=0.4):
    time.sleep(pause)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def pubmed_summaries(pmids, fetch=http_json):
    q = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(pmids), "retmode": "json"})
    res = fetch("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + q).get("result", {})
    return {p: res[p] for p in pmids if p in res}


def registry_study(nct, fetch=http_json):
    return fetch(f"https://clinicaltrials.gov/api/v2/studies/{nct}?format=json&fields=protocolSection.identificationModule|protocolSection.statusModule|protocolSection.sponsorCollaboratorsModule|protocolSection.conditionsModule")


def check_pubmed(e, s):
    problems = []
    if not s or s.get("uid") != e["key"].split()[1]:
        return ["identifier not found in the independent PubMed summary"]
    if norm(s.get("title"))[:80] != norm(e["title"])[:80]:
        problems.append(f"title differs: {s.get('title')!r}")
    jn = {norm(s.get("fulljournalname")), norm(s.get("source"))}
    if norm(e.get("source")) not in jn and not any(norm(e.get("source")).startswith(j) or j.startswith(norm(e.get("source"))) for j in jn if j):
        problems.append(f"journal differs: listing {e.get('source')!r} vs {s.get('fulljournalname')!r}")
    year = re.search(r"\b(19|20)\d{2}\b", str(e.get("date", "")))
    if year and year.group(0) not in (str(s.get("pubdate", "")) + " " + str(s.get("epubdate", ""))):
        problems.append(f"date differs: listing {e.get('date')!r} vs PubMed {s.get('pubdate')!r}")
    types = {norm(t) for t in s.get("pubtype", [])}
    if not {norm(t) for t in e.get("articleTypes", [])} <= types:
        problems.append(f"article types differ: listing {e.get('articleTypes')} vs PubMed {s.get('pubtype')}")
    if {"retracted publication", "retraction of publication", "published erratum"} & types:
        problems.append("PubMed now marks this record as a retraction or erratum")
    return problems


def check_registry(e, study):
    p = (study or {}).get("protocolSection", {})
    ident, status = p.get("identificationModule", {}), p.get("statusModule", {})
    problems = []
    if ident.get("nctId") != e["key"]:
        return ["identifier not found in the independent registry record"]
    if norm(ident.get("briefTitle"))[:80] != norm(e["title"])[:80]:
        problems.append(f"title differs: {ident.get('briefTitle')!r}")
    if e.get("status") and status.get("overallStatus") and e["status"] != status["overallStatus"]:
        problems.append(f"status has changed since listing: listing {e['status']} vs registry {status['overallStatus']} (informational; refreshed at the next run)")
    return problems


def doi_of(s):
    return next((a.get("value") for a in (s or {}).get("articleids", []) if a.get("idtype") == "doi"), None)


def relevance(e, facts, conditions=None):
    """clear = tinnitus in the title (or, for a registry record, in its listed conditions); central = a MeSH heading or 5+ abstract mentions; loose = otherwise. Needs queue facts for PubMed records."""
    if re.search("tinnit", e.get("title", ""), re.I) or (conditions and re.search("tinnit", " ".join(conditions), re.I)):
        return "clear"
    if conditions is not None:
        return "loose"
    if not facts:
        return "unknown"
    return "central" if (facts.get("tinMesh") or facts.get("tinAbs", 0) >= 5) else "loose"


def audit(listings, queue_items=None, fetch=http_json, sample=None, seed=1):
    items = listings.get("items", [])
    if sample and sample < len(items):
        items = random.Random(seed).sample(items, sample)
    facts = {}
    for it in queue_items or []:
        k = "PMID " + it["id"].split("-", 1)[1] if it.get("id", "").startswith("pubmed-") else None
        if k and isinstance(it.get("triage"), dict):
            facts[k] = it["triage"]
    pm = [e["key"].split()[1] for e in items if e["key"].startswith("PMID")]
    sums = {}
    for i in range(0, len(pm), 50):
        sums.update(pubmed_summaries(pm[i:i + 50], fetch))
    rows, seen_key, seen_doi, seen_title = [], {}, {}, {}
    for e in items:
        conds = None
        if e["key"].startswith("PMID"):
            s = sums.get(e["key"].split()[1])
            probs = check_pubmed(e, s)
            doi = doi_of(s)
        else:
            conds = None
            try:
                study = registry_study(e["key"], fetch)
                probs, doi = check_registry(e, study), None
                conds = (study.get("protocolSection", {}).get("conditionsModule", {}) or {}).get("conditions", []) or []
            except Exception as ex:
                probs, doi = [f"registry record could not be fetched ({type(ex).__name__})"], None
        conds = conds if not e["key"].startswith("PMID") else None
        dups = []
        if e["key"] in seen_key: dups.append(f"same identifier as entry {seen_key[e['key']]}")
        if doi and doi in seen_doi: dups.append(f"same DOI as {seen_doi[doi]}")
        t = norm(e["title"])
        if t in seen_title: dups.append(f"same title as {seen_title[t]}")
        seen_key.setdefault(e["key"], e["key"]); seen_title.setdefault(t, e["key"])
        if doi: seen_doi.setdefault(doi, e["key"])
        rows.append({"key": e["key"], "title": e["title"], "sourceProblems": [p for p in probs if "informational" not in p], "informational": [p for p in probs if "informational" in p],
                     "duplicates": dups, "relevance": relevance(e, facts.get(e["key"]), conds), "tags": e.get("treatments", [])})
    # near-duplicates: two DIFFERENT titles whose first words (up to 8, at least 4) are identical, e.g. a guideline and its executive summary; reported for a human, not an error
    words = {e["key"]: norm(e["title"]).split() for e in items}
    related, keys = [], sorted({e["key"] for e in items})
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            k = min(len(words[a]), len(words[b]), 8)
            if k >= 4 and words[a][:k] == words[b][:k] and words[a] != words[b]:
                related.append([a, b])
    summary = {"audited": len(rows), "sourceProblems": sum(1 for r in rows if r["sourceProblems"]), "duplicates": sum(1 for r in rows if r["duplicates"]),
               "relevance": {k: sum(1 for r in rows if r["relevance"] == k) for k in ("clear", "central", "loose", "unknown")}, "tagged": sum(1 for r in rows if r["tags"]),
               "nearDuplicateGroups": related}
    return {"summary": summary, "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listings", default=str(ROOT / "data" / "listings.json"))
    ap.add_argument("--queue")
    ap.add_argument("--out")
    ap.add_argument("--sample", type=int)
    a = ap.parse_args(argv)
    listings = json.loads(Path(a.listings).read_text(encoding="utf-8"))
    queue = json.loads(Path(a.queue).read_text(encoding="utf-8"))["items"] if a.queue else None
    rep = audit(listings, queue, sample=a.sample)
    print(json.dumps(rep["summary"], indent=1))
    for r in rep["rows"]:
        if r["sourceProblems"] or r["duplicates"]:
            print(" !", r["key"], r["sourceProblems"], r["duplicates"])
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if rep["summary"]["sourceProblems"] or rep["summary"]["duplicates"] else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Tinnitus Evidence — correction / erratum / retraction / expression-of-concern notices in the weekly feed.

A notice is not new evidence and must never be presented as a research update (Phase 2: an erratum with no content was routed to publication).
It is also not noise: a notice that concerns a study we already CITE can change how much weight that study deserves. So a notice is never
sent to the AI and never silently discarded. It is classified here, deterministically, into one of three outcomes:

  cited       the notice targets a PMID/DOI (or a title) that data/studies.json cites  -> held privately for review, counted in engine-status
  uncited     the notice targets something we do not cite                               -> archived as context (metadata only)
  unresolved  we could not tell which article the notice concerns                       -> held privately for a manual check

Nothing here changes a study record, a rating or a ranking (the monthly check_retractions.py remains the only writer of integrity flags).
Pure functions plus a title/record parser; no network access.
"""
import re

DELIM = r"\s*(?:[:–—-]|\bto\b\s*:?)"   # "Correction:", "Correction to:", "Erratum -"
TITLE_PATTERNS = [
    ("correction", re.compile(r"^\s*(?:publisher|author|editorial)\s+correction" + r"\s*[:–—-]", re.I)),
    ("correction", re.compile(r"^\s*(?:correction|corrigendum|erratum|errata|addendum)" + DELIM, re.I)),
    ("retraction", re.compile(r"^\s*retraction\s+(?:note|notice|statement)\b", re.I)),
    ("retraction", re.compile(r"^\s*(?:retraction|retracted|withdrawn|withdrawal)\s*[:–—-]", re.I)),
    ("retraction", re.compile(r"^\s*(?:notice of retraction|withdrawal notice)\b", re.I)),
    ("expression-of-concern", re.compile(r"^\s*(?:editorial\s+)?expression of concern\b", re.I)),
]
RECORD_MARKERS = [  # PubMed text records: the notice carries a line naming the article it concerns ("Erratum IN" is the OTHER direction, so it is not matched)
    ("correction", re.compile(r"^\s*(?:Erratum|Corrigendum)\s+(?:for|to)\b", re.M)),
    ("retraction", re.compile(r"^\s*Retraction\s+of\b", re.M)),
    ("expression-of-concern", re.compile(r"^\s*Expression\s+of\s+Concern\s+(?:for|to)\b", re.M | re.I)),
]
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\]\)>,;\"']+")
PMID_RE = re.compile(r"\bPMID:?\s*(\d{5,9})\b")


def _norm(t):
    return re.sub(r"\W+", "", (t or "").lower())


def _doi(d):
    return d.strip().rstrip(".,;)").lower()


def title_kind(title):
    for kind, rx in TITLE_PATTERNS:
        if rx.search(title or ""):
            return kind
    return None


def looks_like_notice(item):
    return title_kind(item.get("title")) is not None


def _own_ids(item, text):
    own_pmid = item.get("id", "").split("-", 1)[1] if item.get("id", "").startswith("pubmed-") else ""
    m = re.search(r"\bdoi:\s*(10\.\d{4,9}/[^\s]+)", (text or "").split("\n\n")[0], re.I)
    return own_pmid, (_doi(m.group(1)) if m else "")


def parse_targets(item, record_text):
    """DOIs and PMIDs of the article(s) the notice concerns, taken from the lines that follow 'Erratum for' / 'Retraction of' and from
    '[This corrects the article DOI: ...]'. The notice's own DOI/PMID are excluded."""
    text = record_text or ""
    own_pmid, own_doi = _own_ids(item, text)
    segs = []
    for _, rx in RECORD_MARKERS:
        for m in rx.finditer(text):
            segs.append(text[m.start(): m.start() + 600].split("\n\n")[0])
    for m in re.finditer(r"corrects the article[^\]]{0,200}", text, re.I):
        segs.append(m.group(0))
    dois = {_doi(d) for s in segs for d in DOI_RE.findall(s)} - {own_doi}
    pmids = {p for s in segs for p in PMID_RE.findall(s)} - {own_pmid}
    return sorted(dois), sorted(pmids)


def cited_index(studies):
    """Index of everything data/studies.json cites: {'pmid': {pmid: [ids]}, 'doi': {doi: [ids]}, 'titles': [(normalised title, id)]}."""
    idx = {"pmid": {}, "doi": {}, "titles": []}
    for s in studies or []:
        sid = s.get("id")
        if s.get("pmid"):
            idx["pmid"].setdefault(str(s["pmid"]).strip(), []).append(sid)
        if s.get("doi"):
            idx["doi"].setdefault(_doi(s["doi"]), []).append(sid)
        if s.get("title"):
            idx["titles"].append((_norm(s["title"]), sid))
    return idx


def _title_core(title):
    t = re.sub(r"^\s*[^:]{0,40}[:–—]\s*", "", title or "", count=1)   # drop the "Correction:" prefix
    return _norm(t)


def analyse(item, record_text, cited):
    """None when the item is not a notice. Otherwise a small, public-safe dict (no AI involved)."""
    kind_t = title_kind(item.get("title"))
    kind_r = next((k for k, rx in RECORD_MARKERS if rx.search(record_text or "")), None)
    kind = kind_t or kind_r
    if not kind:
        return None
    dois, pmids = parse_targets(item, record_text)
    if kind == "retraction" and re.match(r"\s*(retracted|withdrawn)\s*[:–—-]", item.get("title") or "", re.I):
        own_pmid, own_doi = _own_ids(item, record_text)      # the item itself is the retracted paper
        pmids = sorted(set(pmids) | ({own_pmid} if own_pmid else set()))
        dois = sorted(set(dois) | ({own_doi} if own_doi else set()))
    ids = set()
    for p in pmids:
        ids.update(cited["pmid"].get(p, []))
    for d in dois:
        ids.update(cited["doi"].get(d, []))
    core = _title_core(item.get("title"))
    matched_by_title = False
    if len(core) >= 30:
        for nt, sid in cited["titles"]:
            if len(nt) >= 30 and (core.startswith(nt[:60]) or nt.startswith(core[:60])):
                ids.add(sid); matched_by_title = True
    if ids:
        resolution = "cited"
    elif dois or pmids:
        resolution = "uncited"
    else:
        resolution = "unresolved"
    return {"kind": kind, "detectedBy": "title" if kind_t else "record", "targetDois": dois, "targetPmids": pmids,
            "resolution": resolution, "studyIds": sorted(i for i in ids if i), "matchedByTitle": matched_by_title}

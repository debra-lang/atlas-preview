#!/usr/bin/env python3
"""Tinnitus Evidence — retraction / correction back-check for CITED literature.

The weekly scan only sees NEW items; nothing previously linked a retraction notice back to
the study records citing the paper. This module closes that gap:

  * collects every PMID and DOI cited by data/studies.json,
  * PubMed (efetch XML): looks for PublicationType "Retracted Publication" and
    CommentsCorrections RefType RetractionIn / ExpressionOfConcernIn / ErratumIn,
  * Crossref (best effort, DOI-only records): looks for "update-to"/"updated-by"
    entries of type retraction / withdrawal / expression_of_concern / correction,
  * back-links every finding to the study record(s) and treatment(s) citing it.

Findings are returned to weekly_cycle for CLASS B holding — a retraction can obviously
change an evidence rating, so per platform policy the public assessment stays UNCHANGED
until the hold is resolved by review; the affected study record is flagged, never deleted.

Cadence: monthly (runs inside the weekly cycle when >=27 days since the last check —
state in engine/retraction-state.json). Standalone:

  python engine/check_retractions.py            # check all cited PMIDs/DOIs now
  python engine/check_retractions.py --test-pmid 36081433   # prove detection works on a
                                                  known retracted paper (historical test)
"""
import json, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "engine" / "retraction-state.json"
UA = {"User-Agent": "TinnitusEvidence-retraction-check/1.0 (research integrity monitor)"}

FLAG_TYPES = {  # PubMed CommentsCorrections RefType -> our severity
    "RetractionIn": "retracted",
    "ExpressionOfConcernIn": "expression-of-concern",
    "ErratumIn": "erratum",
    "PartialRetractionIn": "partially-retracted",
}
CROSSREF_TYPES = {  # Crossref update types -> our severity
    "retraction": "retracted", "withdrawal": "retracted", "removal": "retracted",
    "expression_of_concern": "expression-of-concern", "correction": "erratum",
    "erratum": "erratum", "partial_retraction": "partially-retracted",
}


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def cited_identifiers(studies):
    """{'pmid': {pmid: [study ids]}, 'doi': {doi: [study ids]}} — DOI checked only when no PMID."""
    pmids, dois = {}, {}
    for s in studies:
        pid = (s.get("pmid") or "").strip()
        doi = (s.get("doi") or "").strip()
        if pid:
            pmids.setdefault(pid, []).append(s["id"])
        elif doi:
            dois.setdefault(doi.lower(), []).append(s["id"])
    return pmids, dois


def check_pubmed(pmids):
    """pmids: {pmid: [study ids]} -> list of finding dicts. Batches of 50."""
    findings = []
    ids = list(pmids)
    for chunk in [ids[i:i + 50] for i in range(0, len(ids), 50)]:
        q = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"})
        root = ET.fromstring(_get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{q}"))
        time.sleep(0.4)  # NCBI courtesy
        for art in root.findall(".//PubmedArticle"):
            pid_el = art.find(".//MedlineCitation/PMID")
            pid = pid_el.text if pid_el is not None else ""
            notices = []
            for pt in art.findall(".//PublicationTypeList/PublicationType"):
                if pt.text == "Retracted Publication":
                    notices.append(("retracted", "PublicationType: Retracted Publication", ""))
            for cc in art.findall(".//CommentsCorrectionsList/CommentsCorrections"):
                sev = FLAG_TYPES.get(cc.get("RefType"))
                if sev:
                    src = cc.findtext("RefSource") or ""
                    npmid = cc.findtext("PMID") or ""
                    notices.append((sev, f"{cc.get('RefType')}: {src}", npmid))
            if notices:
                worst = min(notices, key=lambda n: ["retracted", "partially-retracted",
                                                    "expression-of-concern", "erratum"].index(n[0]))
                findings.append({"identifier": f"PMID {pid}", "severity": worst[0],
                                 "notices": [f"{s} — {d}" + (f" (notice PMID {np})" if np else "")
                                             for s, d, np in notices],
                                 "studyIds": pmids.get(pid, []), "source": "PubMed CommentsCorrections/PublicationType"})
    return findings


def check_crossref(dois):
    """Best-effort Crossref check for DOI-only records ('updated-by' on the work)."""
    findings = []
    for doi, sids in dois.items():
        try:
            data = json.loads(_get(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"))["message"]
        except Exception:
            continue  # Crossref miss is not a finding; PubMed remains the primary channel
        notices = []
        for u in data.get("update-to", []) + data.get("updated-by", []):
            sev = CROSSREF_TYPES.get((u.get("type") or "").lower())
            if sev:
                notices.append((sev, f"Crossref {u.get('type')}: {u.get('label', '')} {u.get('DOI', '')}"))
        if notices:
            worst = min(notices, key=lambda n: ["retracted", "partially-retracted",
                                                "expression-of-concern", "erratum"].index(n[0]))
            findings.append({"identifier": f"DOI {doi}", "severity": worst[0],
                             "notices": [f"{s} — {d}" for s, d in notices],
                             "studyIds": sids, "source": "Crossref update metadata"})
        time.sleep(0.2)
    return findings


def due(state_path=STATE, every_days=27):
    try:
        last = json.loads(Path(state_path).read_text(encoding="utf-8")).get("lastRun", "")
        return (date.today() - date.fromisoformat(last)).days >= every_days
    except Exception:
        return True  # never ran — due


def run(studies, state_path=STATE):
    """Full check. Returns findings list; records state. Caller (weekly_cycle) holds findings."""
    pmids, dois = cited_identifiers(studies)
    findings = check_pubmed(pmids) + check_crossref(dois)
    Path(state_path).write_text(json.dumps({
        "lastRun": date.today().isoformat(), "checkedPmids": len(pmids), "checkedDois": len(dois),
        "findings": findings}, indent=2, ensure_ascii=False), encoding="utf-8")
    return findings


def main():
    if "--test-pmid" in sys.argv:  # historical detection test on a known retracted paper
        pid = sys.argv[sys.argv.index("--test-pmid") + 1]
        f = check_pubmed({pid: ["(test)"]})
        print(json.dumps(f, indent=2))
        print("DETECTED" if f else "NOT DETECTED — check failed")
        sys.exit(0 if f else 1)
    studies = json.loads((ROOT / "data" / "studies.json").read_text(encoding="utf-8"))
    studies = studies["studies"] if isinstance(studies, dict) else studies
    findings = run(studies)
    print(json.dumps(findings, indent=2, ensure_ascii=False) if findings
          else "No retraction/correction notices found for any cited PMID/DOI.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Tinnitus Atlas — weekly research scan.

Fetches the last N days of (1) PubMed tinnitus publications and (2) ClinicalTrials.gov
tinnitus study updates, diffs them against engine/known_ids.json, and appends NEW items
to data/review-queue/queue.json for human review in admin.html.

Nothing this script produces is ever published automatically — it only feeds the queue.

Usage:  python engine/weekly_scan.py [--days 7]
No dependencies beyond the standard library.
"""
import json, re, sys, time, urllib.parse, urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWN = ROOT / "engine" / "known_ids.json"
QUEUE = ROOT / "data" / "review-queue" / "queue.json"
DAYS = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
UA = {"User-Agent": "TinnitusAtlas-weekly-scan/1.0 (research aggregator; contact: site admin)"}

def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

# ---------- PubMed (E-utilities) ----------
def scan_pubmed():
    since = (date.today() - timedelta(days=DAYS)).strftime("%Y/%m/%d")
    term = f'(tinnitus[Title/Abstract]) AND ("{since}"[EDAT] : "3000"[EDAT])'
    q = urllib.parse.urlencode({"db": "pubmed", "term": term, "retmode": "json", "retmax": "100"})
    ids = get_json(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{q}")["esearchresult"].get("idlist", [])
    items = []
    for chunk in [ids[i:i + 50] for i in range(0, len(ids), 50)]:
        time.sleep(0.4)  # NCBI rate limit courtesy
        q2 = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(chunk), "retmode": "json"})
        summ = get_json(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{q2}")["result"]
        for pid in chunk:
            it = summ.get(pid)
            if not it:
                continue
            items.append({
                "id": f"pubmed-{pid}", "kind": "study",
                "title": it.get("title", "").strip(),
                "source": (it.get("fulljournalname") or it.get("source") or "PubMed"),
                "date": it.get("epubdate") or it.get("pubdate") or "",
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                "summary": "New PubMed item — needs evaluation (design, N, outcomes, COI, loudness vs distress).",
                "treatment": "", "proposal": "", "why": "",
            })
    return items

# ---------- ClinicalTrials.gov API v2 ----------
def scan_ctgov():
    since = (date.today() - timedelta(days=DAYS)).isoformat()
    params = urllib.parse.urlencode({
        "query.cond": "tinnitus",
        "filter.advanced": f"AREA[LastUpdatePostDate]RANGE[{since},MAX]",
        "fields": "NCTId,BriefTitle,OverallStatus,Phase,LeadSponsorName,LastUpdatePostDate,EnrollmentCount",
        "pageSize": "100", "format": "json",
    })
    data = get_json(f"https://clinicaltrials.gov/api/v2/studies?{params}")
    items = []
    for s in data.get("studies", []):
        p = s.get("protocolSection", {})
        idm = p.get("identificationModule", {})
        st = p.get("statusModule", {})
        nct = idm.get("nctId", "")
        items.append({
            "id": f"ctgov-{nct}-{st.get('lastUpdatePostDateStruct',{}).get('date','')}",
            "kind": "trial",
            "title": idm.get("briefTitle", ""),
            "source": p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "ClinicalTrials.gov"),
            "date": st.get("lastUpdatePostDateStruct", {}).get("date", ""),
            "url": f"https://clinicaltrials.gov/study/{nct}",
            "summary": f"Trial update — status: {st.get('overallStatus','?')}. Check what changed (status, results, dates).",
            "treatment": "", "proposal": "", "why": "",
        })
    return items

# ---------- Watched feeds (FDA, NIH/NIDCD, journals, regulators…) ----------
def scan_feeds():
    """Generic RSS/Atom watcher driven by engine/sources.json. Failures are per-feed, not fatal."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    cfg = load(ROOT / "engine" / "sources.json", {"feeds": []})
    cutoff = date.today() - timedelta(days=DAYS)
    items = []
    for feed in cfg.get("feeds", []):
        try:
            req = urllib.request.Request(feed["url"], headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                root = ET.fromstring(r.read())
            # RSS: channel/item; Atom: {ns}entry
            entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for e in entries[:50]:
                def text(*tags):
                    for t in tags:
                        el = e.find(t) or e.find("{http://www.w3.org/2005/Atom}" + t)
                        if el is not None and (el.text or el.get("href")):
                            return (el.text or el.get("href")).strip()
                    return ""
                title, summary = text("title"), re.sub(r"<[^>]+>", " ", text("description", "summary"))[:400]
                link = text("link")
                pub = text("pubDate", "published", "updated")
                try:
                    pub_date = parsedate_to_datetime(pub).date() if "," in pub else date.fromisoformat(pub[:10])
                    if pub_date < cutoff:
                        continue
                except Exception:
                    pub_date = None  # keep undated items; the evaluator/admin can judge
                blob = (title + " " + summary).lower()
                if not feed.get("alwaysRelevant") and not any(k in blob for k in feed.get("filter", [])):
                    continue
                items.append({
                    "id": f"feed-{re.sub(r'[^a-z0-9]+', '-', (feed['name'] + '-' + (link or title)).lower())[:120]}",
                    "kind": feed.get("kind", "news"), "title": title, "source": feed["name"],
                    "date": pub_date.isoformat() if pub_date else "", "url": link,
                    "summary": summary or "Watched-feed item — needs evaluation.",
                    "treatment": "", "proposal": "", "why": "",
                })
        except Exception as ex:
            print(f"WARN: feed '{feed.get('name', '?')}' failed: {ex}", file=sys.stderr)
    return items


def main():
    known = set(load(KNOWN, []))
    queue = load(QUEUE, {"items": []})
    existing = {it["id"] for it in queue["items"]}
    new = []
    for scan in (scan_pubmed, scan_ctgov, scan_feeds):
        try:
            new += [it for it in scan() if it["id"] not in known and it["id"] not in existing]
        except Exception as e:
            print(f"WARN: {scan.__name__} failed: {e}", file=sys.stderr)
    # naive duplicate-title collapse (same study reported twice)
    seen_titles, deduped = set(), []
    for it in new:
        key = re.sub(r"\W+", "", it["title"].lower())[:80]
        if key and key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(it)
    queue["items"] = deduped + queue["items"]
    queue["lastScan"] = date.today().isoformat()
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    KNOWN.write_text(json.dumps(sorted(known | {it["id"] for it in deduped})), encoding="utf-8")
    print(f"Added {len(deduped)} new item(s) to the review queue ({len(queue['items'])} total pending).")
    print("Next: open admin.html (served locally) to review, or ask Claude to evaluate the queue.")

if __name__ == "__main__":
    main()

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
    # tiab OR MeSH: catches papers whose title/abstract never says "tinnitus" but are indexed
    # for it (e.g. drug trials with tinnitus as a secondary outcome) — audit blind spot fix
    term = f'(tinnitus[Title/Abstract] OR tinnitus[MeSH Terms]) AND ("{since}"[EDAT] : "3000"[EDAT])'
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
    # Two passes: condition=tinnitus AND full-text term=tinnitus. The term pass catches trials
    # registered under OTHER conditions (Menière, SSNHL, hyperacusis…) that measure tinnitus as
    # an outcome — an audit-confirmed blind spot (e.g. OTO-104). Results are unioned by NCT id.
    studies, seen = [], set()
    for qkey in ("query.cond", "query.term"):
        params = urllib.parse.urlencode({
            qkey: "tinnitus",
            "filter.advanced": f"AREA[LastUpdatePostDate]RANGE[{since},MAX]",
            "fields": "NCTId,BriefTitle,OverallStatus,Phase,LeadSponsorName,LastUpdatePostDate,EnrollmentCount",
            "pageSize": "100", "format": "json",
        })
        try:
            data = get_json(f"https://clinicaltrials.gov/api/v2/studies?{params}")
        except Exception as e:
            print(f"WARN: ctgov {qkey} pass failed: {e}", file=sys.stderr)
            continue
        for s in data.get("studies", []):
            nct = s.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "")
            if nct and nct not in seen:
                seen.add(nct)
                studies.append(s)
    items = []
    for s in studies:
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


# ---------- FDA device databases (openFDA) ----------
def scan_fda():
    """Direct FDA database polling — 510(k), PMA and De Novo decisions plus MAUDE adverse-event
    counts for tinnitus device product codes. The audit showed press-release feeds would have
    MISSED Lenire's own De Novo grant (FDA issued no presser); the databases are authoritative.
    Product codes: KLW (tinnitus masker), QVN (Lenire-type bimodal stimulator)."""
    since = (date.today() - timedelta(days=max(DAYS, 30))).strftime("%Y-%m-%d")  # decisions post slowly
    today = date.today().strftime("%Y-%m-%d")
    items = []
    endpoints = [
        ("510(k) clearance", "https://api.fda.gov/device/510k.json?search="
         + urllib.parse.quote(f'product_code:(KLW OR QVN) AND decision_date:[{since} TO {today}]') + "&limit=20",
         lambda r: (r.get("k_number", ""), f"FDA 510(k) decision: {r.get('device_name','?')} ({r.get('applicant','?')}) — {r.get('decision_description', r.get('decision_code',''))}",
                    f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={r.get('k_number','')}")),
        ("PMA decision", "https://api.fda.gov/device/pma.json?search="
         + urllib.parse.quote(f'product_code:(KLW OR QVN) AND decision_date:[{since} TO {today}]') + "&limit=20",
         lambda r: (r.get("pma_number", ""), f"FDA PMA decision: {r.get('trade_name','?')} ({r.get('applicant','?')})",
                    "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpma/pma.cfm")),
        ("MAUDE adverse events", "https://api.fda.gov/device/event.json?search="
         + urllib.parse.quote(f'device.device_report_product_code:(KLW OR QVN) AND date_received:[{since} TO {today}]') + "&limit=20",
         lambda r: (r.get("report_number", ""), f"MAUDE adverse-event report for a tinnitus device (product code {(r.get('device') or [{}])[0].get('device_report_product_code','?')})",
                    "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/search.cfm")),
    ]
    for name, url, fmt in endpoints:
        try:
            data = get_json(url)
        except Exception as e:
            if "404" in str(e):  # openFDA returns 404 for zero matches — that's a quiet week, not an error
                continue
            print(f"WARN: openFDA {name} failed: {e}", file=sys.stderr)
            continue
        for r in data.get("results", []):
            ident, title, link = fmt(r)
            items.append({
                "id": f"fda-{re.sub(r'[^a-z0-9]+', '-', (name + '-' + ident).lower())[:80]}",
                "kind": "regulatory", "title": title, "source": f"openFDA {name} database",
                "date": date.today().isoformat(), "url": link,
                "summary": f"Authoritative FDA database record ({name}). Needs evaluation; regulatory wording must be exact (cleared ≠ approved ≠ De Novo authorized).",
                "treatment": "", "proposal": "", "why": "",
            })
    return items

# ---------- Company-wire intelligence (Google News RSS; NEVER treated as evidence) ----------
def scan_news_intel():
    """Watches company/topic news via Google News RSS. The audit showed topline results
    (OTO-313, STOPMD-3) surface on business wires months before papers. These items carry
    intelligenceOnly=true: the evaluator/router may publish them ONLY labeled as
    company-reported developments — they can never strengthen an evidence rating."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    cfg = load(ROOT / "engine" / "sources.json", {})
    cutoff = date.today() - timedelta(days=DAYS)
    items = []
    for q in cfg.get("newsIntel", []):
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q["query"]) + "&hl=en-US&gl=US&ceid=US:en"
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                root = ET.fromstring(r.read())
        except Exception as e:
            print(f"WARN: news-intel '{q['name']}' failed: {e}", file=sys.stderr)
            continue
        for e in root.findall(".//item")[:10]:
            title = (e.findtext("title") or "").strip()
            link = (e.findtext("link") or "").strip()
            pub = e.findtext("pubDate") or ""
            try:
                if parsedate_to_datetime(pub).date() < cutoff:
                    continue
            except Exception:
                pass
            blob = title.lower()
            if q.get("filter") and not any(k in blob for k in q["filter"]):
                continue
            items.append({
                "id": f"newsintel-{re.sub(r'[^a-z0-9]+', '-', (q['name'] + '-' + title).lower())[:110]}",
                "kind": "news", "title": title, "source": f"News wire watch: {q['name']}",
                "date": date.today().isoformat(), "url": link, "intelligenceOnly": True,
                "summary": "Company/news-wire intelligence item. NOT evidence — publishable only as a labeled company-reported development after verification.",
                "treatment": "", "proposal": "", "why": "",
            })
    return items

# ---------- Guideline page watcher (content-hash diff; no fragile scraping) ----------
def scan_pages():
    """Watches guideline index pages (AAO-HNSF, NICE NG155…) by content hash. A change emits a
    'review this page' item — we never parse the page's meaning, only detect that it changed.
    State: engine/page-hashes.json."""
    import hashlib
    cfg = load(ROOT / "engine" / "sources.json", {})
    state_p = ROOT / "engine" / "page-hashes.json"
    state = load(state_p, {})
    items = []
    for pg in cfg.get("pages", []):
        try:
            req = urllib.request.Request(pg["url"], headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read()
            # hash only the visible-ish text to ignore markup/nonce churn
            text = re.sub(rb"<script.*?</script>|<style.*?</style>|<[^>]+>", b" ", body, flags=re.S)
            text = re.sub(rb"\s+", b" ", text)
            h = hashlib.sha256(text).hexdigest()
        except Exception as e:
            print(f"WARN: page watch '{pg['name']}' failed: {e}", file=sys.stderr)
            continue
        prev = state.get(pg["url"])
        state[pg["url"]] = h
        if prev and prev != h:
            items.append({
                "id": f"pagewatch-{re.sub(r'[^a-z0-9]+', '-', pg['name'].lower())}-{date.today().isoformat()}",
                "kind": "news", "title": f"Guideline page changed: {pg['name']}",
                "source": "Page watcher (content hash)", "date": date.today().isoformat(),
                "url": pg["url"],
                "summary": "The watched guideline page's content changed since the last scan. Review what changed — a guideline update is a potentially major evidence event.",
                "treatment": "", "proposal": "", "why": "",
            })
    state_p.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return items


def main():
    known = set(load(KNOWN, []))
    queue = load(QUEUE, {"items": []})
    existing = {it["id"] for it in queue["items"]}
    new = []
    for scan in (scan_pubmed, scan_ctgov, scan_feeds, scan_fda, scan_news_intel, scan_pages):
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

#!/usr/bin/env python3
"""Deterministic triage of discovered records by SOURCE METADATA (no AI, no effectiveness judgement). Owner request, 21 Oct 2026.

Four different things, never confused:
  discovered and preserved   every record the scans find. Nothing is ever deleted: it is queued, evaluated, staged, held, or - at most - CATALOGUED (archived with its reason, listed in the digest).
  needs AI evaluation        the 'evaluate' lane. Records are ORDERED by tier so the per-run limit is spent on the most important first; nothing is dropped by the ordering.
  needs clinical review      decided elsewhere (escalation.py, Level 3). Triage only makes sure such records are evaluated FIRST; it never lowers or removes a Level 3 hold.
  eligible for public update only a person's approval of an evaluated, verified item (staged review). Triage publishes nothing.

Tiers (lower = evaluated earlier):  0 correction/retraction/expression-of-concern notice;  1 randomised or other trial, systematic review/meta-analysis/guideline, a strong safety term (title or
abstract), a tracked treatment named in the title, tinnitus in the title together with a tracked treatment in the abstract/MeSH, every FDA/regulatory/page-watch/news-wire record;  2 tinnitus in the title
(and every other registry record);  3 tinnitus not in the title (including a tracked treatment named only in the abstract/MeSH: evaluated, never catalogued, but later).
Catalogue rule C1 (OFF unless eval_settings.json triage.catalogue is exactly true): a PubMed study whose scan-time facts are known AND tinnitus is not in the title AND tinnitus is not a MeSH heading AND
tinnitus appears at most 2 times in the abstract AND there is no tier 0/1 signal AND no weaker safety wording (adverse events, ototoxicity, harm, injury, death ...) in the title or abstract. Missing facts (a failed lookup) mean 'evaluate' (fail open). A small deterministic AUDIT SAMPLE of catalogue
candidates is evaluated anyway every run, so the rule's miss rate is measured instead of assumed.
Facts stored on a queue item are derived values only (counts, flags, treatment ids), never PubMed text: the queue file is public."""
import hashlib, json, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
import escalation, notices   # noqa: E402

RULES_PATH = ENGINE / "triage_rules.json"
_RULES = {}


def rules():
    if not _RULES:
        d = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        d["_aliases"] = {k: re.compile(v, re.I) for k, v in d["aliases"].items()}
        _RULES.update(d)
    return _RULES


def load_settings(settings):
    """Exactly-true semantics, like every other switch: anything else is OFF. auditSample is an integer 0-10 (default 2). SHADOW mode (prospective evidence, nothing archived): catalogue candidates are only FLAGGED; they are evaluated like every other record and what the AI then recommends is counted in engine/triage-evidence.json."""
    t = (settings or {}).get("triage") if isinstance(settings, dict) else None
    t = t if isinstance(t, dict) else {}
    try:
        k = max(0, min(10, int(t.get("auditSample", 2))))
    except (TypeError, ValueError):
        k = 2
    return {"order": t.get("order") is True, "catalogue": t.get("catalogue") is True, "shadow": t.get("shadow") is True, "auditSample": k}


def tracked_in(text):
    return sorted(k for k, rx in rules()["_aliases"].items() if rx.search(text or ""))


# ------------------------------------------------------------------ facts from PubMed XML (derived values only)
def features_from_xml(xml_text):
    """{pmid: facts} from an efetch XML document. facts: tinAbs (mentions of tinnitus in the abstract), tinMesh, tracked [ids], safety [terms], animalOnly, hasAbstract."""
    out = {}
    root = ET.fromstring(xml_text)
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID")
        title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
        ab = " ".join("".join(a.itertext()) for a in art.findall(".//Abstract/AbstractText"))
        mesh = [m.findtext("DescriptorName") or "" for m in art.findall(".//MeshHeading")]
        out[pmid] = {"tinAbs": len(re.findall("tinnit", ab, re.I)), "tinMesh": "Tinnitus" in mesh, "tracked": tracked_in(title + " " + ab + " " + " ".join(mesh)),
                     "safety": escalation._hits(title + ". " + ab, escalation._STRONG), "safetyWeak": escalation._hits(title + ". " + ab, escalation._WEAK), "animalOnly": ("Animals" in mesh and "Humans" not in mesh), "hasAbstract": len(ab) > 150}
    return out


def fetch_xml(ids):
    """One free efetch call (replaced in tests). None on any failure: the records then stay in the 'evaluate' lane."""
    try:
        time.sleep(0.4)
        q = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
        return urllib.request.urlopen(urllib.request.Request("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + q, headers={"User-Agent": "TinnitusEvidence-triage/1.0"}), timeout=60).read().decode("utf-8", "replace")
    except Exception:
        return None


def enrich(items, chunk=50):
    """Attach facts to PubMed queue items that lack them. Failure of any kind leaves the item without facts (fail open). Returns the number enriched."""
    todo = [it for it in items if it.get("id", "").startswith("pubmed-") and not it.get("triage")]
    n = 0
    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        xml = fetch_xml([it["id"].split("-", 1)[1] for it in part])
        if not xml:
            continue
        try:
            facts = features_from_xml(xml)
        except ET.ParseError:
            continue
        for it in part:
            f = facts.get(it["id"].split("-", 1)[1])
            if f is not None:
                it["triage"] = f
                n += 1
    return n


# ------------------------------------------------------------------ classification
def classify(item):
    """Pure function of the item's own metadata. Returns {'lane': 'evaluate'|'catalogue', 'tier': 0-3, 'reasons': [...], 'rule': 'C1'|None}."""
    R = rules()
    iid, title = item.get("id", ""), item.get("title", "") or ""
    pts = [str(x).lower() for x in item.get("pubtypes", []) or []]
    facts = item.get("triage") if isinstance(item.get("triage"), dict) else None
    reasons, tier = [], None
    if item.get("triageForce"):
        return {"lane": "evaluate", "tier": 1, "reasons": ["promoted by the owner"], "rule": None}
    if item.get("notice") or notices.looks_like_notice(item) or any(t in R["noticePubtypes"] for t in pts):
        return {"lane": "evaluate", "tier": 0, "reasons": ["correction, retraction or expression-of-concern notice"], "rule": None}
    tin_title = bool(re.search("tinnit", title, re.I))
    title_tracked = tracked_in(title)
    fact_tracked = sorted(set((facts or {}).get("tracked") or []) - set(title_tracked))
    safety = escalation._hits(title, escalation._STRONG) or ((facts or {}).get("safety") or [])
    if any(t in R["priorityPubtypes"] for t in pts):
        reasons.append("trial, systematic review or guideline (PubMed publication type)")
    if title_tracked:
        reasons.append("names a tracked treatment in the title: " + ", ".join(title_tracked[:4]))
    if fact_tracked and tin_title:
        reasons.append("tinnitus in the title and a tracked treatment named in the abstract or MeSH: " + ", ".join(fact_tracked[:4]))
    if safety:
        reasons.append("strong safety term: " + ", ".join(list(safety)[:3]))
    if item.get("kind") in ("regulatory",) or iid.startswith(("fda-", "pagewatch-", "newsintel-")):
        reasons.append("regulatory, guideline-page or news-wire item")
    if reasons:
        return {"lane": "evaluate", "tier": 1, "reasons": reasons, "rule": None}
    if not iid.startswith("pubmed-"):
        return {"lane": "evaluate", "tier": 2, "reasons": ["registry or other record (always evaluated)"], "rule": None}
    if tin_title:
        return {"lane": "evaluate", "tier": 2, "reasons": ["tinnitus in the title"], "rule": None}
    if facts is None or "tinAbs" not in facts:
        return {"lane": "evaluate", "tier": 3, "reasons": ["scan-time facts unavailable (fail open)"], "rule": None}
    if facts.get("safetyWeak"):
        return {"lane": "evaluate", "tier": 2, "reasons": ["weaker safety wording in the title or abstract (kept for the AI evaluation, never catalogued): " + ", ".join(list(facts["safetyWeak"])[:3])], "rule": None}
    if fact_tracked:
        return {"lane": "evaluate", "tier": 3, "reasons": ["a tracked treatment is named only in the abstract or MeSH (kept for the AI evaluation, never catalogued): " + ", ".join(fact_tracked[:4])], "rule": None}
    if facts.get("tinMesh") or facts.get("tinAbs", 0) > R["catalogueMaxAbstractMentions"]:
        return {"lane": "evaluate", "tier": 3, "reasons": ["tinnitus is a MeSH heading or appears more than %d times in the abstract" % R["catalogueMaxAbstractMentions"]], "rule": None}
    return {"lane": "catalogue", "tier": 3, "rule": "C1", "reasons": ["tinnitus is not in the title or MeSH headings and appears at most %d time(s) in the abstract; no trial, review, tracked-treatment or safety signal" % R["catalogueMaxAbstractMentions"]]}


def order(items):
    """Stable order for the per-run limit: lowest tier first, then the OLDEST first within a tier (queue position 0 is the newest), so nothing starves behind a stream of newer records."""
    idx = {id(it): i for i, it in enumerate(items)}
    return sorted(items, key=lambda it: (classify(it)["tier"], -idx[id(it)]))


def audit_pick(candidates, k, salt):
    """The k catalogue candidates evaluated anyway this run: a deterministic pseudo-random choice (hash of record id and the run date), so it cannot be gamed or reproduced by accident."""
    return {it["id"] for it in sorted(candidates, key=lambda it: hashlib.sha256((salt + "|" + it["id"]).encode("utf-8")).hexdigest())[:k]}


def promote(root, item_id):
    """Owner action: move a catalogued record from the archive back into the queue, to be evaluated first. Returns True if found."""
    root = Path(root)
    ap, qp = root / "data/review-queue/archive.json", root / "data/review-queue/queue.json"
    arch, queue = json.loads(ap.read_text(encoding="utf-8")), json.loads(qp.read_text(encoding="utf-8"))
    hit = next((a for a in arch["items"] if (a.get("item") or {}).get("id") == item_id and str(a.get("reason", "")).startswith("catalogued")), None)
    if not hit:
        return False
    arch["items"] = [a for a in arch["items"] if a is not hit]
    it = dict(hit["item"]); it.setdefault("kind", "study"); it["triageForce"] = True
    it["summary"] = "Promoted by the owner from the catalogue for AI evaluation."
    queue["items"].insert(0, it)
    ap.write_text(json.dumps(arch, indent=2, ensure_ascii=False), encoding="utf-8")
    qp.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "promote":
        print("promoted" if promote(ENGINE.parent, sys.argv[2]) else "not found in the catalogue")
    else:
        print("usage: python engine/triage.py promote <item-id>   (moves a catalogued record back to the queue for AI evaluation)")

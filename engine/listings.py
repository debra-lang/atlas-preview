#!/usr/bin/env python3
"""Tinnitus Evidence - Phase 1: automatic research LISTINGS (no AI, no interpretation). Prepared 23 Oct 2026; ships OFF.

A listing states bibliographic facts about a record the scan found, after the record has been checked against its primary source:
  title, journal or sponsor, date, identifier (PMID or NCT), article type, registry status for trials, the tracked treatments the title names, and a link.
It never says what a study found, whether it is good, or what it means for any treatment. The page that shows it adds the standing line "not yet assessed by Tinnitus Evidence".

What gets listed (all deterministic, shared with engine/triage.py):
  * PubMed studies and registry (ClinicalTrials.gov) records whose primary record could be fetched, whose identifier and title match that record, that are not a retraction, correction or
    expression-of-concern notice, and that are not an incidental mention (triage rule C1: tinnitus absent from the title and MeSH headings and at most twice in the abstract).
  * Never listed: notices (handled by the integrity notices), news-wire items (company intelligence is not evidence), FDA and page-watch items (regulatory notices have their own path),
    anything the owner has paused or topic-held, and anything whose record cannot be verified (it is retried for up to MAX_DEFERRALS cycles, then counted as unverifiable and kept in the queue).
Nothing is deleted: every queue item ends with an outcome recorded on it (listed, screened-out, notice, unverifiable, failed-verification) and counted in the update history.

Settings: engine/automation_settings.json {"listings": true} turns the listings on; anything else (missing file, false, "true", 1) is OFF.
"""
import json, re, sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
import triage, grounding, registry_record   # noqa: E402

SETTINGS_REL = "engine/automation_settings.json"
LISTINGS_REL = "data/listings.json"
HISTORY_REL = "data/update-history.json"
LISTABLE_KINDS = ("study", "trial")
MAX_NEW_PER_RUN = 120          # a first run over a backlog is spread over cycles; nothing is dropped
MAX_DEFERRALS = 3              # cycles an unverifiable record is retried before it is counted as unverifiable
MAX_HISTORY = 400
NOTICE_PUBTYPES = {"retracted publication", "retraction of publication", "published erratum", "expression of concern", "erratum", "corrected and republished article"}
HIGH_IMPACT = re.compile(r"randomi[sz]ed controlled trial|meta-analysis|systematic review|practice guideline|guideline", re.I)


def load_settings(settings):
    """Exactly-true semantics, like every other switch in this project. "listingsIncludePaused": ids the owner has paused (kept out of AI evaluation and publication) that may nevertheless
    be LISTED as bibliographic facts; the pause itself is untouched. Only ids named here are affected (owner decision 23 Oct 2026 for the three 2026 AAO-HNSF guideline records)."""
    s = settings if isinstance(settings, dict) else {}
    ids = s.get("listingsIncludePaused")
    return {"listings": s.get("listings") is True, "updateHistory": s.get("updateHistory") is True,
            "includePaused": sorted({i for i in ids if isinstance(i, str) and i.startswith("pubmed-")}) if isinstance(ids, list) else []}


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def key_of(item):
    """PMID or NCT number: one listing per record, however many queue entries (registry updates) exist."""
    iid = item.get("id", "")
    if iid.startswith("pubmed-"):
        return "PMID " + iid.split("-", 1)[1]
    m = re.search(r"NCT\d{8}", iid + " " + item.get("url", ""))
    return m.group(0) if m else None


def trial_status(item):
    m = re.search(r"status:\s*([A-Z_]+)", item.get("summary", "") or "")
    return m.group(1) if m else None


# Treatments are tagged from the TITLE only, by the keyword aliases in engine/triage_rules.json. Those aliases were written to order the evaluation queue, so a few are too broad to say
# "this record concerns that treatment" (a bare "drug", "cervical", "pulsatile", "stenting", "internet-based", "insomnia", "regenerat..."): they are not used for tagging. "bimodal" alone is
# also Lenire's own description, so the Shore tag needs "Shore" or "somatosensory stimulation". The tag means "the title contains words linked to this treatment", nothing more.
TAG_EXCLUDED = {"digital-cbt", "cbt-i", "off-label-drugs", "somatic-physio", "venous-stenting", "sswr", "regenerative"}


def tags_for(title):
    found = set(triage.tracked_in(title)) - TAG_EXCLUDED
    # the queue-ordering alias for Lenire also matches "neuromodulation" and "trigeminal"; for tagging only the product, the company and "tongue stimulation" count
    if "lenire" in found and not re.search(r"\bLenire\b|tongue stimulation|\bNeuromod\b", title or "", re.I):
        found.discard("lenire")
    if "shore-bimodal" in found and not re.search(r"\bShore\b|somatosensory stimulation", title or "", re.I):
        found.discard("shore-bimodal")
    return sorted(found)


def _field(text, name):
    m = re.search(rf"^{name}:(.*)$", text or "", re.M | re.I)
    return m.group(1) if m else ""


def relevance(item, record_text=None):
    """Is the record about tinnitus, or only mentioning it? Returns (listed?, tier, reason); tier 2 = clearly about tinnitus, tier 3 = listed but less clearly ("Other records").
    PubMed (decided before any fetch, from the scan-time facts): tinnitus in the title, or a MeSH heading -> tier 2; mentioned 3 or more times in the abstract -> tier 3; otherwise a passing mention.
    Registry (decided on the fetched record): tinnitus in the title, official title, conditions, keywords or a PRIMARY outcome -> tier 2; 5 or more mentions in the record -> tier 3; otherwise a passing mention
    (typically an adverse-effect list, an inclusion criterion or a secondary questionnaire). A tracked treatment in the title does NOT make a record relevant (the triage tiers use it to order work, not to judge relevance)."""
    if re.search("tinnit", item.get("title", ""), re.I):
        return True, 2, "tinnitus in the title"
    if item.get("id", "").startswith("pubmed-"):
        f = item.get("triage") if isinstance(item.get("triage"), dict) else {}
        if f.get("tinMesh"):
            return True, 2, "tinnitus is a MeSH heading"
        if (f.get("tinAbs") or 0) >= 3:
            return True, 3, "tinnitus is mentioned %d times in the abstract" % f["tinAbs"]
        return False, 0, "tinnitus is a passing mention (abstract mentions: %s, not a MeSH heading, not in the title)" % f.get("tinAbs", "?")
    t = record_text or ""
    head = " ".join(_field(t, n) for n in ("Title", "Official title", "Conditions", "Keywords"))
    primary = " ".join(m.group(1) for m in re.finditer(r"^PRIMARY OUTCOME[^:\n]*:\s*([^|\n]*)", t, re.M))    # the measure's TITLE only (before the first " | "), not its long description
    if re.search("tinnit", head + " " + primary, re.I):
        return True, 2, "tinnitus in the title, conditions, keywords or a primary outcome"
    n = len(re.findall("tinnit", t, re.I))
    if n >= 5:
        return True, 3, "tinnitus is mentioned %d times in the registry record" % n
    return False, 0, "tinnitus is a passing mention in the registry record (%d mention(s), not in the title, conditions, keywords or a primary outcome)" % n


def verify(item, record_text, meta):
    """Deterministic source verification of one item against its fetched primary record. ok is True only when every check passed."""
    meta = meta or {}
    fetched = meta.get("completeness") in ("COMPLETE", "SHORTENED", "TRUNCATED")
    ident = grounding.identifier_matches(item, record_text) if fetched else None
    title_ok = bool(fetched and norm(item.get("title"))[:60] and norm(item.get("title"))[:60] in norm(record_text))
    pts = [str(p).lower() for p in (meta.get("pubtypes") or item.get("pubtypes") or [])]
    is_notice = any(p in NOTICE_PUBTYPES for p in pts)
    return {"recordFetched": fetched, "identifierMatchesRecord": bool(ident), "titleMatchesRecord": title_ok, "notANotice": not is_notice,
            "ok": bool(fetched and ident and title_ok and not is_notice)}


def entry_for(item, tier, checks, meta, today):
    key = key_of(item)
    is_pm = key.startswith("PMID")
    types = [str(p) for p in (meta.get("pubtypes") or item.get("pubtypes") or [])] if is_pm else ["Registry record"]
    treatments = tags_for(item.get("title", ""))
    e = {"key": key, "kind": item.get("kind"), "title": item.get("title", ""), "source": item.get("source", ""), "date": item.get("date", ""), "url": item.get("url", ""),
         "tier": tier, "articleTypes": types, "treatments": treatments, "highImpact": bool(any(HIGH_IMPACT.search(t) for t in types)), "listedOn": today,
         "verification": {"identifierMatchesRecord": True, "titleMatchesRecord": True, "notANotice": True, "checkedOn": today}}
    if not is_pm:
        e["status"] = trial_status(item)
    return e


def process(items, existing, *, today, fetch_context, record_meta, excluded=lambda it: False, enrich=None):
    """Lists what can be listed. `items` = queue items (mutated: an outcome is recorded on each one processed), `existing` = the current listings.json object.
    Returns (new listings object, counts). fetch_context(item) -> record text; record_meta(item_id) -> its metadata (both from evaluate_queue)."""
    from collections import Counter
    counts = Counter()
    by_key = {e["key"]: e for e in (existing or {}).get("items", [])}
    todo = [it for it in items if it.get("kind") in LISTABLE_KINDS and not it.get("intelligenceOnly") and not it.get("listed") and key_of(it)]
    # one listing per registry record: only the newest queue entry of an NCT is processed, older ones are marked as folded into it
    newest = {}
    for it in todo:
        k = key_of(it)
        if k.startswith("NCT") and (k not in newest or str(it.get("date", "")) > str(newest[k].get("date", ""))):
            newest[k] = it
    for it in list(todo):
        k = key_of(it)
        if k.startswith("NCT") and newest[k] is not it:
            it["listed"] = {"on": today, "outcome": "superseded", "by": newest[k]["id"]}
            counts["superseded"] += 1
            todo.remove(it)
    held = [it for it in todo if excluded(it)]
    for it in held:
        counts["ownerHeld"] += 1          # paused or topic-held by the owner: untouched, not listed, retried only when the hold is lifted
    todo = [it for it in todo if it not in held]
    tier_of = {}
    pm = [it for it in todo if it["id"].startswith("pubmed-")]
    if enrich and pm:
        enrich(pm)
    for it in todo:
        c = triage.classify(it)
        tier_of[it["id"]] = c
    todo.sort(key=lambda it: (tier_of[it["id"]]["tier"], str(it.get("date", ""))), reverse=False)
    handled = 0
    for it in todo:
        c = tier_of[it["id"]]
        if c["tier"] == 0:
            it["listed"] = {"on": today, "outcome": "notice"}
            counts["notice"] += 1
            continue
        if it["id"].startswith("pubmed-") and not isinstance(it.get("triage"), dict):
            it["listDeferred"] = (it.get("listDeferred") or 0) + 1       # relevance facts unavailable (PubMed lookup failed): decide next cycle rather than list blindly
            if it["listDeferred"] >= MAX_DEFERRALS:
                it["listed"] = {"on": today, "outcome": "unverifiable", "reason": "relevance facts could not be fetched after %d cycles" % MAX_DEFERRALS}
                counts["unverifiable"] += 1
            else:
                counts["deferred"] += 1
            continue
        tier = 0
        if it["id"].startswith("pubmed-"):
            ok, tier, why = relevance(it)
            if not ok:
                it["listed"] = {"on": today, "outcome": "screened-out", "reason": why}
                counts["screenedOut"] += 1
                continue
        if handled >= MAX_NEW_PER_RUN:
            counts["waiting"] += 1
            continue
        handled += 1
        text = fetch_context(it)
        meta = record_meta(it["id"]) or registry_record.parse_header(text) or {"completeness": "UNKNOWN"}
        chk = verify(it, text, meta)
        if not chk["recordFetched"]:
            it["listDeferred"] = (it.get("listDeferred") or 0) + 1
            if it["listDeferred"] >= MAX_DEFERRALS:
                it["listed"] = {"on": today, "outcome": "unverifiable", "reason": "the primary record could not be fetched after %d cycles" % MAX_DEFERRALS}
                counts["unverifiable"] += 1
            else:
                counts["deferred"] += 1
            continue
        if not chk["notANotice"]:
            it["listed"] = {"on": today, "outcome": "notice"}
            counts["notice"] += 1
            continue
        if not chk["ok"]:
            it["listed"] = {"on": today, "outcome": "failed-verification", "checks": {k: v for k, v in chk.items() if k != "ok"}}
            counts["failedVerification"] += 1
            continue
        if not it["id"].startswith("pubmed-"):
            ok, tier, why = relevance(it, text)
            if not ok:
                it["listed"] = {"on": today, "outcome": "screened-out", "reason": why}
                counts["screenedOut"] += 1
                continue
        e = entry_for(it, tier, chk, meta, today)
        old = by_key.get(e["key"])
        if old:                            # a registry record already listed: refresh date and status, keep the first listing date
            e["listedOn"] = old["listedOn"]
            if old.get("status") != e.get("status") or old.get("date") != e.get("date"):
                counts["updated"] += 1
        else:
            counts["listed"] += 1
        by_key[e["key"]] = e
        it["listed"] = {"on": today, "outcome": "listed", "key": e["key"]}
    out = sorted(by_key.values(), key=lambda e: (e["listedOn"], e["key"]), reverse=True)
    return {"version": 1, "updated": today, "count": len(out), "items": out}, dict(counts)


def history_entry(today, status, counts, listings_total, cost_usd):
    ev = status.get("evaluation") or {}
    return {"date": today, "scanned": status.get("examined", 0), "newItems": status.get("newItems", 0), "listed": counts.get("listed", 0), "listingsUpdated": counts.get("updated", 0),
            "screenedOut": counts.get("screenedOut", 0), "waitingForVerification": counts.get("deferred", 0) + counts.get("waiting", 0), "unverifiable": counts.get("unverifiable", 0),
            "failedVerification": counts.get("failedVerification", 0), "retractionNoticesFound": status.get("retractionFindings"), "trialStatusUpdates": status.get("trialStatusUpdates", 0),
            "listingsTotal": listings_total, "aiEvaluation": ev.get("state", "not-run"), "aiAttempted": ev.get("attempted", 0), "aiUnusable": ev.get("parseErrors", 0),
            "estimatedCostUSD": round(cost_usd or 0.0, 4)}


def add_history(history, entry):
    """Append (or replace the same day's entry: an idempotent rerun must not double-count), newest first, bounded."""
    rows = [r for r in (history or {}).get("entries", []) if r.get("date") != entry["date"]]
    rows.insert(0, entry)
    return {"version": 1, "entries": rows[:MAX_HISTORY]}

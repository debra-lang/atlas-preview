#!/usr/bin/env python3
"""Tinnitus Atlas — AI evidence evaluation for the review queue.

For every un-evaluated item in data/review-queue/queue.json, this script:
  1. fetches the primary record (PubMed abstract / ClinicalTrials.gov study JSON),
  2. asks Claude to evaluate it against the platform's evidence rules,
  3. writes a structured `evaluation` object + proposed changes back into the queue item.

It NEVER touches the published data/ files — the admin reviews everything in admin.html
first. Requires:  pip install anthropic   and an ANTHROPIC_API_KEY (or `ant auth login`).

Usage:  python engine/evaluate_queue.py [--limit 10] [--model claude-opus-5]
"""
import json, sys, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "data" / "review-queue" / "queue.json"
UA = {"User-Agent": "TinnitusAtlas-evaluator/1.0"}

# Outcome of the most recent main() call, for the caller (weekly_cycle) and the health check. An evaluation step must never look
# successful when it was not: every call records attempted / succeeded / failed counts and the classes of error it met.
LAST_RUN = {}
FATAL_CLASSES = ("auth", "billing", "permission")   # retrying other items cannot help: stop at once instead of burning N doomed calls

MODEL = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "claude-opus-5"
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10

EVAL_FIELDS = """{
  "whatIsNew": "one or two sentences: what is genuinely new here (or 'nothing new' if it recycles known results)",
  "relevanceCategory": "1-6 integer. 1 = direct tinnitus TREATMENT evidence (trial/review of a treatment for tinnitus). 2 = tinnitus-specific science (mechanism, measurement, epidemiology OF TINNITUS itself). 3 = treatment evidence where tinnitus is a SECONDARY outcome of another condition's treatment. 4 = adjacent-condition evidence with real tinnitus relevance (hyperacusis, Menière, SSNHL, pulsatile-tinnitus vascular work). 5 = tinnitus merely INCIDENTAL (a symptom mention inside an unrelated study). 6 = irrelevant / false positive. Categories 5-6 never reach the public feed; 3-4 are archived as context, never treated as treatment evidence.",
  "notRelevant": false,
  "affectedTreatment": "treatment id from the provided list, or 'none' or 'new-treatment-candidate'",
  "studyType": "RCT | crossover RCT | cohort | chart review | meta-analysis | registry update | press release | regulatory record | other",
  "studyQuality": "high | moderate | low | not-a-study",
  "population": "who was studied, plainly, or 'Not reported'",
  "sampleSize": "number or 'Not reported'",
  "controlQuality": "sham/placebo-controlled | active-control | no-control | n/a",
  "randomized": true,
  "blinded": "double | single | none | unclear | n/a",
  "primaryEndpoint": "what it was, or 'Not reported'",
  "secondaryEndpoints": "important ones, or 'Not reported'",
  "comparisonType": "between-group | within-group only | none | Not reported — NEVER present within-group improvement as proof of efficacy",
  "numericalResult": "the key numbers, exactly as reported, or 'none reported'",
  "loudnessEffect": "what this shows about the tinnitus percept itself: none | limited | moderate | strong, + one sentence. NEVER infer loudness from THI/TFI/QoL.",
  "distressEffect": "none | limited | moderate | strong, + one sentence",
  "otherOutcomes": "sleep / quality-of-life / hearing / underlying-disease outcomes, kept separate, or 'Not reported'",
  "clinicalSignificance": "statistical significance is NOT clinical importance — one sentence on whether the effect size matters to patients",
  "safetyObservations": "what THIS study reported about safety (e.g. 'no serious adverse events reported in N=60 over 16 weeks') — never compress to 'safe'; 'Not reported' if absent",
  "safetySignal": false,
  "mainLimitations": ["list"],
  "conflictOfInterest": "manufacturer-funded / author equity / independent / unclear, + detail",
  "regulatorySource": "authoritative (FDA/EMA/registry record) | company announcement | secondary reporting | n/a",
  "evidenceDirection": "strengthens | weakens | no-meaningful-change",
  "changeClass": "routine | major — 'major' if this could change any evidence score, tier, ranking, loudness/distress rating, safety assessment, or regulatory status; one new paper alone is almost never enough to make a major conclusion, but flagging it 'major' HOLDS it for deeper review",
  "proposedScoreChange": {"treatment": "id", "from": 3, "to": 4, "reason": ""} ,
  "proposedRankChange": {"treatment": "id", "from": 7, "to": 5, "reason": ""},
  "importance": "Potentially Important | Interesting but Early | Confirms Previous Evidence | Negative Result | Does Not Change Current Evidence",
  "weeklyTitle": "a plain, accurate headline for the weekly feed (no hype)",
  "whyMatters": "1-2 plain-English sentences for ordinary readers",
  "factuallyVerified": false,
  "factuallyVerifiedReason": "why the factual report itself is (or is not) sufficiently verified to appear in the weekly feed — independent of whether it changes any assessment",
  "summaryForAdmin": "2-3 sentences the admin will read first",
  "confidence": "low | moderate | high — confidence in THIS recommendation",
  "duplicateOf": "existing study id if this merely re-reports something already in the database, else null"
}
Set proposedScoreChange / proposedRankChange to null unless a change is genuinely warranted.
Use "Not reported" or "Unable to verify" instead of inferring missing information."""

RULES = """You evaluate new tinnitus research for an evidence platform. Rules:
- Distinguish LOUDNESS (psychoacoustic loudness matching, loudness ratings of the percept) from
  DISTRESS (THI/TFI/TQ, anxiety, sleep, QoL). Never present a distress improvement as loudness.
- Prefer primary sources; treat press releases as unverified until a paper/registry confirms.
- Flag manufacturer funding and author conflicts.
- A treatment must not gain score merely for being new or technologically impressive.
- Evidence scores (1-5) reflect: study quality, size, randomization, blinding, sham control,
  independent replication, clinical significance, follow-up, safety, COI, regulatory evidence.
- Be skeptical but not dismissive; failed/negative results are important information.
- If the item duplicates a study already in the database (same trial reported elsewhere), say so.
- Items marked intelligenceOnly (news-wire watch) are INTELLIGENCE, not evidence: they can only
  ever publish as labeled company-reported developments and never strengthen any rating."""


def load_paused():
    """Ids listed in engine/paused_ids.json: items the owner wants kept out of automated evaluation and publication."""
    try:
        return set(json.loads((ROOT / "engine" / "paused_ids.json").read_text(encoding="utf-8")).get("ids", []))
    except Exception:
        return set()


def classify_error(e):
    """Map an Anthropic SDK error to a short class: auth | billing | permission | rate_limit | server | other."""
    code = getattr(e, "status_code", None)
    msg = str(getattr(e, "message", "") or e).lower()
    if code == 401 or "invalid x-api-key" in msg or "api key is invalid" in msg or "authentication" in msg:
        return "auth"
    if code == 403:
        return "permission"
    if code == 400 and ("credit balance" in msg or "billing" in msg):
        return "billing"
    if code == 429:
        return "rate_limit"
    if code in (500, 502, 503, 504, 529):
        return "server"
    return "other"


def _record(**kw):
    LAST_RUN.clear()
    LAST_RUN.update({"attempted": 0, "succeeded": 0, "failed": 0, "parseErrors": 0, "errorClasses": {}, "fatal": None, "preflight": "not-run", "reason": None})
    LAST_RUN.update(kw)


def preflight(client, anthropic):
    """One 1-token request before any real work. Returns None when usable, or (class, short message) for a fatal credential/billing/permission
    problem. Non-fatal problems (rate limit, 5xx, network) return None so the normal per-item handling applies. Never logs the key."""
    try:
        client.messages.create(model=MODEL, max_tokens=1, messages=[{"role": "user", "content": "ping"}])
        return None
    except anthropic.APIStatusError as e:
        cls = classify_error(e)
        if cls in FATAL_CLASSES:
            return cls, f"HTTP {getattr(e, 'status_code', '?')}: {str(getattr(e, 'message', e))[:160]}"
        return None
    except Exception:
        return None


def fetch_context(item):
    """Pull the primary record text for the item, best-effort."""
    try:
        if item["id"].startswith("pubmed-"):
            pmid = item["id"].split("-", 1)[1]
            q = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"})
            req = urllib.request.Request(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{q}", headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")[:12000]
        if item["id"].startswith("ctgov-"):
            nct = item["id"].split("-")[1]
            req = urllib.request.Request(f"https://clinicaltrials.gov/api/v2/studies/{nct}?format=json", headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.dumps(json.loads(r.read())["protocolSection"], indent=1)[:12000]
    except Exception as e:
        return f"(could not fetch primary record: {e})"
    return "(no primary record fetcher for this source; evaluate from the metadata alone and lower confidence)"


def main(limit=None):
    """Evaluate pending queue items. Returns (evaluated, skipped_reason) for pipeline use."""
    _record()
    try:
        import anthropic
    except ImportError:
        print("evaluate_queue: 'anthropic' package not installed — evaluation skipped.", file=sys.stderr)
        _record(fatal="not-configured", reason="anthropic package not installed (pip install anthropic)")
        return 0, "anthropic package not installed (pip install anthropic)"
    import os
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        # the SDK defers credential resolution to request time, so check up front
        print("evaluate_queue: ANTHROPIC_API_KEY not set — evaluation skipped.", file=sys.stderr)
        _record(fatal="not-configured", reason="ANTHROPIC_API_KEY not set (add it to GitHub repo Secrets)")
        return 0, "ANTHROPIC_API_KEY not set (add it to GitHub repo Secrets)"
    try:
        client = anthropic.Anthropic()
    except Exception as e:
        print(f"evaluate_queue: no credentials — evaluation skipped ({e}).", file=sys.stderr)
        _record(fatal="not-configured", reason=f"no credentials: {e}")
        return 0, f"no credentials: {e}"
    if limit:
        global LIMIT
        LIMIT = limit

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    treatments = json.loads((ROOT / "data" / "treatments.json").read_text(encoding="utf-8"))
    studies = json.loads((ROOT / "data" / "studies.json").read_text(encoding="utf-8"))
    t_index = [{"id": t["id"], "name": t["name"], "tier": t["tier"], "evidenceScore": t["evidenceScore"],
                "loudness": t["loudness"]["level"], "distress": t["distress"]["level"]} for t in treatments]
    s_index = [{"id": s["id"], "title": s["title"], "year": s["year"]} for s in studies]

    paused = load_paused()   # owner-paused items are never sent to the API (they stay queued, untouched)
    todo = [it for it in queue.get("items", []) if not it.get("evaluation") and it.get("id") not in paused][:LIMIT]
    if not todo:
        print("Nothing to evaluate — queue items all have evaluations (or queue is empty).")
        _record(preflight="skipped-nothing-to-do")
        return 0, None
    pf = preflight(client, anthropic)
    if pf:
        cls, detail = pf
        msg = f"evaluation unavailable ({cls}): {detail}"
        print(f"evaluate_queue: {msg} — no items attempted, all {len(todo)} remain queued.", file=sys.stderr)
        _record(fatal=cls, preflight="failed", reason=msg)
        return 0, msg
    _record(preflight="ok")
    done = 0

    for it in todo:
        print(f"Evaluating {it['id']} — {it['title'][:70]}…", flush=True)
        context = fetch_context(it)
        prompt = (
            f"{RULES}\n\n"
            f"CURRENT TREATMENT DATABASE (id, name, tier, score, loudness, distress):\n{json.dumps(t_index)}\n\n"
            f"STUDIES ALREADY IN DATABASE:\n{json.dumps(s_index)}\n\n"
            f"NEW ITEM METADATA:\n{json.dumps({k: it.get(k) for k in ('id', 'kind', 'title', 'source', 'date', 'url', 'summary')})}\n\n"
            f"PRIMARY RECORD:\n{context}\n\n"
            f"Respond with ONLY a JSON object exactly matching this shape (no markdown fences):\n{EVAL_FIELDS}"
        )
        LAST_RUN["attempted"] += 1
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4000,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.RateLimitError:
            LAST_RUN["failed"] += 1
            LAST_RUN["errorClasses"]["rate_limit"] = LAST_RUN["errorClasses"].get("rate_limit", 0) + 1
            print("  rate-limited; stopping — re-run later."); break
        except anthropic.APIStatusError as e:
            cls = classify_error(e)
            LAST_RUN["failed"] += 1
            LAST_RUN["errorClasses"][cls] = LAST_RUN["errorClasses"].get(cls, 0) + 1
            print(f"  API error {e.status_code} ({cls}){': ' + str(e.message)[:200] if cls == 'other' else ''}; skipping.")   # message shown only for unclassified errors
            if cls in FATAL_CLASSES:
                LAST_RUN["fatal"] = cls
                print(f"  {cls} errors cannot succeed on retry — stopping; remaining items stay queued.", file=sys.stderr)
                break
            continue
        except Exception as e:
            # never let an SDK/client error kill the whole cycle — items simply stay queued
            LAST_RUN["failed"] += 1
            LAST_RUN["errorClasses"]["exception"] = LAST_RUN["errorClasses"].get("exception", 0) + 1
            print(f"  evaluation error ({e}); stopping.", file=sys.stderr)
            LAST_RUN["reason"] = f"evaluation error: {e}"
            return done, f"evaluation error: {e}"

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            start, end = text.index("{"), text.rindex("}") + 1
            ev = json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError) as e:
            print(f"  could not parse evaluation JSON ({e}); storing raw text for admin.")
            ev = {"summaryForAdmin": text[:2000], "confidence": "low", "parseError": True}
            LAST_RUN["parseErrors"] += 1

        it["evaluation"] = ev
        # surface the essentials into the fields admin.html already renders
        it["summary"] = ev.get("summaryForAdmin", it.get("summary", ""))
        if ev.get("affectedTreatment") not in (None, "none"):
            it["treatment"] = ev["affectedTreatment"]
        if ev.get("proposedScoreChange"):
            it["scoreChange"] = {"from": ev["proposedScoreChange"].get("from"), "to": ev["proposedScoreChange"].get("to")}
            it["proposal"] = ev["proposedScoreChange"].get("reason", "")
        if ev.get("proposedRankChange"):
            it["rankChange"] = {"from": ev["proposedRankChange"].get("from"), "to": ev["proposedRankChange"].get("to")}
        it["why"] = ev.get("whatIsNew", "")
        done += 1
        LAST_RUN["succeeded"] += 1
        QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")  # save after each item

    print(f"Done ({done} evaluated, {LAST_RUN['failed']} failed of {LAST_RUN['attempted']} attempted).")
    reason = None
    if LAST_RUN["fatal"]:
        reason = f"evaluation stopped by a {LAST_RUN['fatal']} error after {LAST_RUN['attempted']} attempt(s); {len(todo) - done} item(s) remain queued"
    elif LAST_RUN["failed"]:
        reason = f"{LAST_RUN['failed']} of {LAST_RUN['attempted']} evaluation attempts failed ({LAST_RUN['errorClasses']}); those items remain queued"
    LAST_RUN["reason"] = reason
    return done, reason


if __name__ == "__main__":
    main()

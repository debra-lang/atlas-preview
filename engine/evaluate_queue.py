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
import hashlib, json, re, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import escalation, grounding, language_screen, notices, registry_record, topic_holds, triage   # noqa: E402  (deterministic helpers; none of them calls the network or the AI)
import fda_record
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
  "population": "who was studied, plainly, as the record states it (condition plus any setting, age or inclusion criteria). If the record names only the bare condition (for example 'tinnitus patients') and does not describe the participants, answer exactly: Not reported (record says only: <the words it uses>)",
  "sampleSize": "number or 'Not reported'",
  "controlQuality": "sham/placebo-controlled | active-control | no-control | n/a",
  "randomized": true,
  "blinded": "double | single | none | unclear | n/a",
  "primaryEndpoint": "what it was, or 'Not reported'",
  "secondaryEndpoints": "important ones, or 'Not reported'",
  "comparisonType": "between-group | within-group only | none | Not reported",
  "numericalResult": "the key numbers, exactly as reported, or 'none reported'",
  "loudnessEffect": "what this shows about the tinnitus percept itself: none | limited | moderate | strong, + one sentence. NEVER infer loudness from THI/TFI/QoL.",
  "distressEffect": "none | limited | moderate | strong, + one sentence",
  "otherOutcomes": "sleep / quality-of-life / hearing / underlying-disease outcomes, kept separate, or 'Not reported'",
  "clinicalSignificance": "statistical significance is NOT clinical importance — one sentence on whether the effect size matters to patients",
  "safetyObservations": "what THIS study reported about safety (e.g. 'no serious adverse events reported in N=60 over 16 weeks') — never compress to 'safe'; 'Not reported' if absent",
  "safetySignal": false,
  "mainLimitations": ["list"],
  "conflictOfInterest": "ONE label from: manufacturer-funded | author equity | independent | unclear, then ' - ' and what the record says. Use 'author equity' only if the record says an author holds shares or equity; employment is not equity; if funding or conflicts are not stated write 'unclear - not stated in the record'",
  "regulatorySource": "authoritative (FDA/EMA/registry record) | company announcement | secondary reporting | n/a",
  "evidenceDirection": "strengthens | weakens | no-meaningful-change",
  "changeClass": "routine | major — 'major' if this could change any evidence score, tier, ranking, loudness/distress rating, safety assessment, or regulatory status; one new paper alone is almost never enough to make a major conclusion, but flagging it 'major' HOLDS it for deeper review",
  "proposedScoreChange": {"treatment": "id", "from": 3, "to": 4, "reason": ""} ,
  "proposedRankChange": {"treatment": "id", "from": 7, "to": 5, "reason": ""},
  "importance": "Potentially Important | Interesting but Early | Confirms Previous Evidence | Negative Result | Does Not Change Current Evidence",
  "weeklyTitle": "a plain, accurate headline for the weekly feed (no hype)",
  "whyMatters": "1-2 plain-English sentences for ordinary readers",
  "factuallyVerified": false,
  "factuallyVerifiedReason": "answer BOTH questions separately: (1) is every fact in your report stated in the record? (2) does the record itself give enough verifiable specifics (what was done, in whom, how many, what was found) to check the study's own central claim? Say what the record lacks if (2) is no — independent of whether it changes any assessment",
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
- Items with intelligenceOnly true in the item metadata (news-wire watch) are INTELLIGENCE, not evidence: they can only
  ever publish as labeled company-reported developments and never strengthen any rating.
- comparisonType must be exactly one of the listed options. If the results are within-group only, answer 'within-group only' and
  never present within-group improvement as proof of efficacy.
- SOURCE GROUNDING. State only facts that are written in the PRIMARY RECORD or the item metadata. Do not add from memory: authors'
  affiliations, institutional history, earlier studies, who was 'first', or study characteristics (blinding, sham control, language,
  setting) that the record does not state; write 'Not reported' instead. A limitation that you infer rather than read must be written
  as 'Inference: ...' and never as fact. Copy numbers exactly as the record gives them; do not calculate new ones. Do not add evaluative
  judgements (for example 'well-sized', 'reassuring', 'robust') or descriptions of a product (what it is, whether it is marketed, its mechanism) that the record does not state.
- The PRIMARY RECORD starts with a completeness header. If it says TRUNCATED or UNAVAILABLE, or recordAvailable is false in the metadata,
  say so in mainLimitations and set confidence to 'low' (never 'high'). Results are only 'posted' when the record says hasResults is TRUE.
- factuallyVerified and confidence are your own SELF-ASSESSMENT. They are not independent verification; code checks your numbers and
  claims against the record afterwards and lowers confidence where the record does not support you. factuallyVerified answers TWO different
  questions and is true only if BOTH are yes: (1) is every fact you report stated in the record, with nothing added? (2) does the record itself
  contain enough verifiable specifics about the study (what was done, in whom, how many, and what was found, with figures where results are
  claimed) to check the study's own central claim? A faithful summary of a record that lacks these - for example an abstract that says a
  treatment "shows promise" or "improved outcomes" but gives no design, no sample size and no results - answers (2) no, so factuallyVerified
  must be false, and factuallyVerifiedReason must say what the record lacks. Accurately describing a source is not the same as the source being
  sufficient evidence.
- Correction, erratum, retraction and expression-of-concern notices contain no new evidence: set relevanceCategory 6 and notRelevant
  true (a separate integrity process handles them)."""


PRICES = {"claude-opus-5": (5.0, 25.0), "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}   # USD per million tokens (list prices, checked 21 Oct 2026)


MAX_OUTPUT_TOKENS = 8000   # per-answer ceiling; adaptive-thinking tokens count against it. The model never sees this number, so raising it changes only answers that would have been cut off.
                           # Was 4,000 until 23 Oct 2026 (1 of 18 pilot answers hit it). Raise once to 16,000 only on the evidence in docs: a truncation at this ceiling, or two answers over NEAR_MISS_FRACTION of it within three cycles.
NEAR_MISS_FRACTION = 0.75  # an answer using more than this share of the ceiling is counted as a near miss (an early warning, shown in the run summary)
# ---- Cost controls (all enforced in code, before any paid call) ----
CLIENT_MAX_RETRIES = 1     # SDK-level retries per request (the SDK default is 2). Our own loops never retry a request.
CLIENT_TIMEOUT_S = 480.0   # one request must finish within this; explicit, so a hung connection cannot hold a cycle
MAX_ITEM_ATTEMPTS = 2      # paid attempts on one item that end in an API error; then the item is given up (listed without AI), never retried forever
DEFAULT_MONTHLY_BUDGET_USD = 20.0   # used when eval_settings.json has no valid budget.monthlyUSD; there is no way to switch the cap off
BUDGET_WARN_FRACTION = 0.6


def response_failure(stop_reason, text):
    """Why a model answer cannot be used, or None. stop_reason comes from the API response (None only for test doubles that do not set it).
    'max_tokens' = cut off at the output ceiling (any JSON in it is incomplete by definition, so it is never parsed); 'refusal' = declined; anything
    other than a normal end = unexpected; no text at all = empty."""
    if stop_reason == "max_tokens":
        return "truncated"
    if stop_reason == "refusal":
        return "refused"
    if stop_reason not in (None, "end_turn", "stop_sequence"):
        return "unexpected-stop"
    if not (text or "").strip():
        return "empty"
    return None


def _give_up(it):
    """Store an unusable-evaluation placeholder for an item whose paid attempts all ended in API errors (no further call is made for it)."""
    n = it.get("evalAttempts") or 0
    it["evaluation"] = {"summaryForAdmin": FAILURE_NOTE["attempts-exhausted"] + f" ({n} attempts)", "confidence": "low", "parseError": True, "failureKind": "attempts-exhausted",
                        "stopReason": None, "outputTokens": None, "maxOutputTokens": MAX_OUTPUT_TOKENS}
    it["evalInput"] = {"model": MODEL, "promptHash": prompt_hash(), "maxOutputTokens": MAX_OUTPUT_TOKENS, "attempts": n}
    it["summary"] = it["evaluation"]["summaryForAdmin"]
    LAST_RUN["parseErrors"] = LAST_RUN.get("parseErrors", 0) + 1
    fk = LAST_RUN.setdefault("failureKinds", {})
    fk["attempts-exhausted"] = fk.get("attempts-exhausted", 0) + 1
    print(f"  {it.get('id')}: {n} failed attempts - given up; listed without AI evaluation.", flush=True)


FAILURE_NOTE = {"truncated": "The AI answer was cut off at the output-token limit, so it is incomplete and was not used.",
                "refused": "The AI declined to answer.", "unexpected-stop": "The AI stopped for an unexpected reason.",
                "empty": "The AI returned no text.", "unparseable": "The AI answer was not valid JSON.",
                "attempts-exhausted": "The AI could not be reached for this item after repeated attempts."}


def load_budget():
    """Monthly evaluation budget in USD from eval_settings.json -> budget.monthlyUSD. Anything missing, non-numeric, boolean, zero or negative falls back to the default: the cap cannot be disabled by a typo."""
    try:
        s = json.loads((ROOT / "engine" / "eval_settings.json").read_text(encoding="utf-8"))
        v = s.get("budget", {}).get("monthlyUSD")
    except Exception:
        v = None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 < v <= 10000):
        return DEFAULT_MONTHLY_BUDGET_USD
    return float(v)


def month_spent_usd(today=None):
    """Estimated spend so far this calendar month, from the usage ledger the cycle writes after each run that called the model. No ledger yet = 0.0. A ledger that exists but cannot be read = None
    (callers treat that as 'budget exhausted': never spend blind)."""
    month = (today or time.strftime("%Y-%m-%d"))[:7]
    path = ROOT / "engine" / "usage-ledger.json"
    if not path.exists():
        return 0.0
    try:
        runs = json.loads(path.read_text(encoding="utf-8"))["runs"]
        return round(sum(float(r.get("estimatedCostUSD", 0) or 0) for r in runs if str(r.get("date", ""))[:7] == month), 4)
    except Exception:
        return None


def worst_case_usd(prompt_chars):
    """Upper bound for one call: the whole prompt at 3 characters per token (English runs about 4) plus the full output ceiling, at the model's list prices."""
    pin, pout = PRICES.get(MODEL, PRICES["claude-opus-5"])
    return (prompt_chars / 3.0 * pin + MAX_OUTPUT_TOKENS * pout) / 1e6


def budget_status(extra=0.0, today=None):
    """{monthlyUSD, spentUSD, fraction} for the status file and the health check. `extra` = a run's cost not yet in the ledger on disk. Ledger unreadable = fraction 1.0."""
    monthly, spent = load_budget(), month_spent_usd(today)
    if spent is None:
        return {"monthlyUSD": monthly, "spentUSD": None, "fraction": 1.0}
    spent = round(spent + extra, 4)
    return {"monthlyUSD": monthly, "spentUSD": spent, "fraction": round(spent / monthly, 3)}


def prompt_hash():
    """Fingerprint of the evaluator prompt (rules + field contract). The launch gate requires a benchmark pass on THIS prompt."""
    return hashlib.sha256((RULES + "\n" + EVAL_FIELDS).encode("utf-8")).hexdigest()[:16]


# ---- Cost options (both OFF unless engine/eval_settings.json says exactly true; see autonomy-design/11-CACHING-AND-BATCH.md) ----------------------------------
# promptCaching: the part of the request that is identical for every item (rules + treatment list + study list) is sent as its own text block with a cache
#   breakpoint. The characters the model reads are exactly the same, so the prompt fingerprint above does not change.
# useBatch: items are submitted to the Message Batches API (50% price, results within 24 h) and collected on a LATER run; see batch_cycle below.
CACHE_MIN_TOKENS = 512            # minimum cacheable prefix for claude-opus-5 / opus-5-5 / sonnet-5-5 / haiku-5-5 (below it a breakpoint silently does nothing)
CACHE_WRITE_MULT = 1.25           # 5-minute cache write = 1.25x the input price (default TTL; no 1-hour TTL is used)
BATCH_MULT = 0.5                  # Message Batches: 50% of the standard price on all token usage
CACHE_READ_PRICE = {"claude-opus-5": 0.50, "claude-opus-5-5": 0.20, "claude-sonnet-5-5": 0.20}   # USD/MTok, as documented; a model not listed is charged its full input price (never under-counts)
BATCH_STATE = "engine/batch-state.json"   # public-safe: batch id, item ids, record hashes, prompt fingerprint. No evaluation text and no key.


def load_flags():
    """Fail-closed: a cost option is on only when its setting is the JSON value true. A missing or malformed file means both off."""
    try:
        s = json.loads((ROOT / "engine" / "eval_settings.json").read_text(encoding="utf-8"))
    except Exception:
        s = {}
    s = s if isinstance(s, dict) else {}
    return {"promptCaching": s.get("promptCaching") is True, "useBatch": s.get("useBatch") is True}


def build_prompt_parts(t_index, s_index, item_meta, context):
    """The evaluator prompt as (stable prefix, per-item suffix). prefix + suffix is byte-identical to the single string earlier versions sent."""
    prefix = (f"{RULES}\n\n"
              f"CURRENT TREATMENT DATABASE (id, name, tier, score, loudness, distress):\n{json.dumps(t_index)}\n\n"
              f"STUDIES ALREADY IN DATABASE:\n{json.dumps(s_index)}\n\n")
    suffix = (f"NEW ITEM METADATA:\n{json.dumps(item_meta)}\n\n"
              f"PRIMARY RECORD:\n{context}\n\n"
              f"Respond with ONLY a JSON object exactly matching this shape (no markdown fences):\n{EVAL_FIELDS}")
    return prefix, suffix


def request_content(prefix, suffix, caching):
    """Message content. Caching off: the plain string (exactly the request earlier versions made). On: two text blocks, a breakpoint after the stable prefix."""
    if not caching:
        return prefix + suffix
    return [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": suffix}]


def usage_cost(model, usage, batch=False):
    """(total input tokens, output tokens, estimated USD) for one response. Uncached input at the input price, cache writes at 1.25x, cache reads at the cache-read
    price, output at the output price; every component halved for a batch request. Unknown model: cost 0.0 (as before)."""
    g = lambda k: (getattr(usage, k, 0) or 0) if usage is not None else 0
    fresh, write, read, out = g("input_tokens"), g("cache_creation_input_tokens"), g("cache_read_input_tokens"), g("output_tokens")
    usd = 0.0
    if model in PRICES:
        pin, pout = PRICES[model]
        usd = (fresh * pin + write * pin * CACHE_WRITE_MULT + read * CACHE_READ_PRICE.get(model, pin) + out * pout) / 1e6
        if batch:
            usd *= BATCH_MULT
    return fresh + write + read, out, usd


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
    LAST_RUN.update({"attempted": 0, "succeeded": 0, "failed": 0, "parseErrors": 0, "failureKinds": {}, "nearMisses": 0, "maxOutputTokens": 0, "errorClasses": {}, "fatal": None, "preflight": "not-run", "reason": None, "screened": 0, "recordUnavailable": 0, "inputTokens": 0, "outputTokens": 0, "costUSD": 0.0,
                     "cacheReadTokens": 0, "cacheWriteTokens": 0, "submitted": 0, "batch": None, "batchCollected": None, "catalogued": 0, "auditPicked": 0})
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


RECORD_META = {}   # item id -> metadata of the record last built for it (completeness, hasResults, truncation); read by main()


def _get(url, attempts=3):
    """GET with a polite retry: NCBI answers HTTP 429 to bursts, and any registry can have a transient 5xx/timeout. A permanent error (404 ...) is raised at once."""
    last = None
    for n in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if n + 1 < attempts:
            time.sleep(1.5 * (n + 1))
    raise last


def fetch_context(item):
    """Pull the primary record for the item as TEXT that starts with a completeness header (see registry_record.py). Best-effort: a failed
    fetch or a source without a fetcher yields an explicit UNAVAILABLE record, never an empty or silent one."""
    iid = item.get("id", "")
    try:
        if iid.startswith("pubmed-"):
            pmid = iid.split("-", 1)[1]
            q = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"})
            text, meta = registry_record.finish_pubmed_record(_get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{q}").decode("utf-8", "replace"), pmid)
            if not item.get("pubtypes"):   # PubMed's own publication types (free, one extra call): the evidence-adequacy check exempts reviews and case reports only by these
                try:
                    q2 = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "retmode": "json"})
                    meta["pubtypes"] = [str(x) for x in (json.loads(_get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{q2}"))["result"][pmid].get("pubtype") or [])]
                except Exception:
                    meta["pubtypes"] = []   # lookup failed: no exemption (fails closed)
        elif iid.startswith("ctgov-"):
            nct = iid.split("-")[1]
            text, meta = registry_record.build_ctgov_record(json.loads(_get(f"https://clinicaltrials.gov/api/v2/studies/{nct}?format=json")))
        elif iid.startswith("fda-510-k-clearance-") and re.search(r"ID=(K\d{6,7})\b", item.get("url", "")):
            k = re.search(r"ID=(K\d{6,7})\b", item.get("url", "")).group(1)
            res = json.loads(_get("https://api.fda.gov/device/510k.json?" + urllib.parse.urlencode({"search": f"k_number:{k}", "limit": "1"}))).get("results") or []
            if not res or res[0].get("k_number") != k:
                raise ValueError("the FDA database returned no matching 510(k) record")
            text, meta = fda_record.build_510k_record(res[0])
        elif iid.startswith("fda-pma-decision-"):
            raise ValueError("PMA records are not fetched automatically; held for a person")
        else:
            text, meta = registry_record.unavailable_record("headline and metadata only (this source has no record fetcher)")
    except Exception as e:
        text, meta = registry_record.unavailable_record(f"could not fetch the primary record ({str(e)[:120]})")
    RECORD_META[iid] = meta
    return text


def nct_of(item):
    m = re.search(r"NCT\d{8}", item.get("id", "") + " " + item.get("url", ""))
    return m.group(0) if m else None


def superseded_map(items):
    """{older entry id: newest entry id}. Several queue entries can be successive updates of ONE registry record (same NCT). The evaluator fetches
    the CURRENT record, so every entry would produce the same evaluation: only the newest entry is evaluated; older ones are superseded."""
    best = {}
    for pos, it in enumerate(items):
        n = nct_of(it)
        if not n:
            continue
        m = re.search(r"(\d{4}-\d{2}-\d{2})$", it.get("id", ""))
        key = (m.group(1) if m else str(it.get("date", ""))[:10], -pos)
        if n not in best or key > best[n][0]:
            best[n] = (key, it["id"])
    newest = {n: v[1] for n, v in best.items()}
    return {it["id"]: newest[nct_of(it)] for it in items if nct_of(it) and it["id"] != newest[nct_of(it)]}


def superseded_ids(items):
    return set(superseded_map(items))


def _account(usage, batch=False):
    """Add one response's tokens and estimated cost to LAST_RUN (cache reads/writes and the batch discount are priced by usage_cost)."""
    tin, tout, usd = usage_cost(MODEL, usage, batch)
    LAST_RUN["inputTokens"] += tin
    LAST_RUN["outputTokens"] += tout
    LAST_RUN["cacheReadTokens"] += (getattr(usage, "cache_read_input_tokens", 0) or 0) if usage is not None else 0
    LAST_RUN["cacheWriteTokens"] += (getattr(usage, "cache_creation_input_tokens", 0) or 0) if usage is not None else 0
    LAST_RUN["costUSD"] = round(LAST_RUN["costUSD"] + usd, 4)


def _finish_item(it, text, context, meta, item_meta, treatments, known_words, extra_eval_input=None, stop_reason=None, output_tokens=None):
    """Everything that happens to a model answer: parse, deterministic checks, escalation triggers, fields written back into the queue item. Shared by the
    one-request-at-a-time path and the batch collector, so both apply identical checks."""
    if output_tokens:
        LAST_RUN["maxOutputTokens"] = max(LAST_RUN.get("maxOutputTokens", 0), output_tokens)
        if output_tokens > NEAR_MISS_FRACTION * MAX_OUTPUT_TOKENS:
            LAST_RUN["nearMisses"] = LAST_RUN.get("nearMisses", 0) + 1
    kind = response_failure(stop_reason, text)
    ev = None
    if kind is None:
        try:
            start, end = text.index("{"), text.rindex("}") + 1
            ev = json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError) as e:
            kind = "unparseable"
            print(f"  could not parse evaluation JSON ({type(e).__name__}); storing raw text for admin.")
    if ev is None:
        # No usable evaluation. 'parseError' stays True (weekly_cycle and older readers hold on it); failureKind says WHY, so the record is never blamed for a model-side failure.
        print(f"  evaluation unusable ({kind}, stop_reason={stop_reason}); stored for admin, item held.")
        ev = {"summaryForAdmin": (FAILURE_NOTE.get(kind, "") + " Raw text, if any: " + (text or "")[:1800]).strip(), "confidence": "low", "parseError": True,
              "failureKind": kind, "stopReason": stop_reason, "outputTokens": output_tokens, "maxOutputTokens": MAX_OUTPUT_TOKENS}
        LAST_RUN["parseErrors"] += 1
        fk = LAST_RUN.setdefault("failureKinds", {})
        fk[kind] = fk.get(kind, 0) + 1

    if not ev.get("parseError"):
        # deterministic checks: the model's own factuallyVerified / confidence are self-assessments, so code records what it can verify itself
        fixes = grounding.normalise_enums(ev)
        sc = grounding.source_checks(it, ev, context, meta, known_words)
        sc["enumFixes"] = fixes
        ev["sourceChecks"] = sc
        grounding.clamp_confidence(ev, sc)
        grounding.apply_adequacy(ev, sc)   # fail closed: a record that cannot support the study's own claim overrides the model's 'verified'
        ev["escalation"] = escalation.triggers(it, context, ev, {t["id"] for t in treatments})
    it["evalInput"] = {"sourceKind": meta.get("sourceKind"), "completeness": meta.get("completeness"), "truncated": bool(meta.get("truncated")),
                       "criticalOmitted": bool(meta.get("criticalOmitted")), "hasResults": meta.get("hasResults"), "chars": len(context),
                       "omitted": meta.get("omitted", []), "shortened": meta.get("shortened", []),
                       "recordHash": hashlib.sha256(context.encode("utf-8")).hexdigest()[:16], "model": MODEL, "promptHash": prompt_hash(),
                       "intelligenceOnlyGiven": item_meta["intelligenceOnly"], "maxOutputTokens": MAX_OUTPUT_TOKENS, "outputTokens": output_tokens}
    if extra_eval_input:
        it["evalInput"].update(extra_eval_input)
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


def batch_collect(client, queue, treatments, known_words):
    """Phase 1 of the batch route (useBatch on): collect a batch submitted by an earlier run. Returns (evaluated, state) with state one of
    none | pending | unavailable | collected. While a batch is pending nothing new is submitted. Every result goes through the same checks as a normal answer.
    Safe by construction: a result is used only if the batch was made with THIS prompt fingerprint and model, the item is still queued and un-evaluated,
    and the record fetched now hashes the same as at submission; anything else leaves the item queued (it is simply submitted again)."""
    path = ROOT / BATCH_STATE
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        batch_id = st["batchId"]
        entries = st["items"]
    except Exception:
        return 0, "none"
    try:
        b = client.messages.batches.retrieve(batch_id)
        ended = getattr(b, "processing_status", None) == "ended"
    except Exception as e:
        LAST_RUN["batch"] = {"state": "unavailable", "id": batch_id, "error": type(e).__name__}
        return 0, "unavailable"
    if not ended:
        LAST_RUN["batch"] = {"state": "pending", "id": batch_id, "requests": len(entries)}
        print(f"Batch {batch_id} is still processing; nothing new is submitted until it ends.")
        return 0, "pending"
    try:
        results = list(client.messages.batches.results(batch_id))   # arrives in ANY order: matched by custom_id only
    except Exception as e:
        LAST_RUN["batch"] = {"state": "unavailable", "id": batch_id, "error": type(e).__name__}
        return 0, "unavailable"
    stale = st.get("promptHash") != prompt_hash() or st.get("model") != MODEL
    by_id = {i["id"]: i for i in queue.get("items", [])}
    counts, done, seen = {}, 0, set()

    def bump(k):
        counts[k] = counts.get(k, 0) + 1
        LAST_RUN["errorClasses"]["batch_" + k] = LAST_RUN["errorClasses"].get("batch_" + k, 0) + 1

    for r in results:
        entry = entries.get(getattr(r, "custom_id", None))
        if entry is None or r.custom_id in seen:
            counts["unmatched"] = counts.get("unmatched", 0) + 1
            continue
        seen.add(r.custom_id)
        LAST_RUN["attempted"] += 1
        rtype = getattr(r.result, "type", None)
        if rtype != "succeeded":
            bad = by_id.get(entry["id"])
            if bad is not None:
                bad["evalAttempts"] = (bad.get("evalAttempts") or 0) + 1      # a provider-side failure counts as a paid attempt (the queue is untouched until a batch is collected)
            LAST_RUN["failed"] += 1
            bump(rtype if rtype in ("errored", "expired", "canceled") else "other")
            continue
        _account(getattr(r.result.message, "usage", None), batch=True)   # billed even if the answer is then discarded
        it = by_id.get(entry["id"])
        if stale:
            LAST_RUN["failed"] += 1
            bump("discarded_prompt_changed")
            continue
        if it is None or it.get("evaluation") or it.get("notice") or it.get("topicHold"):
            LAST_RUN["failed"] += 1
            bump("item_no_longer_pending")
            continue
        context = fetch_context(it)
        meta = RECORD_META.pop(it["id"], None) or registry_record.parse_header(context) or {"completeness": "UNKNOWN"}
        if hashlib.sha256(context.encode("utf-8")).hexdigest()[:16] != entry.get("recordHash"):
            LAST_RUN["failed"] += 1
            bump("record_changed")
            continue
        text = next((blk.text for blk in r.result.message.content if blk.type == "text"), "")
        _finish_item(it, text, context, meta, entry["itemMeta"], treatments, known_words, {"batch": True, "batchId": batch_id},
                     stop_reason=getattr(r.result.message, "stop_reason", None), output_tokens=getattr(getattr(r.result.message, "usage", None), "output_tokens", None))
        done += 1
        LAST_RUN["succeeded"] += 1
    missing = len(entries) - len(seen)
    if missing > 0:
        counts["missing"] = missing
        for cid, ent in entries.items():
            if cid not in seen and by_id.get(ent["id"]) is not None:
                by_id[ent["id"]]["evalAttempts"] = (by_id[ent["id"]].get("evalAttempts") or 0) + 1
    try:
        path.unlink()
    except OSError:
        pass
    QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    LAST_RUN["batch"] = LAST_RUN["batchCollected"] = {"state": "collected", "id": batch_id, "evaluated": done, "counts": counts, "discardedPromptChanged": bool(stale)}
    print(f"Batch {batch_id} collected: {done} evaluated, other outcomes {counts}.")
    return done, "collected"


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
        client = anthropic.Anthropic(max_retries=CLIENT_MAX_RETRIES, timeout=CLIENT_TIMEOUT_S)
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
    holds = topic_holds.load_holds()   # owner topic holds (e.g. Lenire/Neuromod): same treatment as paused ids
    superseded = superseded_ids(queue.get("items", []))   # older updates of a registry record that has a newer queue entry: not evaluated again
    cited = notices.cited_index(studies)
    known_words = [w for t in treatments for w in (t["id"].replace("-", " ") + " " + t["name"]).replace("(", " ").replace(")", " ").split()] + \
                  [w for s in studies for w in (s["id"].replace("-", " ") + " " + s["title"]).split()]

    try:
        published = set(json.loads((ROOT / "engine" / "published_ids.json").read_text(encoding="utf-8")))
    except Exception:
        published = set()

    def already_published(it):
        return any(k and k in published for k in (re.sub(r"\W+", "", (it.get(x) or "").lower())[:90] for x in ("url", "title")))

    def pending(it):
        return not (it.get("evaluation") or it.get("notice") or it.get("topicHold") or it.get("languageHold") or it.get("catalogued") or it.get("id") in paused or it.get("id") in superseded
                    or already_published(it) or topic_holds.match_item(it, holds))

    # Phase A (free, no AI): correction / retraction notices are classified, never evaluated and never published as research
    for it in [i for i in queue.get("items", []) if pending(i) and notices.looks_like_notice(i)]:
        info = notices.analyse(it, fetch_context(it), cited)
        RECORD_META.pop(it["id"], None)
        if info:
            it["notice"] = info
            LAST_RUN["screened"] += 1
            print(f"Notice ({info['kind']}, {info['resolution']}): {it['id']} — not sent to the AI.", flush=True)
    if LAST_RUN["screened"]:
        QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")

    flags = load_flags()
    caching = flags["promptCaching"]
    done = 0
    if flags["useBatch"]:
        done, bstate = batch_collect(client, queue, treatments, known_words)
        if bstate == "pending":
            _record(preflight="skipped-batch-pending", screened=LAST_RUN.get("screened", 0), **{k: LAST_RUN[k] for k in ("batch",)})
            return 0, None
        if bstate == "unavailable":
            msg = "the pending batch could not be read from the API; nothing new was submitted, its items stay queued"
            LAST_RUN["reason"] = msg
            return 0, msg

    # Deterministic triage by source metadata (engine/triage.py): both parts are OFF unless eval_settings.json says exactly true. Nothing is deleted: a catalogued record is archived with its reason.
    try:
        _s = json.loads((ROOT / "engine" / "eval_settings.json").read_text(encoding="utf-8"))
    except Exception:
        _s = {}
    tri = triage.load_settings(_s)
    pend = [it for it in queue.get("items", []) if pending(it)]
    if tri["order"] or tri["catalogue"] or tri["shadow"]:
        triage.enrich(pend)                                   # free PubMed lookup of scan-time facts; any failure leaves a record in the evaluate lane
    first = []
    if tri["catalogue"] or tri["shadow"]:
        cands = [it for it in pend if triage.classify(it)["lane"] == "catalogue"]
        audit = triage.audit_pick(cands, tri["auditSample"], time.strftime("%Y-%m-%d"))
        for it in cands:
            if it["id"] in audit:
                it["triageAudit"] = True                       # evaluated anyway: measures how often rule C1 would have missed something
                first.append(it)
                LAST_RUN["auditPicked"] += 1
            elif tri["catalogue"]:
                c = triage.classify(it)
                it["catalogued"] = {"rule": c["rule"], "reason": "; ".join(c["reasons"])}
                LAST_RUN["catalogued"] += 1
            else:
                it["triageShadow"] = True                      # shadow mode: nothing changes for this record; it is evaluated normally and counted
        pend = [it for it in pend if not it.get("catalogued")]
        if cands:
            QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    if tri["order"]:
        pend = first + [it for it in triage.order(pend) if it not in first]
    # An item whose paid attempts keep ending in API errors is given up (stored as an unusable evaluation: listed without AI, counted, never retried automatically).
    for it in [i for i in pend if (i.get("evalAttempts") or 0) >= MAX_ITEM_ATTEMPTS]:
        _give_up(it)
    if any(i.get("evaluation") for i in pend):
        pend = [i for i in pend if not i.get("evaluation")]
        QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
    todo = pend[:LIMIT]
    if not todo:
        print("Nothing to evaluate — queue items all have evaluations (or queue is empty).")
        keep = {k: LAST_RUN.get(k) for k in ("attempted", "succeeded", "failed", "errorClasses", "inputTokens", "outputTokens", "costUSD", "cacheReadTokens", "cacheWriteTokens", "batch", "batchCollected", "parseErrors", "failureKinds", "nearMisses", "maxOutputTokens")}
        gave_up = {k: LAST_RUN.get(k) for k in ("parseErrors", "failureKinds")}      # items given up at the start of this run must still be reported
        _record(preflight="skipped-nothing-to-do", screened=LAST_RUN.get("screened", 0))
        LAST_RUN.update(gave_up)
        if flags["useBatch"]:
            LAST_RUN.update(keep)
        return done, None
    pf = preflight(client, anthropic)
    if pf:
        cls, detail = pf
        msg = f"evaluation unavailable ({cls}): {detail}"
        print(f"evaluate_queue: {msg} — no items attempted, all {len(todo)} remain queued.", file=sys.stderr)
        _record(fatal=cls, preflight="failed", reason=msg, screened=LAST_RUN.get("screened", 0))
        return 0, msg
    LAST_RUN["preflight"] = "ok"
    monthly, spent0 = load_budget(), month_spent_usd()
    if spent0 is None or spent0 >= monthly:
        msg = (f"monthly evaluation budget reached (${spent0:.2f} of ${monthly:.2f} estimated)" if spent0 is not None
               else "usage ledger could not be read; evaluation paused rather than spend blind")
        print(f"evaluate_queue: {msg} — no items attempted, all {len(todo)} remain queued.", file=sys.stderr)
        _record(fatal="budget", preflight="ok", reason=msg, screened=LAST_RUN.get("screened", 0))
        return 0, msg

    def over_budget(prompt_chars, extra=0.0):
        """True when this call's worst case would take the month past the budget (spend so far + this run so far + calls already planned + this call)."""
        return spent0 + LAST_RUN["costUSD"] + extra + worst_case_usd(prompt_chars) > monthly

    def prepare(it):
        """The free screens that run BEFORE any paid call, then the prompt. None = the item is not sent (screened out, or its record is unavailable; it stays queued)."""
        context = fetch_context(it)
        meta = RECORD_META.pop(it["id"], None) or registry_record.parse_header(context) or {"completeness": "UNKNOWN"}
        # free screens on the fetched record BEFORE any paid call: a topic hold that only the abstract reveals, or a notice that the title does not reveal
        hold_id = topic_holds.match_item(it, holds, extra_text=context)
        if hold_id:
            it["topicHold"] = hold_id
            LAST_RUN["screened"] += 1
            print(f"  topic hold '{hold_id}' matched the record — not sent to the AI, stays queued.", flush=True)
            QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
            return None
        info = notices.analyse(it, context, cited)
        if info:
            it["notice"] = info
            LAST_RUN["screened"] += 1
            print(f"  notice ({info['kind']}, {info['resolution']}) — not sent to the AI.", flush=True)
            QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
            return None
        if meta.get("completeness") == "UNAVAILABLE" and it["id"].startswith(("pubmed-", "ctgov-")):
            # a PubMed/registry item whose record could not be fetched must not be evaluated from its headline: no paid call, it stays queued for the next run
            LAST_RUN["recordUnavailable"] = LAST_RUN.get("recordUnavailable", 0) + 1
            print("  primary record could not be fetched - no paid call; the item stays queued for the next run.", flush=True)
            return None
        if it["id"].startswith("pubmed-"):
            # R4 (free, deterministic): an abstract that is not clearly English is held for a person BEFORE any paid call - the code cannot check the model's reading of it
            scr = language_screen.screen(context)
            if scr["hold"]:
                it["languageHold"] = {"state": scr["state"], "articleLanguage": scr["articleLanguage"], "reason": scr["reason"]}
                LAST_RUN["screened"] += 1
                print(f"  language screen ({scr['state']}) - not sent to the AI, held for a person.", flush=True)
                QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
                return None
        if meta.get("itemDate"):
            it["date"] = meta["itemDate"]     # an FDA item's date is the decision date in the FDA record, never the day the scan found it
        if meta.get("pubtypes") and not it.get("pubtypes"):
            it["pubtypes"] = meta["pubtypes"]
        item_meta = {k: it.get(k) for k in ("id", "kind", "title", "source", "date", "url", "summary")}
        item_meta["intelligenceOnly"] = bool(it.get("intelligenceOnly"))
        item_meta["recordAvailable"] = meta.get("completeness") in ("COMPLETE", "SHORTENED", "TRUNCATED")
        prefix, suffix = build_prompt_parts(t_index, s_index, item_meta, context)
        return context, meta, item_meta, prefix, suffix

    if flags["useBatch"]:
        # Phase 2 of the batch route: submit one batch of the prepared items; they are collected by a LATER run (batch_collect). Nothing is evaluated now.
        reqs, entries = [], {}
        for it in todo:
            print(f"Preparing {it['id']} for the batch — {it['title'][:70]}…", flush=True)
            prep = prepare(it)
            if prep is None:
                continue
            context, meta, item_meta, prefix, suffix = prep
            planned = sum(worst_case_usd(r["_chars"]) for r in reqs)
            if over_budget(len(prefix) + len(suffix), planned):
                LAST_RUN["fatal"] = "budget"
                LAST_RUN["reason"] = f"monthly evaluation budget would be exceeded (${monthly:.2f}); {len(todo) - len(reqs)} item(s) stay queued"
                print("  " + LAST_RUN["reason"], file=sys.stderr)
                break
            cid = "it-" + hashlib.sha256(it["id"].encode("utf-8")).hexdigest()[:16]   # custom_id must match [A-Za-z0-9_-]{1,64}
            reqs.append({"custom_id": cid, "_chars": len(prefix) + len(suffix),
                         "params": {"model": MODEL, "max_tokens": MAX_OUTPUT_TOKENS, "thinking": {"type": "adaptive"},
                                    "messages": [{"role": "user", "content": request_content(prefix, suffix, caching)}]}})
            entries[cid] = {"id": it["id"], "recordHash": hashlib.sha256(context.encode("utf-8")).hexdigest()[:16], "itemMeta": item_meta, "meta": meta}
        if not reqs:
            reason = (f"{LAST_RUN['recordUnavailable']} primary record(s) could not be fetched; those items were not sent to the AI and remain queued"
                      if LAST_RUN.get("recordUnavailable") else None)
            LAST_RUN["reason"] = reason
            return done, reason
        try:
            batch = client.messages.batches.create(requests=[{k: v for k, v in r.items() if not k.startswith("_")} for r in reqs])
        except anthropic.APIStatusError as e:
            cls = classify_error(e)
            LAST_RUN["failed"] += 1
            LAST_RUN["errorClasses"][cls] = LAST_RUN["errorClasses"].get(cls, 0) + 1
            if cls in FATAL_CLASSES:
                LAST_RUN["fatal"] = cls
            msg = f"batch submission failed ({cls}); all {len(reqs)} item(s) remain queued"
            LAST_RUN["reason"] = msg
            return done, msg
        except Exception as e:
            LAST_RUN["failed"] += 1
            LAST_RUN["errorClasses"]["exception"] = LAST_RUN["errorClasses"].get("exception", 0) + 1
            msg = f"batch submission failed ({type(e).__name__}); all {len(reqs)} item(s) remain queued"
            LAST_RUN["reason"] = msg
            return done, msg
        state_path = ROOT / BATCH_STATE
        state_path.write_text(json.dumps({"version": 1, "batchId": batch.id, "model": MODEL, "promptHash": prompt_hash(), "promptCaching": caching,
                                          "submittedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "items": entries}, indent=1, ensure_ascii=False), encoding="utf-8")
        LAST_RUN["submitted"] = len(reqs)
        LAST_RUN["batch"] = {"state": "submitted", "id": batch.id, "requests": len(reqs)}
        print(f"Batch {batch.id} submitted with {len(reqs)} item(s); results are collected by a later run.")
        return done, None

    for it in todo:
        print(f"Evaluating {it['id']} — {it['title'][:70]}…", flush=True)
        prep = prepare(it)
        if prep is None:
            continue
        context, meta, item_meta, prefix, suffix = prep
        if over_budget(len(prefix) + len(suffix)):
            LAST_RUN["fatal"] = "budget"
            LAST_RUN["reason"] = f"monthly evaluation budget would be exceeded (${monthly:.2f}); stopped after {done} item(s), the rest stay queued"
            print("  " + LAST_RUN["reason"], file=sys.stderr)
            break
        LAST_RUN["attempted"] += 1
        it["evalAttempts"] = (it.get("evalAttempts") or 0) + 1
        QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")   # the attempt is on record even if this process dies mid-call
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": request_content(prefix, suffix, caching)}],
            )
        except anthropic.RateLimitError:
            it["evalAttempts"] -= 1          # a rate limit is not the item's fault
            QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
            LAST_RUN["failed"] += 1
            LAST_RUN["errorClasses"]["rate_limit"] = LAST_RUN["errorClasses"].get("rate_limit", 0) + 1
            print("  rate-limited; stopping — re-run later."); break
        except anthropic.APIStatusError as e:
            cls = classify_error(e)
            LAST_RUN["failed"] += 1
            LAST_RUN["errorClasses"][cls] = LAST_RUN["errorClasses"].get(cls, 0) + 1
            print(f"  API error {e.status_code} ({cls}){': ' + str(e.message)[:200] if cls == 'other' else ''}; skipping.")   # message shown only for unclassified errors
            if cls == "rate_limit":          # a 429 that did not arrive as RateLimitError: same handling, stop the run
                it["evalAttempts"] -= 1
                QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
                print("  rate-limited; stopping — re-run later."); break
            if cls in FATAL_CLASSES:
                it["evalAttempts"] -= 1      # a key, billing or permission problem is not the item's fault
                QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
                LAST_RUN["fatal"] = cls
                print(f"  {cls} errors cannot succeed on retry — stopping; remaining items stay queued.", file=sys.stderr)
                break
            QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
            continue
        except Exception as e:
            # never let an SDK/client error kill the whole cycle — items simply stay queued
            LAST_RUN["failed"] += 1
            LAST_RUN["errorClasses"]["exception"] = LAST_RUN["errorClasses"].get("exception", 0) + 1
            print(f"  evaluation error ({e}); stopping.", file=sys.stderr)
            LAST_RUN["reason"] = f"evaluation error: {e}"
            return done, f"evaluation error: {e}"

        _account(getattr(response, "usage", None))
        text = next((b.text for b in response.content if b.type == "text"), "")
        _finish_item(it, text, context, meta, item_meta, treatments, known_words, {"promptCaching": True} if caching else None,
                     stop_reason=getattr(response, "stop_reason", None), output_tokens=getattr(getattr(response, "usage", None), "output_tokens", None))
        done += 1
        LAST_RUN["succeeded"] += 1
        QUEUE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")  # save after each item

    print(f"Done ({done} evaluated, {LAST_RUN['failed']} failed of {LAST_RUN['attempted']} attempted).")
    reason = None
    if LAST_RUN["fatal"] == "budget":
        reason = LAST_RUN["reason"]
    elif LAST_RUN["fatal"]:
        reason = f"evaluation stopped by a {LAST_RUN['fatal']} error after {LAST_RUN['attempted']} attempt(s); {len(todo) - done} item(s) remain queued"
    elif LAST_RUN["failed"]:
        reason = f"{LAST_RUN['failed']} of {LAST_RUN['attempted']} evaluation attempts failed ({LAST_RUN['errorClasses']}); those items remain queued"
    elif LAST_RUN.get("recordUnavailable"):
        reason = f"{LAST_RUN['recordUnavailable']} primary record(s) could not be fetched (PubMed / ClinicalTrials.gov); those items were not sent to the AI and remain queued"
    LAST_RUN["reason"] = reason
    return done, reason


if __name__ == "__main__":
    main()

"""OFFLINE scenario runner for the weekly cycle (dev/test tool; never run by the workflow).

Copies the repository's data/ and engine/ into a temp sandbox, replaces the Anthropic SDK and every network fetch with stubs, runs the REAL
weekly cycle one or more times, and writes what happened to a JSON file. No network, no API key, nothing in the repository is touched.

Usage: python run_scenario.py <repo_dir> <spec.json> <out.json>
spec keys (all optional): settings, paused, topicHolds, queue (list of items replacing the queue), records {id: text}, evaluations {id: partial ev},
  extraStudies [study dicts added to data/studies.json], benchmark ('ok' | 'stale' | 'none'), staged (staged-store object written before run 1),
  runs [ {decisions, staged, settings, stagedEncOnly} ... ] one entry per cycle run.
"""
import contextlib, hashlib, io, json, os, re, shutil, subprocess, sys, tempfile, types
from datetime import date
from pathlib import Path

REPO, SPEC, OUT = Path(sys.argv[1]), json.load(open(sys.argv[2], encoding="utf-8")), sys.argv[3]
tmp = Path(tempfile.mkdtemp(prefix="te-p2-"))
shutil.copytree(REPO / "data", tmp / "data")
shutil.copytree(REPO / "engine", tmp / "engine", ignore=shutil.ignore_patterns("tests", "__pycache__"))
(tmp / "data" / "trials.json").write_text("[]", encoding="utf-8")                      # no registry status refresh (network)
(tmp / "engine" / "retraction-state.json").write_text(json.dumps({"lastRun": date.today().isoformat()}), encoding="utf-8")


def W(rel, obj):
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def J(rel, default=None):
    try:
        return json.loads((tmp / rel).read_text(encoding="utf-8"))
    except Exception:
        return default


_today_rep = tmp / "data" / "weekly" / f"{date.today().isoformat()}.json"       # the repo may already hold today's real report; tests need a clean weekly run
_today_rep.unlink(missing_ok=True)
_idx = json.loads((tmp / "data/weekly/index.json").read_text(encoding="utf-8"))
_idx["reports"] = [r for r in _idx["reports"] if r["file"] != _today_rep.name]
(tmp / "data/weekly/index.json").write_text(json.dumps(_idx), encoding="utf-8")
W("engine/eval_settings.json", SPEC.get("settings",{"enabled": True, "mode": "staged", "limitPerRun": 60}))
if "paused" in SPEC:
    W("engine/paused_ids.json", {"ids": SPEC["paused"]})
else:
    W("engine/paused_ids.json", {"ids": []})
if "topicHolds" in SPEC:
    W("engine/topic_holds.json", {"holds": SPEC["topicHolds"]})
if "queue" in SPEC:
    q = J("data/review-queue/queue.json")
    q["items"] = SPEC["queue"]
    W("data/review-queue/queue.json", q)
    W("engine/known_ids.json", sorted(set(J("engine/known_ids.json", [])) | {i["id"] for i in SPEC["queue"]}))
if SPEC.get("extraStudies"):
    s = J("data/studies.json")
    lst = s["studies"] if isinstance(s, dict) else s
    lst.extend(SPEC["extraStudies"])
    W("data/studies.json", s)
if SPEC.get("staged") is not None:
    W("data/review-queue/staged.json", SPEC["staged"])

sys.path.insert(0, str(tmp / "engine"))
CALLS, PROMPTS = {}, {}


class APIStatusError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message); self.status_code = status_code; self.message = message


class RateLimitError(APIStatusError):
    pass


def default_ev(item_id):
    return {"whatIsNew": "Routine finding reported in the record.", "relevanceCategory": 1, "notRelevant": False, "affectedTreatment": "cbt",
            "studyType": "cohort", "studyQuality": "moderate", "population": "Not reported", "sampleSize": "Not reported", "controlQuality": "active-control",
            "randomized": True, "blinded": "unclear", "primaryEndpoint": "Not reported", "secondaryEndpoints": "Not reported",
            "comparisonType": "between-group", "numericalResult": "none reported", "loudnessEffect": "none - not measured", "distressEffect": "none",
            "otherOutcomes": "Not reported", "clinicalSignificance": "Not reported", "safetyObservations": "Not reported", "safetySignal": False,
            "mainLimitations": ["Not reported"], "conflictOfInterest": "unclear", "regulatorySource": "authoritative (FDA/EMA/registry record)",
            "evidenceDirection": "no-meaningful-change", "changeClass": "routine", "proposedScoreChange": None, "proposedRankChange": None,
            "importance": "Does Not Change Current Evidence", "weeklyTitle": "Routine update", "whyMatters": "SECRETMARK " + item_id,
            "factuallyVerified": True, "factuallyVerifiedReason": "stated in the record", "summaryForAdmin": "SECRETMARK admin " + item_id,
            "confidence": "high", "duplicateOf": None}


class _Msgs:
    def create(self, **kw):
        prompt = kw["messages"][0]["content"]
        if kw.get("max_tokens") == 1:
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")])
        m = re.search(r"NEW ITEM METADATA:\n(\{.*?\})\n\nPRIMARY RECORD:\n(.*?)\n\nRespond with ONLY", prompt, re.S)
        meta = json.loads(m.group(1))
        iid = meta["id"]
        CALLS[iid] = CALLS.get(iid, 0) + 1
        PROMPTS[iid] = {"meta": meta, "recordHead": m.group(2)[:400], "comparisonTypeLine": next((l for l in prompt.splitlines() if '"comparisonType"' in l), "")}
        raw = SPEC.get("rawAnswers", {}).get(iid)     # {text, stopReason, outputTokens}: a model answer served as-is (for example cut off at the output limit)
        if raw:
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=raw["text"])] if raw["text"] else [],
                                         usage=types.SimpleNamespace(input_tokens=SPEC.get("tokensIn", 1), output_tokens=raw.get("outputTokens", 1)),
                                         stop_reason=raw.get("stopReason", "end_turn"))
        ev = default_ev(iid)
        ev.update(SPEC.get("evaluations", {}).get(iid, {}))
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(ev))],
                                     usage=types.SimpleNamespace(input_tokens=SPEC.get("tokensIn", 1), output_tokens=SPEC.get("tokensOut", 1)), stop_reason="end_turn")


class _Client:
    def __init__(self, *a, **k):
        self.messages = _Msgs()


fake = types.ModuleType("anthropic")
fake.Anthropic, fake.APIStatusError, fake.RateLimitError = _Client, APIStatusError, RateLimitError
sys.modules["anthropic"] = fake
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-SIMULATED-not-a-real-key"

import weekly_scan, evaluate_queue, weekly_cycle, check_retractions, registry_record, triage  # noqa: E402
triage.fetch_xml = lambda ids: None      # the free PubMed lookup of triage facts is never made in tests (records keep the facts the scenario gives them)
for name in ("scan_pubmed", "scan_ctgov", "scan_feeds", "scan_fda", "scan_news_intel", "scan_pages"):
    setattr(weekly_scan, name, lambda: [])
check_retractions.due = lambda *a, **k: False


def sim_record(item):
    iid = item["id"]
    if iid.startswith("pubmed-"):
        # a realistic, data-bearing abstract (design, sample size, result figures): a data-free simulated record would correctly fail the evidence-adequacy check
        return registry_record.finish_pubmed_record(f"Title: {item.get('title', '')}\nPMID: {iid.split('-', 1)[1]}\nAbstract: Methods: randomized controlled trial; 83 participants were randomized. "
                                                    f"Results: the mean score fell by 6.5 points (95% CI 2.1 to 10.9; p=0.004).\nRecord id {iid}", iid.split("-", 1)[1])[0]
    if iid.startswith("ctgov-"):
        return ("SOURCE: simulated\nRECORD COMPLETENESS: COMPLETE - nothing was left out\nCRITICAL SECTIONS MISSING: no\n"
                f"REGISTRY FIELD hasResults: FALSE (no results posted)\n---\nNCT ID: {iid.split('-')[1]}\nRecord id {iid} {item.get('date', '')}")
    return registry_record.unavailable_record("headline and metadata only (simulated)")[0]


def fake_fetch(item):
    text = SPEC.get("records", {}).get(item["id"]) or sim_record(item)
    evaluate_queue.RECORD_META.pop(item["id"], None)
    if SPEC.get("recordMeta", {}).get(item["id"]):     # a record builder's metadata (for example the FDA decision date), as the real fetch_context would leave it
        evaluate_queue.RECORD_META[item["id"]] = dict(SPEC["recordMeta"][item["id"]])
    return text


evaluate_queue.fetch_context = fake_fetch

RATING_FIELDS = ("tier", "evidenceScore", "confidence", "replication", "independence", "safetyLevel", "category", "subtypeTags", "regulatory", "replicationNote", "scoreRationale")


def ratings_snapshot():
    t = {x["id"]: {f: x.get(f) for f in RATING_FIELDS} | {"loudness": x["loudness"]["level"], "distress": x["distress"]["level"]} for x in J("data/treatments.json")}
    return json.dumps({"treatments": t, "rankings": J("data/rankings.json")}, sort_keys=True)


def bench(kind):
    if kind == "none":
        (tmp / "engine" / "benchmark-report.json").unlink(missing_ok=True)
    else:
        W("engine/benchmark-report.json", {"passed": 8, "cases": 8, "promptHash": evaluate_queue.prompt_hash() if kind == "ok" else "stale-prompt-hash"})


bench(SPEC.get("benchmark", "ok"))
RATINGS0 = ratings_snapshot()
STUDIES0 = json.dumps(J("data/studies.json"), sort_keys=True)
initial = [i["id"] for i in J("data/review-queue/queue.json")["items"]]
PUBLIC = ["data/review-queue/queue.json", "data/review-queue/archive.json", "data/engine-status.json", "engine/audit-log.jsonl", "engine/known_ids.json",
          "engine/published_ids.json", "data/review-queue/decisions.json", f"data/weekly/{date.today().isoformat()}.json", "data/weekly/index.json"]


def run_once(i, run):
    if "paused" in run:
        W("engine/paused_ids.json", {"ids": run["paused"]})
    if run.get("decisions"):   # "@HASH:<id>" = the hash of the staged evaluation as it is now; "@STALE" = a hash that cannot match
        cur = {e["id"]: e["evalHash"] for e in J("data/review-queue/staged.json", {"items": []})["items"]}
        for d in run["decisions"]["decisions"]:
            h = d.get("evalHash", "")
            if h.startswith("@HASH:"):
                d["evalHash"] = cur.get(h[6:], "no-such-staged-item")
            elif h == "@STALE":
                d["evalHash"] = "0000000000000000"
            th = d.get("textHash", "")
            if isinstance(th, str) and th.startswith("@TEXTHASH:"):    # the hash of the public text of a staged item, as the export would show it
                import source_release
                ent = next((e for e in J("data/review-queue/staged.json", {"items": []})["items"] if e["id"] == th[10:]), None)
                d["textHash"] = source_release.text_hash(ent["item"]) if ent else "no-such-staged-item"
    for k, rel in (("decisions", "data/review-queue/decisions.json"), ("staged", "data/review-queue/staged.json"), ("settings", "engine/eval_settings.json")):
        if run.get(k) is not None:
            W(rel, run[k])
    if run.get("stagedEncOnly"):
        (tmp / "data/review-queue/staged.json").unlink(missing_ok=True)
        W("data/review-queue/staged.json.enc", "not really encrypted")
    audit0 = sum(1 for _ in open(tmp / "engine" / "audit-log.jsonl", encoding="utf-8"))
    before_calls = dict(CALLS)
    out, rc = io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            weekly_cycle.main()
    except SystemExit as e:
        rc = e.code or 0
    st = J("data/engine-status.json", {})
    rep = J(f"data/weekly/{date.today().isoformat()}.json", {"items": []})
    log = [json.loads(l) for l in open(tmp / "engine" / "audit-log.jsonl", encoding="utf-8") if l.strip()][audit0:]
    leaks = []
    for rel in PUBLIC:
        p = tmp / rel
        if p.exists() and "SECRETMARK" in p.read_text(encoding="utf-8"):
            leaks.append(rel)
    staged = J("data/review-queue/staged.json", {"items": []})
    held = J("data/review-queue/held.json", {"items": []})
    return {
        "run": i, "exitCode": rc, "status": st, "log": log, "output": out.getvalue()[-500:], "leaks": leaks,
        "apiCalls": {k: v - before_calls.get(k, 0) for k, v in CALLS.items() if v - before_calls.get(k, 0)},
        "totalApiCalls": sum(CALLS.values()) - sum(before_calls.values()),
        "queue": [x["id"] for x in J("data/review-queue/queue.json")["items"]],
        "reportItems": [{"title": x.get("title"), "identifier": (x.get("detail") or {}).get("identifier"), "why": x.get("whyMatters"), "importance": x.get("importance"), "detail": x.get("detail"), "reviewNote": x.get("reviewNote")} for x in rep["items"]],
        "held": [h["item"]["id"] for h in held["items"]], "heldReasons": {h["item"]["id"]: h["reason"] for h in held["items"]},
        "archived": [a["item"]["id"] for a in J("data/review-queue/archive.json", {"items": []})["items"]],
        "staged": {e["id"]: {"route": e["proposedRoute"], "hash": e["evalHash"], "reason": e["reason"], "preview": e.get("weeklyPreview"), "itemDate": (e.get("item") or {}).get("date")} for e in staged["items"]},
        "decisionsFile": J("data/review-queue/decisions.json"),
        "ratingsUnchanged": ratings_snapshot() == RATINGS0, "studiesUnchanged": json.dumps(J("data/studies.json"), sort_keys=True) == STUDIES0,
        "knownIds": sorted(J("engine/known_ids.json", [])),
        "stagedPlainExists": (tmp / "data/review-queue/staged.json").exists(),
        "ledger": J("engine/usage-ledger.json", {"runs": []}),
        "triageEvidence": J("engine/triage-evidence.json"),
    }


R = {"initial": initial, "runs": [], "prompts": None}
for i, run in enumerate(SPEC.get("runs", [{}])):
    R["runs"].append(run_once(i, run))
R["prompts"] = PROMPTS
R["promptHash"] = evaluate_queue.prompt_hash()
json.dump(R, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
shutil.rmtree(tmp, ignore_errors=True)

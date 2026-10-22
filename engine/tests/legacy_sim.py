"""OFFLINE simulation of the weekly cycle against a COPY of the real data (whatever is pending in data/review-queue/queue.json), with a stub in place of the Anthropic API.
Dev/test tool (added with the evaluation-failure fix); never run by the workflow.
Nothing in the repository is touched (everything runs in a temp copy); no network access; no real API key involved.
Usage: python engine/sim_eval_failure.py <repo_dir> <mode> <out.json> [second_mode]
  mode: ok | auth | billing | flaky | crash | allpublish | preview     second_mode (optional): run a second cycle with that mode (e.g. ok)
  allpublish: every evaluation is a routine, verified, relevant item (so duplicates would show up);  preview: runs engine/evaluate_preview.py on 5 items
  env SIM_PAUSE=id1,id2 writes those ids into engine/paused_ids.json before the run
"""
import sys, os, json, shutil, tempfile, types, hashlib, io, contextlib, re, subprocess
from pathlib import Path
REPO, MODE, OUT = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
MODE2 = sys.argv[4] if len(sys.argv) > 4 else None
tmp = Path(tempfile.mkdtemp(prefix="te-backlog-sim-"))
shutil.copytree(REPO / "data", tmp / "data")
shutil.copytree(REPO / "engine", tmp / "engine", ignore=shutil.ignore_patterns("tests", "__pycache__"))
(tmp / "data" / "trials.json").write_text("[]", encoding="utf-8")          # no registry refresh (network)
from datetime import date
(tmp / "engine" / "retraction-state.json").write_text(json.dumps({"lastRun": date.today().isoformat()}), encoding="utf-8")  # not due
sys.path.insert(0, str(tmp / "engine"))
CALLS = {}      # item id -> number of evaluation calls
SUCC = {}       # item id -> number of SUCCESSFUL evaluations (must never exceed 1)
STATE = {"mode": MODE, "n": 0}

# ---- stub anthropic SDK ----
class APIStatusError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message); self.status_code = status_code; self.message = message
class RateLimitError(APIStatusError):
    pass
def _eval_for(item_id):
    h = int(hashlib.sha256(item_id.encode()).hexdigest(), 16)
    cat = [1, 1, 2, 2, 2, 3, 3, 4, 5, 5, 5, 6, 6, 6][h % 14]
    if STATE["mode"] == "allpublish":
        h, cat = 1, 1   # routine + verified + relevant, never major/duplicate
    ev = {"whatIsNew": "sim", "relevanceCategory": cat, "notRelevant": False, "affectedTreatment": "cbt" if cat <= 2 else "none", "studyType": "cohort", "studyQuality": "moderate",
          "population": "sim", "sampleSize": "Not reported", "controlQuality": "n/a", "randomized": True, "blinded": "unclear", "primaryEndpoint": "Not reported",
          "secondaryEndpoints": "Not reported", "comparisonType": "Not reported", "numericalResult": "none reported", "loudnessEffect": "none", "distressEffect": "none",
          "otherOutcomes": "Not reported", "clinicalSignificance": "Not reported", "safetyObservations": "Not reported", "safetySignal": False, "mainLimitations": [],
          "conflictOfInterest": "unclear", "regulatorySource": "n/a", "evidenceDirection": "no-meaningful-change", "changeClass": "routine", "proposedScoreChange": None,
          "proposedRankChange": None, "importance": "Does Not Change Current Evidence", "weeklyTitle": "SIM " + item_id, "whyMatters": "sim",
          "factuallyVerified": (h % 10) != 0, "factuallyVerifiedReason": "sim", "summaryForAdmin": "sim", "confidence": "high", "duplicateOf": None}
    if h % 20 == 0:
        ev.update({"changeClass": "major", "proposedScoreChange": {"treatment": "cbt", "from": 4, "to": 5, "reason": "sim"}})
    if h % 33 == 0:
        ev["duplicateOf"] = "fuller-2020-cochrane"
    return ev
class _Msgs:
    def create(self, **kw):
        prompt = kw["messages"][0]["content"]
        if kw.get("max_tokens") == 1:                                  # preflight ping (patched code)
            if STATE["mode"] in ("auth", "billing"):
                raise APIStatusError(401 if STATE["mode"] == "auth" else 400, "invalid x-api-key" if STATE["mode"] == "auth" else "Your credit balance is too low to access the Anthropic API.")
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")])
        m = re.search(r'NEW ITEM METADATA:\n(\{.*?\})\n\nPRIMARY RECORD', prompt, re.S)
        iid = json.loads(m.group(1))["id"]
        CALLS[iid] = CALLS.get(iid, 0) + 1
        STATE["n"] += 1
        if STATE["mode"] == "auth":
            raise APIStatusError(401, "invalid x-api-key")
        if STATE["mode"] == "billing":
            raise APIStatusError(400, "Your credit balance is too low to access the Anthropic API.")
        if STATE["mode"] == "flaky" and STATE["n"] % 5 == 0:
            raise APIStatusError(500, "internal server error")
        if STATE["mode"] == "crash" and STATE["n"] == 21:
            raise RuntimeError("simulated unexpected client crash")
        SUCC[iid] = SUCC.get(iid, 0) + 1
        txt = _eval_for(iid)
        body = json.dumps(txt) if (STATE["mode"] == "allpublish" or int(hashlib.sha256(iid.encode()).hexdigest(), 16) % 31) else "not json at all"
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=body)])
class _Client:
    def __init__(self, *a, **k): self.messages = _Msgs()
fake = types.ModuleType("anthropic"); fake.Anthropic = _Client; fake.APIStatusError = APIStatusError; fake.RateLimitError = RateLimitError
sys.modules["anthropic"] = fake
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-SIMULATED-not-a-real-key"

import weekly_scan, evaluate_queue, weekly_cycle, check_retractions
for name in ("scan_pubmed", "scan_ctgov", "scan_feeds", "scan_fda", "scan_news_intel", "scan_pages"):
    setattr(weekly_scan, name, lambda: [])
import registry_record
NL = chr(10)
def _sim_record(item):
    iid = item["id"]
    if iid.startswith("pubmed-"):
        return registry_record.finish_pubmed_record("PMID: " + iid.split("-", 1)[1] + NL + "Record id " + iid, iid.split("-", 1)[1])[0]
    if iid.startswith("ctgov-"):
        return NL.join(["SOURCE: simulated", "RECORD COMPLETENESS: COMPLETE - nothing was left out", "CRITICAL SECTIONS MISSING: no", "REGISTRY FIELD hasResults: FALSE (no results posted)", "---",
                        "NCT ID: " + iid.split("-")[1], "Record id " + iid + " " + str(item.get("date", ""))])
    return registry_record.unavailable_record("headline and metadata only (simulated)")[0]
evaluate_queue.fetch_context = _sim_record
(tmp / "engine" / "benchmark-report.json").write_text(json.dumps({"passed": 8, "cases": 8, "promptHash": evaluate_queue.prompt_hash()}), encoding="utf-8")   # the launch gate needs a benchmark pass on THIS prompt
check_retractions.due = lambda *a, **k: False
def J(rel, default=None):
    try: return json.loads((tmp / rel).read_text(encoding="utf-8"))
    except Exception: return default
# scenarios run with evaluation ENABLED unless SIM_SETTINGS=repo (use the repository's own eval_settings.json / paused_ids.json untouched)
if os.environ.get("SIM_SETTINGS") != "repo":
    (tmp / "engine" / "eval_settings.json").write_text(json.dumps({"enabled": True, "mode": os.environ.get("SIM_MODE_PUBLISH", "publish"), "limitPerRun": int(os.environ.get("SIM_LIMIT", "60"))}), encoding="utf-8")
    (tmp / "engine" / "paused_ids.json").write_text(json.dumps({"ids": []}), encoding="utf-8")
if os.environ.get("SIM_PAUSE"):
    (tmp / "engine" / "paused_ids.json").write_text(json.dumps({"ids": os.environ["SIM_PAUSE"].split(",")}), encoding="utf-8")
initial = [i["id"] for i in J("data/review-queue/queue.json")["items"]]
RATING_FIELDS = ("tier", "evidenceScore", "confidence", "replication", "independence", "safetyLevel", "category", "subtypeTags", "regulatory", "replicationNote", "scoreRationale")
def ratings_snapshot():
    t = {x["id"]: {f: x.get(f) for f in RATING_FIELDS} | {"loudness": x["loudness"]["level"], "distress": x["distress"]["level"]} for x in J("data/treatments.json")}
    return json.dumps({"treatments": t, "rankings": J("data/rankings.json")}, sort_keys=True)
RATINGS0 = ratings_snapshot()
STUDIES0 = json.dumps(J("data/studies.json"), sort_keys=True)
known0 = set(J("engine/known_ids.json", []))
audit0 = sum(1 for _ in open(tmp / "engine" / "audit-log.jsonl", encoding="utf-8"))
def run_once(label):
    out, rc = io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            weekly_cycle.main()
    except SystemExit as e:
        rc = e.code or 0
    st = J("data/engine-status.json", {})
    q = J("data/review-queue/queue.json")["items"]
    rep = J(f"data/weekly/{date.today().isoformat()}.json", {"items": []})
    pub = [i.get("detail", {}).get("identifier") for i in rep["items"] if i.get("detail", {}).get("identifier") in initial]
    pub_urls = [i.get("url") for i in rep["items"] if i.get("detail", {}).get("identifier") in initial]
    held = [h["item"]["id"] for h in J("data/review-queue/held.json", {"items": []})["items"] if h["item"]["id"] in initial]
    arch = [a["item"]["id"] for a in J("data/review-queue/archive.json", {"items": []})["items"] if a["item"]["id"] in initial]
    log = [json.loads(l) for l in open(tmp / "engine" / "audit-log.jsonl", encoding="utf-8") if l.strip()][audit0:]
    dropped = sorted({r["identifier"] for r in log if r.get("step") == "route" and r.get("route") in ("irrelevant", "dup") and r.get("identifier") in initial})
    hc = tmp / "engine" / "check_evaluation_health.py"; hexit = None; hout = None
    if hc.exists():
        pp = subprocess.run([sys.executable, str(hc)], capture_output=True, text=True, cwd=str(tmp)); hexit, hout = pp.returncode, (pp.stdout + pp.stderr)[-420:]
    return {"label": label, "mode": STATE["mode"], "exitCode": rc, "ratingsAndRankingsUnchanged": ratings_snapshot() == RATINGS0, "studiesUnchanged": json.dumps(J("data/studies.json"), sort_keys=True) == STUDIES0, "healthCheckExit": hexit, "healthCheckOut": hout, "statusErrors": st.get("errors"), "statusEvaluation": st.get("evaluation"), "lastSuccess": st.get("lastSuccess"),
            "queueRemaining": [i["id"] for i in q if i["id"] in initial], "published": pub, "publishedUrls": pub_urls, "held": held, "archived": arch, "droppedLogged": dropped,
            "reportTitle": rep.get("title"), "firstReportItem": (rep["items"][0]["title"] if rep["items"] else None), "apiCallsPerId": dict(CALLS), "successfulEvaluationsPerId": dict(SUCC),
            "cycleLogTail": out.getvalue()[-600:]}
R = {"initialItems": len(initial)}
if MODE == "preview":
    import runpy
    qpath = tmp / "data" / "review-queue" / "queue.json"
    before = {rel: (tmp / rel).read_bytes() for rel in ("data/review-queue/queue.json", "engine/known_ids.json", "engine/published_ids.json", "data/treatments.json", "data/rankings.json", "data/studies.json")}
    STATE["mode"] = "ok"
    outp = tmp / "preview.json"
    sys.argv = [str(tmp / "engine" / "evaluate_preview.py"), "--limit", "5", "--out", str(outp)]
    try:
        runpy.run_path(str(tmp / "engine" / "evaluate_preview.py"), run_name="__main__")
    except SystemExit:
        pass
    rep = json.loads(outp.read_text(encoding="utf-8"))
    R["preview"] = {"itemsInReport": len(rep["items"]), "wouldRouteCounts": rep["wouldRouteCounts"], "apiCalls": sum(CALLS.values()),
                    "repoFilesUnchanged": all((tmp / rel).read_bytes() == b for rel, b in before.items())}
    json.dump(R, open(OUT, "w", encoding="utf-8"), indent=1)
    print(json.dumps(R, indent=1)); shutil.rmtree(tmp, ignore_errors=True); sys.exit(0)
R["run1"] = run_once("run1")
if MODE2:
    STATE["mode"] = MODE2
    R["run2"] = run_once("run2")
def summarize(r):
    ids = set(initial)
    places = {"queueRemaining": set(r["queueRemaining"]), "published": set(r["published"]), "held": set(r["held"]), "archived": set(r["archived"]), "droppedLogged": set(r["droppedLogged"])}
    covered = set().union(*places.values())
    return {"counts": {k: len(v) for k, v in places.items()}, "uncovered(lost)": sorted(ids - covered), "inMultiplePlaces(excluding publish-under-eval overlap with held)": sorted(i for i in ids if sum(i in v for k, v in places.items() if k != "held") > 1),
            "maxApiCallsForOneItem": max(r["apiCallsPerId"].values()) if r["apiCallsPerId"] else 0, "ratingsAndRankingsUnchanged": r["ratingsAndRankingsUnchanged"], "studiesUnchanged": r["studiesUnchanged"], "maxSuccessfulEvaluationsForOneItem": max(r["successfulEvaluationsPerId"].values()) if r["successfulEvaluationsPerId"] else 0, "totalApiCalls": sum(r["apiCallsPerId"].values()), "knownIdsIncludeAll": ids <= set(J("engine/known_ids.json", [])),
            "duplicatePublishedUrls": sorted({u for u in r["publishedUrls"] if r["publishedUrls"].count(u) > 1})}
for k in ("run1", "run2"):
    if k in R: R[k]["summary"] = summarize(R[k])
json.dump(R, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps({k: (v if k not in ("run1", "run2") else {kk: vv for kk, vv in v.items() if kk in ("mode", "exitCode", "healthCheckExit", "statusErrors", "statusEvaluation", "reportTitle", "summary")}) for k, v in R.items()}, indent=1, ensure_ascii=False)[:3500])
shutil.rmtree(tmp, ignore_errors=True)

"""Offline tests for the weekly AI-evaluation failure handling. No network, no API key: engine/sim_eval_failure.py stubs the Anthropic SDK and runs the
REAL weekly cycle in a temp copy of data/ + engine/. Run:  python -m unittest discover -s engine/tests -v"""
import json, os, subprocess, sys, tempfile, unittest, importlib.util
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
REPO = ENGINE.parent
SIM = Path(__file__).resolve().parent / "legacy_sim.py"


sys.path.insert(0, str(ENGINE))
import evaluate_queue as _eq, notices as _notices, topic_holds as _th, weekly_cycle as _wc   # noqa: E402


def _queue():
    return json.loads((REPO / "data" / "review-queue" / "queue.json").read_text(encoding="utf-8"))["items"]


def _already_published():
    import re
    reg = _wc.Cycle(REPO).published_register()
    return {i["id"] for i in _queue() if any(k and k in reg for k in (re.sub(r"\W+", "", (i.get(x) or "").lower())[:90] for x in ("url", "title")))}


def _paused_ids():
    return set(json.loads((ENGINE / "paused_ids.json").read_text(encoding="utf-8"))["ids"])


def expected_without_api(include_paused=True):
    """Queue entries that never need a paid call: already published, owner-paused, topic-held, superseded registry updates, correction/retraction notices."""
    q = _queue()
    ids = _already_published() | _eq.superseded_ids(q) | {i["id"] for i in q if _th.match_item(i)} | {i["id"] for i in q if _notices.looks_like_notice(i)}
    return ids | (_paused_ids() if include_paused else set())


def simulate(mode, second=None):
    out = Path(tempfile.mkdtemp()) / "sim.json"
    cmd = [sys.executable, str(SIM), str(REPO), mode, str(out)] + ([second] if second else [])
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert p.returncode == 0, p.stdout[-800:] + p.stderr[-800:]
    return json.loads(out.read_text(encoding="utf-8"))


class ClassifyErrors(unittest.TestCase):
    def test_classes(self):
        spec = importlib.util.spec_from_file_location("evaluate_queue_t", ENGINE / "evaluate_queue.py")
        eq = importlib.util.module_from_spec(spec); spec.loader.exec_module(eq)
        self.assertEqual(eq.classify_error(_Err(401, "invalid x-api-key")), "auth")
        self.assertEqual(eq.classify_error(_Err(401, "API key is invalid.")), "auth")
        self.assertEqual(eq.classify_error(_Err(400, "Your credit balance is too low to access the Anthropic API.")), "billing")
        self.assertEqual(eq.classify_error(_Err(403, "forbidden")), "permission")
        self.assertEqual(eq.classify_error(_Err(429, "slow down")), "rate_limit")
        self.assertEqual(eq.classify_error(_Err(529, "overloaded")), "server")
        self.assertEqual(eq.classify_error(_Err(400, "bad request")), "other")


class _Err(Exception):
    def __init__(self, code, msg):
        super().__init__(msg); self.status_code = code; self.message = msg


def conserved(run):
    s = run["summary"]
    return s["ratingsAndRankingsUnchanged"] and s["studiesUnchanged"] and s["uncovered(lost)"] == [] and s["inMultiplePlaces(excluding publish-under-eval overlap with held)"] == [] and s["knownIdsIncludeAll"] and s["maxSuccessfulEvaluationsForOneItem"] <= 1


class FailureModes(unittest.TestCase):
    def test_auth_failure_is_loud_and_loses_nothing(self):
        r = simulate("auth", "ok")
        a, b = r["run1"], r["run2"]
        self.assertEqual(a["statusEvaluation"]["state"], "failed")
        self.assertTrue(a["statusErrors"])                       # not silent
        self.assertEqual(a["healthCheckExit"], 1)                # CI job would be red
        self.assertEqual(a["summary"]["totalApiCalls"], 0)       # fail fast: no doomed calls
        screened = {i["id"] for i in _queue() if _notices.looks_like_notice(i)}
        self.assertEqual(a["summary"]["counts"]["queueRemaining"], r["initialItems"] - len(_already_published() | screened))   # nothing lost, nothing published
        self.assertIn("not been evaluated", a["firstReportItem"])  # public notice is not "nothing found"
        self.assertTrue(conserved(a))
        self.assertEqual(b["statusEvaluation"]["state"], "ok")   # recovery once the key works
        self.assertTrue(conserved(b))
        self.assertEqual(b["summary"]["maxApiCallsForOneItem"], 1)

    def test_billing_failure_is_loud(self):
        a = simulate("billing")["run1"]
        self.assertEqual(a["statusEvaluation"]["state"], "failed")
        self.assertEqual(a["statusEvaluation"]["fatal"], "billing")
        self.assertEqual(a["healthCheckExit"], 1)
        self.assertEqual(a["summary"]["totalApiCalls"], 0)

    def test_partial_failures_are_reported_and_retried_once(self):
        r = simulate("flaky", "ok")
        a, b = r["run1"], r["run2"]
        self.assertEqual(a["statusEvaluation"]["state"], "degraded")
        self.assertGreater(a["statusEvaluation"]["failed"], 0)
        self.assertTrue(a["statusErrors"])
        self.assertTrue(conserved(a)); self.assertTrue(conserved(b))
        self.assertEqual(set(b["queueRemaining"]), {i["id"] for i in _queue() if _th.match_item(i)})

    def test_unexpected_client_crash_is_reported(self):
        r = simulate("crash", "ok")
        self.assertEqual(r["run1"]["statusEvaluation"]["state"], "degraded")
        self.assertTrue(r["run1"]["statusErrors"])
        self.assertTrue(conserved(r["run1"])); self.assertTrue(conserved(r["run2"]))

    def test_healthy_run_processes_each_item_once(self):
        r = simulate("ok", "ok")
        a, b = r["run1"], r["run2"]
        self.assertEqual(a["statusEvaluation"]["state"], "ok"); self.assertEqual(a["healthCheckExit"], 0)
        topic_held = {i["id"] for i in _queue() if _th.match_item(i)}
        self.assertEqual(set(b["queueRemaining"]), topic_held)              # only the topic-held (Lenire/Neuromod) items stay queued
        self.assertEqual(b["summary"]["maxApiCallsForOneItem"], 1)          # nothing evaluated twice
        self.assertEqual(b["summary"]["totalApiCalls"], r["initialItems"] - len(expected_without_api(include_paused=False)))   # (already-published duplicates are no longer paid for)   # every item that needs the AI, exactly once across the two runs
        self.assertTrue(conserved(a)); self.assertTrue(conserved(b))


class DeployedConfiguration(unittest.TestCase):
    """The repository's own settings (evaluation OFF, four paused items) with a stub that counts EVERY API call."""

    def run_repo_config(self):
        out = Path(tempfile.mkdtemp()) / "sim.json"
        p = subprocess.run([sys.executable, str(SIM), str(REPO), "ok", str(out), "ok"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                           env={**os.environ, "SIM_SETTINGS": "repo", "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(p.returncode, 0, p.stdout[-500:] + p.stderr[-500:])
        return json.loads(out.read_text(encoding="utf-8"))

    def test_nothing_is_evaluated_published_or_lost_while_disabled(self):
        cfg = json.loads((ENGINE / "eval_settings.json").read_text(encoding="utf-8"))
        self.assertIs(cfg["enabled"], False)
        self.assertEqual(cfg["limitPerRun"], 10)
        r = self.run_repo_config()
        for run in (r["run1"], r["run2"]):
            self.assertEqual(run["statusEvaluation"]["state"], "disabled")
            self.assertEqual(run["summary"]["totalApiCalls"], 0)                      # not even a preflight ping
            self.assertEqual(sorted(run["queueRemaining"]), sorted(set(run["queueRemaining"])))
            self.assertEqual(len(run["queueRemaining"]), r["initialItems"] - len(_already_published()))   # every queued item preserved (exact duplicates of published items were always dropped)
            for k in ("published", "held", "archived"):
                self.assertEqual(run[k], [], k)
            self.assertEqual(run["droppedLogged"], sorted(_already_published()))             # only exact duplicates of already-published items are dropped (as before)
            self.assertEqual(run["healthCheckExit"], 0)                               # a deliberate pause is not a red run
            self.assertTrue(conserved(run))
            self.assertIn("paused", (run["firstReportItem"] or "").lower())           # public notice never says 'quiet week'
            self.assertNotIn("nothing met the bar", json.dumps(run["firstReportItem"]).lower())

    def test_missing_or_malformed_settings_fail_closed(self):
        for content in (None, "{not json", json.dumps({"enabled": "true"}), json.dumps({"limitPerRun": 60})):
            sandbox = Path(tempfile.mkdtemp())
            import shutil
            shutil.copytree(REPO / "data", sandbox / "data"); shutil.copytree(ENGINE, sandbox / "engine")
            target = sandbox / "engine" / "eval_settings.json"
            if content is None:
                target.unlink()
            else:
                target.write_text(content, encoding="utf-8")
            out = Path(tempfile.mkdtemp()) / "sim.json"
            p = subprocess.run([sys.executable, str(SIM), str(sandbox), "ok", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                               env={**os.environ, "SIM_SETTINGS": "repo", "PYTHONIOENCODING": "utf-8"})
            self.assertEqual(p.returncode, 0, p.stdout[-400:] + p.stderr[-400:])
            run = json.loads(out.read_text(encoding="utf-8"))["run1"]
            self.assertEqual(run["statusEvaluation"]["state"], "disabled", content)
            self.assertEqual(run["summary"]["totalApiCalls"], 0, content)

    def test_paused_ids_exist_in_the_queue_and_survive(self):
        paused = json.loads((ENGINE / "paused_ids.json").read_text(encoding="utf-8"))["ids"]
        self.assertEqual(len(paused), 4)
        queue = {i["id"] for i in json.loads((REPO / "data" / "review-queue" / "queue.json").read_text(encoding="utf-8"))["items"]}
        self.assertTrue(set(paused) <= queue, sorted(set(paused) - queue))
        r = self.run_repo_config()
        self.assertTrue(set(paused) <= set(r["run2"]["queueRemaining"]))


class DedupePauseAndPreview(unittest.TestCase):
    def test_no_url_published_twice_in_one_run(self):
        r = simulate("allpublish", "allpublish")
        for run in (r["run1"], r["run2"]):
            self.assertEqual(run["summary"]["duplicatePublishedUrls"], [])
            self.assertTrue(conserved(run))
        self.assertGreater(len(r["run2"]["published"]), 20)   # the scenario really publishes

    def test_paused_items_are_never_evaluated_published_or_lost(self):
        q = json.loads((REPO / "data" / "review-queue" / "queue.json").read_text(encoding="utf-8"))["items"]
        paused = [q[0]["id"], q[5]["id"], q[40]["id"]]
        env = dict(os.environ, SIM_PAUSE=",".join(paused))
        out = Path(tempfile.mkdtemp()) / "sim.json"
        p = subprocess.run([sys.executable, str(SIM), str(REPO), "ok", str(out), "ok"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, env={**env, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(p.returncode, 0, p.stdout[-500:] + p.stderr[-500:])
        r = json.loads(out.read_text(encoding="utf-8"))
        b = r["run2"]
        self.assertEqual(sorted(b["queueRemaining"]), sorted(set(paused) | {i["id"] for i in _queue() if _th.match_item(i)}))   # exactly the paused and topic-held ones remain queued
        for pid in paused:
            self.assertNotIn(pid, b["apiCallsPerId"])                               # never sent to the API
            self.assertNotIn(pid, b["published"] + b["held"] + b["archived"] + b["droppedLogged"])
        self.assertEqual(b["statusEvaluation"]["paused"], len(set(paused) | {i["id"] for i in _queue() if _th.match_item(i)}))   # paused ids + topic-held items
        self.assertEqual(b["statusEvaluation"]["awaitingEvaluation"], 0)            # paused items are not counted as a backlog
        self.assertEqual(b["healthCheckExit"], 0)

    def test_per_run_limit_throttles_the_backlog(self):
        out = Path(tempfile.mkdtemp()) / "sim.json"
        p = subprocess.run([sys.executable, str(SIM), str(REPO), "ok", str(out), "ok"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                           env={**os.environ, "SIM_LIMIT": "15", "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(p.returncode, 0, p.stdout[-500:] + p.stderr[-500:])
        r = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(r["run1"]["statusEvaluation"]["attempted"], 15)
        self.assertEqual(r["run2"]["statusEvaluation"]["attempted"], 15)
        self.assertTrue(conserved(r["run2"]))

    def test_preview_changes_no_repo_file(self):
        v = simulate("preview")["preview"]
        self.assertGreaterEqual(v["itemsInReport"], 5)                    # 5 evaluated (+ any item the free screens kept away from the AI)
        self.assertEqual(v["apiCalls"], 5)
        self.assertTrue(v["repoFilesUnchanged"])


if __name__ == "__main__":
    unittest.main()

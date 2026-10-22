"""The 1st-and-15th schedule must be safe: a longer look-back cannot duplicate anything, the run a deployment triggers cannot spend money or publish AI output
while evaluation is off, the safety-net thresholds match the new cadence, and the pinned SDK exposes everything the engine uses. Offline."""
import importlib.util, inspect, json, os, shutil, subprocess, sys, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import weekly_cycle, weekly_scan  # noqa: E402


def sandbox():
    d = Path(tempfile.mkdtemp(prefix="te-lb-"))
    (d / "data" / "review-queue").mkdir(parents=True); (d / "engine").mkdir()
    (d / "data" / "review-queue" / "queue.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    (d / "engine" / "known_ids.json").write_text("[]", encoding="utf-8")
    return d


def item(i, title=None):
    return {"id": f"pubmed-{i}", "kind": "study", "title": title or f"Tinnitus study number {i}", "source": "PubMed", "date": "2026 Oct 1", "url": f"https://pubmed.ncbi.nlm.nih.gov/{i}/"}


class LookbackCannotDuplicate(unittest.TestCase):
    def scan(self, root, items):
        c = weekly_cycle.Cycle(root, days=20)
        q = c.scan(fixtures=[("PubMed", lambda: [dict(x) for x in items])])
        c.commit()
        return c, q

    def test_overlapping_windows_add_each_record_once(self):
        root = sandbox()
        _, q1 = self.scan(root, [item(1), item(2), item(3)])
        self.assertEqual([i["id"] for i in q1["items"]], ["pubmed-1", "pubmed-2", "pubmed-3"])
        c2, q2 = self.scan(root, [item(1), item(2), item(3), item(4)])               # the next run's window still contains 1-3
        self.assertEqual(sorted(i["id"] for i in q2["items"]), ["pubmed-1", "pubmed-2", "pubmed-3", "pubmed-4"])
        self.assertEqual(c2.status["newItems"], 1)
        c3, q3 = self.scan(root, [item(1), item(2), item(3), item(4)])
        self.assertEqual(c3.status["newItems"], 0); self.assertEqual(len(q3["items"]), 4)

    def test_a_record_that_already_left_the_queue_is_never_queued_again(self):
        root = sandbox()
        self.scan(root, [item(1), item(2)])
        qp = root / "data" / "review-queue" / "queue.json"
        qq = json.loads(qp.read_text(encoding="utf-8")); qq["items"] = [i for i in qq["items"] if i["id"] != "pubmed-1"]   # evaluated, then staged / held / archived / published
        qp.write_text(json.dumps(qq), encoding="utf-8")
        c, q = self.scan(root, [item(1), item(2)])
        self.assertEqual(c.status["newItems"], 0)
        self.assertEqual([i["id"] for i in q["items"]], ["pubmed-2"])
        self.assertIn("pubmed-1", json.loads((root / "engine" / "known_ids.json").read_text(encoding="utf-8")))

    def test_the_same_story_from_two_sources_collapses(self):
        root = sandbox()
        c, q = self.scan(root, [item(1, "Same Title"), {**item(2, "Same   title!"), "id": "feed-x"}])
        self.assertEqual(len(q["items"]), 1)

    def test_scanner_ids_do_not_depend_on_the_window(self):
        calls = []

        def fake_get_json(url):
            calls.append(url)
            if "esearch" in url:
                return {"esearchresult": {"count": "2", "idlist": ["111", "222"]}}
            if "esummary" in url:
                return {"result": {"111": {"title": "A", "pubtype": []}, "222": {"title": "B", "pubtype": []}}}
            return {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT00000001", "briefTitle": "T"}, "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-10-02"}},
                                                      "sponsorCollaboratorsModule": {"leadSponsor": {"name": "S"}}, "designModule": {"phases": ["PHASE2"], "enrollmentInfo": {"count": 10}}}}]}
        orig, orig_days, orig_sleep = weekly_scan.get_json, weekly_scan.DAYS, weekly_scan.time.sleep
        weekly_scan.get_json, weekly_scan.time.sleep = fake_get_json, lambda s: None
        try:
            ids = {}
            for days in (7, 20):
                weekly_scan.DAYS = days
                ids[days] = {"pm": sorted(i["id"] for i in weekly_scan.scan_pubmed())}
                try:
                    ids[days]["ct"] = sorted(i["id"] for i in weekly_scan.scan_ctgov())
                except Exception:
                    ids[days]["ct"] = "n/a"
            self.assertEqual(ids[7], ids[20])
            self.assertEqual(ids[20]["pm"], ["pubmed-111", "pubmed-222"])
            since = (date.today() - timedelta(days=20)).strftime("%Y/%m/%d")
            self.assertTrue(any(since in u.replace("%2F", "/") for u in calls), "the 20-day window was not used")
        finally:
            weekly_scan.get_json, weekly_scan.DAYS, weekly_scan.time.sleep = orig, orig_days, orig_sleep


class DeploymentTriggeredRun(unittest.TestCase):
    """Deploying changes weekly.yml, which also triggers a run (push path). With evaluation off it must be free and publish no AI output."""
    def test_workflow_triggers_and_the_secrets_it_can_reach(self):
        t = (REPO / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
        self.assertIn('paths: [".github/workflows/weekly.yml"]', t)                     # the one push trigger: changes to this file only
        self.assertEqual(t.count("ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}"), 1)   # the key reaches exactly one step: the cycle
        self.assertEqual(json.loads((ENGINE / "eval_settings.json").read_text(encoding="utf-8"))["enabled"], False)

    def test_two_runs_in_one_day_with_evaluation_off_cost_nothing_and_publish_nothing_from_the_ai(self):
        queue = [pubmed_item(90200001 + k) for k in range(4)]
        archived0 = [a["item"]["id"] for a in json.loads((REPO / "data" / "review-queue" / "archive.json").read_text(encoding="utf-8")).get("items", [])]
        for cfg in ({"enabled": False, "mode": "staged", "limitPerRun": 10}, {"enabled": False, "mode": "publish", "limitPerRun": 10},
                    {"enabled": "true", "mode": "publish", "limitPerRun": 10}, {"mode": "publish"}):
            r = run_scenario({"queue": queue, "settings": cfg, "runs": [{}, {}]})
            for run in r["runs"]:
                self.assertEqual(run["totalApiCalls"], 0, cfg)                          # not even the 1-token preflight
                self.assertEqual(run["status"]["evaluation"]["state"], "disabled", cfg)
                self.assertEqual(sorted(run["queue"]), sorted(i["id"] for i in queue), cfg)   # preserved untouched
                self.assertEqual((run["held"], run["staged"]), ([], {}), cfg)
                self.assertEqual(run["archived"], archived0, cfg)                       # nothing new archived (the archive already holds earlier context items)
                self.assertTrue(all(x["importance"] == "Not yet assessed" for x in run["reportItems"]), [x["title"] for x in run["reportItems"]])   # only the honest "paused" notice
                titles = [x["title"] for x in run["reportItems"]]
                self.assertEqual(len(titles), len(set(titles)), "duplicate entries in the same-day report")
                self.assertTrue(run["ratingsUnchanged"] and run["studiesUnchanged"] and run["leaks"] == [])

    def test_an_item_that_somehow_already_carries_an_evaluation_cannot_publish_in_staged_mode(self):
        ev = {"factuallyVerified": True, "confidence": "high", "relevanceCategory": 1, "studyType": "randomized controlled trial", "affectedTreatment": "cbt"}
        it = pubmed_item(90200099, evaluation=ev)
        r = run_scenario({"queue": [it], "settings": {"enabled": False, "mode": "staged"}, "runs": [{}]})["runs"][0]
        self.assertNotIn("pubmed-90200099", [x["identifier"] for x in r["reportItems"]])


class SafetyNetMatchesTheCadence(unittest.TestCase):
    def health(self, disabled_days_ago, awaiting=0):
        d = Path(tempfile.mkdtemp(prefix="te-hc-"))
        (d / "engine").mkdir(); (d / "data").mkdir()
        shutil.copy(ENGINE / "check_evaluation_health.py", d / "engine")
        since = (date.today() - timedelta(days=disabled_days_ago)).isoformat()
        (d / "data" / "engine-status.json").write_text(json.dumps({"evaluation": {"state": "disabled", "disabledSince": since, "awaitingEvaluation": awaiting}}), encoding="utf-8")
        p = subprocess.run([sys.executable, str(d / "engine" / "check_evaluation_health.py")], capture_output=True, text=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        shutil.rmtree(d, ignore_errors=True)
        return p.returncode

    def test_a_deliberate_pause_is_not_red_for_three_runs(self):
        for days in (0, 14, 17, 31, 45):                                                # up to three missed 1st/15th runs
            self.assertEqual(self.health(days), 0, days)
        self.assertEqual(self.health(50), 1)                                            # still the safety net against forgetting a pause
        self.assertGreaterEqual(json.loads((ENGINE / "eval_settings.json").read_text(encoding="utf-8")).get("disabledSince", "2026-10-21"), "2026-10-21")


class PinnedSdkHasWhatTheEngineUses(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("anthropic"), "anthropic not installed")
    def test_surface(self):
        import anthropic, re
        pin = re.search(r'anthropic==([0-9.]+)', (REPO / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")).group(1)
        self.assertEqual(anthropic.__version__, pin, "the SDK these tests run against must be the pinned one")
        for n in ("Anthropic", "APIStatusError", "RateLimitError"):
            self.assertTrue(hasattr(anthropic, n), n)
        c = anthropic.Anthropic(api_key="not-a-real-key")
        params = set(inspect.signature(c.messages.create).parameters)
        self.assertTrue({"model", "max_tokens", "messages", "thinking"} <= params, params)
        for n in ("create", "retrieve", "results"):
            self.assertTrue(callable(getattr(c.messages.batches, n)), n)
        e_params = set(inspect.signature(anthropic.APIStatusError.__init__).parameters)
        self.assertTrue({"message", "response", "body"} <= e_params, e_params)


if __name__ == "__main__":
    unittest.main()

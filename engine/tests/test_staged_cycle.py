"""Cycle-level tests: the REAL weekly cycle runs in a temp sandbox with the Anthropic SDK and all network fetches stubbed (see run_scenario.py).
Covers staged publication (D13), duplicate registry updates (D11), notices in the cycle (D1), topic holds in the cycle (D12) and prompt inputs (D9).
Run:  python -m unittest discover -s engine/tests -v"""
import json, os, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import evaluate_queue, registry_record, staged_review, topic_holds, notices  # noqa: E402

A, B, C3 = pubmed_item(90000001, "Trial A"), pubmed_item(90000002, "Trial B"), pubmed_item(90000003, "Trial C")
STAGED = {"enabled": True, "mode": "staged", "limitPerRun": 60}
PUBLISH = {"enabled": True, "mode": "publish", "limitPerRun": 60}


def ids_in_report(run):
    return sorted(x["identifier"] for x in run["reportItems"] if x["identifier"])


class StagedModeTests(unittest.TestCase):
    def test_evaluated_items_are_staged_privately_and_nothing_is_published(self):
        r = run_scenario({"queue": [A, B, C3], "settings": STAGED, "runs": [{}]})
        a = r["runs"][0]
        self.assertEqual(a["exitCode"], 0)
        self.assertEqual(ids_in_report(a), [])                                           # nothing from the evaluations is public
        self.assertEqual(sorted(a["staged"]), sorted([A["id"], B["id"], C3["id"]]))
        self.assertEqual({v["route"] for v in a["staged"].values()}, {"publish"})        # proposed outcome is recorded for the owner, not acted on
        self.assertEqual(a["leaks"], [])                                                 # no evaluation text in any public file
        self.assertEqual(a["queue"], [])                                                 # staged items leave the plaintext queue ...
        self.assertTrue(set(r["initial"]) <= set(a["knownIds"]))                         # ... but are never rescanned
        self.assertEqual(a["apiCalls"], {A["id"]: 1, B["id"]: 1, C3["id"]: 1})
        self.assertTrue(a["ratingsUnchanged"] and a["studiesUnchanged"])
        self.assertEqual(a["status"]["staged"]["new"], 3)
        self.assertEqual(a["status"]["evaluation"]["mode"], "staged")
        notice = next(x for x in a["reportItems"] if x["importance"] == "Not yet assessed")
        self.assertIn("awaiting editorial review", notice["title"])                      # the public report is honest, never "quiet week"
        self.assertNotIn("nothing met the bar", json.dumps(a["reportItems"]).lower())
        for e in a["log"]:
            if e.get("step") == "stage":
                self.assertNotIn("classification", e)                                    # even the public audit log reveals no AI classification

    def test_explicit_publish_mode_still_publishes_items_that_pass_every_check(self):
        a = run_scenario({"queue": [A, B], "settings": PUBLISH, "runs": [{}]})["runs"][0]
        self.assertEqual(ids_in_report(a), sorted([A["id"], B["id"]]))
        self.assertEqual(a["staged"], {})

    def test_mode_fails_closed(self):
        for cfg in ({"enabled": True}, {"enabled": True, "mode": "Publish"}, {"enabled": True, "mode": "auto"}, {"enabled": True, "mode": None}, {"enabled": True, "mode": True}):
            a = run_scenario({"queue": [A], "settings": cfg, "runs": [{}]})["runs"][0]
            self.assertEqual(ids_in_report(a), [], cfg)
            self.assertEqual(list(a["staged"]), [A["id"]], cfg)

    def test_failing_automated_checks_hold_even_in_publish_mode(self):
        ev = {A["id"]: {"numericalResult": "RR = 1.52 (95% CI 1.41 to 1.77)"}, B["id"]: {"whatIsNew": "The first trial of its kind."}}
        a = run_scenario({"queue": [A, B, C3], "settings": PUBLISH, "evaluations": ev, "runs": [{}]})["runs"][0]
        self.assertEqual(ids_in_report(a), [C3["id"]])
        self.assertEqual(sorted(a["held"]), sorted([A["id"], B["id"]]))
        self.assertIn("numbers", a["heldReasons"][A["id"]]); self.assertIn("novelty", a["heldReasons"][B["id"]])

    def test_undecryptable_staged_store_stops_the_cycle_instead_of_losing_items(self):
        r = run_scenario({"queue": [A], "settings": STAGED, "runs": [{"stagedEncOnly": True}]})
        a = r["runs"][0]
        self.assertEqual(a["exitCode"], 1)
        self.assertIn("refusing to run", a["output"] + json.dumps(a["status"]["errors"]))
        self.assertEqual(a["totalApiCalls"], 0)


class OwnerDecisionTests(unittest.TestCase):
    def two_runs(self, decisions, **extra):
        spec = {"queue": [A, B], "settings": STAGED, "runs": [{}, {"decisions": {"decisions": decisions}}, {}]}
        spec.update(extra)
        return run_scenario(spec)["runs"]

    def test_approve_and_reject(self):
        r0, r1, r2 = self.two_runs([{"id": A["id"], "decision": "approve", "evalHash": f"@HASH:{A['id']}"}, {"id": B["id"], "decision": "reject", "evalHash": f"@HASH:{B['id']}"}])
        self.assertEqual(ids_in_report(r1), [A["id"]])                                   # only the approved item became public
        self.assertEqual(r1["staged"], {})
        self.assertEqual(r1["decisionsFile"], {"decisions": []})                         # applied decisions are consumed
        self.assertEqual(r1["status"]["staged"]["decisions"]["applied"], 1); self.assertEqual(r1["status"]["staged"]["decisions"]["rejected"], 1)
        self.assertEqual(r2["totalApiCalls"], 0)                                         # the rejected item is never evaluated again ...
        self.assertNotIn(B["id"], r2["queue"]); self.assertIn(B["id"], r2["knownIds"])   # ... and never rescanned
        self.assertEqual(ids_in_report(r2), [A["id"]])                                   # nothing is published twice
        self.assertTrue(all(x["ratingsUnchanged"] and x["studiesUnchanged"] for x in (r1, r2)))

    def test_a_decision_for_a_different_evaluation_is_not_applied(self):
        r0, r1, r2 = self.two_runs([{"id": A["id"], "decision": "approve", "evalHash": "@STALE"}])
        self.assertEqual(ids_in_report(r1), [])
        self.assertIn(A["id"], r1["staged"])                                             # still waiting for a real decision
        self.assertEqual(r1["status"]["staged"]["decisions"]["stale"], 1)

    def test_approving_an_unknown_or_already_applied_item_publishes_nothing(self):
        r0, r1, r2 = self.two_runs([{"id": "pubmed-12121212", "decision": "approve", "evalHash": "abc"}])
        self.assertEqual(ids_in_report(r1), []); self.assertEqual(r1["status"]["staged"]["decisions"]["invalid"], 1)

    def test_corrections_are_applied_and_forbidden_fields_are_refused(self):
        ok = {"id": A["id"], "decision": "correct", "evalHash": f"@HASH:{A['id']}", "corrections": {"weeklyTitle": "Edited by the owner", "whyMatters": "Owner wording."}}
        r0, r1, r2 = self.two_runs([ok])
        item = next(x for x in r1["reportItems"] if x["identifier"] == A["id"])
        self.assertEqual((item["title"], item["why"]), ("Edited by the owner", "Owner wording."))
        corrected = [e for e in r1["log"] if e.get("step") == "owner-decision" and e.get("corrected")]
        self.assertEqual(corrected[0]["corrected"], ["weeklyTitle", "whyMatters"])
        for bad in ({"proposedScoreChange": {"treatment": "cbt", "from": 2, "to": 4}}, {"changeClass": "routine"}, {"safetySignal": False}, {"importance": "Made Up"}, {"weeklyTitle": ""}):
            r0, r1, r2 = self.two_runs([{"id": A["id"], "decision": "correct", "evalHash": f"@HASH:{A['id']}", "corrections": bad}])
            self.assertEqual(ids_in_report(r1), [], bad)
            self.assertIn(A["id"], r1["staged"], bad)                                    # nothing was applied and the item still waits
            self.assertEqual(r1["status"]["staged"]["decisions"]["invalid"], 1, bad)
            self.assertTrue(r1["ratingsUnchanged"])

    def test_route_override_can_only_downgrade(self):
        r0, r1, r2 = self.two_runs([{"id": A["id"], "decision": "approve", "routeOverride": "hold", "evalHash": f"@HASH:{A['id']}"}])
        self.assertEqual(ids_in_report(r1), []); self.assertIn(A["id"], r1["held"])
        low = {A["id"]: {"confidence": "low"}}                                            # the model's low confidence -> proposed outcome 'hold'
        r0, r1, r2 = self.two_runs([{"id": A["id"], "decision": "approve", "routeOverride": "publish", "evalHash": f"@HASH:{A['id']}"}], evaluations=low)
        self.assertEqual(r0["staged"][A["id"]]["route"], "hold")
        self.assertEqual(ids_in_report(r1), []); self.assertEqual(r1["status"]["staged"]["decisions"]["invalid"], 1)    # cannot upgrade a hold to publish

    def test_requeue_sends_the_item_back_for_a_fresh_evaluation(self):
        r0, r1, r2 = self.two_runs([{"id": A["id"], "decision": "requeue", "evalHash": f"@HASH:{A['id']}"}])
        self.assertEqual(ids_in_report(r1), [])
        self.assertEqual(r2["apiCalls"], {A["id"]: 1})                                    # evaluated again on the next run
        self.assertIn(A["id"], r2["staged"])

    def test_paused_item_cannot_be_approved_until_released(self):
        spec = {"queue": [A], "settings": STAGED, "runs": [{}, {"paused": [A["id"]], "decisions": {"decisions": [{"id": A["id"], "decision": "approve", "evalHash": f"@HASH:{A['id']}"}]}}, {"paused": []}]}
        r0, r1, r2 = run_scenario(spec)["runs"]
        self.assertEqual(ids_in_report(r1), []); self.assertEqual(r1["status"]["staged"]["decisions"]["blocked"], 1)
        self.assertEqual(len(r1["decisionsFile"]["decisions"]), 1)                        # the decision is kept, not lost
        self.assertEqual(ids_in_report(r2), [A["id"]])                                    # applied after the owner releases the pause

    def test_forged_duplicate_staged_entry_cannot_publish_twice(self):
        e1 = staged_review.make_entry(dict(A, evaluation={"x": 1}), "publish", "r", None, now="2026-10-21T00:00:00")
        twin = dict(A, id="pubmed-90000099", evaluation={"x": 2})                         # same url and title as A, different id
        e2 = staged_review.make_entry(twin, "publish", "r", None, now="2026-10-21T00:00:00")
        for e in (e1, e2):
            e["item"]["evaluation"] = {"relevanceCategory": 1, "affectedTreatment": "cbt", "weeklyTitle": "T", "whyMatters": "W", "importance": "Does Not Change Current Evidence", "studyType": "RCT"}
            e["evalHash"] = staged_review.eval_hash(e)
        decisions = {"decisions": [{"id": e["id"], "decision": "approve", "evalHash": e["evalHash"]} for e in (e1, e2)]}
        r = run_scenario({"queue": [], "settings": STAGED, "staged": {"items": [e1, e2]}, "runs": [{"decisions": decisions}]})["runs"][0]
        self.assertEqual(sum(1 for x in r["reportItems"] if x["identifier"] in (A["id"], twin["id"])), 1)                  # published once, not twice
        self.assertEqual(r["status"]["staged"]["decisions"]["alreadyPublished"], 1)


class DuplicateRegistryTests(unittest.TestCase):
    """D11: successive updates of one registry record (NCT06898515 and NCT07784192 are queued twice in production)."""
    Q = [ctgov_item("NCT06898515", "2026-10-13", "FASTR-II"), ctgov_item("NCT06898515", "2026-10-08", "FASTR-II"),
         ctgov_item("NCT07784192", "2026-10-08", "Other trial"), ctgov_item("NCT07784192", "2026-10-05", "Other trial"), ctgov_item("NCT09999999", "2026-10-01", "Single")]

    def test_only_the_newest_update_of_each_trial_is_evaluated_and_staged(self):
        a = run_scenario({"queue": self.Q, "settings": STAGED, "runs": [{}]})["runs"][0]
        self.assertEqual(a["apiCalls"], {"ctgov-NCT06898515-2026-10-13": 1, "ctgov-NCT07784192-2026-10-08": 1, "ctgov-NCT09999999-2026-10-01": 1})
        self.assertEqual(sorted(a["staged"]), ["ctgov-NCT06898515-2026-10-13", "ctgov-NCT07784192-2026-10-08", "ctgov-NCT09999999-2026-10-01"])
        dropped = {e["identifier"]: e["route"] for e in a["log"] if e.get("step") == "route" and e.get("route") == "dup"}
        self.assertEqual(sorted(dropped), ["ctgov-NCT06898515-2026-10-08", "ctgov-NCT07784192-2026-10-05"])
        self.assertEqual(a["queue"], [])

    def test_publish_mode_publishes_each_trial_once(self):
        a = run_scenario({"queue": self.Q, "settings": PUBLISH, "runs": [{}]})["runs"][0]
        self.assertEqual(ids_in_report(a), ["ctgov-NCT06898515-2026-10-13", "ctgov-NCT07784192-2026-10-08", "ctgov-NCT09999999-2026-10-01"])
        urls = [x["detail"]["identifier"] for x in a["reportItems"] if x["identifier"]]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(a["status"]["rejectedDuplicates"], 2)

    def test_older_update_is_never_chosen_even_if_it_appears_first_in_the_queue(self):
        q = [self.Q[1], self.Q[0]]
        a = run_scenario({"queue": q, "settings": STAGED, "runs": [{}]})["runs"][0]
        self.assertEqual(list(a["apiCalls"]), ["ctgov-NCT06898515-2026-10-13"])

    def test_helper_on_the_real_queue_finds_the_two_known_duplicates(self):
        sup = evaluate_queue.superseded_ids(real_queue())
        self.assertEqual(sup, {"ctgov-NCT06898515-2026-10-08", "ctgov-NCT07784192-2026-10-05"})


class NoticeCycleTests(unittest.TestCase):
    ERR = fixture("phase2_preview_run.json")["items"]
    ERR = next(i for i in ERR if "42821511" in i["id"])
    ITEM = pubmed_item(42821511, ERR["title"])
    REC = {"pubmed-42821511": registry_record.finish_pubmed_record(fixture("sources_raw.json")["pubmed-42821511"], "42821511")[0]}

    def test_uncited_notice_is_archived_never_evaluated_never_published(self):
        for cfg in (STAGED, PUBLISH):
            a = run_scenario({"queue": [self.ITEM, A], "settings": cfg, "records": self.REC, "runs": [{}]})["runs"][0]
            self.assertNotIn("pubmed-42821511", a["apiCalls"])
            self.assertIn("pubmed-42821511", a["archived"])
            self.assertNotIn("pubmed-42821511", ids_in_report(a))
            self.assertEqual(a["status"]["notices"], {"cited": 0, "uncited": 1, "unresolved": 0})
            if cfg is STAGED:
                self.assertEqual(a["leaks"], [])

    def test_notice_about_a_cited_study_is_held_privately_and_flagged(self):
        cited = [{"id": "fnirs-2020", "title": "Objective measurement of tinnitus using fNIRS", "doi": "10.1371/journal.pone.0241695", "year": 2020}]
        a = run_scenario({"queue": [self.ITEM], "settings": STAGED, "records": self.REC, "extraStudies": cited, "runs": [{}]})["runs"][0]
        self.assertEqual(a["apiCalls"], {})
        self.assertIn("pubmed-42821511", a["held"])                                       # preserved (held.json is encrypted by the workflow), not discarded
        self.assertIn("fnirs-2020", a["heldReasons"]["pubmed-42821511"])
        self.assertEqual(a["status"]["notices"]["cited"], 1)
        self.assertEqual(ids_in_report(a), []); self.assertNotIn("pubmed-42821511", a["archived"])
        self.assertTrue(a["studiesUnchanged"])                                            # study records are never edited by the weekly path
        self.assertTrue(a["ratingsUnchanged"])

    def test_unresolvable_notice_is_held_for_a_manual_check(self):
        a = run_scenario({"queue": [self.ITEM], "settings": STAGED, "runs": [{}]})["runs"][0]   # default simulated record has no 'Erratum for' line
        self.assertIn("pubmed-42821511", a["held"]); self.assertEqual(a["status"]["notices"]["unresolved"], 1)

    def test_notice_screening_works_while_evaluation_is_switched_off(self):
        a = run_scenario({"queue": [self.ITEM], "settings": {"enabled": False, "mode": "staged"}, "records": self.REC, "runs": [{}]})["runs"][0]
        self.assertEqual(a["status"]["evaluation"]["state"], "disabled")
        self.assertEqual(a["queue"], ["pubmed-42821511"])                                 # nothing is processed while OFF; nothing is published either
        self.assertEqual(ids_in_report(a), [])


class TopicHoldCycleTests(unittest.TestCase):
    def test_real_queue_lenire_items_are_never_sent_to_the_api(self):
        a = run_scenario({"settings": {"enabled": True, "mode": "staged", "limitPerRun": 100}, "paused": json.loads((ENGINE / "paused_ids.json").read_text(encoding="utf-8"))["ids"],
                          "runs": [{}]})["runs"][0]
        lenire = [i["id"] for i in real_queue() if i["id"].startswith("newsintel-neuromod-lenire-")]
        self.assertEqual(len(lenire), 3)
        for i in lenire + json.loads((ENGINE / "paused_ids.json").read_text(encoding="utf-8"))["ids"]:
            self.assertNotIn(i, a["apiCalls"]); self.assertIn(i, a["queue"]); self.assertNotIn(i, a["staged"])
        self.assertNotIn("pubmed-42821511", a["apiCalls"])                                # the erratum never reaches the AI
        self.assertEqual(a["status"]["evaluation"]["paused"], 6)                          # 3 paused guideline records + 3 Lenire/Neuromod items (the 4th paused id IS one of the 3)
        self.assertEqual(a["leaks"], [])
        self.assertTrue(a["ratingsUnchanged"] and a["studiesUnchanged"])

    def test_record_text_alone_can_trigger_the_hold_before_any_paid_call(self):
        it = pubmed_item(90000010, "Bimodal stimulation for chronic tinnitus: a randomised trial")
        rec = {it["id"]: registry_record.finish_pubmed_record("PMID: 90000010\nThe Lenire device was tested in 300 patients.", "90000010")[0]}
        a = run_scenario({"queue": [it, A], "settings": STAGED, "records": rec, "runs": [{}]})["runs"][0]
        self.assertNotIn(it["id"], a["apiCalls"]); self.assertIn(it["id"], a["queue"]); self.assertEqual(list(a["staged"]), [A["id"]])

    def test_unrelated_neuromodulation_is_evaluated_normally(self):
        it = pubmed_item(90000011, "Neuromodulation for Subjective Tinnitus: A Systematic Review and Meta-Analysis of Randomized Trials.")
        a = run_scenario({"queue": [it], "settings": STAGED, "runs": [{}]})["runs"][0]
        self.assertEqual(a["apiCalls"], {it["id"]: 1})


class PromptInputTests(unittest.TestCase):
    """D9 and the record header reach the model."""

    def test_intelligence_flag_record_availability_and_header_are_in_the_prompt(self):
        news = news_item("cilcare-tokyo", "Cilcare opens Tokyo subsidiary")
        r = run_scenario({"queue": [news, A], "settings": STAGED, "runs": [{}]})
        pm = r["prompts"]
        self.assertTrue(pm[news["id"]]["meta"]["intelligenceOnly"]); self.assertFalse(pm[news["id"]]["meta"]["recordAvailable"])
        self.assertIn("RECORD COMPLETENESS: UNAVAILABLE", pm[news["id"]]["recordHead"])
        self.assertFalse(pm[A["id"]]["meta"]["intelligenceOnly"]); self.assertTrue(pm[A["id"]]["meta"]["recordAvailable"])
        self.assertIn("RECORD COMPLETENESS: COMPLETE", pm[A["id"]]["recordHead"])
        for v in pm.values():
            self.assertNotIn("NEVER", v["comparisonTypeLine"])

    def test_headline_only_news_is_staged_as_a_hold_with_low_confidence(self):
        news = news_item("cilcare-tokyo", "Cilcare opens Tokyo subsidiary")
        a = run_scenario({"queue": [news], "settings": STAGED, "runs": [{}]})["runs"][0]
        self.assertEqual(a["staged"][news["id"]]["route"], "hold")
        self.assertIn("not verified", a["staged"][news["id"]]["reason"])


class RecordFetchTests(unittest.TestCase):
    """Found in the offline dry run: NCBI answered HTTP 429 to back-to-back fetches and a paid call was spent on an empty record."""

    def _patched(self, behaviour):
        import urllib.error, urllib.request
        calls = {"n": 0}

        class Resp:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return b"ok"

        def fake(req, timeout=0):
            calls["n"] += 1
            return behaviour(calls["n"], req, urllib.error, Resp)
        return calls, fake

    def run_get(self, behaviour):
        calls, fake = self._patched(behaviour)
        o_url, o_sleep = evaluate_queue.urllib.request.urlopen, evaluate_queue.time.sleep
        evaluate_queue.urllib.request.urlopen, evaluate_queue.time.sleep = fake, (lambda s: None)
        try:
            try:
                return calls, evaluate_queue._get("http://example.test/x"), None
            except Exception as e:   # noqa: BLE001
                return calls, None, e
        finally:
            evaluate_queue.urllib.request.urlopen, evaluate_queue.time.sleep = o_url, o_sleep

    def test_transient_errors_are_retried(self):
        def b(n, req, ue, Resp):
            if n < 3:
                raise ue.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
            return Resp()
        calls, out, err = self.run_get(b)
        self.assertEqual((out, calls["n"], err), (b"ok", 3, None))

    def test_permanent_errors_are_not_retried_and_persistent_ones_give_up(self):
        calls, out, err = self.run_get(lambda n, req, ue, Resp: (_ for _ in ()).throw(ue.HTTPError(req.full_url, 404, "Not Found", {}, None)))
        self.assertEqual((calls["n"], getattr(err, "code", None)), (1, 404))
        calls, out, err = self.run_get(lambda n, req, ue, Resp: (_ for _ in ()).throw(ue.HTTPError(req.full_url, 503, "Unavailable", {}, None)))
        self.assertEqual((calls["n"], getattr(err, "code", None)), (3, 503))

    def test_an_unfetchable_pubmed_record_costs_nothing_and_stays_queued(self):
        rec = {A["id"]: registry_record.unavailable_record("could not fetch the primary record (HTTP Error 429: Too Many Requests)")[0]}
        a = run_scenario({"queue": [A, B], "settings": STAGED, "records": rec, "runs": [{}]})["runs"][0]
        self.assertEqual(a["apiCalls"], {B["id"]: 1})                                   # no paid call for the item without a record
        self.assertIn(A["id"], a["queue"]); self.assertNotIn(A["id"], a["staged"])
        self.assertEqual(a["status"]["evaluation"]["state"], "degraded")                # visible, not silent
        self.assertEqual(a["status"]["evaluation"]["recordUnavailable"], 1)
        self.assertEqual(ids_in_report(a), [])


class BenchmarkGateTests(unittest.TestCase):
    def test_a_benchmark_pass_on_an_older_prompt_does_not_unlock_evaluation(self):
        for kind in ("stale", "none"):
            a = run_scenario({"queue": [A], "settings": STAGED, "benchmark": kind, "runs": [{}]})["runs"][0]
            self.assertEqual(a["status"]["evaluation"]["state"], "blocked-gate", kind)
            self.assertEqual(a["totalApiCalls"], 0, kind)
        a = run_scenario({"queue": [A], "settings": STAGED, "benchmark": "ok", "runs": [{}]})["runs"][0]
        self.assertEqual(a["totalApiCalls"], 1)


@unittest.skipUnless(shutil.which("openssl"), "openssl not available")
class EncryptionAndCliTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="te-staged-"))
        (self.root / "data" / "review-queue").mkdir(parents=True)
        ev = {"whatIsNew": "X", "weeklyTitle": "T", "whyMatters": "W", "importance": "Does Not Change Current Evidence", "studyType": "RCT",
              "sourceChecks": {"recordFetched": True, "completeness": "COMPLETE", "ungroundedNumbers": [], "unsupportedTerms": [], "ungroundedNames": [], "enumFixes": []},
              "factuallyVerified": True, "confidence": "high", "confidenceModel": "high", "summaryForAdmin": "SECRETMARK", "mainLimitations": ["a"]}
        self.entry = staged_review.make_entry(dict(A, evaluation=ev, evalInput={"recordHash": "abc"}), "publish", "r", {"title": "T", "importance": "x", "summary": "S", "whyMatters": "W", "detail": {}})
        self.plain = self.root / staged_review.STAGED_REL
        self.plain.write_text(json.dumps({"items": [self.entry]}), encoding="utf-8")
        os.environ["STATE_KEY"] = "test-passphrase-not-real"

    def tearDown(self):
        os.environ.pop("STATE_KEY", None)
        shutil.rmtree(self.root, ignore_errors=True)

    def test_round_trip_in_the_workflows_own_format(self):
        enc = self.root / (staged_review.STAGED_REL + ".enc")
        staged_review.encrypt_file(self.plain, enc)
        self.assertNotIn(b"SECRETMARK", enc.read_bytes())                                 # ciphertext reveals nothing
        self.plain.unlink()
        self.assertEqual(staged_review.load_staged(self.root)["items"][0]["id"], A["id"])
        import subprocess                                                                 # the exact command the workflow runs
        p = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-in", str(enc), "-pass", "env:STATE_KEY"], capture_output=True)
        self.assertEqual(p.returncode, 0); self.assertIn(b"SECRETMARK", p.stdout)
        os.environ["STATE_KEY"] = "wrong"
        with self.assertRaises(RuntimeError):
            staged_review.load_staged(self.root)

    def test_cli_export_and_decide(self):
        out = self.root / "review.md"
        self.assertEqual(staged_review.main(["export", "--out", str(out), "--root", str(self.root)]), 0)
        md = out.read_text(encoding="utf-8")
        self.assertIn("NOT verification", md); self.assertIn("Automated source checks", md); self.assertIn(self.entry["evalHash"], md)
        self.assertEqual(staged_review.main(["decide", A["id"], "approve", "--hash", self.entry["evalHash"], "--root", str(self.root)]), 0)
        dec = json.loads((self.root / staged_review.DECISIONS_REL).read_text(encoding="utf-8"))["decisions"]
        self.assertEqual((dec[0]["decision"], dec[0]["evalHash"]), ("approve", self.entry["evalHash"]))
        self.assertEqual(staged_review.main(["decide", A["id"], "approve", "--hash", "deadbeef", "--root", str(self.root)]), 2)
        self.assertEqual(staged_review.main(["decide", A["id"], "correct", "--set", "proposedScoreChange=3", "--root", str(self.root)]), 2)   # forbidden field refused locally
        self.assertEqual(staged_review.main(["decide", "pubmed-0", "approve", "--root", str(self.root)]), 2)
        self.assertEqual(staged_review.main(["decide", A["id"], "correct", "--set", "whyMatters=Edited", "--root", str(self.root)]), 0)
        dec = json.loads((self.root / staged_review.DECISIONS_REL).read_text(encoding="utf-8"))["decisions"]
        self.assertEqual(len(dec), 1); self.assertEqual(dec[0]["corrections"], {"whyMatters": "Edited"})   # one decision per item: the latest replaces the earlier one


if __name__ == "__main__":
    unittest.main()

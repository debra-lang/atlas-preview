"""E2. A duplicate check must not lose a different record. Later updates of an already-registered trial stay, every record with its own safeguard keeps it, a record nobody has read is not dropped, and no duplicate check or model verdict can discard a Level 3 safety trigger. A real repeat is still dropped, on purpose.
The REAL weekly cycle runs in a temp sandbox (run_scenario.py), with the model stubbed. AI stays off in production. Run:  python -m unittest discover -s engine/tests -v"""
import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401

OFF = {"enabled": False, "mode": "staged", "limitPerRun": 10}
STAGED = {"enabled": True, "mode": "staged", "limitPerRun": 10}
PUBLISH = {"enabled": True, "mode": "publish", "limitPerRun": 10}
NCT = "NCT99000555"
URL = f"https://clinicaltrials.gov/study/{NCT}"
UPDATE = ctgov_item(NCT, title="A later update of a tinnitus trial", source="ClinicalTrials.gov", date="2026-10-13")
PUB_URL = "https://pubmed.ncbi.nlm.nih.gov/990777/"
FULL_EV = {"whatIsNew": "Routine finding reported in the record.", "relevanceCategory": 1, "notRelevant": False, "affectedTreatment": "cbt", "studyType": "cohort", "studyQuality": "moderate", "importance": "Does Not Change Current Evidence", "weeklyTitle": "Routine update", "whyMatters": "A reason.", "factuallyVerified": True, "confidence": "high", "changeClass": "routine", "duplicateOf": None}
LEVEL3 = [{"tier": "level3", "kind": "safety term", "detail": "serious adverse event"}]


def pm(**k):
    return pubmed_item(990777, "A tinnitus paper seen before", source="J Audiol", url=PUB_URL, **k)


def scenario(item, settings=OFF, register=(PUB_URL,), **k):
    run = run_scenario({"queue": [item], "settings": settings, "paused": [], "registerAdd": list(register), **k, "runs": k.get("runs", [{}])})["runs"]
    for r in run:
        if r["exitCode"]:
            raise AssertionError(f"the run stopped: {r['output'][-300:]}")
    return run[0] if len(run) == 1 else run


class KeptThoughItsLinkIsRegistered(unittest.TestCase):
    """Each kept where its own safeguard sends it. Today's route drops every one of these as already published."""

    def test_a_later_update_of_a_registered_trial_stays_queued(self):
        run = scenario(UPDATE, register=(URL,))
        self.assertIn(UPDATE["id"], run["queue"])
        self.assertEqual(run["status"]["rejectedDuplicates"], 0)

    def test_a_record_waiting_to_be_read_stays_queued(self):
        run = scenario(pm())
        self.assertIn(pm()["id"], run["queue"])
        self.assertEqual(run["status"]["rejectedDuplicates"], 0)

    def test_a_cited_notice_goes_to_the_private_held_store(self):
        it = pm(notice={"kind": "retraction", "resolution": "cited", "studyIds": ["s1"]})
        self.assertEqual(scenario(it)["held"], [it["id"]])

    def test_a_notice_that_could_not_be_resolved_goes_to_the_private_held_store(self):
        it = pm(notice={"kind": "correction", "resolution": "unresolved"})
        self.assertEqual(scenario(it)["held"], [it["id"]])

    def test_an_uncited_notice_goes_to_the_archive(self):
        it = pm(notice={"kind": "correction", "resolution": "uncited"})
        self.assertIn(it["id"], scenario(it)["archived"])

    def test_a_language_hold_goes_to_the_private_held_store(self):
        it = pm(languageHold={"state": "not-english", "articleLanguage": "ger", "reason": "the abstract is in German"})
        self.assertEqual(scenario(it)["held"], [it["id"]])

    def test_a_catalogued_record_goes_to_the_archive(self):
        it = pm(catalogued={"rule": "C1", "reason": "a passing mention"})
        self.assertIn(it["id"], scenario(it)["archived"])

    def test_an_unusable_ai_answer_goes_to_review(self):
        it = pm(evaluation={"parseError": True, "failureKind": "truncated"})
        self.assertEqual(scenario(it, STAGED)["staged"][it["id"]]["route"], "hold")
        self.assertEqual(scenario(it, PUBLISH)["held"], [it["id"]])

    def test_a_level_3_record_goes_to_review(self):
        it = pm(evaluation={**FULL_EV, "escalation": LEVEL3})
        self.assertEqual(scenario(it, STAGED)["staged"][it["id"]]["route"], "hold")
        self.assertEqual(scenario(it, PUBLISH)["held"], [it["id"]])

    def test_paused_and_held_records_stay_queued_as_they_did(self):
        it = pm()
        self.assertIn(it["id"], run_scenario({"queue": [it], "settings": OFF, "paused": [it["id"]], "registerAdd": [PUB_URL], "runs": [{}]})["runs"][0]["queue"])
        marked = pm(topicHold="lenire-neuromod")
        self.assertIn(it["id"], scenario(marked)["queue"])


class WhenARegistryUpdateIsRead(unittest.TestCase):
    def test_the_evaluator_reads_it_and_it_goes_to_the_owner(self):
        run = scenario(UPDATE, STAGED, register=(URL,))
        self.assertEqual(run["apiCalls"], {UPDATE["id"]: 1})
        self.assertIn(UPDATE["id"], run["staged"])
        self.assertEqual([x for x in run["reportItems"] if NCT in json.dumps(x)], [], "nothing public while it is staged")

    def test_results_posted_stay_with_a_person(self):
        rec = "\n".join(["SOURCE: simulated", "RECORD COMPLETENESS: COMPLETE - nothing was left out", "CRITICAL SECTIONS MISSING: no", "REGISTRY FIELD hasResults: TRUE (results posted)", "---", f"Title: {UPDATE['title']}", f"NCT ID: {NCT}"])
        run = scenario(UPDATE, PUBLISH, register=(URL,), records={UPDATE["id"]: rec}, recordMeta={UPDATE["id"]: {"completeness": "COMPLETE", "hasResults": True}})
        self.assertEqual(run["held"], [UPDATE["id"]])
        self.assertEqual([x for x in run["reportItems"] if NCT in json.dumps(x)], [])

    def test_two_updates_of_one_trial_in_one_run_give_one_line(self):
        older = ctgov_item(NCT, title="An earlier update of a tinnitus trial", source="ClinicalTrials.gov", date="2026-09-01")
        run = run_scenario({"queue": [UPDATE, older], "settings": PUBLISH, "paused": [], "registerAdd": [URL], "runs": [{}]})["runs"][0]
        self.assertEqual(run["apiCalls"], {UPDATE["id"]: 1})
        self.assertEqual(len([x for x in run["reportItems"] if (x.get("identifier") or "") == UPDATE["id"]]), 1)
        self.assertEqual(len([x for x in run["reportItems"] if NCT in json.dumps(x)]), 1)

    def test_the_owners_approval_of_one_is_not_read_as_already_published(self):
        runs = run_scenario({"queue": [UPDATE], "settings": STAGED, "paused": [], "registerAdd": [URL], "runs": [{}, {"decisions": {"decisions": [{"id": UPDATE["id"], "decision": "approve", "evalHash": f"@HASH:{UPDATE['id']}", "decidedAt": "2026-11-01"}]}}]})["runs"]
        out = runs[1]["status"]["staged"]["decisions"]
        self.assertEqual((out["applied"], out["alreadyPublished"]), (1, 0))
        self.assertEqual(len([x for x in runs[1]["reportItems"] if x.get("identifier") == UPDATE["id"]]), 1)


class ARealRepeatIsStillDropped(unittest.TestCase):
    def test_a_read_record_with_the_same_link_goes_on_purpose_with_a_row_in_the_log(self):
        for name, s in (("staged", STAGED), ("publish", PUBLISH)):
            with self.subTest(name):
                it = pm(evaluation=dict(FULL_EV))
                run = scenario(it, s)
                self.assertEqual(run["status"]["rejectedDuplicates"], 1)
                self.assertNotIn(it["id"], run["queue"])
                self.assertEqual(run["staged"], {})
                self.assertEqual([r["reason"] for r in run["log"] if r.get("identifier") == it["id"]], ["already published in the research-updates feed"])

    def test_with_the_same_title_too(self):
        it = pubmed_item(990778, "A tinnitus paper seen before under another number", source="J Audiol", evaluation=dict(FULL_EV))
        run = scenario(it, PUBLISH, register=(it["title"],))
        self.assertEqual(run["status"]["rejectedDuplicates"], 1)

    def test_one_waiting_to_be_read_is_read_then_dropped(self):
        it = pm()
        run = scenario(it, STAGED)
        self.assertEqual(run["apiCalls"], {it["id"]: 1})
        self.assertEqual(run["status"]["rejectedDuplicates"], 1)
        self.assertNotIn(it["id"], run["queue"])


class ASafetyTriggerOutranksEveryVerdict(unittest.TestCase):
    """LE-33: a model's answer must never outrank a deterministic safety trigger."""

    VERDICTS = {"a duplicate": {"duplicateOf": "some-study"}, "not relevant": {"notRelevant": True}, "no treatment and no importance": {"affectedTreatment": "none", "importance": None}, "category 5": {"relevanceCategory": 5}, "category 6": {"relevanceCategory": 6},
                "category 3": {"relevanceCategory": 3}, "category 4": {"relevanceCategory": 4}, "not a study": {"studyType": "other", "studyQuality": "not-a-study"}}

    def test_each_verdict_reaches_a_person_in_either_mode(self):
        for name, verdict in self.VERDICTS.items():
            it = pubmed_item(990780, "A tinnitus paper", source="J Audiol", url="https://pubmed.ncbi.nlm.nih.gov/990780/", evaluation={**FULL_EV, **verdict, "escalation": LEVEL3})
            with self.subTest(name, mode="staged"):
                self.assertTrue(scenario(it, STAGED, register=())["staged"][it["id"]]["reason"].startswith("Level 3 trigger"))
            with self.subTest(name, mode="publish"):
                run = scenario(it, PUBLISH, register=())
                self.assertEqual(run["held"], [it["id"]])
                self.assertTrue(run["heldReasons"][it["id"]].startswith("Level 3 trigger"))

    def test_the_control_each_verdict_alone_still_does_what_it_did(self):
        for name, verdict in self.VERDICTS.items():
            it = pubmed_item(990780, "A tinnitus paper", source="J Audiol", url="https://pubmed.ncbi.nlm.nih.gov/990780/", evaluation={**FULL_EV, **verdict})
            with self.subTest(name):
                run = scenario(it, PUBLISH, register=())
                self.assertEqual(run["held"], [])
                self.assertNotIn(it["id"], run["queue"])

    def test_a_level_2_trigger_does_not_outrank_them(self):
        it = pubmed_item(990780, "A tinnitus paper", source="J Audiol", url="https://pubmed.ncbi.nlm.nih.gov/990780/", evaluation={**FULL_EV, "duplicateOf": "some-study", "escalation": [{"tier": "level2", "kind": "x", "detail": "y"}]})
        run = scenario(it, PUBLISH, register=())
        self.assertEqual(run["status"]["rejectedDuplicates"], 1)


if __name__ == "__main__":
    unittest.main()

"""Option B. While an intentional hold is active, a routine status change on a linked trial adds no automated item: no line in the weekly report, nothing on the product's page, no product named anywhere new.
The registry fact stays on the trial's own record. A halted status is still reported, naming no product, and tells the owner. The REAL weekly cycle runs in a temp sandbox (run_scenario.py).
Run:  python -m unittest discover -s engine/tests -v"""
import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401

NCT, OTHER = "NCT99000901", "NCT99000902"
LINKED = {"nctId": NCT, "title": "EEG biomarker study with the Lenire device", "sponsor": "University of Minnesota", "status": "Active, not recruiting", "treatment": "lenire", "n": 40, "phase": "NA", "country": "USA"}
CLEAN = {**LINKED, "nctId": OTHER, "title": "EEG biomarker study with a sound device", "treatment": "cbt"}
AUTO = {"listings": True, "updateHistory": True}
SETTINGS = {"AI off (production)": {"enabled": False, "mode": "staged", "limitPerRun": 10}, "AI on, staged": {"enabled": True, "mode": "staged", "limitPerRun": 100}, "AI on, publish": {"enabled": True, "mode": "publish", "limitPerRun": 100}}
OFF = SETTINGS["AI off (production)"]
REC = "\n".join(["SOURCE: simulated", "RECORD COMPLETENESS: COMPLETE - nothing was left out", "CRITICAL SECTIONS MISSING: no", "REGISTRY FIELD hasResults: FALSE (no results posted)", "---", f"NCT ID: {NCT}", "Title: A plain title", "Conditions: Tinnitus", "Primary outcome: Tinnitus Handicap Inventory", "Interventions: Device: Lenire", "Sponsor: University of Minnesota"])


def study(nct, status):
    return {"protocolSection": {"identificationModule": {"nctId": nct, "briefTitle": "x", "officialTitle": "x"}, "statusModule": {"overallStatus": status}}}


def go(trials=(LINKED,), status="COMPLETED", settings=OFF, runs=None, queue=(), records=None, paused=()):
    out = run_scenario({"trials": [dict(t) for t in trials], "registry": {t["nctId"]: study(t["nctId"], status) for t in trials}, "queue": list(queue), "records": records or {}, "settings": settings, "automation": AUTO, "paused": list(paused), "runs": runs or [{}]})["runs"]
    if any(r["exitCode"] for r in out):      # a run that stopped adds no item either, which would prove nothing below
        raise AssertionError(f"the run stopped: {out[-1]['output'][-300:]}")
    return out


def lines(run, nct=NCT):
    return [x for x in run["reportItems"] if nct in json.dumps(x)]


class ARoutineChange(unittest.TestCase):
    def test_adds_no_item_and_nothing_on_the_product_page(self):
        for name, s in SETTINGS.items():
            run = go(settings=s)[0]
            with self.subTest(setting=name):
                self.assertEqual(lines(run), [])
                self.assertEqual([l for l in run["latest"]["lenire"] if NCT in json.dumps(l)], [])
                self.assertEqual(run["status"].get("trialStatusItemsWithheld"), 1)

    def test_the_registry_fact_stays_on_the_trials_own_record(self):
        t = go()[0]["trials"][0]
        self.assertTrue(t["status"].startswith("Completed (verified at ClinicalTrials.gov "))
        self.assertEqual({k: v for k, v in t.items() if k != "status"}, {k: v for k, v in LINKED.items() if k != "status"})

    def test_the_record_of_it_names_no_product(self):
        rows = [r for r in go()[0]["log"] if r.get("step") == "trial-status-item"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["identifier"], rows[0]["published"], rows[0]["held"]), (NCT, False, True))
        self.assertNotIn("lenire", json.dumps(rows).lower())

    def test_each_way_a_trial_can_be_linked_to_a_hold(self):
        plain = {**LINKED, "title": "A plain title", "treatment": "cbt"}
        marked = {**ctgov_item(NCT, title="A plain title", source="University of Minnesota", date="2026-10-13"), "topicHold": "lenire-neuromod"}
        for name, trial, kw in (("the name in the title", {**plain, "title": "A study of Lenire"}, {}), ("only the treatment label", {**plain, "treatment": "lenire"}, {}), ("only the sponsor", {**plain, "sponsor": "Neuromod Devices"}, {}),
                                ("a hold mark on its queued record", plain, {"queue": [marked], "records": {marked["id"]: REC}}), ("an owner pause on its record", plain, {"paused": [marked["id"]], "queue": [{k: v for k, v in marked.items() if k != "topicHold"}], "records": {marked["id"]: REC}})):
            with self.subTest(name):
                run = go(trials=(trial,), **kw)[0]
                self.assertEqual(lines(run), [])
                self.assertEqual(run["status"].get("trialStatusItemsWithheld"), 1)

    def test_release_1s_exact_comparison_still_sees_a_change_to_recruiting(self):
        run = go(status="RECRUITING")[0]
        self.assertTrue(run["trials"][0]["status"].startswith("Recruiting (verified at ClinicalTrials.gov "))
        self.assertEqual(lines(run), [])
        self.assertEqual(run["status"].get("trialStatusItemsWithheld"), 1)

    def test_no_change_at_all_is_not_counted_as_withheld(self):
        run = go(status="ACTIVE_NOT_RECRUITING")[0]
        self.assertEqual(run["trials"][0]["status"], LINKED["status"])
        self.assertIsNone(run["status"].get("trialStatusItemsWithheld"))

    def test_a_word_like_the_held_one_is_not_a_link(self):
        run = go(trials=({**LINKED, "title": "A neuromodulation study", "treatment": "cbt"},))[0]
        self.assertEqual(len(lines(run)), 1)


class EveryOtherTrial(unittest.TestCase):
    def test_a_trial_no_hold_touches_publishes_as_before_in_the_same_run(self):
        run = go(trials=(LINKED, CLEAN))[0]
        self.assertEqual(lines(run), [])
        self.assertEqual([x["title"] for x in lines(run, OTHER)], [f"Trial status change: {OTHER} is now 'Completed'"])
        self.assertEqual(len([l for l in run["latest"]["cbt"] if OTHER in json.dumps(l)]), 1)
        self.assertEqual(run["status"].get("trialStatusItemsWithheld"), 1)

    def test_with_no_hold_in_force_the_same_trial_publishes_normally(self):
        run = go(runs=[{"topicHolds": []}])[0]
        self.assertEqual(len(lines(run)), 1)
        self.assertEqual(len([l for l in run["latest"]["lenire"] if NCT in json.dumps(l)]), 1)
        self.assertIsNone(run["status"].get("trialStatusItemsWithheld"))


class AHaltedTrial(unittest.TestCase):
    """Terminated, suspended or withdrawn can reflect a safety or integrity problem, so it is not suppressed."""

    def test_is_reported_naming_no_product_and_tells_the_owner(self):
        for status, words in (("TERMINATED", "Terminated"), ("SUSPENDED", "Suspended"), ("WITHDRAWN", "Withdrawn")):
            run = go(status=status)[0]
            with self.subTest(status):
                self.assertEqual([x["title"] for x in lines(run)], [f"Trial status change: {NCT} is now '{words}'"])
                self.assertNotIn("lenire", json.dumps(lines(run)).lower())
                self.assertNotIn("minnesota", json.dumps(lines(run)).lower())
                self.assertEqual([l for l in run["latest"]["lenire"] if NCT in json.dumps(l)], [])
                self.assertEqual(run["status"].get("holdTrialHaltedNeedsOwner"), 1)

    def test_on_a_trial_no_hold_touches_is_an_ordinary_item(self):
        run = go(trials=(CLEAN,), status="TERMINATED")[0]
        self.assertEqual(len(lines(run, OTHER)), 1)
        self.assertIsNone(run["status"].get("holdTrialHaltedNeedsOwner"))


if __name__ == "__main__":
    unittest.main()

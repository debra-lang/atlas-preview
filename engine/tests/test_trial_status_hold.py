"""Automatic registry status updates stay on for tracked trials, including trials linked to a topic hold (owner decision, 1 Nov 2026). They may state only the registry's status:
they must not release a held record, bring in anything a sponsor wrote, or change a rating or an evidence conclusion. The REAL weekly cycle runs in a temp sandbox (run_scenario.py).
Run:  python -m unittest discover -s engine/tests -v"""
import json, re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401

NCT = "NCT99000901"
TRIAL = {"nctId": NCT, "title": "EEG biomarker study with the Lenire device", "sponsor": "University of Minnesota", "status": "Active, not recruiting", "treatment": "lenire", "n": 40, "phase": "NA", "country": "USA", "completionEst": "2027", "watch": False, "whyItMatters": "Tracked."}
PROMO = "Breakthrough cure: Lenire eliminates tinnitus in every patient"
AUTO = {"listings": True, "updateHistory": True}
SETTINGS = {"AI off (production)": {"enabled": False, "mode": "staged", "limitPerRun": 10},
            "AI on, staged": {"enabled": True, "mode": "staged", "limitPerRun": 100},
            "AI on, publish": {"enabled": True, "mode": "publish", "limitPerRun": 100}}


def study(status="COMPLETED"):
    # what a sponsor can write sits beside the status: none of it may reach the site
    return {"protocolSection": {"identificationModule": {"nctId": NCT, "briefTitle": PROMO, "officialTitle": PROMO}, "statusModule": {"overallStatus": status},
                                "descriptionModule": {"briefSummary": PROMO}, "sponsorCollaboratorsModule": {"leadSponsor": {"name": PROMO}}}}


def scenario(settings, status="COMPLETED", queue=(), records=None, runs=2):
    return run_scenario({"trials": [dict(TRIAL)], "registry": {NCT: study(status)}, "queue": list(queue), "records": records or {}, "settings": settings, "automation": AUTO, "paused": [], "runs": [{} for _ in range(runs)]})["runs"]


class StatusLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {n: scenario(s) for n, s in SETTINGS.items()}

    def test_the_update_is_published_once_and_says_only_the_status(self):
        for name, runs in self.runs.items():
            with self.subTest(setting=name):
                lines = [x for x in runs[0]["reportItems"] if NCT in (x.get("title") or "")]
                self.assertEqual(len(lines), 1)
                self.assertEqual(lines[0]["title"], f"Trial status change: {NCT} is now 'Completed'")
                self.assertEqual(lines[0]["importance"], "Does Not Change Current Evidence")
                self.assertEqual(lines[0]["detail"]["changesAssessment"], "No — trial status only.")
                self.assertEqual(len([x for x in runs[1]["reportItems"] if NCT in (x.get("title") or "")]), 1)  # the next cycle (same day here, so the same report) adds no second line

    def test_nothing_a_sponsor_wrote_reaches_the_site(self):
        for name, runs in self.runs.items():
            with self.subTest(setting=name):
                self.assertNotIn(PROMO, json.dumps([r["reportItems"] for r in runs] + [runs[1]["trials"], runs[1]["latest"], runs[1]["listings"]]))

    def test_the_refresh_asks_the_registry_for_the_status_field_only(self):
        for name, runs in self.runs.items():
            with self.subTest(setting=name):
                self.assertTrue(runs[0]["registryUrls"])
                for u in runs[0]["registryUrls"]:
                    self.assertIn("fields=OverallStatus", u)

    def test_only_the_trial_status_changes_in_the_tracked_record(self):
        for name, runs in self.runs.items():
            with self.subTest(setting=name):
                t = runs[1]["trials"][0]
                self.assertTrue(t["status"].startswith("Completed (verified at ClinicalTrials.gov "))
                self.assertEqual({k: v for k, v in t.items() if k != "status"}, {k: v for k, v in TRIAL.items() if k != "status"})

    def test_no_rating_ranking_study_or_evidence_conclusion_changes(self):
        base = scenario(SETTINGS["AI off (production)"], status="ACTIVE_NOT_RECRUITING", runs=1)[0]   # the same sandbox with no status change
        self.assertEqual([x for x in base["reportItems"] if NCT in (x.get("title") or "")], [])
        for name, runs in self.runs.items():
            for run in runs:
                with self.subTest(setting=name, run=run["run"]):
                    self.assertTrue(run["ratingsUnchanged"]); self.assertTrue(run["studiesUnchanged"])
                    self.assertEqual(run["treatmentsWithoutLatest"], base["treatmentsWithoutLatest"])          # every treatment field except the factual 'latest' news list
                    self.assertEqual(run["rankingsHash"], base["rankingsHash"])

    def test_the_news_line_on_the_treatment_is_the_status_line_only(self):
        for name, runs in self.runs.items():
            with self.subTest(setting=name):
                new = [l for l in runs[1]["latest"]["lenire"] if NCT in (l.get("text") or "")]
                self.assertEqual([l["text"] for l in new], [f"Trial status change: {NCT} is now 'Completed'"])


class RegistryValues(unittest.TestCase):
    # KNOWN GAP, for owner decision (1 Nov 2026): the registry returns a fixed list of status values and no sponsor text, but a value outside the site's own list is published as it stands.
    @unittest.expectedFailure
    def test_a_status_outside_the_known_list_is_not_published(self):
        runs = scenario(SETTINGS["AI off (production)"], status="APPROVED_FOR_MARKETING", runs=1)
        self.assertEqual([x for x in runs[0]["reportItems"] if NCT in (x.get("title") or "")], [])
        self.assertEqual(runs[0]["trials"][0]["status"], TRIAL["status"])


class HeldRecords(unittest.TestCase):
    """A status update must not release, publish, list, evaluate or lose a held record of the same trial or topic."""
    SAME = ctgov_item(NCT, title="EEG biomarker study with the Lenire device", source="University of Minnesota", date="2026-10-13")
    OTHER = pubmed_item(990911, "Lenire outcomes in chronic tinnitus", source="J Audiol", date="2026 Oct 12", triage={"tinAbs": 4, "tinMesh": True, "tracked": [], "safety": [], "safetyWeak": [], "animalOnly": False, "hasAbstract": True})

    def test_another_held_record_stays_held(self):
        for name, s in SETTINGS.items():
            runs = scenario(s, queue=[self.OTHER])
            with self.subTest(setting=name):
                self.assertIn(self.OTHER["id"], runs[1]["queue"])
                self.assertNotIn("PMID 990911", {e["key"] for e in (runs[1]["listings"] or {}).get("items", [])})
                self.assertFalse(any(self.OTHER["id"] in r["apiCalls"] for r in runs))
                self.assertNotIn(self.OTHER["title"], json.dumps([r["reportItems"] for r in runs]))

    def test_a_held_record_that_already_has_an_evaluation_stays_held(self):
        # only the route's own hold protects this one: the AI gate never sees an item that has already been evaluated
        ev = {"whatIsNew": "Routine finding.", "relevanceCategory": 1, "notRelevant": False, "affectedTreatment": "lenire", "changeClass": "routine", "proposedScoreChange": None, "proposedRankChange": None,
              "importance": "Does Not Change Current Evidence", "weeklyTitle": "A routine Lenire finding", "whyMatters": "Routine.", "factuallyVerified": True, "factuallyVerifiedReason": "stated in the record", "confidence": "high", "duplicateOf": None}
        it = {**self.OTHER, "id": "pubmed-990912", "url": "https://pubmed.ncbi.nlm.nih.gov/990912/", "evaluation": ev}
        for name, s in SETTINGS.items():
            runs = scenario(s, queue=[it])
            with self.subTest(setting=name):
                self.assertIn(it["id"], runs[1]["queue"])
                self.assertFalse(any(it["id"] in r["staged"] for r in runs))
                self.assertNotIn("A routine Lenire finding", json.dumps([r["reportItems"] for r in runs]))

    # KNOWN DEFECT, for owner decision (1 Nov 2026): route() checks 'already published' before the hold, and a status update registers the trial's URL, so on the next cycle a held record of
    # that trial is dropped as a duplicate. It is never published, listed or evaluated, but it leaves the queue. No held record has been affected so far.
    @unittest.expectedFailure
    def test_a_held_record_of_the_same_trial_stays_held_and_is_not_lost(self):
        for name, s in SETTINGS.items():
            runs = scenario(s, queue=[self.SAME])
            with self.subTest(setting=name):
                self.assertFalse(any(self.SAME["id"] in r["apiCalls"] for r in runs))
                self.assertNotIn(NCT, {e["key"] for e in (runs[1]["listings"] or {}).get("items", [])})
                self.assertEqual([x for r in runs for x in r["reportItems"] if self.SAME["id"] in json.dumps(x)], [])
                self.assertIn(self.SAME["id"], runs[1]["queue"], "a held record must stay queued (never lost)")


if __name__ == "__main__":
    unittest.main()

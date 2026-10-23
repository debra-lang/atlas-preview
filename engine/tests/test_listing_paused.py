"""Offline tests for listing owner-paused records (owner decision, 23 Oct 2026): the three 2026 AAO-HNSF guideline records may be LISTED as verified bibliographic facts, while their pause
(no AI evaluation, no publication as research, no change to any treatment assessment) stays exactly as it is. Only ids named in automation_settings.json are affected."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402,F401
import listings  # noqa: E402
from common import run_scenario, pubmed_item  # noqa: E402

FACTS = {"tinAbs": 6, "tinMesh": True, "tracked": [], "safety": [], "safetyWeak": [], "animalOnly": False, "hasAbstract": True}
G1, G2, OTHER = (pubmed_item(990001, "Clinical Practice Guideline: Tinnitus Update", source="Otolaryngol Head Neck Surg"),
                 pubmed_item(990002, "Executive Summary of the Clinical Practice Guideline on Tinnitus", source="Otolaryngol Head Neck Surg"),
                 pubmed_item(990003, "Tinnitus counselling study", source="J Audiol"))
SETTINGS = {"enabled": True, "mode": "staged", "limitPerRun": 10}


def queue():
    return [{**i, "triage": dict(FACTS)} for i in (G1, G2, OTHER)]


class Settings(unittest.TestCase):
    def test_the_allow_list_is_validated(self):
        self.assertEqual(listings.load_settings({"listings": True, "listingsIncludePaused": ["pubmed-2", "pubmed-1", "pubmed-1"]})["includePaused"], ["pubmed-1", "pubmed-2"])
        for bad in (None, "pubmed-1", 5, {"a": 1}, [1, None, "ctgov-NCT1", "newsintel-x", ""]):
            self.assertEqual(listings.load_settings({"listings": True, "listingsIncludePaused": bad})["includePaused"], [], bad)
        self.assertEqual(listings.load_settings({"listings": True})["includePaused"], [])


class Cycle(unittest.TestCase):
    def test_paused_records_are_listed_only_when_named_and_stay_paused(self):
        r = run_scenario({"queue": queue(), "settings": SETTINGS, "paused": ["pubmed-990001", "pubmed-990002"],
                          "automation": {"listings": True, "listingsIncludePaused": ["pubmed-990001"]}, "runs": [{}]})["runs"][0]
        self.assertEqual({e["key"] for e in r["listings"]["items"]}, {"PMID 990001", "PMID 990003"})            # the named paused record is listed, the unnamed one is not
        self.assertIn("pubmed-990001", r["queue"]); self.assertIn("pubmed-990002", r["queue"])                     # both still queued, nothing lost
        self.assertEqual(r["status"]["evaluation"]["paused"], 2)                                                 # both still counted as paused
        self.assertEqual(sorted(r["apiCalls"]), ["pubmed-990003"])                                               # only the unpaused record reached the AI (evaluation is on in this scenario)
        self.assertTrue(r["ratingsUnchanged"] and r["studiesUnchanged"])

    def test_without_the_allow_list_every_paused_record_stays_out_as_before(self):
        r = run_scenario({"queue": queue(), "settings": SETTINGS, "paused": ["pubmed-990001", "pubmed-990002"], "automation": {"listings": True}, "runs": [{}]})["runs"][0]
        self.assertEqual({e["key"] for e in r["listings"]["items"]}, {"PMID 990003"})

    def test_a_paused_record_is_listed_once_and_the_pause_survives_later_cycles(self):
        spec = {"queue": queue(), "settings": SETTINGS, "paused": ["pubmed-990001"], "automation": {"listings": True, "listingsIncludePaused": ["pubmed-990001"]}, "runs": [{}, {}]}
        a, b = run_scenario(spec)["runs"]
        self.assertEqual(a["listings"]["count"], b["listings"]["count"])
        self.assertIn("pubmed-990001", b["queue"]); self.assertEqual(b["totalApiCalls"], 0)


if __name__ == "__main__":
    unittest.main()

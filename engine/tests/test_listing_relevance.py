"""Offline tests for the listing relevance rule (engine/listings.relevance). The 23 Oct dry run over the real queue showed it was necessary: of 19 registry records 16 were only passing
mentions of tinnitus (an adverse-effect list, an exclusion note, a secondary questionnaire), and 12 of 34 PubMed records listed because a tracked treatment word ("cervical", "hearing aid",
"intratympanic") was in the title. No network. Run:  python -m unittest discover -s engine/tests -v"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402,F401
import listings, registry_record  # noqa: E402
from common import pubmed_item, ctgov_item  # noqa: E402

FACTS_PASSING = {"tinAbs": 1, "tinMesh": False, "tracked": [], "safety": [], "safetyWeak": [], "animalOnly": False, "hasAbstract": True}


def pubmed(title, **facts):
    return {"id": "pubmed-1", "title": title, "triage": {"tinAbs": 0, "tinMesh": False, **facts}}


def registry(title="A trial", conditions="Hearing Loss", extra="", keywords=""):
    return (f"NCT ID: NCT1\nTitle: {title}\nOfficial title: {title}\nOverall status: RECRUITING\nConditions: {conditions}\n" + (f"Keywords: {keywords}\n" if keywords else "") + f"BRIEF SUMMARY: s\n{extra}")


class PubMedRule(unittest.TestCase):
    def test_title_mesh_and_three_mentions(self):
        self.assertEqual(listings.relevance(pubmed("Tinnitus after cochlear implantation"))[:2], (True, 2))
        self.assertEqual(listings.relevance(pubmed("Hearing outcomes", tinMesh=True))[:2], (True, 2))
        self.assertEqual(listings.relevance(pubmed("Hearing outcomes", tinAbs=3))[:2], (True, 3))
        for n in (0, 1, 2):
            self.assertFalse(listings.relevance(pubmed("Hearing outcomes", tinAbs=n))[0], n)

    def test_a_tracked_treatment_or_a_trial_in_the_title_does_not_make_a_record_relevant(self):
        for title in ("Intratympanic gentamicin for vertigo: a case report", "Cervical artery dissection and quality of life", "Predicting hearing aid satisfaction",
                      "Hyperbaric oxygen for sudden hearing loss", "A randomised trial of local anaesthetic toxicity"):
            self.assertFalse(listings.relevance(pubmed(title, tinAbs=1))[0], title)

    def test_missing_facts_are_not_relevant_here_the_caller_defers_before_asking(self):
        self.assertFalse(listings.relevance({"id": "pubmed-2", "title": "Hearing outcomes"})[0])


class RegistryRule(unittest.TestCase):
    IT = {"id": "ctgov-NCT1-2026-10-20", "title": "A trial"}

    def test_title_conditions_keywords_and_primary_outcome_are_tier_2(self):
        self.assertEqual(listings.relevance(self.IT, registry(conditions="Tinnitus; Tinnitus, Bilateral"))[:2], (True, 2))
        self.assertEqual(listings.relevance(self.IT, registry(keywords="subjective tinnitus"))[:2], (True, 2))
        self.assertEqual(listings.relevance(self.IT, registry(extra="PRIMARY OUTCOME 1: Tinnitus severity | time frame: 12 weeks\n"))[:2], (True, 2))
        self.assertEqual(listings.relevance({"id": "ctgov-NCT1", "title": "Tinnitus device trial"}, registry())[:2], (True, 2))

    def test_five_mentions_is_tier_3_and_fewer_are_passing_mentions(self):
        self.assertEqual(listings.relevance(self.IT, registry(extra="tinnitus tinnitus tinnitus tinnitus tinnitus\n"))[:2], (True, 3))
        for extra in ("Exclusion: toxicity (perioral numbness, tinnitus, seizure)\n", "SECONDARY OUTCOME 3: Tinnitus Handicap Inventory\n", "tinnitus tinnitus tinnitus tinnitus\n", ""):
            self.assertFalse(listings.relevance(self.IT, registry(extra=extra))[0], extra)


class InProcess(unittest.TestCase):
    def test_pubmed_is_decided_before_any_fetch_and_registry_records_after_it(self):
        loose = pubmed_item(81, "Intratympanic gentamicin for vertigo", source="J")
        loose["triage"] = {**FACTS_PASSING, "tinAbs": 2, "tracked": ["intratympanic"]}
        trial = ctgov_item("NCT09999992", "2026-10-20", "Pain after hip surgery", summary="Trial update - status: RECRUITING.")
        text = ("SOURCE: x\nRECORD COMPLETENESS: COMPLETE - nothing was left out\nCRITICAL SECTIONS MISSING: no\n---\n" f"Title: {trial['title']}\nNCT ID: NCT09999992\nConditions: Pain\nEXCLUSION: tinnitus, seizure\n")
        fetched = []

        def fetch(it):
            fetched.append(it["id"])
            return text

        out, counts = listings.process([loose, trial], {"items": []}, today="2026-11-01", fetch_context=fetch, record_meta=lambda i: {"completeness": "COMPLETE"})
        self.assertEqual((counts, out["items"]), ({"screenedOut": 2}, []))
        self.assertEqual(fetched, [trial["id"]])
        self.assertIn("passing mention", loose["listed"]["reason"]); self.assertIn("registry record", trial["listed"]["reason"])

    def test_the_tier_on_a_listing_is_the_relevance_tier(self):
        a = pubmed_item(82, "Tinnitus counselling", source="J"); a["triage"] = {**FACTS_PASSING, "tinAbs": 5, "tinMesh": True}
        b = pubmed_item(83, "Hearing outcomes in older adults", source="J"); b["triage"] = {**FACTS_PASSING, "tinAbs": 4}
        texts = {}
        for it in (a, b):
            raw = f"1. J. 2026.\n\n{it['title']}\n\nPMID: {it['id'].split('-')[1]}\n"
            texts[it["id"]] = registry_record.finish_pubmed_record(raw, it["id"].split("-")[1])
        metas = {}

        def fetch(it):
            t, m = texts[it["id"]]
            metas[it["id"]] = m
            return t

        out, counts = listings.process([a, b], {"items": []}, today="2026-11-01", fetch_context=fetch, record_meta=lambda i: metas.pop(i, None))
        self.assertEqual({e["key"]: e["tier"] for e in out["items"]}, {"PMID 82": 2, "PMID 83": 3})


if __name__ == "__main__":
    unittest.main()

"""Tests for the refinements on branch phase3-ops: deterministic Level 3 triggers, usage accounting, non-English abstract flag, plural 'senior authors', outcome-domain stems.
Offline: no network, no key."""
import copy, importlib.util, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import escalation, grounding, registry_record  # noqa: E402

NOABS = (FIX / "pubmed_no_abstract_42706196.txt").read_text(encoding="utf-8")


def cases():
    spec = importlib.util.spec_from_file_location("rb_p3", ENGINE / "run_benchmark.py")
    m = importlib.util.module_from_spec(spec)
    old, sys.argv = sys.argv, ["x"]
    try:
        spec.loader.exec_module(m)
    finally:
        sys.argv = old
    return m.CASES


class EscalationTriggers(unittest.TestCase):
    def kinds(self, title, text, ev=None, tracked=("acupuncture",)):
        return [(e["tier"], e["kind"]) for e in escalation.triggers({"title": title}, text, ev or {}, tracked)]

    def test_the_seizure_vignette_triggers_level_3(self):
        self.assertIn(("level3", "safety-term"), self.kinds("Benchmark vignette C6", cases()["C6"]))

    def test_strong_terms_and_their_negation(self):
        self.assertIn(("level3", "safety-term"), self.kinds("t", "Two patients developed anaphylaxis after the injection."))
        self.assertIn(("level3", "safety-term"), self.kinds("t", "The regulator issued a safety communication."))
        self.assertNotIn(("level3", "safety-term"), self.kinds("t", "No seizures were reported and there were no serious adverse events."))

    def test_memory_recall_is_not_a_product_recall(self):
        self.assertEqual(self.kinds("t", "Immediate recall was worse in the hearing-loss group."), [])
        self.assertIn(("level3", "safety-term"), self.kinds("t", "The manufacturer announced a voluntary recall of the device."))

    def test_weak_terms_are_flags_only(self):
        k = self.kinds("t", "Mortality and adverse events were recorded in the registry.")
        self.assertEqual(k, [("flag", "weak-safety-term")])

    def test_evidence_bearing_on_a_tracked_treatment_is_level_3(self):
        self.assertIn(("level3", "bears-on-tracked-treatment"), self.kinds("t", "x", {"evidenceDirection": "weakens", "affectedTreatment": "acupuncture"}))
        self.assertEqual(self.kinds("t", "x", {"evidenceDirection": "no-meaningful-change", "affectedTreatment": "acupuncture"}), [])
        self.assertEqual(self.kinds("t", "x", {"evidenceDirection": "weakens", "affectedTreatment": "none"}), [])

    def test_the_real_phase2_items_do_not_trigger_level_3(self):
        raw = fixture("sources_raw.json")
        for k in ("pubmed-42839938", "pubmed-42867641", "pubmed-42865451", "pubmed-42821511"):
            es = escalation.triggers({"title": ""}, raw[k], {}, ())
            self.assertFalse([e for e in es if e["tier"] == "level3"], k)


class CycleHoldsLevel3(unittest.TestCase):
    def test_a_safety_term_in_the_record_forces_a_hold_even_in_publish_mode(self):
        item = pubmed_item(90000041, "A device study")
        rec = {item["id"]: registry_record.finish_pubmed_record("PMID: 90000041\n" + "Three patients had a first-time seizure within hours of using the device. " * 12, "90000041")[0]}
        r = run_scenario({"queue": [item], "records": rec, "settings": {"enabled": True, "mode": "publish", "limitPerRun": 5}, "runs": [{}]})["runs"][0]
        self.assertEqual(r["held"], [item["id"]])
        self.assertIn("Level 3 trigger", r["heldReasons"][item["id"]])
        self.assertEqual([x for x in r["reportItems"] if x["identifier"]], [])

    def test_a_tracked_treatment_direction_forces_a_hold(self):
        item = pubmed_item(90000042, "An acupuncture trial")
        ev = {item["id"]: {"evidenceDirection": "strengthens", "affectedTreatment": "acupuncture"}}
        r = run_scenario({"queue": [item], "evaluations": ev, "settings": {"enabled": True, "mode": "publish", "limitPerRun": 5}, "runs": [{}]})["runs"][0]
        self.assertEqual(r["held"], [item["id"]]); self.assertIn("bears-on-tracked-treatment", r["heldReasons"][item["id"]])


class UsageAccounting(unittest.TestCase):
    def test_tokens_and_estimated_cost_reach_the_status_block(self):
        items = [pubmed_item(90000051), pubmed_item(90000052), pubmed_item(90000053)]
        r = run_scenario({"queue": items, "tokensIn": 11000, "tokensOut": 2300, "settings": {"enabled": True, "mode": "staged", "limitPerRun": 10}, "runs": [{}]})["runs"][0]
        u = r["status"]["evaluation"]["usage"]
        self.assertEqual((u["inputTokens"], u["outputTokens"], u["model"]), (33000, 6900, "claude-opus-5"))
        self.assertAlmostEqual(u["estimatedCostUSD"], round(3 * (11000 * 5 + 2300 * 25) / 1e6, 4), places=4)   # $0.3375 at Opus 5 list price


class NonEnglishAbstract(unittest.TestCase):
    def test_a_publisher_supplied_chinese_abstract_is_flagged_and_caps_confidence(self):
        text, meta = registry_record.finish_pubmed_record(NOABS, "42706196")
        self.assertTrue(meta["nonEnglishAbstract"])
        ev = {"confidence": "high", "whatIsNew": "x"}
        sc = grounding.source_checks({"id": "pubmed-42706196", "title": "t", "summary": ""}, ev, text + " PMID: 42706196", meta, [])
        self.assertTrue(sc["nonEnglishAbstract"])
        self.assertEqual(grounding.clamp_confidence(ev, sc), "moderate")

    def test_an_english_record_is_not_flagged(self):
        raw = fixture("sources_raw.json")["pubmed-42839938"]
        self.assertFalse(registry_record.finish_pubmed_record(raw, "42839938")[1]["nonEnglishAbstract"])


class CheckRefinements(unittest.TestCase):
    def test_plural_senior_authors_is_caught(self):
        ev = {"conflictOfInterest": "independent - two senior authors declare unrelated honoraria"}
        self.assertEqual([t["term"] for t in grounding.unsupported_terms(ev, "the record names no roles")], ["senior authors"])
        self.assertEqual(grounding.unsupported_terms(ev, "Note: two senior authors declare honoraria"), [])

    def test_outcome_domain_stems_match_the_records_own_words(self):
        self.assertEqual(grounding.ungrounded_domain_terms({"weeklyTitle": "Bothersome tinnitus linked to more depression"}, "higher depressive symptoms (PHQ-9)"), [])
        self.assertEqual(len(grounding.ungrounded_domain_terms({"whyMatters": "It matters for quality of life."}, "everyday functioning")), 1)


if __name__ == "__main__":
    unittest.main()

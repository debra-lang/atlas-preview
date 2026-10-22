"""Tests for the deterministic evidence-adequacy backstop (engine/grounding.evidence_adequacy / apply_adequacy) and its place in the publication gate.
Offline: no key, no network. The model's own answer is never trusted for this check; the RECORD text decides."""
import copy, itertools, json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import grounding, registry_record, weekly_cycle, run_benchmark as rb  # noqa: E402

HEADER_OK = "SOURCE: PubMed abstract record (NCBI efetch, text format)\nRECORD COMPLETENESS: COMPLETE - nothing was left out\nCRITICAL SECTIONS MISSING: no\n---\n"
S_CUE = "The sample comprised 83 participants."                       # sample size
D_CUE = "Methods: a randomized, double-blind design with a primary outcome questionnaire."   # design / endpoint wording
R_CUE = "The mean score fell by 6.5 points (95% CI 2.1 to 10.9; p=0.004)."                   # result figures
FILLER = "Tinnitus is a common condition."
C4_TEXT = "Conference abstract (no full paper): 'A new neuromodulation approach shows promise in tinnitus patients, with meaningful improvements observed after treatment.'"


def item(kind="study", pubtypes=None, n=90000009):
    it = {"id": f"pubmed-{n}", "kind": kind, "title": "A tinnitus report", "url": f"https://pubmed.ncbi.nlm.nih.gov/{n}/"}
    if pubtypes is not None:
        it["pubtypes"] = pubtypes
    return it


def rec(*parts, n=90000009):
    return HEADER_OK + f"Title: A tinnitus report\n" + "\n".join(parts) + f"\nPMID: {n}"


def ev(**kw):
    e = {"relevanceCategory": 1, "notRelevant": False, "affectedTreatment": "cbt", "studyType": "RCT", "studyQuality": "moderate", "sampleSize": "Not reported", "primaryEndpoint": "Not reported",
         "numericalResult": "none reported", "loudnessEffect": "none - not measured", "distressEffect": "none", "changeClass": "routine", "factuallyVerified": True, "confidence": "high",
         "importance": "Does Not Change Current Evidence", "evidenceDirection": "no-meaningful-change"}
    e.update(kw)
    return e


def level(it, e, text):
    return grounding.evidence_adequacy(it, e, text)


class CueCombinations(unittest.TestCase):
    def test_all_eight_combinations_of_sample_design_and_results(self):
        expect = {0: "insufficient", 1: "thin", 2: "adequate", 3: "adequate"}
        for combo in itertools.product([False, True], repeat=3):
            parts = [FILLER] + [c for flag, c in zip(combo, (S_CUE, D_CUE, R_CUE)) if flag]
            r = level(item(), ev(), rec(*parts))
            self.assertEqual(r["level"], expect[sum(combo)], combo)
            self.assertEqual((r["cues"]["sampleSize"], r["cues"]["design"], r["cues"]["results"]), combo)
            self.assertEqual(r["adequate"], sum(combo) > 0)                              # only a record with none of the three fails closed

    def test_the_c4_vignette_is_insufficient_and_the_other_frozen_vignettes_are_not_blocked(self):
        out = {c: level(item(), {"studyType": "other"}, t)["level"] for c, t in rb.CASES.items()}
        self.assertEqual(out["C4"], "insufficient")
        self.assertTrue(all(v != "insufficient" for c, v in out.items() if c != "C4"), out)   # C1-C3, C5-C8 keep their behaviour

    def test_completeness_header_words_are_not_study_specifics(self):
        r = level(item(), ev(), HEADER_OK + "PMID: 90000009")                                # nothing but the machine header and an identifier
        self.assertEqual(r["level"], "insufficient")
        self.assertEqual(level(item(), ev(), HEADER_OK + "PMID: 90000009 Record id 90000009 records")["level"], "insufficient")   # an id followed by 'records' is not a sample size

    def test_cues_that_appear_only_inside_the_machine_header_do_not_count(self):
        text = "SOURCE: PubMed abstract record\nRECORD COMPLETENESS: COMPLETE - 83 participants were randomized, mean fell by 6.5 points, p=0.01\nCRITICAL SECTIONS MISSING: no\n---\nPMID: 90000009"
        self.assertEqual(level(item(), ev(), text)["level"], "insufficient")

    def test_word_numbers_and_citation_digits_do_not_fake_a_sample(self):
        self.assertFalse(level(item(), ev(), rec("Hear Res. 2026 Sep;12(3):45-50. doi:10.1000/xyz"))["cues"]["sampleSize"])


class ModelClaimsVersusRecord(unittest.TestCase):
    def gate(self, e, text, it=None):
        it = dict(it or item(), evaluation=e)
        sc = grounding.source_checks(it, e, text, {"completeness": "COMPLETE"}); e["sourceChecks"] = sc; grounding.clamp_confidence(e, sc); grounding.apply_adequacy(e, sc)
        return grounding.source_checks_pass(e), sc

    def test_invented_numbers_are_refused_by_the_gate_through_the_existing_grounding_check_or_the_adequacy_check(self):
        (ok, why), sc = self.gate(ev(sampleSize="60 participants"), rec(FILLER, D_CUE))                 # design cue only (thin) + invented sample size
        self.assertFalse(ok); self.assertIn("numbers", why)
        (ok, why), sc = self.gate(ev(numericalResult="mean fall 6.5 points"), rec(FILLER, S_CUE, D_CUE))   # result invented
        self.assertFalse(ok); self.assertIn("numbers", why)
        (ok, why), sc = self.gate(ev(sampleSize="60 participants"), rec(FILLER))                        # data-free record + invented sample size: refused (numbers come first)
        self.assertFalse(ok)
        self.assertEqual(sc["evidenceAdequacy"]["level"], "insufficient")                              # and the adequacy check independently fails it
        (ok, _), _ = self.gate(ev(sampleSize="83 participants", numericalResult="fell by 6.5 points"), rec(S_CUE, D_CUE, R_CUE))
        self.assertTrue(ok)

    def test_a_qualitative_result_and_a_spelled_out_sample_are_not_misread_as_fabrication(self):
        # regression from the earlier real benchmark answers: C8 (n=12 per group, result described in words) and C6 (three patients) must not be held by the backstop
        c8 = "Preclinical study in a mouse noise-exposure model: compound R eliminated behavioral evidence of tinnitus in treated animals versus controls (n=12 per group). No human data."
        r = level(item(), ev(sampleSize="n=12 per group", numericalResult="n=12 per group; compound R 'eliminated behavioral evidence of tinnitus'", studyType="other"), rec(c8))
        self.assertTrue(r["adequate"], r)
        c6 = "Case series and regulator notice: three patients experienced first-time seizures within hours of using consumer neurostimulation device Q for tinnitus."
        r = level(item(), ev(sampleSize="3", numericalResult="Three patients experienced first-time seizures", studyType="regulatory record"), rec(c6))
        self.assertTrue(r["cues"]["sampleSize"]); self.assertTrue(r["adequate"], r)

    def test_missing_variations_in_the_models_fields_do_not_decide_adequacy(self):
        for v in ("Not reported", "none reported", "N/A", "Unable to verify", "", None, "Not stated in the record"):
            r = level(item(), ev(sampleSize=v, primaryEndpoint=v, numericalResult=v), rec(S_CUE, D_CUE, R_CUE))
            self.assertEqual(r["level"], "adequate", v)                                       # the record has the specifics, so 'Not reported' answers do not block it
            r = level(item(), ev(sampleSize=v, primaryEndpoint=v, numericalResult=v), rec(FILLER))
            self.assertEqual(r["level"], "insufficient", v)                                   # and the record without them fails whatever the fields say

    def test_a_benefit_asserted_with_no_result_figure_is_insufficient_even_with_a_sample_and_a_design_word(self):
        promo = rec("In this randomized trial of 40 patients, the device showed meaningful improvements.")
        self.assertEqual(level(item(), ev(distressEffect="none"), promo)["level"], "adequate")        # model claims no effect: nothing to verify
        for f in ("loudnessEffect", "distressEffect"):
            for lv in ("limited", "moderate", "strong"):
                r = level(item(), ev(**{f: lv + " - patients improved"}), promo)
                self.assertFalse(r["adequate"], (f, lv)); self.assertTrue(any("no result figure" in x for x in r["reasons"]))
        self.assertTrue(level(item(), ev(distressEffect="limited - fell by 6.5 points"), rec(S_CUE, D_CUE, R_CUE))["adequate"])   # with figures it is fine


class IncompleteRecords(unittest.TestCase):
    def test_header_only_cut_off_and_very_short_records_fail_closed(self):
        for text in (HEADER_OK, rec(), rec("Tinnitus"), rec("Background: tinnitus affects many people. Methods:"), rec("Results: improvement was"),
                     HEADER_OK.replace("COMPLETE - nothing", "TRUNCATED - 5000 characters at the end were not shown") + "PMID: 90000009"):
            self.assertFalse(level(item(), ev(), text)["adequate"], text[:60])

    def test_a_partly_cut_abstract_that_still_has_two_cues_is_adequate_here_and_blocked_by_the_completeness_gate_instead(self):
        text = HEADER_OK.replace("COMPLETE - nothing", "TRUNCATED - 900 characters at the end were not shown").replace("CRITICAL SECTIONS MISSING: no", "CRITICAL SECTIONS MISSING: yes") + "Title: x\n" + S_CUE + " " + D_CUE
        self.assertTrue(level(item(), ev(), text)["adequate"])
        sc = grounding.source_checks(item(), ev(), text, {"completeness": "TRUNCATED", "criticalOmitted": True})
        self.assertFalse(grounding.source_checks_pass({"sourceChecks": sc})[0])              # the existing completeness gate still blocks it


class PrimaryVersusReview(unittest.TestCase):
    DATA_FREE_REVIEW = rec("This article discusses mechanisms of sensory gating and how the auditory striatum may integrate input.")

    def test_pubmed_publication_types_exempt_reviews_cases_commentary_and_notices(self):
        for pt, why in ((["Journal Article", "Review"], "review"), (["Systematic Review"], "review"), (["Meta-Analysis"], "review"), (["Case Reports"], "case report"),
                        (["Editorial"], "commentary"), (["Letter"], "commentary"), (["Published Erratum"], "notice"), (["Practice Guideline"], "review")):
            r = level(item(pubtypes=pt), ev(), self.DATA_FREE_REVIEW)
            self.assertEqual((r["level"], r["exemptReason"]), ("exempt", why), pt)

    def test_the_same_data_free_text_without_a_review_publication_type_is_primary_and_fails(self):
        self.assertEqual(level(item(pubtypes=["Journal Article"]), ev(), self.DATA_FREE_REVIEW)["level"], "insufficient")
        self.assertEqual(level(item(), ev(studyType="RCT"), self.DATA_FREE_REVIEW)["level"], "insufficient")

    def test_the_model_label_alone_never_exempts(self):
        r = level(item(), ev(studyType="narrative review"), rec("A new approach shows promise in tinnitus patients, with meaningful improvements."))   # data-free promotional text, mislabelled
        self.assertEqual(r["level"], "insufficient")
        r = level(item(), ev(studyType="narrative review"), rec("This narrative review discusses mechanisms of tinnitus and treatment options."))   # label plus corroborating text
        self.assertEqual((r["level"], r["exemptReason"]), ("exempt", "review"))
        r = level(item(), ev(studyType="protocol"), rec("Study protocol: we will randomise adults to two arms."))
        self.assertEqual(r["exemptReason"], "protocol")
        self.assertEqual(level(item(), ev(studyType="protocol"), rec(FILLER))["level"], "insufficient")   # 'protocol' with nothing to corroborate it

    def test_an_exempt_type_cannot_hide_invented_numbers_the_gate_still_refuses_them(self):
        e = ev(sampleSize="60 participants", numericalResult="fell by 6.5")
        it = dict(item(pubtypes=["Review"]), evaluation=e)
        sc = grounding.source_checks(it, e, self.DATA_FREE_REVIEW, {"completeness": "COMPLETE"}); e["sourceChecks"] = sc
        self.assertEqual(sc["evidenceAdequacy"]["level"], "exempt")                                    # reviews are exempt from the cue requirement ...
        ok, why = grounding.source_checks_pass(e)
        self.assertFalse(ok); self.assertIn("numbers", why)                                            # ... but never from the grounding check

    def test_only_study_items_are_assessed(self):
        for kind in ("trial", "regulatory", "news"):
            r = level(item(kind=kind), ev(), HEADER_OK + "nothing")
            self.assertEqual((r["applies"], r["level"], r["adequate"]), (False, "not-applicable", True), kind)

    def test_real_public_abstracts(self):
        fx = json.loads((FIX / "adequacy_real_abstracts.json").read_text(encoding="utf-8"))
        expect = {"42788144": "adequate", "42654475": "adequate", "42730729": "adequate", "42710361": "adequate", "42766619": "adequate",     # primary studies with specifics
                  "42716330": "exempt", "42870902": "exempt", "42706196": "exempt", "42900640": "exempt", "42894823": "exempt",                 # reviews and case reports by PubMed type
                  "42787500": "adequate"}                                                                                                         # two-case report, no pubtype tag: "two cases" is a sample, plus a design cue
        for pmid, want in expect.items():
            f = fx[pmid]
            it = {"id": "pubmed-" + pmid, "kind": "study", "title": f["title"], "pubtypes": f["pubtypes"]}
            self.assertEqual(grounding.evidence_adequacy(it, {"studyType": "other"}, HEADER_OK + f["abstract"])["level"], want, pmid)


class FailClosedGate(unittest.TestCase):
    def good_checks(self):
        return copy.deepcopy(grounding.PASSING_CHECKS)

    def test_the_gate_requires_a_positive_assessment(self):
        sc = self.good_checks()
        self.assertTrue(grounding.source_checks_pass({"sourceChecks": sc})[0])
        old = self.good_checks(); old.pop("evidenceAdequacy"); old["version"] = 1                       # an evaluation made before the check existed
        ok, why = grounding.source_checks_pass({"sourceChecks": old}); self.assertFalse(ok); self.assertIn("not assessed", why)
        for bad in ({}, {"assessed": False, "adequate": True}, {"assessed": True}, {"assessed": True, "adequate": "yes"}, {"assessed": True, "adequate": None}, {"assessed": True, "adequate": False, "reasons": ["x"]}, "adequate", None, []):
            sc = self.good_checks(); sc["evidenceAdequacy"] = bad
            self.assertFalse(grounding.source_checks_pass({"sourceChecks": sc})[0], bad)

    def test_apply_adequacy_overrides_the_model_and_keeps_its_original_answer(self):
        e = ev(factuallyVerified=True, confidence="high")
        sc = grounding.source_checks(item(), e, rec(FILLER), {"completeness": "COMPLETE"})
        grounding.clamp_confidence(e, sc)
        self.assertTrue(grounding.apply_adequacy(e, sc))
        self.assertEqual((e["factuallyVerified"], e["factuallyVerifiedModel"], e["confidence"], e["confidenceModel"]), (False, True, "low", "high"))
        self.assertIn("no sample size", e["evidenceAdequacyNote"])
        e2 = ev(factuallyVerified=True, confidence="high")
        sc2 = grounding.source_checks(item(), e2, rec(S_CUE, D_CUE, R_CUE), {"completeness": "COMPLETE"}); grounding.clamp_confidence(e2, sc2)
        self.assertFalse(grounding.apply_adequacy(e2, sc2)); self.assertTrue(e2["factuallyVerified"]); self.assertEqual(e2["confidence"], "high")


class PublicationGate(unittest.TestCase):
    """The real Cycle.route(): a data-free promotional abstract is held even when the model says verified with moderate or high confidence."""

    def routed(self, e, text, extra_item=None):
        it = dict(item(), evaluation=e, evalInput={"hasResults": None}); it.update(extra_item or {})
        sc = grounding.source_checks(it, e, text, {"completeness": "COMPLETE"})
        e["sourceChecks"] = sc; grounding.clamp_confidence(e, sc); grounding.apply_adequacy(e, sc)
        return weekly_cycle.Cycle(REPO).route(it, set(), set())

    def test_data_free_promotional_abstract_is_held_whatever_the_model_says(self):
        for conf in ("moderate", "high"):
            r, why = self.routed(ev(factuallyVerified=True, confidence=conf), rec(C4_TEXT))
            self.assertEqual(r, "hold", conf); self.assertIn("insufficient to verify", why)

    def test_the_same_model_answer_on_a_record_with_specifics_publishes(self):
        r, _ = self.routed(ev(factuallyVerified=True, confidence="moderate"), rec(S_CUE, D_CUE, R_CUE))
        self.assertEqual(r, "publish")

    def test_a_possible_major_change_on_a_data_free_record_is_held_not_published_under_evaluation(self):
        r, _ = self.routed(ev(factuallyVerified=True, confidence="high", changeClass="major"), rec(C4_TEXT))
        self.assertEqual(r, "hold")
        r, _ = self.routed(ev(factuallyVerified=True, confidence="high", changeClass="major"), rec(S_CUE, D_CUE, R_CUE))
        self.assertEqual(r, "publish-under-eval")                                             # control: with specifics the old behaviour is unchanged

    def test_earlier_specific_messages_keep_precedence(self):
        e = ev(factuallyVerified=True, confidence="high", numericalResult="fell by 12.3 points")
        r, why = self.routed(e, rec(S_CUE, D_CUE))                                            # ungrounded number: the number message comes first
        self.assertEqual(r, "hold"); self.assertTrue("numbers" in why or "numerical" in why or "insufficient" in why)

    def test_registry_regulatory_and_news_items_are_not_affected(self):
        e = ev(factuallyVerified=True, confidence="high")
        for kind, iid in (("trial", "ctgov-NCT01234567-2026-10-13"), ("regulatory", "fda-510-k-clearance-k260413"), ("news", "newsintel-x")):
            sc = grounding.source_checks({"id": iid, "kind": kind, "title": "x", "url": "u"}, e, "SOURCE: x\nRECORD COMPLETENESS: COMPLETE - ok\nCRITICAL SECTIONS MISSING: no\n---\nNCT ID: NCT01234567", {"completeness": "COMPLETE"})
            self.assertEqual(sc["evidenceAdequacy"]["level"], "not-applicable", kind)      # their completeness and source gates are unchanged


class EndToEndScenario(unittest.TestCase):
    """Full cycle in PUBLISH mode with a fake model that says 'verified, high' about everything."""

    def spec(self, mode):
        free = registry_record.finish_pubmed_record("PMID: 90000071\nTitle: Promotional abstract\n" + C4_TEXT, "90000071")[0]
        good = registry_record.finish_pubmed_record("PMID: 90000072\nTitle: Data-bearing abstract\n" + "\n".join((S_CUE, D_CUE, R_CUE)), "90000072")[0]
        return {"queue": [pubmed_item(90000071, "Promotional abstract"), pubmed_item(90000072, "Data-bearing abstract")],
                "records": {"pubmed-90000071": free, "pubmed-90000072": good}, "settings": {"enabled": True, "mode": mode, "limitPerRun": 5}, "runs": [{}]}

    def test_data_free_record_is_never_published_in_publish_mode_and_is_held_with_the_reason(self):
        run = run_scenario(self.spec("publish"))["runs"][0]
        ids = [x["identifier"] for x in run["reportItems"]]
        self.assertNotIn("pubmed-90000071", ids); self.assertIn("pubmed-90000072", ids)    # the control item with specifics DOES publish
        self.assertIn("pubmed-90000071", run["held"]); self.assertIn("insufficient to verify", run["heldReasons"]["pubmed-90000071"])
        self.assertNotIn("pubmed-90000072", run["held"])
        self.assertTrue(run["ratingsUnchanged"] and run["studiesUnchanged"])

    def test_in_staged_mode_the_data_free_record_is_proposed_as_hold_never_as_publish(self):
        run = run_scenario(self.spec("staged"))["runs"][0]
        self.assertTrue(all(x["identifier"] is None for x in run["reportItems"]))        # staged: no study is public (only the generic "awaiting editorial review" line)
        self.assertEqual(run["staged"]["pubmed-90000071"]["route"], "hold")                # the owner is never offered it as a publication
        self.assertEqual(run["staged"]["pubmed-90000072"]["route"], "publish")
        self.assertIn("insufficient to verify", run["staged"]["pubmed-90000071"]["reason"])


class ScanCapturesPublicationTypes(unittest.TestCase):
    def test_scan_pubmed_stores_pubmed_publication_types_on_each_item(self):
        import weekly_scan
        calls = []

        def fake_get_json(url):
            calls.append(url)
            if "esearch" in url:
                return {"esearchresult": {"count": "2", "idlist": ["90000081", "90000082"]}}
            return {"result": {"uids": ["90000081", "90000082"],
                               "90000081": {"title": "A review of tinnitus", "pubtype": ["Journal Article", "Review"], "fulljournalname": "J", "pubdate": "2026 Oct"},
                               "90000082": {"title": "A trial", "pubdate": "2026 Oct"}}}
        orig, orig_sleep = weekly_scan.get_json, weekly_scan.time.sleep
        weekly_scan.get_json, weekly_scan.time.sleep = fake_get_json, lambda *_: None
        try:
            items = weekly_scan.scan_pubmed()
        finally:
            weekly_scan.get_json, weekly_scan.time.sleep = orig, orig_sleep
        self.assertEqual({i["id"]: i["pubtypes"] for i in items}, {"pubmed-90000081": ["Journal Article", "Review"], "pubmed-90000082": []})


class ReviewPacketShowsBothQuestions(unittest.TestCase):
    def test_the_reviewer_sees_evidence_adequacy_separately_from_the_models_answer(self):
        import staged_review
        e = ev(factuallyVerified=True, confidence="high")
        it = dict(item(), evaluation=e, evalInput={})
        sc = grounding.source_checks(it, e, rec(C4_TEXT), {"completeness": "COMPLETE"}); e["sourceChecks"] = sc; grounding.clamp_confidence(e, sc); grounding.apply_adequacy(e, sc)
        entry = staged_review.make_entry(it, "hold", "not sufficiently verified", {"title": "x"}, now="2026-10-26T06:10:00")
        page = staged_review.render_review({"items": [entry]})
        self.assertIn("adequacy of the EVIDENCE in the record", page); self.assertIn("insufficient", page); self.assertIn("overridden to false", page)
        good = ev(factuallyVerified=True, confidence="high")
        it2 = dict(item(), evaluation=good, evalInput={})
        sc2 = grounding.source_checks(it2, good, rec(S_CUE, D_CUE, R_CUE), {"completeness": "COMPLETE"}); good["sourceChecks"] = sc2; grounding.clamp_confidence(good, sc2); grounding.apply_adequacy(good, sc2)
        page2 = staged_review.render_review({"items": [staged_review.make_entry(it2, "publish", "ok", {"title": "x"}, now="2026-10-26T06:10:00")]})
        self.assertIn("EVIDENCE in the record (a separate question from whether the report is faithful to it): adequate", page2); self.assertNotIn("overridden", page2)


if __name__ == "__main__":
    unittest.main()

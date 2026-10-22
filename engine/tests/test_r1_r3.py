"""Tests for R1 (FDA record + regulatory items held), R2 (high-impact study on a tracked treatment held), R3 (advice to the reader), ISO-date grounding and the publication-type lookup.
Offline: no key, no network (HTTP is stubbed)."""
import copy, json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import escalation, evaluate_queue, fda_record, grounding, registry_record, weekly_cycle  # noqa: E402

FDA = json.loads((FIX / "fda_510k_K260413.json").read_text(encoding="utf-8"))["results"][0]
HEADER = "SOURCE: x\nRECORD COMPLETENESS: COMPLETE - nothing was left out\nCRITICAL SECTIONS MISSING: no\n---\n"
TRACKED = {"cbt", "tavns", "digital-cbt"}


def ev(**kw):
    e = {"relevanceCategory": 1, "notRelevant": False, "affectedTreatment": "none", "studyType": "cohort", "studyQuality": "moderate", "sampleSize": "Not reported", "primaryEndpoint": "Not reported",
         "numericalResult": "none reported", "loudnessEffect": "none", "distressEffect": "none", "changeClass": "routine", "factuallyVerified": True, "confidence": "high",
         "importance": "Does Not Change Current Evidence", "evidenceDirection": "no-meaningful-change", "weeklyTitle": "A study", "whyMatters": "It describes a cohort.", "whatIsNew": "A cohort study."}
    e.update(kw)
    return e


def kinds(item, e, rec="", tracked=TRACKED):
    return sorted(t["kind"] for t in escalation.triggers(item, rec, e, tracked) if t["tier"] == "level3")


class R1FdaRecord(unittest.TestCase):
    def test_the_record_carries_the_decision_date_and_the_item_date_comes_from_it(self):
        text, meta = fda_record.build_510k_record(FDA)
        self.assertIn("Decision date: 2026-08-13", text); self.assertIn("510(k) number: K260413", text); self.assertIn("Levo Medical Corporation", text)
        self.assertNotIn("2026-09-04", text)
        self.assertEqual((meta["completeness"], meta["criticalOmitted"], meta["itemDate"]), ("COMPLETE", False, "2026-08-13"))
        self.assertEqual(registry_record.parse_header(text)["completeness"], "COMPLETE")

    def test_fetch_context_builds_the_record_from_the_database_and_refuses_a_mismatch(self):
        item = {"id": "fda-510-k-clearance-k260413", "kind": "regulatory", "url": "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID=K260413", "date": "2026-09-04"}
        orig = evaluate_queue._get
        try:
            evaluate_queue._get = lambda url, attempts=3: json.dumps({"results": [FDA]}).encode()
            text = evaluate_queue.fetch_context(item)
            self.assertIn("Decision date: 2026-08-13", text); self.assertEqual(evaluate_queue.RECORD_META[item["id"]]["itemDate"], "2026-08-13")
            evaluate_queue._get = lambda url, attempts=3: json.dumps({"results": [dict(FDA, k_number="K111111")]}).encode()
            text = evaluate_queue.fetch_context(item)
            self.assertIn("UNAVAILABLE", text); self.assertIsNone(evaluate_queue.RECORD_META[item["id"]].get("itemDate"))      # wrong record: no date, no facts
            def boom(url, attempts=3): raise OSError("down")
            evaluate_queue._get = boom
            self.assertIn("UNAVAILABLE", evaluate_queue.fetch_context(item))
        finally:
            evaluate_queue._get = orig

    def test_a_date_the_record_does_not_contain_is_refused_the_detection_date_in_particular(self):
        text, meta = fda_record.build_510k_record(FDA)
        it = {"id": "fda-510-k-clearance-k260413", "kind": "regulatory", "title": "FDA 510(k) decision: Levo Gen 2", "date": "2026-08-13", "url": "https://www.accessdata.fda.gov/x?ID=K260413"}
        bad = ev(whatIsNew="received a Substantially Equivalent decision (K260413) on 2026-09-04.")
        sc = grounding.source_checks(it, bad, text, meta)
        self.assertEqual([d["date"] for d in sc["ungroundedDates"]], ["2026-09-04"]); self.assertFalse(sc["ok"])
        bad["sourceChecks"] = sc; self.assertFalse(grounding.source_checks_pass(bad)[0])
        only = ev(whatIsNew="Decision on 2026-09-04.")
        sc2 = grounding.source_checks(it, only, text, meta); only["sourceChecks"] = sc2
        self.assertFalse(grounding.source_checks_pass(only)[0]); self.assertEqual([d["date"] for d in sc2["ungroundedDates"]], ["2026-09-04"])   # refused (the number check also sees the digits)
        text2 = text + "Note: 2026, 09 and 04 appear separately.\n"                                      # digits present elsewhere, so the number check alone would pass: the date check still catches it
        sc3 = grounding.source_checks(it, only, text2, meta); only["sourceChecks"] = sc3
        self.assertEqual(sc3["ungroundedNumbers"], []); self.assertFalse(sc3["ok"])      # only the date check can have failed here
        self.assertEqual(grounding.source_checks_pass(only), (False, "dates in the evaluation were not found in the source record"))
        good = ev(whatIsNew="received a Substantially Equivalent decision (K260413) on 2026-08-13; received 2026-02-09.")
        self.assertEqual(grounding.source_checks(it, good, text, meta)["ungroundedDates"], [])
        grounding.clamp_confidence(bad, sc); self.assertEqual(bad["confidence"], "low")

    def test_the_items_own_date_is_an_allowed_source_for_a_date_in_the_text(self):
        it = {"id": "pubmed-90000009", "kind": "study", "title": "x", "date": "2026-10-13", "url": "u"}
        sc = grounding.source_checks(it, ev(whatIsNew="Published 2026-10-13."), HEADER + "Methods: randomized; 40 participants; mean fell 5 points (p=0.01)", {"completeness": "COMPLETE"})
        self.assertEqual(sc["ungroundedDates"], [])

    def test_every_regulatory_item_is_a_level3_trigger_and_other_kinds_are_not(self):
        self.assertEqual(kinds({"kind": "regulatory", "title": "FDA clears a device"}, ev()), ["regulatory-item"])
        for k in ("study", "trial", "news"):
            self.assertNotIn("regulatory-item", kinds({"kind": k, "title": "x"}, ev()))


class R2HighImpactStudy(unittest.TestCase):
    def test_rct_review_and_meta_analysis_on_a_tracked_treatment_hold_whatever_the_model_says(self):
        for st in ("RCT", "crossover RCT", "randomized controlled trial", "randomised trial", "meta-analysis", "Meta analysis", "systematic review", "systematic review and meta-analysis"):
            for direction in ("no-meaningful-change", "strengthens", "weakens", "unclear"):
                self.assertIn("high-impact-study-on-tracked-treatment", kinds({"kind": "study", "title": "x"}, ev(studyType=st, affectedTreatment="cbt", evidenceDirection=direction)), (st, direction))

    def test_other_study_types_untracked_treatments_and_non_randomised_studies_do_not_trigger(self):
        for st in ("cohort", "chart review", "registry update", "press release", "regulatory record", "other", "non-randomised controlled study", "nonrandomized trial", "quasi-randomized trial", "case series"):
            self.assertNotIn("high-impact-study-on-tracked-treatment", kinds({"kind": "study", "title": "x"}, ev(studyType=st, affectedTreatment="cbt")), st)
        for t in ("none", "new-treatment-candidate", "", None, "some-untracked-id"):
            self.assertNotIn("high-impact-study-on-tracked-treatment", kinds({"kind": "study", "title": "x"}, ev(studyType="RCT", affectedTreatment=t)), t)

    def test_on_the_50_september_items_it_would_have_added_exactly_one_hold(self):
        hits = []
        for w in ("2026-09-07", "2026-09-14", "2026-09-21", "2026-09-26"):
            for it in json.loads((REPO / "data" / "weekly" / f"{w}.json").read_text(encoding="utf-8"))["items"]:
                e = ev(studyType=(it.get("detail") or {}).get("studyType", ""), affectedTreatment=it.get("treatment") or "none")
                tracked = {t["id"] for t in real_treatments()}
                if "high-impact-study-on-tracked-treatment" in kinds({"kind": it["kind"], "title": it["title"]}, e, tracked=tracked):
                    hits.append(it["url"].rstrip("/").rsplit("/", 1)[-1])
        self.assertEqual(hits, ["42730729"])           # the sound-paired VNS trial; acceptance rule: stop if this ever exceeds 3


def real_treatments():
    return json.loads((REPO / "data" / "treatments.json").read_text(encoding="utf-8"))


class R3AdviceToTheReader(unittest.TestCase):
    def test_advice_addressed_to_the_reader_in_public_fields_triggers_a_hold(self):
        for f, text in (("whyMatters", "If you have pulsatile tinnitus, a normal tympanometry result should not be used as a reason to skip imaging."),
                        ("weeklyTitle", "Patients with tinnitus should stop taking the drug"), ("whatIsNew", "You should talk to your doctor before trying the device."),
                        ("whyMatters", "Do not rely on this result."), ("whyMatters", "People with tinnitus must avoid loud music.")):
            self.assertIn("advice-to-reader", kinds({"kind": "study", "title": "x"}, ev(**{f: text})), text)

    def test_negated_or_descriptive_mentions_and_internal_fields_do_not_trigger(self):
        for text in ("It tests no treatment and changes nothing about what patients should do today.", "The authors never say patients should switch treatment.",
                     "The study describes a cohort of adults.", "Clinicians should continue to pursue imaging."):
            self.assertNotIn("advice-to-reader", kinds({"kind": "study", "title": "x"}, ev(whyMatters=text)), text)
        self.assertNotIn("advice-to-reader", kinds({"kind": "study", "title": "x"}, ev(summaryForAdmin="If you have time, check this.")))          # internal field, not public text

    def test_on_the_50_september_items_it_flagged_exactly_the_tympanometry_item_as_published_and_flags_nothing_after_the_correction(self):
        log = json.loads((REPO / "data" / "corrections-log.json").read_text(encoding="utf-8"))
        before = {(f["reportDate"], f["itemUrl"], f["field"]): f["before"] for f in log["fields"]}   # the text exactly as it was first published

        def scan(published):
            hits = []
            for w in ("2026-09-07", "2026-09-14", "2026-09-21", "2026-09-26"):
                for it in json.loads((REPO / "data" / "weekly" / f"{w}.json").read_text(encoding="utf-8"))["items"]:
                    title, why, new = it["title"], it.get("whyMatters", ""), it.get("summary", "")
                    if published:
                        title = before.get((w, it["url"], "Headline"), title)
                        why = before.get((w, it["url"], "Why it matters"), why)
                        new = before.get((w, it["url"], "Summary"), new)
                    if "advice-to-reader" in kinds({"kind": it["kind"], "title": title}, ev(weeklyTitle=title, whyMatters=why, whatIsNew=new)):
                        hits.append(it["url"].rstrip("/").rsplit("/", 1)[-1])
            return hits
        self.assertEqual(scan(True), ["42788144"])      # acceptance rule: at most one false alarm in 50 as published
        self.assertEqual(scan(False), [])               # the advice addressed to patients was removed by correction C4b


class GateAndScenarios(unittest.TestCase):
    def test_level3_kinds_route_to_hold_in_the_real_router_even_when_everything_else_passes(self):
        def route(e, item_extra):
            e = copy.deepcopy(e); e["sourceChecks"] = dict(grounding.PASSING_CHECKS)
            e["escalation"] = escalation.triggers(dict({"kind": "study", "title": "x"}, **item_extra), "", e, TRACKED)
            it = {"id": "pubmed-90000009", "kind": "study", "title": "x", "url": "https://pubmed.ncbi.nlm.nih.gov/90000009/", "evaluation": e}; it.update(item_extra)
            return weekly_cycle.Cycle(REPO).route(it, set(), set())
        self.assertEqual(route(ev(), {})[0], "publish")                                                       # control: nothing triggers, it publishes
        self.assertEqual(route(ev(studyType="RCT", affectedTreatment="cbt"), {})[0], "hold")                  # R2
        self.assertEqual(route(ev(whyMatters="If you have tinnitus, you should see a doctor."), {})[0], "hold")   # R3

    def test_a_regulatory_item_never_publishes_in_publish_mode_or_staged_mode(self):
        url = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID=K999999"      # a K number the published register has not seen (K260413 is already published, so it would route as a duplicate)
        item = {"id": "fda-510-k-clearance-k999999", "kind": "regulatory", "title": "FDA 510(k) decision: Levo Gen 2 (Levo Medical Corporation) - Substantially Equivalent", "source": "openFDA", "date": "2026-09-04",
                "url": url, "summary": "x", "treatment": "", "proposal": "", "why": ""}
        text, _ = fda_record.build_510k_record(dict(FDA, k_number="K999999"))
        for mode in ("publish", "staged"):
            run = run_scenario({"queue": [item], "records": {item["id"]: text}, "settings": {"enabled": True, "mode": mode, "limitPerRun": 5}, "runs": [{}]})["runs"][0]
            self.assertTrue(all(x["identifier"] is None for x in run["reportItems"]), mode)                  # nothing about this item is public
            where = run["held"] if mode == "publish" else [k for k, v in run["staged"].items() if v["route"] == "hold"]
            self.assertIn(item["id"], where, mode)
            self.assertTrue(run["ratingsUnchanged"])


    def test_the_items_date_becomes_the_decision_date_from_the_record_not_the_day_the_scan_found_it(self):
        url = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID=K999998"
        item = {"id": "fda-510-k-clearance-k999998", "kind": "regulatory", "title": "FDA 510(k) decision: Levo Gen 2", "source": "openFDA", "date": "2026-09-04", "url": url, "summary": "x", "treatment": "", "proposal": "", "why": ""}
        text, meta = fda_record.build_510k_record(dict(FDA, k_number="K999998"))
        run = run_scenario({"queue": [item], "records": {item["id"]: text}, "recordMeta": {item["id"]: meta}, "settings": {"enabled": True, "mode": "staged", "limitPerRun": 5}, "runs": [{}]})["runs"][0]
        self.assertEqual(run["staged"][item["id"]]["itemDate"], "2026-08-13")
        run = run_scenario({"queue": [item], "records": {item["id"]: text}, "settings": {"enabled": True, "mode": "staged", "limitPerRun": 5}, "runs": [{}]})["runs"][0]
        self.assertEqual(run["staged"][item["id"]]["itemDate"], "2026-09-04")        # control: without the record's metadata the scan date stays (the test would not notice a broken assignment otherwise)


class PublicationTypeLookup(unittest.TestCase):
    ESUM = json.dumps({"result": {"uids": ["90000009"], "90000009": {"pubtype": ["Journal Article", "Review"]}}}).encode()

    def run_fetch(self, item, esummary):
        calls = []
        orig = evaluate_queue._get

        def fake(url, attempts=3):
            calls.append(url)
            if "efetch" in url:
                return b"1. J. 2026.\n\nTitle\n\nAbstract text. PMID: 90000009\n"
            if isinstance(esummary, Exception):
                raise esummary
            return esummary
        try:
            evaluate_queue._get = fake
            text = evaluate_queue.fetch_context(item)
        finally:
            evaluate_queue._get = orig
        return text, evaluate_queue.RECORD_META[item["id"]], calls

    def test_the_types_are_looked_up_once_when_the_item_has_none(self):
        text, meta, calls = self.run_fetch({"id": "pubmed-90000009", "kind": "study"}, self.ESUM)
        self.assertEqual(meta["pubtypes"], ["Journal Article", "Review"]); self.assertEqual(sum("esummary" in c for c in calls), 1)

    def test_an_item_that_already_has_types_costs_no_extra_call(self):
        text, meta, calls = self.run_fetch({"id": "pubmed-90000009", "kind": "study", "pubtypes": ["Review"]}, self.ESUM)
        self.assertEqual(sum("esummary" in c for c in calls), 0); self.assertNotIn("pubtypes", meta)

    def test_a_failed_lookup_leaves_no_exemption_and_does_not_stop_the_record(self):
        text, meta, calls = self.run_fetch({"id": "pubmed-90000009", "kind": "study"}, OSError("down"))
        self.assertEqual(meta["pubtypes"], []); self.assertIn("Abstract text", text)
        it = {"id": "pubmed-90000009", "kind": "study", "title": "x", "pubtypes": meta["pubtypes"]}
        self.assertEqual(grounding.evidence_adequacy(it, {"studyType": "other"}, HEADER + "This article discusses mechanisms.")["level"], "insufficient")   # fails closed


if __name__ == "__main__":
    unittest.main()

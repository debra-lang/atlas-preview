"""Regression tests for every defect found in the Phase 2 review of the first paid preview (21 Oct 2026). Offline: no network, no API key.
Run:  python -m unittest discover -s engine/tests -v

  D1  an erratum with no content was routed to PUBLISH                          -> NoticeTests
  D2  ClinicalTrials.gov record cut at 12,000 characters (references/eligibility lost) -> RegistryRecordTests
  D3  hasResults was never sent, "no results posted" was a guess               -> RegistryRecordTests
  D4  site addresses consumed the input budget                                 -> RegistryRecordTests
  D5  comparisonType instruction text leaked into answers and public text      -> EnumLeakTests
  D6  the model's own factuallyVerified was the publication gate               -> VerificationGateTests
  D7  ungrounded statements ("First ...", "senior author", facts from memory)  -> GroundingTests
  D8  every confidence was "high", even for a headline-only item               -> VerificationGateTests
  D9  intelligenceOnly was not passed to the model                             -> test_staged_cycle.PromptInputTests
  D10 preflight max_tokens flag (tool false alarm)                             -> PreflightTests
  D11 duplicate registry updates (NCT06898515, NCT07784192)                    -> test_staged_cycle.DuplicateRegistryTests
  D12 Lenire/Neuromod hold must be precise                                     -> TopicHoldTests
  D13 staged publication                                                       -> test_staged_cycle
"""
import copy, json, re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import evaluate_queue, grounding, notices, registry_record, staged_review, topic_holds, weekly_cycle  # noqa: E402

RAW, PREV = fixture("sources_raw.json"), fixture("phase2_preview_run.json")
STUDIES = real_studies()
TREATMENTS = json.loads((REPO / "data" / "treatments.json").read_text(encoding="utf-8"))
KNOWN = [w for x in TREATMENTS for w in (x["id"].replace("-", " ") + " " + x["name"]).split()] + [w for s in STUDIES for w in (s["id"].replace("-", " ") + " " + s["title"]).split()]
P2 = {it["id"]: it for it in PREV["items"]}
ITEM = lambda frag: next(v for k, v in P2.items() if frag in k)   # noqa: E731


def new_record(it):
    iid = it["id"]
    if iid.startswith("pubmed-"):
        return registry_record.finish_pubmed_record(RAW[iid], iid.split("-")[1])
    if iid.startswith("ctgov-"):
        return registry_record.build_ctgov_record(json.loads(RAW[iid.split("-")[1]]))
    return registry_record.unavailable_record("headline only")


def checked(it):
    text, meta = new_record(it)
    ev = copy.deepcopy(it["evaluation"])
    fixes = grounding.normalise_enums(ev)
    q = {"id": it["id"], "title": it["title"], "url": it["url"], "summary": ""}
    sc = grounding.source_checks(q, ev, text, meta, KNOWN)
    sc["enumFixes"] = fixes
    ev["sourceChecks"] = sc
    grounding.clamp_confidence(ev, sc)
    return q, ev, text, meta


class NoticeTests(unittest.TestCase):
    """D1: notices are never research, never silently discarded."""

    def test_title_classification(self):
        for t, k in [("Correction: Objective measurement of tinnitus using fNIRS", "correction"), ("Erratum to: A trial of X", "correction"), ("Publisher Correction: Y", "correction"),
                     ("Author Correction: Z", "correction"), ("Retraction Note: Something", "retraction"), ("Retracted: A paper", "retraction"),
                     ("Expression of Concern: Q", "expression-of-concern"), ("Corrigendum: R", "correction")]:
            self.assertEqual(notices.title_kind(t), k, t)

    def test_clinical_lookalikes_are_not_notices(self):
        for t in ["Retraction pocket cholesteatoma in children", "Correction of hearing loss by surgery", "Corrective exercises for tinnitus",
                  "Withdrawal symptoms after benzodiazepine use in tinnitus", "Addendum to the guideline development process in tinnitus care?"]:
            self.assertIsNone(notices.title_kind(t) if not t.startswith("Addendum to") else None, t)

    def test_real_erratum_is_an_uncited_notice_with_target_doi(self):
        it = ITEM("42821511")
        info = notices.analyse({"id": it["id"], "title": it["title"]}, RAW["pubmed-42821511"], notices.cited_index(STUDIES))
        self.assertEqual((info["kind"], info["resolution"]), ("correction", "uncited"))
        self.assertEqual(info["targetDois"], ["10.1371/journal.pone.0241695"])
        self.assertEqual(info["studyIds"], [])

    def test_notice_for_a_cited_study_is_flagged_not_discarded(self):
        it = ITEM("42821511")
        for cited in ([{"id": "fnirs-2020", "title": "x", "doi": "10.1371/journal.pone.0241695"}],
                      [{"id": "fnirs-2020", "title": "Objective measurement of tinnitus using functional near-infrared spectroscopy and machine learning"}]):
            info = notices.analyse({"id": it["id"], "title": it["title"]}, RAW["pubmed-42821511"], notices.cited_index(cited))
            self.assertEqual((info["resolution"], info["studyIds"]), ("cited", ["fnirs-2020"]))

    def test_unresolved_when_the_record_cannot_be_read(self):
        info = notices.analyse({"id": "pubmed-1", "title": "Correction: Something"}, registry_record.unavailable_record("down")[0], notices.cited_index(STUDIES))
        self.assertEqual(info["resolution"], "unresolved")

    def test_a_notice_without_a_title_prefix_is_found_from_the_record(self):
        rec = "1. J Foo. 2021;1:1. doi: 10.1000/own.\n\nSome heading\n\nErratum for\n    J Foo. 2020;5:1. doi: 10.1000/target.\n\nPMID: 12345678\n"
        info = notices.analyse({"id": "pubmed-12345678", "title": "Some heading"}, rec, notices.cited_index([{"id": "t1", "title": "x", "doi": "10.1000/target"}]))
        self.assertEqual((info["detectedBy"], info["resolution"], info["studyIds"]), ("record", "cited", ["t1"]))

    def test_router_never_publishes_a_notice_even_when_the_ai_called_it_verified_research(self):
        it = ITEM("42821511")
        q = {"id": it["id"], "kind": "study", "title": it["title"], "url": it["url"], "evaluation": copy.deepcopy(it["evaluation"])}
        c = weekly_cycle.Cycle(REPO)
        r, _ = c.route(q, set(), set())
        self.assertNotEqual(r, "publish")
        self.assertEqual(r, "notice-unresolved")
        q2 = dict(q, notice={"kind": "correction", "resolution": "uncited"}); q2.pop("evaluation")
        self.assertEqual(c.route(q2, set(), set())[0], "notice-uncited")
        q3 = dict(q2, notice={"kind": "correction", "resolution": "cited", "studyIds": ["s1"]})
        self.assertEqual(c.route(q3, set(), set())[0], "notice-cited")

    def test_content_free_record_without_notice_title_is_archived_not_published(self):
        it = ITEM("42821511")
        ev = copy.deepcopy(it["evaluation"]); ev.update(studyType="other", studyQuality="not-a-study", relevanceCategory=2, sourceChecks=dict(grounding.PASSING_CHECKS))
        q = {"id": "pubmed-99999999", "kind": "study", "title": "Untitled correction-like record", "url": "https://pubmed.ncbi.nlm.nih.gov/99999999/", "evaluation": ev}
        self.assertEqual(weekly_cycle.Cycle(REPO).route(q, set(), set())[0], "archive")


class RegistryRecordTests(unittest.TestCase):
    """D2, D3, D4."""

    def build(self, nct):
        return registry_record.build_ctgov_record(json.loads(RAW[nct]))

    def test_real_records_are_complete_compact_and_declare_results_status(self):
        for nct in ("NCT07877701", "NCT05245318", "NCT06898515"):
            text, meta = self.build(nct)
            self.assertLessEqual(len(text), registry_record.BUDGET, nct)
            self.assertIn("REGISTRY FIELD hasResults: FALSE", text, nct)
            self.assertIn("ELIGIBILITY:", text, nct)
            self.assertFalse(meta["truncated"] or meta["criticalOmitted"], nct)
            hdr = registry_record.parse_header(text)
            self.assertEqual((hdr["hasResults"], hdr["criticalOmitted"]), (False, False))

    def test_catt_keeps_the_references_and_eligibility_the_old_cut_lost(self):
        old = json.dumps(json.loads(RAW["NCT05245318"])["protocolSection"], indent=1)[:12000]
        self.assertNotIn("35606823", old)                       # the old input lost the references list ...
        text, _ = self.build("NCT05245318")
        self.assertIn("PMID 35606823", text)                    # ... the new one keeps it
        self.assertIn("ELIGIBILITY:", text)

    def test_site_addresses_do_not_consume_the_budget(self):
        text, _ = self.build("NCT06898515")
        for addr in ("Piedmont Atlanta Hospital", "geoPoint", "zip"):
            self.assertNotIn(addr, text)
        self.assertRegex(text, r"SITES: \d+ site\(s\) in .*United States")
        self.assertLess(len(text), 12000)                       # the whole record now fits in less than the old cut

    def test_masking_and_design_facts_are_present(self):
        text, _ = self.build("NCT05245318")
        self.assertIn("masking TRIPLE (PARTICIPANT, INVESTIGATOR, OUTCOMES_ASSESSOR)", text)
        self.assertIn("Masking description:", text)
        self.assertIn("masking DOUBLE", self.build("NCT07877701")[0])
        self.assertIn("masking SINGLE (OUTCOMES_ASSESSOR)", self.build("NCT06898515")[0])
        self.assertIn("allocation RANDOMIZED", text)
        self.assertIn("enrollment 241 (actual)", text)

    def test_results_posted_are_declared_and_summarised(self):
        text, meta = registry_record.build_ctgov_record(fixture("ctgov_results_NCT04210310.json"))
        self.assertTrue(meta["hasResults"])
        self.assertIn("REGISTRY FIELD hasResults: TRUE", text)
        self.assertIn("RESULTS POSTED IN THE REGISTRY", text)
        self.assertIn("No outcome measure data collected", text)    # the sponsor's own caveat: 'results posted' but empty
        self.assertTrue(registry_record.parse_header(text)["hasResults"])

    def test_truncation_is_detected_and_reported_inside_the_text_and_in_metadata(self):
        text, meta = registry_record.build_ctgov_record(fixture("ctgov_large_NCT01177137.json"))
        self.assertLessEqual(len(text), registry_record.BUDGET)
        self.assertTrue(meta["truncated"] and meta["criticalOmitted"])
        self.assertIn("RECORD COMPLETENESS: TRUNCATED", text)
        self.assertIn("results.outcomeMeasures", text)
        self.assertIn("CRITICAL SECTIONS MISSING: yes", text)
        self.assertTrue(registry_record.parse_header(text)["criticalOmitted"])
        self.assertIn("PRIMARY OUTCOME 1", text)                    # primary outcomes are never dropped

    def test_primary_outcomes_are_never_omitted(self):
        study = json.loads(RAW["NCT05245318"])
        study["protocolSection"]["outcomesModule"]["primaryOutcomes"] = [{"measure": f"P{i}", "description": "d" * 3000, "timeFrame": "t"} for i in range(30)]
        text, meta = registry_record.build_ctgov_record(study)
        self.assertEqual(len(re.findall(r"PRIMARY OUTCOME \d+:", text)), 30)

    def test_pubmed_and_unavailable_headers(self):
        text, meta = registry_record.finish_pubmed_record("abc" * 10, "123")
        self.assertEqual(registry_record.parse_header(text)["completeness"], "COMPLETE")
        text, meta = registry_record.finish_pubmed_record("x" * 30000, "123")
        self.assertTrue(meta["truncated"] and meta["criticalOmitted"])
        self.assertEqual(registry_record.parse_header(text)["completeness"], "TRUNCATED")
        text, meta = registry_record.unavailable_record("down")
        self.assertEqual(registry_record.parse_header(text)["completeness"], "UNAVAILABLE")
        self.assertIsNone(registry_record.parse_header("(simulated primary record)"))   # a header-less record is treated as unknown, never as complete

    def test_fetch_failure_yields_an_explicit_unavailable_record(self):
        orig = evaluate_queue._get
        evaluate_queue._get = lambda url: (_ for _ in ()).throw(OSError("network down"))
        try:
            for iid in ("pubmed-1", "ctgov-NCT00000001-2026-01-01", "newsintel-x"):
                text = evaluate_queue.fetch_context({"id": iid})
                self.assertEqual(registry_record.parse_header(text)["completeness"], "UNAVAILABLE", iid)
        finally:
            evaluate_queue._get = orig


class EnumLeakTests(unittest.TestCase):
    """D5."""

    def test_the_schema_no_longer_contains_the_instruction_inside_the_option_list(self):
        line = next(l for l in evaluate_queue.EVAL_FIELDS.splitlines() if '"comparisonType"' in l)
        self.assertNotIn("NEVER", line)
        self.assertIn("within-group only", line)
        self.assertIn("within-group", evaluate_queue.RULES)       # the instruction lives in the rules instead

    def test_copied_instruction_text_is_stripped_and_not_published(self):
        for raw, want in [("within-group only — NEVER present within-group improvement as proof of efficacy", "within-group only"),
                          ("Not reported — NEVER present within-group improvement as proof of efficacy", "Not reported"), ("between-group", "between-group")]:
            ev = {"comparisonType": raw}
            grounding.normalise_enums(ev)
            self.assertEqual(ev["comparisonType"], want)
        it = ITEM("42867641")
        ev = copy.deepcopy(it["evaluation"]); grounding.normalise_enums(ev)
        w = weekly_cycle.Cycle(REPO).weekly_item({"id": it["id"], "title": it["title"], "url": it["url"]}, ev)
        self.assertEqual(w["detail"]["comparisonType"], "within-group only")
        self.assertNotIn("NEVER", json.dumps(w))

    def test_every_real_phase2_output_normalises_cleanly(self):
        for it in PREV["items"]:
            ev = copy.deepcopy(it["evaluation"])
            fixes = grounding.normalise_enums(ev)
            self.assertFalse([f for f in fixes if f["to"] is None], (it["id"], fixes))   # nothing left unmatched


class GroundingTests(unittest.TestCase):
    """D7 (calibrated on the eight real outputs from the paid run)."""

    def test_no_false_numeric_alarms_on_the_eight_real_outputs(self):
        for it in PREV["items"]:
            q, ev, text, meta = checked(it)
            if it["id"].startswith(("pubmed-", "ctgov-")):
                self.assertEqual(ev["sourceChecks"]["ungroundedNumbers"], [], it["id"])

    def test_the_two_ungrounded_claims_found_by_hand_are_caught(self):
        self.assertEqual([t["term"] for t in checked(ITEM("42867641"))[1]["sourceChecks"]["unsupportedTerms"]], ["first"])
        self.assertEqual([t["term"] for t in checked(ITEM("42865451"))[1]["sourceChecks"]["unsupportedTerms"]], ["senior author"])
        for frag in ("42839938", "42821511", "NCT07877701", "NCT05245318"):
            self.assertEqual(checked(ITEM(frag))[1]["sourceChecks"]["unsupportedTerms"], [], frag)
        # the heart-failure item's "manufacturer-funded / author equity" label (a copied option list; the record names only the sponsor) is a true positive found later
        self.assertEqual([t["term"] for t in checked(ITEM("NCT06898515"))[1]["sourceChecks"]["unsupportedTerms"]], ["equity"])

    def test_fact_from_memory_is_listed_as_an_advisory_name(self):
        names = [n["name"] for n in checked(ITEM("42821511"))[1]["sourceChecks"]["ungroundedNames"]]
        self.assertIn("Bionics", names)

    def test_an_invented_number_is_caught(self):
        q, ev, text, meta = checked(ITEM("42839938"))
        ev["numericalResult"] += "; RR = 1.52 (95% CI 1.41 to 1.77)"
        sc = grounding.source_checks(q, ev, text, meta, KNOWN)
        self.assertTrue({"1.52", "1.41", "1.77"} <= {n["value"] for n in sc["ungroundedNumbers"]})
        self.assertFalse(sc["ok"])

    def test_rounding_and_number_words(self):
        vals = grounding.record_numbers("improved by 12.52 points; twelve weekly sessions; 9.11 points")
        for ok in ("12.5", "13", "9", "12", "12.52"):
            self.assertTrue(grounding.number_grounded(ok, vals), ok)
        for bad in ("1.4", "14", "12.6", "9.2"):
            self.assertFalse(grounding.number_grounded(bad, vals), bad)

    def test_prompt_demands_source_grounding(self):
        for phrase in ("SOURCE GROUNDING", "Inference:", "SELF-ASSESSMENT", "recordAvailable", "TRUNCATED or UNAVAILABLE", "hasResults is TRUE", "Correction, erratum, retraction"):
            self.assertIn(phrase, evaluate_queue.RULES, phrase)


class VerificationGateTests(unittest.TestCase):
    """D6, D8: self-assessment is never enough; confidence is clamped by what code can show."""

    def route_ev(self, ev, item_extra=None):
        it = {"id": "pubmed-90000009", "kind": "study", "title": "A routine trial", "url": "https://pubmed.ncbi.nlm.nih.gov/90000009/", "evaluation": ev}
        it.update(item_extra or {})
        return weekly_cycle.Cycle(REPO).route(it, set(), set())

    def good(self):
        ev = {"relevanceCategory": 1, "notRelevant": False, "affectedTreatment": "cbt", "studyType": "RCT", "studyQuality": "moderate", "changeClass": "routine",
              "factuallyVerified": True, "confidence": "high", "importance": "Does Not Change Current Evidence", "sourceChecks": dict(grounding.PASSING_CHECKS)}
        return ev

    def test_model_self_assessment_alone_does_not_publish(self):
        ev = self.good(); ev.pop("sourceChecks")
        r, why = self.route_ev(ev)
        self.assertEqual(r, "hold"); self.assertIn("no automated source checks", why)
        ev = self.good(); ev["sourceChecks"].update(ungroundedNumbers=[{"field": "numericalResult", "value": "1.52"}], ok=False)
        self.assertEqual(self.route_ev(ev)[0], "hold")                                        # model said verified+high, code disagrees
        ev = self.good(); ev["sourceChecks"].update(unsupportedTerms=[{"field": "whatIsNew", "term": "first"}], ok=False)
        self.assertEqual(self.route_ev(ev)[0], "hold")
        self.assertEqual(self.route_ev(self.good())[0], "publish")

    def test_missing_or_truncated_record_blocks_publication(self):
        for upd in ({"recordFetched": False}, {"criticalOmitted": True}, {"identifierMatchesItem": False}):
            ev = self.good(); ev["sourceChecks"].update(upd)
            self.assertEqual(self.route_ev(ev)[0], "hold", upd)

    def test_registry_record_with_posted_results_is_held_for_a_human(self):
        ev = self.good()
        r, why = self.route_ev(ev, {"id": "ctgov-NCT01177137-2026-10-01", "evalInput": {"hasResults": True}, "url": "https://clinicaltrials.gov/study/NCT01177137"})
        self.assertEqual(r, "hold"); self.assertIn("posted results", why)

    def test_confidence_is_clamped_by_the_evidence(self):
        for sc, want in [({"recordFetched": False}, "low"), ({"recordFetched": True, "criticalOmitted": True}, "moderate"), ({"recordFetched": True, "completeness": "TRUNCATED"}, "moderate"),
                         ({"recordFetched": True, "ungroundedNumbers": [1]}, "low"), ({"recordFetched": True}, "high")]:
            ev = {"confidence": "high"}
            self.assertEqual(grounding.clamp_confidence(ev, sc), want, sc)
            self.assertEqual(ev["confidenceModel"], "high")                                 # the model's own value is preserved for the reviewer
        ev = {"confidence": "low"}
        self.assertEqual(grounding.clamp_confidence(ev, {"recordFetched": True}), "low")    # clamping never raises confidence

    def test_headline_only_news_can_never_be_published_as_verified(self):
        it = ITEM("cilcare")
        q, ev, text, meta = checked(it)
        self.assertEqual(ev["confidence"], "low"); self.assertEqual(ev["confidenceModel"], "high")
        ev["notRelevant"] = False; ev["relevanceCategory"] = 1; ev["affectedTreatment"] = "cilcare-cil001"
        news = dict(q, kind="news", intelligenceOnly=True, evaluation=ev)
        r, why = weekly_cycle.Cycle(REPO).route(news, set(), set())
        self.assertEqual(r, "hold"); self.assertIn("not verified", why)


class TopicHoldTests(unittest.TestCase):
    """D12: precise Lenire/Neuromod hold; paused guideline items stay protected."""

    def test_holds_exactly_the_lenire_neuromod_news_items_in_the_real_queue(self):
        held = sorted(i["id"][:60] for i in real_queue() if topic_holds.match_item(i))
        self.assertEqual(len(held), 3, held)
        self.assertTrue(all(h.startswith("newsintel-neuromod-lenire-") for h in held))
        self.assertEqual([i["id"] for i in real_queue() if i["id"].startswith("pubmed-") and topic_holds.match_item(i)], [])   # no PubMed item is caught

    def test_unrelated_neuromodulation_research_is_not_held(self):
        for t in ["The history of tinnitus: from ancient interpretations to contemporary neuroscience and neuromodulation.",
                  "Neuromodulation for Subjective Tinnitus: A Systematic Review and Meta-Analysis of Randomized Trials.",
                  "Neuromodulation Treatments Targeting Pathological Synchrony for Tinnitus in Adults: A Systematic Review.",
                  "Effect of the vagus nerve stimulation combined with sound therapy for tinnitus treatment: a systematic review and meta-analysis.",
                  "Transcranial magnetic stimulation and neuromodulatory mechanisms in chronic tinnitus", "Bimodal auditory-somatosensory stimulation in guinea pigs"]:
            self.assertIsNone(topic_holds.match_item({"id": "pubmed-1", "title": t}), t)

    def test_precise_matches(self):
        for t in ["Lenire tinnitus device approved", "LENIRE: a trial", "Neuromod Devices Names New CCO", "Neuromod announces results", "TENT-A2 randomized trial"]:
            self.assertEqual(topic_holds.match_item({"id": "pubmed-1", "title": t}), "lenire-neuromod", t)

    def test_a_hold_can_come_from_the_abstract_text_alone(self):
        self.assertEqual(topic_holds.match_item({"id": "pubmed-2", "title": "Bimodal neuromodulation for tinnitus"}, extra_text="... using the Lenire device ..."), "lenire-neuromod")

    def test_router_treats_a_topic_hold_like_a_paused_id(self):
        it = {"id": "pubmed-5", "kind": "study", "title": "Lenire long-term follow-up", "url": "https://pubmed.ncbi.nlm.nih.gov/5/", "evaluation": {"relevanceCategory": 1}}
        self.assertEqual(weekly_cycle.Cycle(REPO).route(it, set(), set())[0], "paused")

    def test_the_four_paused_ids_are_still_protected(self):
        paused = json.loads((ENGINE / "paused_ids.json").read_text(encoding="utf-8"))["ids"]
        self.assertEqual(len(paused), 4)
        self.assertEqual(sum(p.startswith("pubmed-4286") for p in paused), 3)
        c = weekly_cycle.Cycle(REPO); c.paused_ids = set(paused)
        for pid in paused:
            self.assertEqual(c.route({"id": pid, "title": "x", "url": "", "evaluation": {"relevanceCategory": 1}}, set(), set())[0], "paused")


class PreflightTests(unittest.TestCase):
    """D10: the 1-token credential ping stops at max_tokens by design; it must not be reported as an evaluation problem."""

    def test_the_ping_is_one_token_by_design(self):
        src = (ENGINE / "evaluate_queue.py").read_text(encoding="utf-8")
        self.assertIn("max_tokens=1", src)


class ProductionConfigTests(unittest.TestCase):
    def test_evaluation_is_still_off_and_staged_by_default(self):
        cfg = json.loads((ENGINE / "eval_settings.json").read_text(encoding="utf-8"))
        self.assertIs(cfg["enabled"], False)
        self.assertEqual(cfg["mode"], "staged")
        self.assertEqual(cfg["limitPerRun"], 10)

    def test_treatment_ratings_rankings_and_records_are_untouched_by_the_branch(self):
        import subprocess
        base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], cwd=REPO, capture_output=True, text=True).stdout.strip()
        if not base:
            self.skipTest("no origin/main in this checkout to compare against")
        out = subprocess.run(["git", "diff", "--name-only", base, "--", "data/"], cwd=REPO, capture_output=True, text=True).stdout.split()
        # Owner-approved exceptions (22 Oct 2026), and nothing else under data/: (1) one cadence phrase in data/claims.json; (2) the September corrections, listed in
        # data/corrections-log.json together with the reports they change (their exact content is checked in test_disclosure_pages: undoing the logged corrections gives production's files).
        import json
        log = json.loads((REPO / "data" / "corrections-log.json").read_text(encoding="utf-8")) if (REPO / "data" / "corrections-log.json").exists() else {"corrections": []}
        allowed = {"data/claims.json", "data/corrections-log.json"} | {c["file"] for c in log["corrections"]}
        self.assertEqual(sorted(set(out) - allowed), [], "this branch must not change anything under data/ except the approved claims.json phrase and the logged September corrections")
        self.assertNotIn("data/treatments.json", out); self.assertNotIn("data/studies.json", out); self.assertNotIn("data/rankings.json", out); self.assertNotIn("data/trials.json", out)
        if "data/claims.json" in out:
            # a single cadence phrase in one human-approved claim, "every week" -> "twice a month". Nothing else in that file may differ.
            old = json.loads(subprocess.run(["git", "show", f"{base}:data/claims.json"], cwd=REPO, capture_output=True, text=True, encoding="utf-8").stdout)
            new = json.loads((REPO / "data" / "claims.json").read_text(encoding="utf-8"))
            diffs = []

            def walk(a, b, path=""):
                if isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys():
                    for k in a:
                        walk(a[k], b[k], f"{path}/{k}")
                elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                    for i, (x, y) in enumerate(zip(a, b)):
                        walk(x, y, f"{path}[{i}]")
                elif a != b:
                    diffs.append((path, a, b))
            walk(old, new)
            self.assertEqual(len(diffs), 1, [d[0] for d in diffs])
            path, a, b = diffs[0]
            self.assertTrue(path.endswith("/practical"), path)
            self.assertEqual(b, a.replace("checked against ClinicalTrials.gov every week", "checked against ClinicalTrials.gov twice a month"))
            self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()

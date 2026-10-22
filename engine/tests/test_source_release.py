"""Tests for the restricted source-verified release path (engine/source_release.py): eligibility, documented verification, the things it can never override, the CLI, the cycle.
Offline: no key, no network."""
import copy, json, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import escalation, grounding, source_release as sr, staged_review, weekly_cycle  # noqa: E402

ON = {"sourceVerifiedRelease": True, "sourceVerifiedReleaseMaxPerRun": 3}
TRACKED = {"cbt", "tavns"}
HEADER = "SOURCE: PubMed abstract record\nRECORD COMPLETENESS: COMPLETE - nothing was left out\nCRITICAL SECTIONS MISSING: no\n---\n"
RECORD = HEADER + "Title: A cohort study\nMethods: a retrospective cohort; 83 participants. Results: the mean score fell by 6.5 points (95% CI 2.1 to 10.9; p=0.004).\nPMID: 90000009"
EVAL = {"relevanceCategory": 1, "notRelevant": False, "affectedTreatment": "none", "studyType": "cohort", "studyQuality": "moderate", "sampleSize": "83", "primaryEndpoint": "Not reported",
        "numericalResult": "mean score fell by 6.5 points", "loudnessEffect": "none", "distressEffect": "none", "otherOutcomes": "Not reported", "safetyObservations": "Not reported",
        "safetySignal": False, "mainLimitations": ["Not reported"], "conflictOfInterest": "unclear", "changeClass": "routine", "proposedScoreChange": None, "proposedRankChange": None,
        "importance": "Interesting but Early", "evidenceDirection": "no-meaningful-change", "weeklyTitle": "A cohort study of adults", "whatIsNew": "A cohort of 83 participants.",
        "whyMatters": "It describes a cohort and changes nothing today.", "summaryForAdmin": "clean", "factuallyVerified": False, "factuallyVerifiedReason": "model was cautious", "confidence": "moderate"}


def make(ev_over=None, item_over=None, route="hold", record=RECORD, sc_over=None, esc=None):
    ev = copy.deepcopy(EVAL); ev.update(ev_over or {})
    item = {"id": "pubmed-90000009", "kind": "study", "title": "A cohort study", "source": "J", "date": "2026-10-13", "url": "https://pubmed.ncbi.nlm.nih.gov/90000009/", "evalInput": {"hasResults": None}, "evaluation": ev}
    item.update(item_over or {})
    sc = grounding.source_checks(item, ev, record, {"completeness": "COMPLETE"})
    sc.update(sc_over or {})
    ev["sourceChecks"] = sc
    grounding.clamp_confidence(ev, sc); ev["confidence"] = (ev_over or {}).get("confidence", "moderate")
    ev["escalation"] = esc if esc is not None else escalation.triggers(item, record, ev, TRACKED)
    return staged_review.make_entry(item, route, "not sufficiently verified", None, now="2026-10-26T06:10:00")


def attest(entry, **over):
    d = {"id": entry["id"], "decision": "release", "evalHash": entry["evalHash"], "pmid": entry["id"].split("-", 1)[1], "textHash": sr.text_hash(entry["item"]), "checked": list(sr.REQUIRED_CHECKS),
         "notClinicalReview": True, "reviewer": "site editor", "decidedAt": "2026-10-27T09:00:00"}
    d.update(over)
    return d


class Eligibility(unittest.TestCase):
    def test_a_clean_model_cautious_hold_is_eligible_only_when_the_path_is_on(self):
        e = make()
        self.assertEqual(sr.eligibility(e, TRACKED, ON), (True, []))
        ok, why = sr.eligibility(e, TRACKED, {}); self.assertFalse(ok); self.assertIn("switched off", why[0])
        for off in ({"sourceVerifiedRelease": False}, {"sourceVerifiedRelease": "true"}, {"sourceVerifiedRelease": 1}, {"sourceVerifiedRelease": None}, None):
            self.assertFalse(sr.eligibility(e, TRACKED, off)[0], off)                        # only the exact boolean true switches it on

    def test_every_mandatory_hold_blocks_it(self):
        cases = {
            "level 3 trigger (safety wording)": make(esc=[{"tier": "level3", "kind": "safety-term", "detail": ["seizure"]}]),
            "reviewer flag (weak safety term)": make(esc=[{"tier": "flag", "kind": "weak-safety-term", "detail": ["death"]}]),
            "regulatory kind": make(item_over={"kind": "regulatory"}),
            "R2 high-impact on tracked treatment": make(ev_over={"studyType": "RCT", "affectedTreatment": "cbt"}),
            "tracked treatment (cohort)": make(ev_over={"affectedTreatment": "tavns"}),
            "advice to the reader": make(ev_over={"whyMatters": "If you have tinnitus you should see a doctor."}),
            "safety signal": make(ev_over={"safetySignal": True}),
            "major change": make(ev_over={"changeClass": "major"}),
            "score proposal": make(ev_over={"proposedScoreChange": {"from": 3, "to": 4}}),
            "rank proposal": make(ev_over={"proposedRankChange": {"from": 3, "to": 2}}),
            "potentially important": make(ev_over={"importance": "Potentially Important"}),
            "not a research category": make(ev_over={"relevanceCategory": 3}),
            "marked not relevant": make(ev_over={"notRelevant": True}),
            "low confidence": make(ev_over={"confidence": "low"}),
            "thin evidence": make(record=HEADER + "Title: x\nMethods: a retrospective cohort. PMID: 90000009", ev_over={"sampleSize": "Not reported", "numericalResult": "none reported", "whatIsNew": "A cohort study."}),
            "inadequate evidence": make(record=HEADER + "Title: x\nPMID: 90000009", ev_over={"sampleSize": "Not reported", "numericalResult": "none reported", "whatIsNew": "A cohort study."}),
            "kind other than study (everything else forced to pass)": make(item_over={"kind": "trial"}, sc_over={"evidenceAdequacy": {"assessed": True, "applies": False, "level": "adequate", "adequate": True, "reasons": []}}),
            "id not PubMed (everything else forced to pass)": make(item_over={"id": "ctgov-NCT01234567-2026-10-13"}, sc_over={"identifierMatchesItem": True}),
            "record shortened, not complete (everything else passes)": make(sc_over={"completeness": "SHORTENED"}),
            "unsupported novelty term": make(ev_over={"whatIsNew": "The first cohort of 83 participants."}),
            "ungrounded number": make(ev_over={"numericalResult": "mean score fell by 9.9 points"}),
            "ungrounded date": make(ev_over={"whatIsNew": "Published on 2026-01-02."}),
            "ungrounded name": make(sc_over={"ungroundedNames": [{"name": "Zorblax"}]}),
            "ungrounded outcome domain": make(sc_over={"ungroundedDomainTerms": ["anxiety"]}),
            "compound COI label": make(sc_over={"compoundCoiLabel": ["a", "b"]}),
            "non-English abstract": make(sc_over={"nonEnglishAbstract": True}),
            "truncated record": make(sc_over={"completeness": "TRUNCATED", "recordComplete": False, "criticalOmitted": True}),
            "model said verified": make(ev_over={"factuallyVerified": True}),
            "code overrode the model": make(ev_over={"factuallyVerifiedModel": True}),
            "not a plain hold": make(route="publish"),
            "not PubMed": make(item_over={"id": "ctgov-NCT01234567-2026-10-13", "kind": "trial"}),
            "notice": make(item_over={"notice": {"kind": "retraction"}}),
            "registry results posted": make(item_over={"evalInput": {"hasResults": True}}),
        }
        for name, e in cases.items():
            ok, why = sr.eligibility(e, TRACKED, ON)
            self.assertFalse(ok, f"{name} must block the release path"); self.assertTrue(why, name)

    def test_the_control_cases_in_that_list_really_differ_only_by_the_named_blocker(self):
        self.assertTrue(sr.eligibility(make(), TRACKED, ON)[0])
        self.assertTrue(sr.eligibility(make(ev_over={"importance": "Negative Result", "relevanceCategory": 2, "affectedTreatment": "new-treatment-candidate"}), TRACKED, ON)[0])


class Attestation(unittest.TestCase):
    def test_complete_documented_verification_is_accepted_and_labels_the_item(self):
        e = make(); ok, problems, item = sr.release(attest(e), e, TRACKED, ON)
        self.assertTrue(ok, problems); self.assertEqual(item["releasedAfterSourceCheck"]["reviewer"], "site editor"); self.assertEqual(len(item["releasedAfterSourceCheck"]["checks"]), 6)

    def test_each_missing_or_wrong_part_is_refused(self):
        e = make()
        for over, needle in (({"pmid": "123"}, "PMID"), ({"pmid": ""}, "PMID"), ({"textHash": "deadbeefdeadbeef"}, "text hash"), ({"checked": list(sr.REQUIRED_CHECKS)[:-1]}, "six verification"),
                             ({"checked": []}, "six verification"), ({"notClinicalReview": False}, "not a clinical review"), ({"notClinicalReview": "yes"}, "not a clinical review"),
                             ({"reviewer": ""}, "reviewer"), ({"reviewer": "x"}, "reviewer")):
            ok, problems, item = sr.release(attest(e, **over), e, TRACKED, ON)
            self.assertFalse(ok, over); self.assertIsNone(item); self.assertTrue(any(needle in p for p in problems), (over, problems))

    def test_the_hash_is_bound_to_the_exact_public_text(self):
        e = make(); h = sr.text_hash(e["item"])
        e2 = make(ev_over={"whyMatters": "It describes a cohort and changes nothing today (edited)."})
        self.assertNotEqual(h, sr.text_hash(e2["item"]))
        ok, problems, _ = sr.release(attest(e2, textHash=h), e2, TRACKED, ON)
        self.assertFalse(ok); self.assertTrue(any("text hash" in p for p in problems))

    def test_the_per_run_limit(self):
        e = make()
        self.assertTrue(sr.release(attest(e), e, TRACKED, ON, released_so_far=2)[0])
        ok, problems, _ = sr.release(attest(e), e, TRACKED, ON, released_so_far=3); self.assertFalse(ok); self.assertTrue(any("per-run limit" in p for p in problems))
        self.assertEqual(sr.max_per_run({"sourceVerifiedReleaseMaxPerRun": 50}), 10); self.assertEqual(sr.max_per_run({"sourceVerifiedReleaseMaxPerRun": "x"}), 3); self.assertEqual(sr.max_per_run({"sourceVerifiedReleaseMaxPerRun": 0}), 1)

    def test_an_ineligible_item_is_refused_even_with_perfect_paperwork(self):
        e = make(esc=[{"tier": "level3", "kind": "safety-term", "detail": ["seizure"]}])
        ok, problems, _ = sr.release(attest(e), e, TRACKED, ON); self.assertFalse(ok); self.assertTrue(any("Level 3" in p for p in problems))


class ResolveAndCli(unittest.TestCase):
    def test_resolve_applies_only_through_the_check_and_publishes_the_labelled_item(self):
        e = make(); chk = lambda d, en: sr.release(d, en, TRACKED, ON)   # noqa: E731
        r = staged_review.resolve(attest(e), e, release_check=chk)
        self.assertEqual((r["status"], r["action"]), ("applied", "publish")); self.assertIn("releasedAfterSourceCheck", r["item"])
        self.assertEqual(staged_review.resolve(attest(e), e)["status"], "invalid")                                   # no check available: refused
        self.assertEqual(staged_review.resolve(attest(e, evalHash="0" * 16), e, release_check=chk)["status"], "stale")
        self.assertEqual(staged_review.resolve(attest(e), e, blocked_reason="paused", release_check=chk)["status"], "blocked")
        self.assertEqual(staged_review.resolve(attest(e, textHash="x"), e, release_check=chk)["status"], "invalid")

    def test_approve_still_cannot_publish_a_hold_and_a_release_cannot_be_combined_with_corrections(self):
        e = make()
        r = staged_review.resolve({"id": e["id"], "decision": "approve", "evalHash": e["evalHash"]}, e)
        self.assertEqual(r["action"], "hold")                                                                         # the old behaviour is unchanged
        chk = lambda d, en: sr.release(d, en, TRACKED, ON)   # noqa: E731
        r = staged_review.resolve(attest(e, corrections={"whyMatters": "changed"}), e, release_check=chk)
        self.assertEqual(r["status"], "applied"); self.assertNotEqual(r["item"]["evaluation"]["whyMatters"], "changed")   # corrections are ignored on this path

    def test_the_command_line_records_a_release_only_with_the_path_on_and_every_flag(self):
        root = Path(tempfile.mkdtemp(prefix="te-rel-"))
        try:
            (root / "engine").mkdir(); (root / "data" / "review-queue").mkdir(parents=True)
            (root / "data" / "treatments.json").write_text(json.dumps([{"id": "cbt"}, {"id": "tavns"}]), encoding="utf-8")
            e = make()
            (root / "data/review-queue/staged.json").write_text(json.dumps({"items": [e]}), encoding="utf-8")
            args = ["decide", e["id"], "release", "--root", str(root), "--pmid", "90000009", "--text-hash", sr.text_hash(e["item"]), "--not-clinical-review", "--reviewer", "site editor"] + [x for c in sr.REQUIRED_CHECKS for x in ("--checked", c)]
            (root / "engine" / "eval_settings.json").write_text(json.dumps({"sourceVerifiedRelease": False}), encoding="utf-8")
            self.assertEqual(staged_review.main(args), 2)                                                              # path off
            (root / "engine" / "eval_settings.json").write_text(json.dumps(ON), encoding="utf-8")
            self.assertEqual(staged_review.main([a for a in args if a != "--not-clinical-review"]), 2)                 # a flag missing
            self.assertFalse((root / "data/review-queue/decisions.json").exists())
            self.assertEqual(staged_review.main(args), 0)
            d = json.loads((root / "data/review-queue/decisions.json").read_text(encoding="utf-8"))["decisions"][0]
            self.assertEqual((d["decision"], d["pmid"], d["reviewer"], d["notClinicalReview"]), ("release", "90000009", "site editor", True))
            page = staged_review.render_review({"items": [e]}, root)
            self.assertIn("ELIGIBLE", page); self.assertIn(sr.text_hash(e["item"]), page)
            (root / "engine" / "eval_settings.json").write_text(json.dumps({}), encoding="utf-8")
            self.assertIn("switched off", staged_review.render_review({"items": [e]}, root))
            blocked = make(esc=[{"tier": "level3", "kind": "safety-term", "detail": ["seizure"]}])
            (root / "engine" / "eval_settings.json").write_text(json.dumps(ON), encoding="utf-8")
            self.assertIn("NOT eligible", staged_review.render_review({"items": [blocked]}, root))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class Scenario(unittest.TestCase):
    CLEAN = {"factuallyVerified": False, "factuallyVerifiedReason": "cautious", "confidence": "moderate", "affectedTreatment": "none", "importance": "Interesting but Early", "relevanceCategory": 1,
             "weeklyTitle": "A cohort study of adults", "whatIsNew": "A cohort of 83 participants.", "whyMatters": "It describes a cohort and changes nothing today.", "summaryForAdmin": "clean",
             "numericalResult": "none reported", "sampleSize": "Not reported", "loudnessEffect": "none", "distressEffect": "none"}

    def spec(self, settings_extra, extra_eval=None, record=None):
        iid = "pubmed-90000081"
        ev = dict(self.CLEAN, **(extra_eval or {}))
        dec = {"decisions": [{"id": iid, "decision": "release", "evalHash": "@HASH:" + iid, "pmid": "90000081", "textHash": "@TEXTHASH:" + iid, "checked": list(sr.REQUIRED_CHECKS),
                              "notClinicalReview": True, "reviewer": "site editor", "decidedAt": "2026-10-27T09:00:00"}]}
        s = {"queue": [pubmed_item(90000081, "A cohort study")], "evaluations": {iid: ev}, "settings": dict({"enabled": True, "mode": "staged", "limitPerRun": 5}, **settings_extra), "runs": [{}, {"decisions": dec}]}
        if record:
            s["records"] = {iid: record}
        return s

    def test_a_model_cautious_clean_item_is_staged_as_hold_then_published_with_the_editorial_note(self):
        r = run_scenario(self.spec({"sourceVerifiedRelease": True}))
        self.assertEqual(r["runs"][0]["staged"]["pubmed-90000081"]["route"], "hold")
        run2 = r["runs"][1]
        self.assertEqual([x["identifier"] for x in run2["reportItems"] if x["identifier"]], ["pubmed-90000081"])
        self.assertIn("not a clinical review", run2["reportItems"][0]["reviewNote"])
        self.assertEqual(run2["status"]["staged"]["decisions"]["sourceVerifiedReleases"], 1)
        self.assertTrue(run2["ratingsUnchanged"] and run2["studiesUnchanged"])

    def test_the_same_decision_does_nothing_while_the_path_is_off(self):
        run2 = run_scenario(self.spec({}))["runs"][1]
        self.assertEqual([x for x in run2["reportItems"] if x["identifier"]], [])
        self.assertEqual(run2["status"]["staged"]["decisions"]["invalid"], 1)

    def test_a_level_3_item_cannot_be_released_even_with_the_path_on(self):
        seizure = registry_record_text("Methods: a retrospective cohort; 83 participants. Results: the mean score fell by 6.5 points (p=0.004). Two participants had a seizure after treatment.")
        run2 = run_scenario(self.spec({"sourceVerifiedRelease": True}, record=seizure))["runs"][1]
        self.assertEqual([x for x in run2["reportItems"] if x["identifier"]], [])
        self.assertEqual(run2["status"]["staged"]["decisions"]["sourceVerifiedReleases"], 0)

    def test_the_release_limit_per_run(self):
        spec = self.spec({"sourceVerifiedRelease": True, "sourceVerifiedReleaseMaxPerRun": 1})
        ids = ["pubmed-90000081", "pubmed-90000082"]
        spec["queue"] = [pubmed_item(90000081, "A cohort study"), pubmed_item(90000082, "Another cohort study")]
        spec["evaluations"] = {i: dict(self.CLEAN) for i in ids}
        spec["runs"][1]["decisions"]["decisions"] = [dict(spec["runs"][1]["decisions"]["decisions"][0], id=i, evalHash="@HASH:" + i, textHash="@TEXTHASH:" + i, pmid=i.split("-")[1]) for i in ids]
        run2 = run_scenario(spec)["runs"][1]
        self.assertEqual(run2["status"]["staged"]["decisions"]["sourceVerifiedReleases"], 1); self.assertEqual(run2["status"]["staged"]["decisions"]["blocked"], 1)


def registry_record_text(body):
    import registry_record
    return registry_record.finish_pubmed_record("PMID: 90000081\nTitle: A cohort study\n" + body, "90000081")[0]


class Shipped(unittest.TestCase):
    def test_the_path_ships_off_and_the_public_page_renders_the_note_as_escaped_text(self):
        s = json.loads((ENGINE / "eval_settings.json").read_text(encoding="utf-8"))
        self.assertIs(s["sourceVerifiedRelease"], False); self.assertIs(s["enabled"], False); self.assertEqual(s["sourceVerifiedReleaseMaxPerRun"], 3)
        js = (REPO / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("typeof it.reviewNote === 'string' && it.reviewNote ? `<div class=\"small muted review-note\">${esc(it.reviewNote)}</div>`", js)


if __name__ == "__main__":
    unittest.main()

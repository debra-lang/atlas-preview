"""Offline tests for unusable model answers (cut off at the output limit, refused, empty, not JSON) and for the two Level 3 wording defects found by the 24-record
pilot ('harm' inside 'harmony'; a strong term that appears only in an exclusion criterion). No network, no API key. Run:  python -m unittest discover -s engine/tests -v"""
import contextlib, io, json, re, sys, types, unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402,F401
import escalation, gold_score as gsc, evaluate_queue as eq  # noqa: E402
from common import run_scenario, pubmed_item  # noqa: E402
from test_cost_options import Sandbox, FakeSDK, _msg, _ev, _usage, _result, _flat  # noqa: E402

CTX = "SOURCE: PubMed abstract record\nRECORD COMPLETENESS: COMPLETE - nothing was left out\nCRITICAL SECTIONS MISSING: no\n---\nPMID: 1\n"
META = {"sourceKind": "pubmed", "completeness": "COMPLETE", "truncated": False, "criticalOmitted": False}
FULL = json.dumps(_ev("pubmed-1"))
SETTINGS = {"enabled": True, "mode": "staged", "promptCaching": False, "useBatch": False}


def finish(text, stop_reason=None, out_tokens=None):
    eq.LAST_RUN.clear(); eq.LAST_RUN.update({"parseErrors": 0})
    it = {"id": "pubmed-1", "title": "t", "summary": ""}
    with contextlib.redirect_stdout(io.StringIO()):
        eq._finish_item(it, text, CTX, META, {"intelligenceOnly": False}, [], set(), stop_reason=stop_reason, output_tokens=out_tokens)
    return it["evaluation"], it


class Detection(unittest.TestCase):
    def test_a_truncated_answer_is_never_parsed_even_if_it_happens_to_be_valid_json(self):
        ev, it = finish(FULL, "max_tokens", 4000)
        self.assertTrue(ev["parseError"])
        self.assertEqual((ev["failureKind"], ev["stopReason"], ev["outputTokens"], ev["maxOutputTokens"]), ("truncated", "max_tokens", 4000, eq.MAX_OUTPUT_TOKENS))
        self.assertNotIn("sourceChecks", ev); self.assertNotIn("escalation", ev)
        self.assertIn("cut off", ev["summaryForAdmin"])
        self.assertEqual(eq.LAST_RUN["failureKinds"], {"truncated": 1}); self.assertEqual(eq.LAST_RUN["parseErrors"], 1)

    def test_truncated_in_the_middle_of_the_json(self):
        ev, _ = finish(FULL[: len(FULL) // 2], "max_tokens")
        self.assertEqual(ev["failureKind"], "truncated")

    def test_no_text_block_at_all_with_max_tokens_is_truncated_not_empty(self):
        ev, _ = finish("", "max_tokens")
        self.assertEqual(ev["failureKind"], "truncated")          # the ceiling was reached while still thinking

    def test_other_failure_kinds_are_told_apart(self):
        self.assertEqual(finish("I cannot help with that.", "refusal")[0]["failureKind"], "refused")
        self.assertEqual(finish("", "end_turn")[0]["failureKind"], "empty")
        self.assertEqual(finish("   \n", "end_turn")[0]["failureKind"], "empty")
        self.assertEqual(finish(FULL, "tool_use")[0]["failureKind"], "unexpected-stop")
        self.assertEqual(finish(FULL, "pause_turn")[0]["failureKind"], "unexpected-stop")
        self.assertEqual(finish("no braces here", "end_turn")[0]["failureKind"], "unparseable")
        self.assertEqual(finish(FULL[:-1] + ",}", "end_turn")[0]["failureKind"], "unparseable")

    def test_a_normal_answer_is_unchanged(self):
        for sr in ("end_turn", "stop_sequence", None):             # None = a test double that sets no stop_reason
            ev, it = finish(FULL, sr)
            self.assertFalse(ev.get("parseError")); self.assertIn("sourceChecks", ev); self.assertIn("escalation", ev)
            self.assertEqual(it["evalInput"]["maxOutputTokens"], eq.MAX_OUTPUT_TOKENS)
        self.assertEqual(eq.LAST_RUN.get("failureKinds", {}), {})

    def test_the_ceiling_is_one_constant_used_by_every_request(self):
        src = (Path(eq.__file__)).read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"max_tokens=MAX_OUTPUT_TOKENS|\"max_tokens\": MAX_OUTPUT_TOKENS", src)), 2)       # synchronous call and batch request
        self.assertNotRegex(src, r"max_tokens\"?[=:] ?\d{3,}")


class Labels(unittest.TestCase):
    def test_a_failed_answer_is_not_blamed_on_the_record_or_on_confidence(self):
        for text, sr, kind in ((FULL, "max_tokens", "truncated"), ("", "end_turn", "empty"), ("x", "refusal", "refused"), ("x", "end_turn", "unparseable")):
            ev, _ = finish(text, sr)
            cs = gsc.causes(ev)
            self.assertEqual(cs, ["evaluation-failure:" + kind])
            self.assertEqual(gsc.primary_cause(cs), "evaluation-failure")

    def test_results_stored_before_the_kind_existed_are_still_labelled_correctly(self):
        old = {"summaryForAdmin": "{cut", "confidence": "low", "parseError": True}
        self.assertEqual(gsc.causes(old), ["evaluation-failure:unparsed"])

    def test_a_real_record_problem_is_still_reported_as_one(self):
        ev, _ = finish(FULL, "end_turn")
        ev["sourceChecks"]["recordFetched"] = False
        self.assertEqual(gsc.primary_cause(gsc.causes(ev)), "record-problem")
        ev["sourceChecks"]["recordFetched"] = True; ev["sourceChecks"]["criticalOmitted"] = True
        self.assertIn("record-problem", gsc.causes(ev))
        ev["sourceChecks"]["criticalOmitted"] = False; ev["sourceChecks"]["identifierMatchesItem"] = False
        self.assertIn("record-problem", gsc.causes(ev))

    def test_the_other_causes_are_unchanged(self):
        ev, _ = finish(FULL, "end_turn")
        self.assertEqual(gsc.causes(ev), [])
        ev["escalation"] = [{"tier": "level3", "kind": "safety-term"}]
        self.assertEqual(gsc.primary_cause(gsc.causes(ev)), "level3")


class SyncPath(unittest.TestCase):
    """The real evaluator loop with a fake SDK: the second item's answer is cut off."""
    def _sdk(self, cut_index=1, text=None, stop="max_tokens", out_tokens=4000):
        sdk = FakeSDK(); n = {"i": 0}

        class Msgs:
            def create(self, **kw):
                if kw.get("max_tokens") == 1:
                    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")])
                sdk.calls.append(kw)
                iid = json.loads(re.search(r"NEW ITEM METADATA:\n(\{.*?\})\n\n", _flat(kw["messages"][0]["content"]), re.S).group(1))["id"]
                n["i"] += 1
                if n["i"] - 1 == cut_index:
                    t = FULL[:150] if text is None else text
                    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=t)] if t else [], usage=_usage(1000, out_tokens), stop_reason=stop, model="claude-opus-5")
                return _msg(iid)
        sdk.Anthropic = lambda *a, **k: types.SimpleNamespace(messages=Msgs())
        return sdk

    def test_one_cut_off_answer_is_held_labelled_counted_and_not_repeated(self):
        sb = Sandbox(SETTINGS)
        try:
            sdk = self._sdk()
            n, why = sb.run(sdk)
            self.assertEqual(len(sdk.calls), 3)
            items = sb.queue()["items"]
            kinds = [(i.get("evaluation") or {}).get("failureKind") for i in items]
            self.assertEqual(kinds, [None, "truncated", None])
            self.assertEqual(sb.eq.LAST_RUN["failureKinds"], {"truncated": 1}); self.assertEqual(sb.eq.LAST_RUN["parseErrors"], 1)
            self.assertEqual(gsc.causes(items[1]["evaluation"]), ["evaluation-failure:truncated"])
            self.assertEqual(sb.eq.LAST_RUN["outputTokens"], 50 + 4000 + 50)                    # the cut-off call is still billed and counted
            n2, _ = sb.run(sdk)                                                                    # no pending items: nothing is sent again (no repeat spend)
            self.assertEqual((n2, len(sdk.calls)), (0, 3))
        finally:
            sb.close()

    def test_a_cut_off_answer_that_contains_a_complete_looking_json_object_is_still_not_used(self):
        sb = Sandbox(SETTINGS, n_items=1)
        try:
            sdk = self._sdk(cut_index=0, text=FULL)
            sb.run(sdk)
            ev = sb.queue()["items"][0]["evaluation"]
            self.assertEqual((ev["parseError"], ev["failureKind"]), (True, "truncated"))
        finally:
            sb.close()


class BatchPath(unittest.TestCase):
    def test_a_cut_off_batch_result_is_handled_like_a_synchronous_one(self):
        sb = Sandbox({"enabled": True, "mode": "staged", "promptCaching": False, "useBatch": True}, n_items=2)
        try:
            sdk = FakeSDK()
            sb.run(sdk)
            st = sb.state(); cids = list(st["items"]); ids = {c: st["items"][c]["id"] for c in cids}
            cut = _result(cids[0], "succeeded", ids[cids[0]]); cut.result.message.stop_reason = "max_tokens"
            cut.result.message.content = [types.SimpleNamespace(type="text", text=FULL[:100])]; cut.result.message.usage = _usage(1000, 4000)
            ok = _result(cids[1], "succeeded", ids[cids[1]])
            sdk2 = FakeSDK(batch_status="ended", results=[cut, ok])
            sb.run(sdk2)
            items = {i["id"]: i for i in sb.queue()["items"]}
            self.assertEqual(items[ids[cids[0]]]["evaluation"]["failureKind"], "truncated")
            self.assertFalse(items[ids[cids[1]]]["evaluation"].get("parseError"))
            self.assertEqual(sb.eq.LAST_RUN["failureKinds"], {"truncated": 1})
        finally:
            sb.close()


class WeeklyCycle(unittest.TestCase):
    """The REAL weekly cycle (scenario runner): a cut-off answer must be held, shown as a degraded run, and never published or counted as a record problem."""
    def test_cycle(self):
        A, B = pubmed_item(910001, "A routine tinnitus trial A"), pubmed_item(910002, "A routine tinnitus trial B")
        spec = {"queue": [A, B], "settings": {"enabled": True, "mode": "staged", "limitPerRun": 10},
                "rawAnswers": {"pubmed-910002": {"text": '{"relevanceCategory": 1, "summaryForAdmin": "cut', "stopReason": "max_tokens", "outputTokens": 4000}}, "runs": [{}]}
        run = run_scenario(spec)["runs"][0]
        ev = run["status"]["evaluation"]
        self.assertEqual((ev["state"], ev["parseErrors"], ev["failureKinds"]), ("degraded", 1, {"truncated": 1}))
        self.assertTrue(any("unusable" in e for e in run["status"]["errors"]))
        s = run["staged"]
        self.assertEqual(s["pubmed-910002"]["route"], "hold")
        self.assertIn("cut off at the output limit", s["pubmed-910002"]["reason"])
        self.assertEqual(s["pubmed-910001"]["route"], "publish")                               # the healthy neighbour is unaffected
        self.assertTrue(run["ratingsUnchanged"] and run["studiesUnchanged"])
        self.assertEqual(run["leaks"], [])


class HarmWord(unittest.TestCase):
    def weak(self, text):
        return escalation._hits(text, escalation._WEAK)

    def test_harmony_and_other_look_alikes_no_longer_match(self):
        for w in ("harmony", "harmonic", "harmonious", "harmonization", "harmonised", "pharmacological", "Harmon", "charm", "Harmsworth"):
            self.assertEqual([x for x in self.weak(f"The {w} of the study") if x.startswith("harm")], [], w)
        self.assertEqual(self.weak("rhythm, melody, harmony, and tempo"), [])

    def test_real_harm_wording_still_matches(self):
        for w in ("harm", "harms", "harmed", "harming", "harmful", "harmfully", "harmfulness", "harmless", "Harm", "HARMFUL"):
            self.assertIn(w.lower(), self.weak(f"No benefit and possible {w} was seen") + self.weak(f"{w} was seen"), w)

    def test_differential_every_old_match_that_is_not_a_look_alike_is_kept(self):
        old = re.compile(r"\bharm\w*", re.I)                     # the previous pattern
        corpus = "harm harms harmed harming harmful harmfully harmfulness harmless harmony harmonic harmonious harmonization harmonised harmoniously harmed-related"
        lost = {m.group(0).lower() for m in old.finditer(corpus)} - set(self.weak(corpus))
        self.assertEqual(lost, {"harmony", "harmonic", "harmonious", "harmonization", "harmonised", "harmoniously"})     # exactly the look-alikes; every real harm word, "harmless" included, is kept

    def test_the_music_therapy_review_gets_no_weak_flag_but_keeps_its_other_triggers(self):
        item = {"title": "Music Therapy and Tinnitus Treatment: Systematic Review and Meta-Analysis."}
        ev = {"affectedTreatment": "music-therapy", "studyType": "systematic review and meta-analysis", "evidenceDirection": "neutral"}
        t = escalation.triggers(item, "mask tinnitus using rhythm, melody, harmony, and tempo.", ev, {"music-therapy"})
        kinds = [x["kind"] for x in t]
        self.assertNotIn("weak-safety-term", kinds)
        self.assertIn("high-impact-study-on-tracked-treatment", kinds)                          # the R2 hold is untouched

    def test_strong_terms_are_unchanged(self):
        for s in ("seizures", "convulsions", "anaphylaxis", "suicidal", "serious adverse events", "life-threatening", "cardiac arrest", "permanent hearing loss", "product recall", "warning letter"):
            self.assertTrue(escalation._hits(f"Patients reported {s} during follow-up.", escalation._STRONG), s)


class ExclusionWording(unittest.TestCase):
    def trig(self, text):
        t = [x for x in escalation.triggers({"title": "t"}, text, {}, set()) if x["kind"] == "safety-term"]
        return t[0] if t else None

    def test_the_fasa_wording_is_annotated_but_still_a_level_3_hold(self):
        t = self.trig("We analysed 9775 adults, excluding those with a history of cancer, pregnancy or medical conditions known to cause tinnitus, such as stroke, seizures or multiple sclerosis.")
        self.assertIsNotNone(t); self.assertEqual(t["tier"], "level3"); self.assertEqual(t["detail"], ["seizures"]); self.assertEqual(t["exclusionOnly"], ["seizures"])

    def test_it_is_only_an_annotation_every_hold_stays_a_hold(self):
        for s in ("Exclusion criteria: seizure disorder.", "Patients were ineligible if they had a history of seizures.", "Participants with seizures were excluded.",
                  "Excluding patients with suicidal ideation."):
            t = self.trig(s)
            self.assertIsNotNone(t, s); self.assertEqual(t["tier"], "level3", s)

    def test_adversarial_wording_is_not_annotated_as_exclusion_only(self):
        for s in ("Two patients were excluded after seizures occurred.", "Participants were excluded because of seizures.", "Patients who developed seizures were excluded from the analysis.",
                  "Excluded from the analysis: 3 participants following seizures.", "Seizures occurred in 3 patients; 2 were excluded.", "Excluding dropouts, seizures were seen in 4 participants.",
                  "Patients were excluded; seizures were reported in 3.", "After exclusion of non-completers, seizures occurred in 2 patients.", "A 44-year-old woman with a 1-year history of focal seizures.",
                  "Participants who experienced seizures were excluded.", "Excluded: patients who had a seizure during the study.", "Exclusion of 5 patients due to convulsions.",
                  "Seizure was the most common serious adverse event in excluded and included patients alike."):
            t = self.trig(s)
            self.assertIsNotNone(t, s); self.assertEqual(t["tier"], "level3", s); self.assertNotIn("exclusionOnly", t, s)

    def test_a_term_that_is_also_mentioned_outside_the_exclusion_is_not_exclusion_only(self):
        t = self.trig("Patients with seizures were excluded. Seizures occurred in three participants during the trial.")
        self.assertIsNotNone(t); self.assertNotIn("exclusionOnly", t)

    def test_a_mixed_record_annotates_only_the_exclusion_only_term(self):
        t = self.trig("Excluding patients with a history of seizures or suicidal ideation. One participant developed anaphylaxis.")
        self.assertEqual(sorted(t["detail"]), ["anaphylaxis", "seizures", "suicidal"])
        self.assertEqual(t["exclusionOnly"], ["seizures", "suicidal"])

    def test_negated_mentions_are_still_ignored_as_before(self):
        self.assertIsNone(self.trig("No seizures were observed."))

    def test_no_change_for_records_without_exclusion_wording(self):
        t = self.trig("Two patients had seizures.")
        self.assertEqual((t["tier"], t["detail"]), ("level3", ["seizures"])); self.assertNotIn("exclusionOnly", t)

    def test_other_triggers_are_unaffected(self):
        ev = {"affectedTreatment": "acupuncture", "studyType": "randomized controlled trial", "evidenceDirection": "weakens"}
        kinds = [x["kind"] for x in escalation.triggers({"title": "t"}, "Excluding patients with seizures.", ev, {"acupuncture"})]
        self.assertEqual(sorted(kinds), ["bears-on-tracked-treatment", "high-impact-study-on-tracked-treatment", "safety-term"])


if __name__ == "__main__":
    unittest.main()

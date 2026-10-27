"""The owner-approved held-review record changes (engine/approved-record-changes.json, 27 Oct 2026) and the safeguard that allows them.
Proves (1) the data contain exactly the approved edits, (2) the approval list itself is narrow, and (3) unrelated changes made on top of the
approved ones are still caught. Run: python -X utf8 -m unittest discover -s engine/tests"""
import copy, json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import approved_changes as ac

load = lambda f: json.loads((ROOT / f).read_text(encoding="utf-8"))


def published_equivalent(t, s, r, base):
    """The safeguard's rule: undo exactly the approved changes (raises if any is missing or altered), drop notMeasured flags,
    and require the published files exactly. Same steps as test_disclosure_pages / test_phase2_regressions."""
    t, s, r = ac.revert(t, s, r)
    for x in t:
        for k in ("loudness", "distress"):
            x[k].pop("notMeasured", None)
    return (t, s, r) == base


class TestApprovedRecordChanges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = ac.load()
        cls.now = (load("data/treatments.json"), load("data/studies.json"), load("data/rankings.json"))
        bt, bs, br = ac.revert(*cls.now)
        for x in bt:
            for k in ("loudness", "distress"):
                x[k].pop("notMeasured", None)
        cls.base = (bt, bs, br)

    # ---- (1) the data contain exactly the approved edits
    def test_data_files_contain_exactly_the_approved_changes(self):
        self.assertTrue(published_equivalent(*copy.deepcopy(self.now), self.base))

    def test_reverted_data_equal_the_published_files(self):
        # ties the baseline above to what is actually published (the commit test_disclosure_pages compares against), so the
        # mutation tests below are measured against the real public record, not against themselves
        import subprocess
        BASE = "a69020cc76615cfff7827ca3c3d4c438623cb128"
        show = lambda f: json.loads(subprocess.run(["git", "show", f"{BASE}:{f}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout)
        self.assertEqual(self.base, (show("data/treatments.json"), show("data/studies.json"), show("data/rankings.json")))

    def test_apply_then_revert_round_trips(self):
        t, s, r = ac.revert(*self.now)
        self.assertEqual(ac.apply(t, s, r), self.now)

    def test_files_keep_their_exact_serialisation(self):
        for f, obj in zip(("data/treatments.json", "data/studies.json", "data/rankings.json"), self.now):
            self.assertEqual((ROOT / f).read_bytes().decode("utf-8"), ac.dump(obj), f)

    # ---- (2) the approval list is narrow and says what was approved
    def test_only_the_approved_reviews_are_listed(self):
        self.assertEqual([a["heldItem"] for a in self.m["approvals"]],
                         ["classification-review-spi-1005-loudness-2026-10-27", "classification-review-hearing-aids-loudness-2026-10-27",
                          "classification-review-spi-1005-distress-2026-10-27", "classification-review-hearing-aids-loudness-level-2026-10-27",
                          "classification-review-spi-1005-score-2026-10-27"])
        self.assertEqual([(c["id"], [tuple(f["path"]) for f in c["fields"]]) for c in self.m["treatments"]],
                         [("spi-1005", [("loudness", "level"), ("loudness", "summary"), ("studies",)]), ("hearing-aids", [("loudness", "summary")]),
                          ("spi-1005", [("distress", "level"), ("distress", "summary"), ("oneLiner",), ("scoreRationale",)]), ("hearing-aids", [("loudness", "summary")]),
                          ("spi-1005", [("limitations", 1)])])
        self.assertIn("factual wording correction only", self.m["approvals"][-1]["decision"], "the score review stays open")
        self.assertEqual([(c["id"], [tuple(f["path"]) for f in c["fields"]]) for c in self.m["rankings"]["top"]],
                         [("hearing-aids", [("detail", "loudness")]), ("hearing-aids", [("detail", "loudness")])])
        # a later approval of the same field starts exactly where the earlier one ended
        ha = [c for c in self.m["treatments"] if c["id"] == "hearing-aids"]
        self.assertEqual(ha[1]["fields"][0]["from"], ha[0]["fields"][0]["to"])
        rt = self.m["rankings"]["top"]
        self.assertEqual(rt[1]["fields"][0]["from"], rt[0]["fields"][0]["to"])
        self.assertEqual([x["id"] for x in self.m["studiesAdded"]], ["stopmd3-ctgov-results", "spi1005-phase2b-ctgov-results"])

    def test_no_rank_tier_score_or_other_rating_changes(self):
        t, _, r = self.now
        T = {x["id"]: x for x in t}
        bT = {x["id"]: x for x in self.base[0]}
        self.assertEqual([x["id"] for x in r["top"]], [x["id"] for x in self.base[2]["top"]], "Top 10 order unchanged")
        self.assertEqual([x["rank"] for x in r["top"]], [x["rank"] for x in self.base[2]["top"]])
        self.assertEqual(r["history"][-1]["top"], [x["id"] for x in r["top"]], "history note records the unchanged Top 10")
        for tid in T:
            for k in ("tier", "evidenceScore"):
                self.assertEqual(T[tid][k], bT[tid][k], f"{tid} {k}")
            if tid != "spi-1005":
                self.assertEqual(T[tid]["loudness"]["level"], bT[tid]["loudness"]["level"], f"{tid} loudness level")
                nm = lambda d: {k: v for k, v in d.items() if k != "notMeasured"}   # the 26 Oct 'Not measured' flags are a separate, earlier approval
                self.assertEqual(nm(T[tid]["distress"]), bT[tid]["distress"], f"{tid} distress unchanged")
        self.assertEqual((T["spi-1005"]["evidenceScore"], T["spi-1005"]["tier"]), (2, 3), "SPI-1005 score 2/5 and tier kept (separate consistency review)")
        self.assertEqual(T["hearing-aids"]["loudness"]["level"], "limited")
        self.assertEqual(T["somatic-physio"]["loudness"], bT["somatic-physio"]["loudness"], "somatic physiotherapy is on hold")

    def test_spi1005_wording_meets_the_approved_conditions(self):
        spi = {x["id"]: x for x in self.now[0]}["spi-1005"]
        self.assertEqual(spi["loudness"]["level"], "none")
        self.assertNotIn("notMeasured", spi["loudness"], "loudness WAS measured: 'None shown', never 'Not measured'")
        s = spi["loudness"]["summary"]
        for need in ("placebo-controlled", "Ménière's disease", "self-rated tinnitus loudness", "−0.8 vs −0.9", "not yet peer-reviewed", "no loudness data in other kinds of tinnitus"):
            self.assertIn(need, s)
        self.assertNotRegex(s.lower(), r"\b(ineffective|does not work|doesn't work|proven|useless)\b", "no claim of universal ineffectiveness")
        # distress (approved 27 Oct 2026): 'None shown', Ménière's-specific, and the three factual corrections
        self.assertEqual(spi["distress"]["level"], "none"); self.assertNotIn("notMeasured", spi["distress"])
        d = spi["distress"]["summary"]
        for need in ("placebo-controlled", "Ménière's disease", "−7.9 vs −6.6", "open-label extension", "not yet peer-reviewed", "no data in other kinds of tinnitus"):
            self.assertIn(need, d)
        self.assertNotRegex(d.lower(), r"\b(ineffective|does not work|doesn't work|proven|useless)\b")
        self.assertNotIn("unblinded", spi["oneLiner"]); self.assertIn("placebo-controlled", spi["oneLiner"])
        self.assertNotIn("the tinnitus outcomes are open-label", spi["scoreRationale"]); self.assertIn("earns 2/5", spi["scoreRationale"])
        self.assertNotIn("no blinded tinnitus outcome has been published", d)
        lim = spi["limitations"]
        self.assertEqual(len(lim), 3)
        self.assertNotIn("Tinnitus data are open-label PROs", lim)
        self.assertIn("placebo-controlled Ménière's trials", lim[1]); self.assertIn("uncontrolled open-label extension", lim[1])
        self.assertEqual(lim[0], "No peer-reviewed Phase 3 publication yet"); self.assertEqual(lim[2], "Indication is Meniere's, not tinnitus")
        S = {x["id"]: x for x in self.now[1]}
        for sid in ("stopmd3-ctgov-results", "spi1005-phase2b-ctgov-results"):
            self.assertIn(sid, spi["studies"])
            self.assertIn("Registry-only reporting", S[sid]["limitations"]); self.assertIn("Ménière", S[sid]["limitations"])

    def test_hearing_aid_wording_separates_self_rated_from_matched_loudness(self):
        ha = {x["id"]: x for x in self.now[0]}["hearing-aids"]
        line = [x for x in self.now[2]["top"] if x["id"] == "hearing-aids"][0]["detail"]["loudness"]
        for txt in (ha["loudness"]["summary"], line):
            self.assertIn("1.4", txt)
            self.assertRegex(txt, r"(matching it to a tone|tone-matched)")
            self.assertRegex(txt, r"(did not report a statistical comparison|not statistically compared)", "no superiority claim without a statistical comparison")
            self.assertNotRegex(txt.lower(), r"(more than (in )?the other|better than|superior|largest)", "no comparison claim")
            self.assertNotIn("measured loudness did not change", txt)
        self.assertTrue(line.startswith("Limited — ")); self.assertEqual(ha["loudness"]["level"], "limited")

    def test_history_entries_are_appended_and_say_why(self):
        for tid in {c["id"] for c in self.m["treatments"]}:
            rec = {x["id"]: x for x in self.now[0]}[tid]
            base = {x["id"]: x for x in self.base[0]}[tid]
            appended = [h for c in self.m["treatments"] if c["id"] == tid for h in c["appendHistory"]]
            self.assertEqual(rec["history"][:len(base["history"])], base["history"], "earlier history untouched")
            self.assertEqual(rec["history"][len(base["history"]):], appended, "approved entries appended in approval order")
            for h in appended:
                self.assertEqual(h["date"], "2026-10-27"); self.assertIn("Held review 2026-10-27", h["reason"]); self.assertIn("approved by the owner", h["reason"])
        n = len(self.base[2]["history"])
        self.assertEqual(self.now[2]["history"][:n], self.base[2]["history"])
        self.assertEqual(self.now[2]["history"][n:], self.m["rankings"]["appendHistory"])

    # ---- (3) unrelated changes on top of the approved ones are still blocked
    def _blocked(self, mutate):
        t, s, r = copy.deepcopy(self.now)
        mutate({x["id"]: x for x in t}, s, r)
        try:
            ok = published_equivalent(t, s, r, self.base)
        except ac.ApprovedChangeMismatch:
            ok = False
        self.assertFalse(ok, "an unapproved change slipped through the safeguard")

    def test_blocks_another_treatment_rating(self):
        self._blocked(lambda T, s, r: T["hearing-aids"]["loudness"].__setitem__("level", "none"))

    def test_blocks_spi1005_distress_change(self):
        self._blocked(lambda T, s, r: T["spi-1005"]["distress"].__setitem__("level", "moderate"))
        self._blocked(lambda T, s, r: T["spi-1005"]["distress"].__setitem__("summary", T["spi-1005"]["distress"]["summary"] + " Proven ineffective."))
        self._blocked(lambda T, s, r: T["spi-1005"].__setitem__("oneLiner", "changed"))
        self._blocked(lambda T, s, r: T["spi-1005"].__setitem__("scoreRationale", "changed"))

    def test_blocks_other_edits_to_the_spi1005_limitations(self):
        self._blocked(lambda T, s, r: T["spi-1005"]["limitations"].__setitem__(1, "Tinnitus data are open-label PROs"))
        self._blocked(lambda T, s, r: T["spi-1005"]["limitations"].__setitem__(0, "changed"))
        self._blocked(lambda T, s, r: T["spi-1005"]["limitations"].append("extra"))
        self._blocked(lambda T, s, r: T["spi-1005"]["limitations"].pop())

    def test_blocks_the_hearing_aid_wording_being_rolled_back_or_altered(self):
        first = [c for c in ac.load()["treatments"] if c["id"] == "hearing-aids"][0]["fields"][0]["to"]
        self._blocked(lambda T, s, r: T["hearing-aids"]["loudness"].__setitem__("summary", first))
        self._blocked(lambda T, s, r: T["hearing-aids"]["loudness"].__setitem__("summary", T["hearing-aids"]["loudness"]["summary"].replace("1.4", "2.4")))
        self._blocked(lambda T, s, r: T["hearing-aids"]["history"].pop())

    def test_blocks_somatic_physio_change(self):
        self._blocked(lambda T, s, r: T["somatic-physio"]["loudness"].__setitem__("level", "none"))

    def test_blocks_a_different_spi1005_summary(self):
        self._blocked(lambda T, s, r: T["spi-1005"]["loudness"].__setitem__("summary", T["spi-1005"]["loudness"]["summary"] + " It does not work."))

    def test_blocks_spi1005_score_or_tier(self):
        self._blocked(lambda T, s, r: T["spi-1005"].__setitem__("evidenceScore", 1))
        self._blocked(lambda T, s, r: T["spi-1005"].__setitem__("tier", 4))

    def test_blocks_an_unrelated_text_edit(self):
        self._blocked(lambda T, s, r: T["cbt"].__setitem__("oneLiner", T["cbt"]["oneLiner"] + "!"))

    def test_blocks_edited_or_deleted_history(self):
        self._blocked(lambda T, s, r: T["spi-1005"]["history"][0].__setitem__("reason", "rewritten"))
        self._blocked(lambda T, s, r: T["hearing-aids"]["history"].pop(0))
        self._blocked(lambda T, s, r: T["spi-1005"]["history"].append({"date": "2026-10-27", "change": "extra", "reason": "extra"}))

    def test_blocks_extra_or_altered_study_records(self):
        self._blocked(lambda T, s, r: s.append({"id": "unapproved-study", "title": "x"}))
        self._blocked(lambda T, s, r: [x for x in s if x["id"] == "stopmd3-ctgov-results"][0].__setitem__("n", "999"))
        self._blocked(lambda T, s, r: s[0].__setitem__("title", s[0]["title"] + " (edited)"))
        self._blocked(lambda T, s, r: s.pop(0))

    def test_blocks_rank_or_ranking_text_changes(self):
        def swap(T, s, r):
            r["top"][0], r["top"][1] = r["top"][1], r["top"][0]
        self._blocked(swap)
        self._blocked(lambda T, s, r: [x for x in r["top"] if x["id"] == "hearing-aids"][0].__setitem__("rank", 5))
        self._blocked(lambda T, s, r: [x for x in r["top"] if x["id"] == "cbt"][0]["detail"].__setitem__("loudness", "changed"))
        self._blocked(lambda T, s, r: r["history"].pop())

    def test_blocks_a_missing_approved_change(self):
        self._blocked(lambda T, s, r: T["spi-1005"]["loudness"].__setitem__("level", "limited"))

    def test_blocks_a_new_not_measured_flag_on_a_rated_outcome(self):
        # notMeasured is only for outcomes rated none; the real safeguards assert that separately — here: it must not hide a level change
        self._blocked(lambda T, s, r: T["tdcs"]["loudness"].update({"level": "none", "notMeasured": True}))


if __name__ == "__main__":
    unittest.main()

"""The 24-record pilot tools (owner side): the draw, the blind checklist, the reconciliation and the scorer. Offline: the PubMed calls are replaced by synthetic records."""
import csv, io, json, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import pilot_tool as P, pilot_score as S, gold_sampler, registry_record  # noqa: E402

HEAD = "SOURCE: PubMed abstract record\nRECORD COMPLETENESS: COMPLETE - nothing was left out\nCRITICAL SECTIONS MISSING: no\n---\n"
GOOD = ("BACKGROUND: Tinnitus affects many adults. METHODS: In a retrospective cohort of 83 participants we measured the loudness score before and after treatment. RESULTS: The mean score fell by 6.5 points "
        "(95% CI 2.1 to 10.9; p = 0.004) over twelve weeks, and the change was larger in the active group. CONCLUSIONS: The treatment was associated with a modest improvement in this cohort.")


def rec_text(abstract, title="A tinnitus study", marker=""):
    parts = ["1. J Test. 2026;1:1.", title + ".", "Doe J(1).\n\nAuthor information:\n(1)Dept of ENT, Somewhere, Country."]
    return HEAD + "\n\n".join(parts + ([marker] if marker else []) + ([abstract] if abstract else []) + ["DOI: 10.1/x\nPMID: 1"])


def pool(n=500):
    out = []
    for i in range(n):
        k = i % 25
        pts = ["Journal Article"] + (["Randomized Controlled Trial"] if k == 1 else ["Review"] if k in (2, 3) else ["Systematic Review"] if k == 4 else ["Case Reports"] if k == 5 else ["Letter"] if k == 6 else
                                     ["Published Erratum"] if k == 7 else ["Observational Study"] if k in (8, 9) else [])
        out.append({"id": f"pubmed-{3000000 + i}", "title": ("Tinnitus " if i % 3 else "Hearing ") + f"study {i}", "pubtypes": pts, "year": "2026", "lang": ["fre"] if k == 10 else ["chi"] if k == 11 else ["ger"] if k == 12 else ["eng"]})
    return out


def spool(n=40):
    return [{"id": f"pubmed-{4000000 + i}", "title": f"Tinnitus safety study {i}", "pubtypes": ["Journal Article"], "year": "2026", "lang": ["eng"]} for i in range(n)]


def fetch_stub(pmid):
    return rec_text("Short note." if int(pmid) % 7 == 0 else GOOD * 2)


SEED = "owner private seed phrase 123"


class Draw(unittest.TestCase):
    def draw(self, seed=SEED, exclude=(), p=None):
        return P.plan_draw(p or pool(), spool(), seed, set(exclude), fetch=fetch_stub)

    def test_the_24_record_mix(self):
        rows, warn = self.draw()
        self.assertEqual(warn, [])
        self.assertEqual(len(rows), 24); self.assertEqual(len({r["id"] for r in rows}), 24)
        s = [r["stratum"] for r in rows]
        self.assertEqual((s.count("special:notice"), s.count("special:non-english"), s.count("special:safety-query"), s.count("short"), s.count("review-case")), (3, 3, 4, 3, 3))
        self.assertEqual(sum(1 for x in s if x.startswith("ordinary")), 8)
        self.assertGreaterEqual(s.count("ordinary/tinnitus-in-title"), 5)
        short = [r for r in rows if r["stratum"] == "short"]
        for r in short:
            self.assertEqual(int(r["id"].split("-")[1]) % 7, 0)                           # chosen by the abstract-length check, not by label

    def test_deterministic_private_and_excludes_everything_already_seen(self):
        a, b = self.draw()[0], self.draw()[0]
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])
        c = self.draw(seed="a different private phrase 456")[0]
        self.assertNotEqual([r["id"] for r in a], [r["id"] for r in c])
        banned = {r["id"] for r in a}
        d = self.draw(exclude=banned)[0]
        self.assertFalse(banned & {r["id"] for r in d})
        with self.assertRaises(ValueError):
            P.plan_draw(pool(), spool(), "short", set(), fetch=fetch_stub)

    def test_a_thin_pool_is_reported_not_hidden(self):
        thin = [c for c in pool() if "Published Erratum" not in c["pubtypes"]]
        rows, warn = self.draw(p=thin)
        self.assertTrue(any("notice" in w for w in warn)); self.assertEqual(len(rows), 24)         # the shortfall is topped up from the general draw, and reported
        self.assertEqual(sum(1 for r in rows if r["stratum"] == "special:notice"), 0)

    def test_the_output_folder_must_be_outside_the_repository_and_the_draw_is_made_once(self):
        d = Path(tempfile.mkdtemp(prefix="te-pilot-"))
        (d / "records.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            P.cmd_draw(type("A", (), {"out": str(d), "exclude_file": [], "root": None, "term": "x", "mindate": "2026/01/01", "maxdate": "2026/10/01"})())
        self.assertIn("already exists", str(cm.exception))
        shutil.rmtree(d, ignore_errors=True)


def records(n=3):
    return [{"id": f"pubmed-{i}", "title": f"Title {i} <script>alert(1)</script>", "year": "2026", "pubtypes": ["Journal Article"], "language": ["eng"], "text": rec_text(GOOD, f"Title {i}")} for i in range(1, n + 1)]


class Sheet(unittest.TestCase):
    def test_blind_complete_and_escaped(self):
        h = P.make_sheet(records(3) + [{"id": "pubmed-9", "title": "Etude", "year": "2026", "pubtypes": [], "language": ["fre"], "text": rec_text("Les acouphènes sont fréquents.")}])
        for i in (1, 2, 3, 9):
            self.assertIn(f'data-id="pubmed-{i}"', h)
        self.assertEqual(h.count('type="radio"'), 4 * 6 * 2)
        self.assertNotIn("<script>alert(1)</script>", h)                                    # titles are escaped
        self.assertIn("&lt;script&gt;", h)
        self.assertIn('class="cant"', h)                                                    # only the non-English record offers 'cannot read'
        self.assertEqual(h.count('class="cant"'), 1)
        for forbidden in ("automatic reading", "evaluation", "Level 3", "proposedRoute", "language screen"):
            self.assertNotIn(forbidden, h.replace("sticky", ""), forbidden)                  # nothing from the pipeline can anchor the checker
        for k in P.KEYS:
            self.assertIn(k, h)

    def test_javascript_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        import re
        for name, html_ in (("sheet", P.make_sheet(records(2))), ("reconcile", P.make_reconcile(records(2), {r["id"]: {"id": r["id"], **{k: "yes" for k in P.KEYS}, "cannot_read": "no"} for r in records(2)},
                                                                                              [(records(2)[0], "safety", "yes", "no", "")]))):
            js = re.findall(r"<script>(.*?)</script>", html_, re.S)[-1]
            f = Path(tempfile.mkdtemp()) / "x.js"; f.write_text(js, encoding="utf-8")
            r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, name + r.stderr[:400])


class Reading(unittest.TestCase):
    def read(self, abstract, title="A tinnitus study", pubtypes=("Journal Article",)):
        return P.code_reading({"id": "pubmed-1", "title": title, "pubtypes": list(pubtypes), "text": rec_text(abstract, title)})

    def test_the_six_questions(self):
        r = self.read(GOOD)
        self.assertEqual([r[k][0] for k in P.KEYS], ["yes", "yes", "yes", "no", "no", "yes"])
        self.assertEqual(self.read(GOOD + " One participant had a seizure.")["safety"][0], "yes")
        self.assertEqual(self.read(GOOD + " There were no seizures.")["safety"][0], "no")                    # a statement that there were none is No
        self.assertEqual(self.read("")["abstract"][0], "no")
        self.assertEqual(self.read(GOOD, title="Erratum: a tinnitus study")["notice"][0], "yes")
        self.assertEqual(self.read(GOOD, pubtypes=("Published Erratum",))["notice"][0], "yes")
        self.assertEqual(self.read("This approach shows promise for many people.")["results"][0], "no")


def write_answers(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["id"] + P.KEYS + ["cannot_read", "note"])
        for r in rows:
            w.writerow(r)


class Reconcile(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="te-pilot-"))
        self.recs = [{"id": "pubmed-1", "title": "T1", "year": "2026", "pubtypes": [], "language": ["eng"], "text": rec_text(GOOD + " One participant had a seizure.", "T1")},
                     {"id": "pubmed-2", "title": "T2", "year": "2026", "pubtypes": [], "language": ["eng"], "text": rec_text(GOOD, "T2")},
                     {"id": "pubmed-3", "title": "T3", "year": "2026", "pubtypes": [], "language": ["chi"], "text": rec_text("耳鸣是无明确相应外部声源时的声音感知，其发生与听觉信息在丘脑水平的加工处理过程密切相关。本研究纳入八十四例患者，结果显示治疗组评分明显下降。", "T3")}]
        (self.d / "records.json").write_text(json.dumps({"records": self.recs}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_only_disagreements_are_shown_and_cannot_read_rows_are_not_compared(self):
        ans = self.d / "a.csv"
        write_answers(ans, [["pubmed-1", "yes", "yes", "yes", "no", "no", "yes", "no", ""],                    # missed the seizure
                            ["pubmed-2", "yes", "yes", "yes", "yes", "no", "yes", "no", ""],                    # says safety wording where there is none
                            ["pubmed-3", "", "", "", "", "no", "yes", "yes", ""]])
        diffs = P.disagreements(self.recs, P.read_answers(ans))
        self.assertEqual(sorted((r["id"], k) for r, k, *_ in diffs), [("pubmed-1", "safety"), ("pubmed-2", "safety")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            P.cmd_reconcile(type("A", (), {"dir": str(self.d), "answers": str(ans)})())
        html_ = (self.d / "reconcile.html").read_text(encoding="utf-8")
        self.assertIn("pubmed-1", html_); self.assertIn("pubmed-2", html_); self.assertNotIn('data-id="pubmed-3"', html_)
        self.assertIn("seizure", html_)                                                                          # the evidence the code found is shown
        self.assertFalse((self.d / "pilot-final.csv").exists())

    def test_no_disagreement_writes_the_final_file_directly(self):
        ans = self.d / "a.csv"
        write_answers(ans, [["pubmed-1", "yes", "yes", "yes", "yes", "no", "yes", "no", ""], ["pubmed-2", "yes", "yes", "yes", "no", "no", "yes", "no", ""], ["pubmed-3", "", "", "", "", "no", "yes", "yes", ""]])
        with redirect_stdout(io.StringIO()):
            P.cmd_reconcile(type("A", (), {"dir": str(self.d), "answers": str(ans)})())
        rows = list(csv.DictReader(open(self.d / "pilot-final.csv", encoding="utf-8-sig")))
        self.assertEqual(len(rows), 3); self.assertEqual(rows[2]["cannot_read"], "yes")

    def test_incomplete_or_missing_answers_stop_the_tool(self):
        ans = self.d / "a.csv"
        write_answers(ans, [["pubmed-1", "yes", "", "yes", "yes", "no", "yes", "no", ""], ["pubmed-2", "yes", "yes", "yes", "no", "no", "yes", "no", ""], ["pubmed-3", "", "", "", "", "no", "yes", "yes", ""]])
        with self.assertRaises(SystemExit):
            P.cmd_reconcile(type("A", (), {"dir": str(self.d), "answers": str(ans)})())
        write_answers(ans, [["pubmed-1", "yes", "yes", "yes", "yes", "no", "yes", "no", ""]])
        with self.assertRaises(SystemExit):
            P.cmd_reconcile(type("A", (), {"dir": str(self.d), "answers": str(ans)})())


def final_row(i, s="yes", d="yes", r="yes", safety="no", notice="no", abstract="yes", cant="no"):
    return {"id": i, "sample_size": s, "design": d, "results": r, "safety": safety, "notice": notice, "abstract": abstract, "cannot_read": cant}


class Score(unittest.TestCase):
    def setUp(self):
        self.recs = [{"id": f"pubmed-{i}", "title": "t", "pubtypes": ["Journal Article"], "text": rec_text(GOOD)} for i in range(1, 9)]
        self.fin = [final_row(r["id"]) for r in self.recs]
        self.res = {r["id"]: {"outcome": "feed", "causes": []} for r in self.recs}

    def run_(self, **kw):
        return S.score(self.fin, self.recs, self.res, **kw)

    def test_clean_pass_and_clean_holds_reported(self):
        for i in (6, 7, 8):
            self.res[f"pubmed-{i}"] = {"outcome": "held", "causes": [], "primaryCause": "model-not-verified-only"}
        o = self.run_()
        self.assertEqual((o["overall"], o["unsafe"]["count"], o["feedRecommendations"], o["cleanCandidatesHeld"]), ("PASS", 0, 5, 3))
        self.assertEqual(o["cleanCandidatesHeldByCause"], {"model-not-verified-only": 3})
        for i in range(2, 9):
            self.res[f"pubmed-{i}"] = {"outcome": "held", "causes": [], "primaryCause": "model-not-verified-only"}
        self.assertIn("more than half of the clean records were held (usability, not safety)", self.run_()["investigate"])

    def test_each_unsafe_feed_recommendation_fails(self):
        cases = {"notice": dict(notice="yes"), "no-abstract": dict(abstract="no"), "safety-wording": dict(safety="yes"), "no-verifiable-specifics": dict(s="no", d="no", r="no"), "language-unverifiable": dict(cant="yes")}
        for why, kw in cases.items():
            self.fin[0] = final_row("pubmed-1", **kw); self.res["pubmed-1"] = {"outcome": "feed", "causes": []}
            o = self.run_()
            self.assertEqual(o["overall"], "FAIL", why)
            self.assertIn(why, o["ids"]["unsafe"][0][1])

    def test_data_free_review_or_letter_is_not_unsafe_by_that_rule(self):
        self.fin[0] = final_row("pubmed-1", s="no", d="no", r="no"); self.recs[0]["pubtypes"] = ["Review"]; self.res["pubmed-1"] = {"outcome": "feed", "causes": []}
        self.assertEqual(self.run_()["overall"], "PASS")

    def test_a_non_english_abstract_recommended_for_the_feed_fails(self):
        self.recs[0]["text"] = rec_text("耳鸣是无明确相应外部声源时的声音感知，其发生与听觉信息在丘脑水平的加工处理过程密切相关。本研究纳入八十四例患者，结果显示治疗组评分明显下降。")
        self.res["pubmed-1"] = {"outcome": "feed", "causes": []}
        self.assertEqual(self.run_()["overall"], "FAIL")
        self.res["pubmed-1"] = {"outcome": "language-held", "causes": ["language-hold"]}
        self.assertEqual(self.run_()["overall"], "PASS")

    def test_not_scored_when_answers_or_results_are_missing_or_the_run_is_invalid(self):
        self.assertTrue(self.run_(run_valid=False)["overall"].startswith("NOT SCORED"))
        del self.res["pubmed-2"]; self.assertTrue(self.run_()["overall"].startswith("NOT SCORED"))
        self.res["pubmed-2"] = {"outcome": "held"}; self.fin[3]["design"] = ""; self.assertTrue(self.run_()["overall"].startswith("NOT SCORED"))

    def test_investigation_flags_do_not_fail_but_are_not_a_clean_pass(self):
        self.fin[0] = final_row("pubmed-1", safety="yes"); self.res["pubmed-1"] = {"outcome": "held", "causes": ["model-not-verified"]}      # safety wording but never escalated
        o = self.run_()
        self.assertEqual(o["overall"], "PASS WITH INVESTIGATION"); self.assertIn("safety-wording record not escalated to Level 3", o["investigate"])
        self.fin[0] = final_row("pubmed-1"); self.res["pubmed-1"] = {"outcome": "held"}
        self.fin[1] = final_row("pubmed-2", notice="yes"); self.res["pubmed-2"] = {"outcome": "no-outcome"}
        self.assertIn("notice not handled as a notice", self.run_()["investigate"])

    def test_zero_of_ten_bound(self):
        self.assertEqual(S.upper_bound(0, 10), 0.259); self.assertEqual(S.upper_bound(0, 8), 0.312)


if __name__ == "__main__":
    unittest.main()

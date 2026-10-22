"""Tests for the 60-record hidden gold set tooling (gold_sampler special strata and private strata file; gold_agreement). Offline: synthetic pools, no network."""
import csv, io, json, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import gold_sampler as gs  # noqa: E402
import gold_agreement as ga  # noqa: E402

TYPES = [["Randomized Controlled Trial"], ["Systematic Review", "Meta-Analysis"], ["Observational Study"], ["Review"], ["Case Reports"], ["Journal Article"]]
SEED = "owner-private-seed-one"


def pool(n=1500, notices=6, noneng=12):
    out = []
    for i in range(n):
        tin = i % 5 != 0
        c = {"id": f"pubmed-{60000000 + i}", "title": ("Tinnitus outcomes in cohort %d" if tin else "Hearing loss and balance study %d") % i, "pubtypes": list(TYPES[i % 6]), "year": "2024", "lang": ["eng"]}
        if i < notices:
            c["pubtypes"] = ["Retraction of Publication"]
        if notices <= i < notices + noneng:
            c["lang"] = ["chi"]
        out.append(c)
    return out


def safety(n=40):
    return [{"id": f"pubmed-{70000000 + i}", "title": f"Tinnitus and seizure risk report {i}", "pubtypes": ["Journal Article"], "year": "2025", "lang": ["eng"]} for i in range(n)]


SPECIAL = {"notice": 3, "non-english": 5, "safety-query": 5}


class SixtyDraw(unittest.TestCase):
    def draw(self, seed=SEED, exclude=frozenset(), **kw):
        return gs.select_with_report(kw.pop("pool", pool()), seed, 60, set(exclude), special=SPECIAL, safety_pool=safety())

    def test_exactly_60_unique_records_with_the_rare_categories_guaranteed(self):
        rows, warn = self.draw()
        self.assertEqual(len(rows), 60); self.assertEqual(len({r["id"] for r in rows}), 60); self.assertEqual(warn, [])
        n = lambda k: sum(r["stratum"] == "special:" + k for r in rows)
        self.assertGreaterEqual(n("notice"), 3); self.assertGreaterEqual(n("non-english"), 5); self.assertGreaterEqual(n("safety-query"), 5)
        self.assertTrue(all(gs.is_notice(r) for r in rows if r["stratum"] == "special:notice"))
        self.assertTrue(all(gs.is_non_english(r) for r in rows if r["stratum"] == "special:non-english"))
        main = [r for r in rows if not r["stratum"].startswith("special:")]
        self.assertEqual(len(main), 60 - 13)
        titled = sum(r["stratum"].startswith("title/") for r in main)
        self.assertTrue(abs(titled - len(main) / 2) <= 4, titled)                         # about half likely-relevant, half ambiguous

    def test_deterministic_seed_dependent_and_excludes_exposed_records(self):
        a, _ = self.draw(); b, _ = self.draw(); c, _ = self.draw(seed="another-private-seed-2")
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b]); self.assertNotEqual([r["id"] for r in a], [r["id"] for r in c])
        ex = {r["id"] for r in a}                                                          # exclude the whole first draw (including its special records)
        d, _ = self.draw(exclude=ex)
        self.assertFalse({r["id"] for r in d} & ex); self.assertEqual(len(d), 60)

    def test_a_short_rare_stratum_is_reported_not_hidden_and_the_set_is_still_filled(self):
        rows, warn = gs.select_with_report(pool(notices=1, noneng=2), SEED, 60, set(), special=SPECIAL, safety_pool=safety())
        self.assertEqual(len(rows), 60)
        self.assertTrue(any("'notice'" in w and "only 1 of the 3" in w for w in warn)); self.assertTrue(any("'non-english'" in w for w in warn))

    def test_old_call_without_special_still_works(self):
        rows = gs.select(pool(), SEED, 60, set())
        self.assertEqual(len(rows), 60); self.assertFalse(any(r["stratum"].startswith("special:") for r in rows))


class Files(unittest.TestCase):
    def run_main(self, tmp, extra=()):
        out = Path(tmp) / "private" / "candidates.csv"; out.parent.mkdir()
        root = Path(tmp) / "clone"; (root / "data").mkdir(parents=True)
        calls = []

        def fake_fetch(term, a, b):
            calls.append(term)
            return safety() if "seizure" in term else pool()
        buf = io.StringIO()
        with mock.patch.object(gs, "fetch_pool", fake_fetch), redirect_stdout(buf):
            gs.main(["--seed", SEED, "--n", "60", "--root", str(root), "--out", str(out), *extra])
        return out, buf.getvalue(), calls

    def test_candidate_file_has_no_labels_strata_or_seed_and_a_separate_owner_file_exists(self):
        with tempfile.TemporaryDirectory() as t:
            out, printed, calls = self.run_main(t)
            text = out.read_text(encoding="utf-8-sig")
            self.assertNotIn(SEED, text); self.assertNotIn(SEED, printed); self.assertNotIn("special:", text); self.assertNotIn("stratum", text.splitlines()[0])
            rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
            self.assertEqual(len(rows), 60); self.assertTrue(all(r[c] == "" for r in rows for c in gs.LABEL_COLUMNS))
            self.assertIn("language", rows[0])
            self.assertEqual(open(out, "rb").read(3), b"\xef\xbb\xbf")                      # BOM so Excel shows accents
            strata = Path(str(out) + ".strata.csv"); self.assertTrue(strata.exists())
            st = list(csv.DictReader(open(strata, encoding="utf-8")))
            self.assertEqual({r["id"] for r in st}, {r["id"] for r in rows}); self.assertTrue(any(r["stratum"] == "special:safety-query" for r in st))
            self.assertIn("Commitment SHA-256", printed); self.assertEqual(len(calls), 2)   # main query + safety query

    def test_without_a_seed_argument_the_seed_comes_from_a_hidden_prompt_and_must_match_twice(self):
        with tempfile.TemporaryDirectory() as t:
            fake = iter([SEED, SEED])
            with mock.patch.object(gs.getpass, "getpass", lambda prompt="": next(fake)):
                out, printed, _ = self.run_main_noseed(t)
            self.assertNotIn(SEED, printed); self.assertNotIn(SEED, out.read_text(encoding="utf-8-sig"))
            a = [r["id"] for r in csv.DictReader(open(out, encoding="utf-8-sig"))]
        with tempfile.TemporaryDirectory() as t:                                           # the same seed typed at the prompt gives the same draw as --seed
            out2, _, _ = self.run_main(t)
            b = [r["id"] for r in csv.DictReader(open(out2, encoding="utf-8-sig"))]
        self.assertEqual(a, b)
        with tempfile.TemporaryDirectory() as t, self.assertRaises(SystemExit):
            mism = iter([SEED, SEED + "x"])
            with mock.patch.object(gs.getpass, "getpass", lambda prompt="": next(mism)):
                self.run_main_noseed(t)
        with tempfile.TemporaryDirectory() as t, self.assertRaises(SystemExit):
            short = iter(["short", "short"])
            with mock.patch.object(gs.getpass, "getpass", lambda prompt="": next(short)):
                self.run_main_noseed(t)

    def run_main_noseed(self, tmp):
        out = Path(tmp) / "private" / "candidates.csv"; out.parent.mkdir()
        root = Path(tmp) / "clone"; (root / "data").mkdir(parents=True)
        buf = io.StringIO()
        with mock.patch.object(gs, "fetch_pool", lambda term, a, b: safety() if "seizure" in term else pool()), redirect_stdout(buf):
            gs.main(["--n", "60", "--root", str(root), "--out", str(out)])
        return out, buf.getvalue(), None

    def test_clinician_only_columns_are_separate_and_technical_columns_cover_all_four_labels(self):
        for who in ("labeller1", "labeller2", "adjudicated"):
            for f in gs.TECH:
                self.assertIn(f"{who}_{f}", gs.LABEL_COLUMNS)
        self.assertEqual(len([c for c in gs.LABEL_COLUMNS if c.startswith("CLINICIAN_ONLY")]), 4)

    def test_exclude_file_accepts_csv_and_text_with_ids_urls_and_bare_pmids(self):
        with tempfile.TemporaryDirectory() as t:
            txt = Path(t) / "e.txt"; txt.write_text("pubmed-12345678\nhttps://pubmed.ncbi.nlm.nih.gov/23456789/\n34567890 and the year 2026 and 12345\n", encoding="utf-8")
            self.assertEqual(gs.read_exclude_file(txt), {"pubmed-12345678", "pubmed-23456789", "pubmed-34567890"})
            c = Path(t) / "e.csv"; c.write_text("﻿id,title\npubmed-1111111,x\n", encoding="utf-8")
            self.assertEqual(gs.read_exclude_file(c), {"pubmed-1111111"})

    def test_refuses_to_write_inside_the_repository_even_with_a_custom_root(self):
        with tempfile.TemporaryDirectory() as t, self.assertRaises(SystemExit):
            gs.main(["--seed", SEED, "--root", t, "--out", str(Path(t) / "sub" / "c.csv")])


def labelled(n=60, disagree=(), regroup=(), clin=False):
    rows = []
    for i in range(n):
        r = {"id": f"pubmed-{i}"}
        rel = str(1 + i % 6)
        for who in ("labeller1", "labeller2", "adjudicated"):
            r[f"{who}_relevance_1to6"] = rel; r[f"{who}_study_type"] = ["rct", "observational", "review-other"][i % 3]
            r[f"{who}_abstract_present"] = "yes"; r[f"{who}_notice_type"] = "none"
            r[f"{who}_has_sample_size"] = "yes" if i % 4 else "no"; r[f"{who}_has_design"] = "yes"; r[f"{who}_has_result_figures"] = "yes" if i % 3 else "no"; r[f"{who}_safety_wording"] = "yes" if i % 10 == 0 else "no"
        if i in disagree:
            r["labeller2_study_type"] = "other"; r["adjudicated_study_type"] = ""
        if i in regroup:
            r["labeller2_relevance_1to6"] = {"1": "2", "2": "1", "3": "4", "4": "3", "5": "6", "6": "5"}[rel]; r["adjudicated_relevance_1to6"] = rel
        for c in ("CLINICIAN_ONLY_evidence_direction",):
            r[c] = "weakens" if clin else ""
        rows.append(r)
    return rows


class Agreement(unittest.TestCase):
    def test_kappa_known_values(self):
        a = ["y"] * 20 + ["y"] * 5 + ["n"] * 10 + ["n"] * 15
        b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
        k, po = ga.kappa(a, b)
        self.assertAlmostEqual(k, 0.4, 6); self.assertAlmostEqual(po, 0.7, 6)
        self.assertEqual(ga.kappa(["a", "b"], ["a", "b"])[0], 1.0)
        self.assertIsNone(ga.kappa(["a", "a"], ["a", "a"])[0])                             # undefined, not 1
        self.assertEqual(ga.kappa([], []), (None, None))

    def test_perfect_agreement_is_ready_and_one_unadjudicated_disagreement_is_not(self):
        self.assertTrue(ga.analyse(labelled())["ready"])
        r = ga.analyse(labelled(disagree={3}))
        self.assertFalse(r["ready"]); self.assertEqual(r["unresolved_ids"], ["pubmed-3"]); self.assertTrue(any("unadjudicated" in x for x in r["notReadyBecause"]))

    def test_unlabelled_records_block_readiness(self):
        rows = labelled(); rows[5]["labeller2_relevance_1to6"] = ""
        r = ga.analyse(rows); self.assertFalse(r["ready"]); self.assertEqual(r["both_complete"], 59)

    def test_grouped_relevance_forgives_neighbouring_categories_but_the_six_way_does_not(self):
        r = ga.analyse(labelled(regroup=set(range(0, 60, 2))))
        self.assertEqual(r["fields"]["relevance_group"]["kappa"], 1.0)
        self.assertLess(r["fields"]["relevance_1to6"]["kappa"], 1.0)
        self.assertEqual(r["fields"]["relevance_1to6"]["disagreements"], 30)

    def test_clinician_columns_are_counted_but_change_no_technical_number(self):
        a, b = ga.analyse(labelled()), ga.analyse(labelled(clin=True))
        self.assertEqual(a["clinician_columns_filled"], 0); self.assertEqual(b["clinician_columns_filled"], 60)
        self.assertEqual(a["fields"], b["fields"]); self.assertEqual(a["ready"], b["ready"])

    def test_report_prints_no_ids_unless_asked_and_always_states_the_limit(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "l.csv"
            rows = labelled(disagree={3})
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ga.main(["--labels", str(p)])
            self.assertEqual(rc, 1); self.assertNotIn("pubmed-3", buf.getvalue()); self.assertIn("do not establish clinical validity", buf.getvalue())
            buf = io.StringIO()
            with redirect_stdout(buf):
                ga.main(["--labels", str(p), "--list-disagreements"])
            self.assertIn("pubmed-3", buf.getvalue())

    def test_bootstrap_interval_is_reproducible_and_brackets_the_estimate_for_noisy_labels(self):
        rows = labelled(); import random as _r
        rng = _r.Random(3)
        for r in rows:
            if rng.random() < 0.2:
                r["labeller2_study_type"] = "other"
        res = ga.analyse(rows)["fields"]["study_type"]
        self.assertEqual(res, ga.analyse(rows)["fields"]["study_type"])
        lo, hi = res["kappa95CI"]; self.assertTrue(lo <= res["kappa"] <= hi)


class CueLabels(unittest.TestCase):
    def test_the_cue_and_safety_labels_exist_as_technical_columns_and_are_scored(self):
        for who in ("labeller1", "labeller2", "adjudicated"):
            for f in ("has_sample_size", "has_design", "has_result_figures", "safety_wording"):
                self.assertIn(f"{who}_{f}", gs.LABEL_COLUMNS)
        r = ga.analyse(labelled())
        self.assertTrue(r["cueLabelsInterpretable"]); self.assertEqual(set(r["cueKappas"]), {"has_sample_size", "has_design", "has_result_figures", "safety_wording"})

    def test_poor_agreement_on_a_cue_makes_the_backstop_measurement_uninterpretable_but_not_the_set_unusable(self):
        rows = labelled()
        for i, r in enumerate(rows):
            if i % 2:
                r["labeller2_has_result_figures"] = "no" if r["labeller1_has_result_figures"] == "yes" else "yes"
        res = ga.analyse(rows)
        self.assertFalse(res["cueLabelsInterpretable"]); self.assertLess(res["cueKappas"]["has_result_figures"], 0.7)
        self.assertGreater(res["fields"]["has_result_figures"]["disagreements"], 0)

    def test_a_missing_cue_label_blocks_readiness(self):
        rows = labelled(); rows[7]["labeller2_safety_wording"] = ""
        res = ga.analyse(rows); self.assertFalse(res["ready"]); self.assertEqual(res["both_complete"], 59)


if __name__ == "__main__":
    unittest.main()

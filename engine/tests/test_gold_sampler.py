"""Tests for engine/gold_sampler.py (hidden gold-set candidate draw). Offline: the PubMed pool is synthetic; no network."""
import csv, json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import gold_sampler as gs  # noqa: E402

TYPES = [["Randomized Controlled Trial"], ["Systematic Review", "Meta-Analysis"], ["Observational Study"], ["Review"], ["Case Reports"], ["Journal Article"]]


def pool(n=1200):
    out = []
    for i in range(n):
        tin = i % 5 != 0
        out.append({"id": f"pubmed-{50000000 + i}", "title": ("Tinnitus outcomes in cohort %d" if tin else "Hearing loss and balance study %d") % i, "pubtypes": TYPES[i % 6], "year": "2024"})
    return out


class Draw(unittest.TestCase):
    def test_deterministic_for_one_seed_and_different_for_another(self):
        a = gs.select(pool(), "owner-private-seed-one", 120, set())
        b = gs.select(pool(), "owner-private-seed-one", 120, set())
        c = gs.select(pool(), "owner-private-seed-two", 120, set())
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])
        self.assertNotEqual([r["id"] for r in a], [r["id"] for r in c])
        self.assertEqual(len(a), 120)
        self.assertEqual(gs.commitment(a), gs.commitment(b)); self.assertNotEqual(gs.commitment(a), gs.commitment(c))

    def test_a_short_seed_is_refused(self):
        with self.assertRaises(ValueError):
            gs.select(pool(), "short", 10, set())

    def test_exposed_records_are_never_drawn(self):
        exclude = {r["id"] for r in pool()[:900]}
        rows = gs.select(pool(), "owner-private-seed-one", 100, exclude)
        self.assertFalse({r["id"] for r in rows} & exclude)

    def test_strata_are_all_represented(self):
        rows = gs.select(pool(), "owner-private-seed-one", 120, set())
        strata = {r["stratum"] for r in rows}
        self.assertTrue(any(s.startswith("title/") for s in strata) and any(s.startswith("no-tinnitus-in-title/") for s in strata))
        for typ in ("rct", "systematic-review", "observational", "review-other", "case-or-letter", "other"):
            self.assertTrue(any(s.endswith("/" + typ) for s in strata), typ)

    def test_study_type_mapping(self):
        self.assertEqual(gs.study_type(["Randomized Controlled Trial", "Journal Article"]), "rct")
        self.assertEqual(gs.study_type(["Meta-Analysis"]), "systematic-review")
        self.assertEqual(gs.study_type(["Letter"]), "case-or-letter")
        self.assertEqual(gs.study_type(["Journal Article"]), "other")


class ExposureAndOutput(unittest.TestCase):
    def test_everything_the_project_has_seen_is_in_the_exposed_set(self):
        ex = gs.exposed_ids(REPO)
        self.assertTrue({i["id"] for i in real_queue()} <= ex)
        self.assertIn("pubmed-42839938", ex)                                              # a test fixture
        cited = {"pubmed-" + str(s["pmid"]) for s in real_studies() if s.get("pmid")}
        self.assertTrue(cited <= ex)
        known = set(json.loads((ENGINE / "known_ids.json").read_text(encoding="utf-8")))
        self.assertTrue(known <= ex)                                                      # every id the scanner has ever seen

    def test_the_candidate_file_carries_no_labels_and_never_the_seed(self):
        rows = gs.select(pool(), "owner-private-seed-one", 30, set())
        d = Path(tempfile.mkdtemp()); out = d / "c.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["id", "year", "pubtypes", "title", "stratum"] + gs.LABEL_COLUMNS); w.writeheader()
            for r in rows:
                w.writerow({"id": r["id"], "year": r["year"], "pubtypes": ";".join(r["pubtypes"]), "title": r["title"], "stratum": r["stratum"]})
        text = out.read_text(encoding="utf-8")
        self.assertNotIn("owner-private-seed-one", text)
        for r in csv.DictReader(open(out, encoding="utf-8")):
            self.assertTrue(all(r[c] == "" for c in gs.LABEL_COLUMNS))                     # nothing pre-labelled, nothing from the AI
        self.assertTrue([c for c in gs.LABEL_COLUMNS if c.startswith("CLINICIAN_ONLY")])   # clinical judgements have their own, separate columns

    def test_the_tool_refuses_to_write_inside_the_public_repository(self):
        with self.assertRaises(SystemExit):
            gs.main(["--seed", "owner-private-seed-one", "--out", str(REPO / "candidates.csv")])


if __name__ == "__main__":
    unittest.main()

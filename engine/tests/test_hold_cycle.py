"""The real fetch, the real hold check and the real weekly cycle together, with only the network answer stubbed. A hold must keep a record off the public list, and a fault in the check must stop a listing, never pass it as clean.
Run:  python -m unittest discover -s engine/tests -v"""
import contextlib, io, json, shutil, sys, tempfile, unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, ctgov_item, pubmed_item   # noqa: E402

import check_retractions, evaluate_queue, topic_holds, triage, weekly_cycle, weekly_scan   # noqa: E402

TODAY = date.today().isoformat()
FACTS = {"tinAbs": 4, "tinMesh": True, "tracked": [], "safety": [], "safetyWeak": [], "animalOnly": False, "hasAbstract": True}
PAUSED_ITEM = pubmed_item(990001, "A routine tinnitus trial", source="J Audiol", triage=FACTS)
A, B = "NCT99000777", "NCT99000778"
HUGE = "&#" + "9" * 5000 + ";"


def trial(nct, summary="Registry update - needs evaluation."):
    return ctgov_item(nct, title=f"A tinnitus trial of sound therapy {nct}", source="ClinicalTrials.gov", date="2026-10-13", summary=summary)


def study(nct=A, detail="A description.", sites="A Clinic"):
    title = f"A tinnitus trial of sound therapy {nct}"
    return {"protocolSection": {"identificationModule": {"nctId": nct, "briefTitle": title, "officialTitle": title, "organization": {"fullName": "A University"}},
                                "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-10-13"}}, "sponsorCollaboratorsModule": {"leadSponsor": {"name": "A University"}},
                                "descriptionModule": {"briefSummary": "A study of tinnitus.", "detailedDescription": detail}, "conditionsModule": {"conditions": ["Tinnitus"]}, "eligibilityModule": {"eligibilityCriteria": "Adults."},
                                "designModule": {"studyType": "INTERVENTIONAL"}, "armsInterventionsModule": {"interventions": [{"name": "Sound therapy", "type": "BEHAVIORAL"}]},
                                "contactsLocationsModule": {"locations": [{"facility": sites}]}}, "derivedSection": {"miscInfoModule": {"versionHolder": "2026-11-01"}}, "hasResults": False}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="te-hc-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        rel = {"engine/paused_ids.json": {"comment": "x", "ids": [PAUSED_ITEM["id"]]}, "engine/topic_holds.json": json.loads((ENGINE / "topic_holds.json").read_text(encoding="utf-8")),
               "engine/scan-state.json": {"pubmed": TODAY, "ctgov": TODAY}, "engine/sources.json": {"feeds": [{"name": "a", "url": "https://example.invalid/a"}], "newsIntel": [{"name": "n", "query": "tinnitus"}], "pages": [{"name": "b", "url": "https://example.invalid/b"}]},
               "engine/page-hashes.json": {"https://example.invalid/b": "abc"}, "engine/retraction-state.json": {"lastRun": TODAY}, "engine/triage_rules.json": json.loads((ENGINE / "triage_rules.json").read_text(encoding="utf-8")),
               "engine/published_ids.json": ["somepublishedkey"], "engine/eval_settings.json": {"enabled": False, "mode": "staged"}, "engine/automation_settings.json": {"listings": True, "updateHistory": True},
               "data/review-queue/archive.json": {"items": [], "emptyOnPurpose": True}, "data/review-queue/held.json": {"items": []}, "data/weekly/index.json": {"reports": [{"date": "2026-01-01", "file": "2026-01-01.json", "title": "x"}]}, "data/weekly/2026-01-01.json": {"items": []},
               "data/trials.json": [], "data/studies.json": [{"id": "s1", "title": "A study", "year": 2020}], "data/treatments.json": [{"id": "cbt", "name": "CBT"}], "data/listings.json": {"version": 1, "count": 0, "items": []}, "data/update-history.json": {"version": 1, "entries": []}}
        for r, o in rel.items():
            self.W(r, o)
        self.answers = {}
        self.addCleanup(setattr, evaluate_queue, "_get", evaluate_queue._get)
        evaluate_queue._get = self.stub_get
        evaluate_queue.RECORD_FULL.clear()
        evaluate_queue.RECORD_META.clear()

    def W(self, rel, obj):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")

    def J(self, rel):
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def stub_get(self, url, attempts=3):
        for k, v in self.answers.items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                return v if isinstance(v, bytes) else json.dumps(v, ensure_ascii=False).encode("utf-8")
        raise OSError("no answer for this address in the test")

    def put(self, *items):
        self.W("data/review-queue/queue.json", {"items": [PAUSED_ITEM, *items]})
        self.W("engine/known_ids.json", sorted({PAUSED_ITEM["id"], *(i["id"] for i in items)}))

    def cycle(self):
        saved = {n: getattr(weekly_scan, n) for n in ("scan_pubmed", "scan_ctgov", "scan_feeds", "scan_fda", "scan_news_intel", "scan_pages")}
        for n in saved:
            setattr(weekly_scan, n, lambda: [])
        due, eng, argv, fx = check_retractions.due, weekly_cycle.ENGINE, sys.argv, triage.fetch_xml
        check_retractions.due, weekly_cycle.ENGINE, sys.argv, triage.fetch_xml = (lambda *a, **k: False), self.root / "engine", ["weekly_cycle.py"], (lambda ids: None)
        out, rc = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                weekly_cycle.main()
        except SystemExit as e:
            rc = e.code or 0
        finally:
            for n, f in saved.items():
                setattr(weekly_scan, n, f)
            check_retractions.due, weekly_cycle.ENGINE, sys.argv, triage.fetch_xml = due, eng, argv, fx
        return rc, out.getvalue()

    def listed(self):
        return {e["key"] for e in self.J("data/listings.json")["items"]}

    def mark(self, item):
        return next(i for i in self.J("data/review-queue/queue.json")["items"] if i["id"] == item["id"]).get("topicHold")


class ThroughTheRealCycle(Base):
    def test_a_clean_record_is_listed_so_the_tests_below_are_not_passing_because_nothing_ever_lists(self):
        self.put(trial(A))
        self.answers = {A: study()}
        rc, out = self.cycle()
        self.assertEqual(rc, 0, out[-400:])
        self.assertIn(A, self.listed())

    def test_a_name_only_in_a_field_the_compact_text_leaves_out_is_held(self):
        for name, s in (("a site", study(sites="Neuromod Devices Test Centre")), ("a site after a line break", study(sites="Clinic\nLenire centre")), ("after a line break, past the cut", study(detail=" ".join(["word"] * 8000) + "\nLenire device"))):
            with self.subTest(name):
                self.put(trial(A))
                self.W("data/listings.json", {"version": 1, "count": 0, "items": []})
                self.answers = {A: s}
                rc, out = self.cycle()
                self.assertEqual(rc, 0, out[-400:])
                self.assertNotIn(A, self.listed())
                self.assertEqual(self.mark(trial(A)), "lenire-neuromod")

    def test_the_held_record_does_not_stop_a_clean_one(self):
        self.put(trial(A), trial(B))
        self.answers = {A: study(A, detail="x\nLenire"), B: study(B)}
        self.cycle()
        self.assertEqual(self.listed(), {B})

    def test_a_name_nested_as_deep_as_a_real_answer_can_arrive_is_held(self):
        deep = "x\nLenire"
        for _ in range(500):
            deep = [deep]
        self.put(trial(A))
        self.answers = {A: {**study(), "extra": deep}}
        rc, out = self.cycle()
        self.assertEqual(rc, 0, out[-400:])
        self.assertNotIn(A, self.listed())
        self.assertEqual(self.mark(trial(A)), "lenire-neuromod")

    def test_an_answer_too_deep_for_the_json_reader_lists_nothing(self):
        """The JSON reader stops here, before the hold check. This guards existing handling; it cannot show that the hold check works."""
        self.put(trial(A))
        self.answers = {A: b'{"x": ' + b"[" * 200000 + b"1" + b"]" * 200000 + b"}"}
        rc, out = self.cycle()
        self.assertEqual(rc, 0, out[-400:])
        self.assertNotIn(A, self.listed())


class TheOwnerLiftsTheHold(Base):
    def test_the_mark_goes_and_the_record_is_listed(self):
        self.put({**trial(A), "topicHold": "lenire-neuromod"})
        self.W("engine/topic_holds.json", {"holds": [], "emptyOnPurpose": True})
        self.answers = {A: study(A, detail="x\nLenire")}
        rc, out = self.cycle()
        self.assertEqual(rc, 0, out[-400:])
        self.assertIsNone(self.mark(trial(A)))
        self.assertIn(A, self.listed())


class OversizedEntities(Base):
    def test_in_a_record_it_stops_nothing_and_hides_nothing(self):
        self.put(trial(A), trial(B))
        self.answers = {A: study(A, detail="x " + HUGE), B: study(B)}
        rc, out = self.cycle()
        self.assertEqual(rc, 0, out[-400:])
        self.assertEqual(self.listed(), {A, B}, "one strange character must not stop every listing")

    def test_beside_a_held_name_the_record_is_still_held(self):
        for name, detail in (("after", HUGE + " Lenire"), ("before", "Lenire " + HUGE), ("on the next line", HUGE + "\nLenire"), ("twice encoded", "&amp;#" + "9" * 5000 + "; Lenire")):
            with self.subTest(name):
                self.put(trial(A))
                self.W("data/listings.json", {"version": 1, "count": 0, "items": []})
                self.answers = {A: study(A, detail=detail)}
                rc, out = self.cycle()
                self.assertEqual(rc, 0, out[-400:])
                self.assertNotIn(A, self.listed())
                self.assertEqual(self.mark(trial(A)), "lenire-neuromod")

    def test_in_a_queue_item_it_does_not_stop_the_run(self):
        for name, it in (("summary", trial(A, summary=HUGE)), ("title", {**trial(A), "title": trial(A)["title"] + " " + HUGE})):
            with self.subTest(name):
                self.put(it, trial(B))
                self.W("data/listings.json", {"version": 1, "count": 0, "items": []})
                (self.root / "data/engine-status.json").unlink(missing_ok=True)     # a fresh start: preflight would rightly refuse emptied listings after a run that left some
                self.answers = {A: study(A), B: study(B)}
                rc, out = self.cycle()
                self.assertEqual(rc, 0, out[-400:])
                self.assertIn(B, self.listed())
                self.assertNotIn("listings step failed", json.dumps(self.J("data/engine-status.json")))


class AFaultInTheCheckNeverReadsAsClean(Base):
    def test_a_fault_in_the_text_forms_reaches_the_caller(self):
        """If this were swallowed and read as no hold, every record could list."""
        with mock.patch.object(topic_holds, "_plain", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                topic_holds.match_item({"id": "x", "title": "Anything"}, topic_holds.load_holds(ENGINE / "topic_holds.json"))

    def test_a_fault_on_the_record_lists_nothing(self):
        """Existing handling of a fault, guarded so that no change weakens it. It cannot show that the hold check works."""
        self.put(trial(A))
        self.answers = {A: study()}
        real = topic_holds.match_item

        def fault(it, holds=None, extra_text=""):
            if extra_text:
                raise RuntimeError("injected")
            return real(it, holds, extra_text)
        with mock.patch.object(topic_holds, "match_item", fault):
            rc, out = self.cycle()
        self.assertNotIn(A, self.listed())
        self.assertIn("listings step failed", json.dumps(self.J("data/engine-status.json")))

    def test_a_fault_everywhere_stops_the_run_and_lists_nothing(self):
        self.put(trial(A))
        self.answers = {A: study()}
        with mock.patch.object(topic_holds, "_plain", side_effect=RuntimeError("injected")):
            rc, out = self.cycle()
        self.assertNotEqual(rc, 0, "the run must not end as if nothing happened")
        self.assertNotIn(A, self.listed())

    def test_a_fault_reading_the_record_lists_nothing(self):
        self.put(trial(A))
        self.answers = {A: study()}
        with mock.patch.object(topic_holds, "record_text", side_effect=RuntimeError("injected")):
            rc, out = self.cycle()
        self.assertEqual(rc, 0, out[-400:])
        self.assertNotIn(A, self.listed())


if __name__ == "__main__":
    unittest.main()

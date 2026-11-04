"""E1-D. Once a record carries a hold mark, nothing a source says removes it: only the owner, by lifting the whole hold or by a per-record release in engine/hold_releases.json. The real fetch, the real hold check and the real cycle together, with only the network answer stubbed.
Run:  python -m unittest discover -s engine/tests -v"""
import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ctgov_item, pubmed_item, run_scenario   # noqa: E402
from cycle_sandbox import ITEM, KNOWN, QUEUE, Sandbox, W   # noqa: E402
from test_hold_cycle import A, B, FACTS, PAUSED_ITEM, Base, study, trial   # noqa: E402

import state_files   # noqa: E402

HOLD = "lenire-neuromod"
REL = "engine/hold_releases.json"
OTHER_HOLD = {"id": "other-topic", "label": "Another topic", "patterns": ["\\bacoustic crown\\b"]}
LENIRE_HOLD = {"id": HOLD, "label": "Lenire", "patterns": ["\\blenire\\b", "\\bTENT-[ABC]\\d?\\b"]}


def release(record, hold=HOLD):
    return {"recordId": record, "holdId": hold, "decidedOn": "2026-11-01", "reason": "Not the held topic."}


def pm(n=990501):
    return pubmed_item(n, f"A tinnitus study {n}", source="J Audiol", triage=FACTS)


def pm_answer(n=990501, extra=""):
    return f"1. J Audiol. 2026.\n\nA tinnitus study {n}.\n\nSmith J.\n\nMethods: randomized controlled trial; 83 participants were randomized. Results: the mean score fell by 6.5 points (95% CI 2.1 to 10.9; p=0.004).{extra}\n\nPMID: {n}\n".encode("utf-8")


class Case(Base):
    def status(self):
        return self.J("data/engine-status.json")

    def marks(self):
        return {i["id"]: i["topicHold"] for i in self.J("data/review-queue/queue.json")["items"] if i.get("topicHold")}

    def go(self):
        rc, out = self.cycle()
        self.assertEqual(rc, 0, out[-400:])
        return out

    def asked(self):
        """Every record address the run asked for."""
        return [u for u in self.urls]

    def stub_get(self, url, attempts=3):
        self.urls.append(url)
        return super().stub_get(url, attempts)

    def setUp(self):
        self.urls = []
        super().setUp()


class NothingASourceSaysRemovesAMark(Case):
    def test_the_control_the_same_answers_list_a_record_with_no_mark(self):
        """Without this, the tests below could pass only because nothing can list."""
        self.put(trial(A))
        self.answers = {A: study(A)}
        self.go()
        self.assertEqual(self.listed(), {A})

    def test_no_answer_of_any_kind_removes_a_registry_mark(self):
        for name, answer in (("the record without the name", study(A)), ("a failed fetch", OSError("down")), ("another record", study(B)), ("an empty answer", {}), ("an error message", {"error": "try later"}), ("not JSON", b"<html>busy</html>")):
            with self.subTest(name):
                self.put({**trial(A), "topicHold": HOLD})
                self.answers = {A: answer}
                self.go()
                self.assertEqual(self.marks(), {trial(A)["id"]: HOLD})
                self.assertEqual(self.listed(), set())

    def test_no_answer_of_any_kind_removes_a_pubmed_mark(self):
        it = pm()
        for name, answer in (("the record without the name", pm_answer()), ("a failed fetch", OSError("down")), ("an empty answer", b"")):
            with self.subTest(name):
                self.put({**it, "topicHold": HOLD})
                self.answers = {"efetch": answer, "esummary": {"result": {"990501": {"pubtype": []}}}}
                self.go()
                self.assertEqual(self.marks(), {it["id"]: HOLD})
                self.assertEqual(self.listed(), set())

    def test_it_holds_through_many_runs_and_the_record_is_not_even_fetched(self):
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: study(A)}
        for _ in range(4):
            self.go()
            self.assertEqual(self.marks(), {trial(A)["id"]: HOLD})
        self.assertEqual(self.listed(), set())
        self.assertEqual([u for u in self.urls if A in u], [], "nothing a source says could change this, so it is not asked")

    def test_a_mark_found_by_the_record_stays_when_the_record_later_drops_the_name(self):
        self.put(trial(A))
        self.answers = {A: study(A, detail="x\nLenire")}
        self.go()
        self.assertEqual(self.marks(), {trial(A)["id"]: HOLD})
        self.answers = {A: study(A)}
        self.go()
        self.assertEqual(self.marks(), {trial(A)["id"]: HOLD})
        self.assertEqual(self.listed(), set())

    def test_a_mark_on_a_record_the_listing_step_never_visits_stays(self):
        news = {"id": "newsintel-x-1", "kind": "news", "title": "A plain headline", "source": "Wire", "summary": "", "url": "https://example.invalid/x", "intelligenceOnly": True, "topicHold": HOLD}
        self.put(news)
        self.go()
        self.assertEqual(self.marks(), {"newsintel-x-1": HOLD})


class ANewerEntryOfTheSameRecord(Case):
    def older(self, **k):
        return {**ctgov_item(A, title=f"A tinnitus trial of sound therapy {A}", source="ClinicalTrials.gov", date="2026-09-01"), **k}

    def test_it_takes_on_the_older_entrys_mark_whatever_its_own_record_says(self):
        self.put(self.older(topicHold=HOLD), trial(A))
        self.answers = {A: study(A)}
        self.go()
        self.assertEqual(self.marks(), {self.older()["id"]: HOLD, trial(A)["id"]: HOLD})
        self.assertEqual(self.listed(), set())

    def test_a_hold_only_the_older_entrys_title_shows_reaches_it_too(self):
        self.put(self.older(title="An older title naming Lenire"), trial(A))
        self.answers = {A: study(A)}
        self.go()
        self.assertEqual(self.listed(), set())
        self.assertEqual(self.marks().get(trial(A)["id"]), HOLD)

    def test_a_marked_newer_entry_stops_counting_its_older_one_as_a_backlog_twice(self):
        self.put(self.older(topicHold=HOLD), trial(A))
        self.answers = {A: study(A)}
        self.go()
        ev = self.status()["evaluation"]
        self.assertEqual(ev["paused"], 3)                 # the paused record and both marked entries
        self.assertEqual(ev["awaitingEvaluation"], 0)


class TheOwnerLiftsTheWholeHold(Case):
    def lift(self):
        self.W("engine/topic_holds.json", {"holds": [], "emptyOnPurpose": True})

    def test_the_mark_goes_on_the_next_run_and_the_record_lists(self):
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: study(A)}
        self.lift()
        self.go()
        self.assertEqual(self.marks(), {})
        self.assertEqual(self.listed(), {A})
        self.assertEqual(self.status()["holdMarksCleared"], 1)

    def test_a_mark_on_a_record_the_listing_step_never_visits_goes_too(self):
        self.put({"id": "newsintel-x-1", "kind": "news", "title": "A plain headline", "source": "Wire", "summary": "", "url": "https://example.invalid/x", "intelligenceOnly": True, "topicHold": HOLD})
        self.lift()
        self.go()
        self.assertEqual(self.marks(), {})

    def test_the_mark_goes_with_the_listing_step_switched_off(self):
        self.put({**trial(A), "topicHold": HOLD})
        self.W("engine/automation_settings.json", {"listings": False, "updateHistory": False})
        self.lift()
        self.go()
        self.assertEqual(self.marks(), {})

    def test_the_record_is_still_checked_against_a_hold_in_force(self):
        self.W("engine/topic_holds.json", {"holds": [OTHER_HOLD]})
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: study(A, detail="x\nAcoustic Crown")}
        self.go()
        self.assertEqual(self.marks(), {trial(A)["id"]: "other-topic"})
        self.assertEqual(self.listed(), set())

    def test_the_record_is_still_checked_against_its_source(self):
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: OSError("down")}
        self.lift()
        self.go()
        self.assertEqual(self.marks(), {})
        self.assertEqual(self.listed(), set(), "a record that could not be fetched is not listed, mark or no mark")

    def test_lifting_another_hold_leaves_this_mark(self):
        self.W("engine/topic_holds.json", {"holds": [LENIRE_HOLD]})
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: study(A)}
        self.go()
        self.assertEqual(self.marks(), {trial(A)["id"]: HOLD})


class APerRecordRelease(Case):
    def test_it_clears_the_mark_and_the_record_lists_though_its_text_still_shows_the_hold(self):
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: study(A, detail="in a tent-A shelter")}
        self.W(REL, {"releases": [release(trial(A)["id"])]})
        self.go()
        self.assertEqual(self.marks(), {})
        self.assertEqual(self.listed(), {A})
        self.assertEqual(self.status()["holdMarksCleared"], 1)
        self.assertEqual(self.status()["holdMarksAwaitingOwner"], 0)

    def test_the_control_without_it_the_same_text_is_held(self):
        self.put(trial(A))
        self.answers = {A: study(A, detail="in a tent-A shelter")}
        self.go()
        self.assertEqual(self.marks(), {trial(A)["id"]: HOLD})

    def test_it_covers_a_hold_seen_only_in_the_title_with_no_mark_at_all(self):
        it = {**trial(A), "title": "A tinnitus study in a tent-A shelter"}
        s = study(A)
        s["protocolSection"]["identificationModule"]["briefTitle"] = it["title"]
        self.put(it)
        self.answers = {A: s}
        self.go()
        self.assertEqual(self.listed(), set())
        self.W(REL, {"releases": [release(it["id"])]})
        self.go()
        self.assertEqual(self.listed(), {A})

    def test_it_stays_released_on_later_runs(self):
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: study(A, detail="in a tent-A shelter")}
        self.W(REL, {"releases": [release(trial(A)["id"])]})
        self.go()
        self.go()
        self.assertEqual(self.marks(), {})

    def test_a_later_registry_update_is_a_new_entry_and_is_checked_again(self):
        old = {**ctgov_item(A, title=f"A tinnitus trial of sound therapy {A}", source="ClinicalTrials.gov", date="2026-09-01"), "topicHold": HOLD}
        self.put(old)
        self.answers = {A: study(A, detail="in a tent-A shelter")}
        self.W(REL, {"releases": [release(old["id"])]})
        self.go()
        self.assertEqual(self.listed(), {A})
        queue = self.J("data/review-queue/queue.json")["items"]
        self.W("data/review-queue/queue.json", {"items": [trial(A), *queue]})
        self.W("engine/known_ids.json", sorted({trial(A)["id"], *(i["id"] for i in queue)}))
        self.go()
        self.assertEqual(self.marks(), {trial(A)["id"]: HOLD}, "the same text under a new entry is held again")

    def test_an_update_that_no_longer_shows_the_hold_refreshes_the_listing(self):
        old = {**ctgov_item(A, title=f"A tinnitus trial of sound therapy {A}", source="ClinicalTrials.gov", date="2026-09-01"), "topicHold": HOLD}
        self.put(old)
        self.answers = {A: study(A, detail="in a tent-A shelter")}
        self.W(REL, {"releases": [release(old["id"])]})
        self.go()
        queue = self.J("data/review-queue/queue.json")["items"]
        self.W("data/review-queue/queue.json", {"items": [trial(A), *queue]})
        self.W("engine/known_ids.json", sorted({trial(A)["id"], *(i["id"] for i in queue)}))
        self.answers = {A: study(A)}
        self.go()
        self.assertEqual(self.marks(), {})

    def test_a_release_of_the_older_entry_does_not_reach_a_newer_one_waiting_beside_it(self):
        old = ctgov_item(A, title=f"A tinnitus trial of sound therapy {A}", source="ClinicalTrials.gov", date="2026-09-01")
        self.put({**old, "topicHold": HOLD}, trial(A))
        self.answers = {A: study(A, detail="in a tent-A shelter")}
        self.W(REL, {"releases": [release(old["id"])]})
        self.go()
        self.assertEqual(self.marks(), {trial(A)["id"]: HOLD})
        self.assertEqual(self.listed(), set())

    def test_a_release_of_the_newer_entry_lets_it_list_and_the_older_keeps_its_own_mark(self):
        old = ctgov_item(A, title=f"A tinnitus trial of sound therapy {A}", source="ClinicalTrials.gov", date="2026-09-01")
        self.put({**old, "topicHold": HOLD}, trial(A))
        self.answers = {A: study(A)}
        self.W(REL, {"releases": [release(trial(A)["id"])]})
        self.go()
        self.assertEqual(self.listed(), {A})
        self.assertEqual(self.marks(), {old["id"]: HOLD})

    def test_another_record_or_another_hold_is_not_covered(self):
        for name, r in (("another record", release(trial(B)["id"])), ("another hold", release(trial(A)["id"], "other-topic")), ("the same trial's number alone", release(A)), ("a record id that only starts the same", release(trial(A)["id"][:-1]))):
            with self.subTest(name):
                self.put({**trial(A), "topicHold": HOLD})
                self.W("data/listings.json", {"version": 1, "count": 0, "items": []})
                self.answers = {A: study(A)}
                self.W(REL, {"releases": [r]})
                self.go()
                self.assertEqual(self.marks(), {trial(A)["id"]: HOLD})
                self.assertEqual(self.listed(), set())

    def test_every_other_hold_still_applies(self):
        self.W("engine/topic_holds.json", {"holds": [LENIRE_HOLD, OTHER_HOLD]})
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: study(A, detail="Acoustic Crown in a tent-A shelter")}
        self.W(REL, {"releases": [release(trial(A)["id"])]})
        self.go()
        self.assertEqual(self.marks(), {trial(A)["id"]: "other-topic"})
        self.assertEqual(self.listed(), set())

    def test_the_record_is_still_checked_against_its_source(self):
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: OSError("down")}
        self.W(REL, {"releases": [release(trial(A)["id"])]})
        self.go()
        self.assertEqual(self.marks(), {})
        self.assertEqual(self.listed(), set())

    def test_it_does_not_touch_a_pause(self):
        it = {**PAUSED_ITEM}
        self.put()
        self.W(REL, {"releases": [release(it["id"])]})
        self.go()
        self.assertEqual(self.listed(), set())
        self.assertIn(it["id"], [i["id"] for i in self.J("data/review-queue/queue.json")["items"]])

    def test_a_release_naming_a_hold_since_lifted_does_no_harm(self):
        self.W("engine/topic_holds.json", {"holds": [], "emptyOnPurpose": True})
        self.put(trial(A))
        self.answers = {A: study(A)}
        self.W(REL, {"releases": [release(trial(A)["id"])]})
        self.go()
        self.assertEqual(self.listed(), {A})


GOOD = release("ctgov-NCT99000777-2026-10-13")
BAD_RELEASES = [
    ("{not json", "not valid JSON"), ("", "not valid JSON"), ('{"releases": [], "releases": []}', "a key appears twice"), ("null", "must be a JSON object"), ("[]", "must be a JSON object"),
    ({"release": []}, "unknown key 'release'"), ({}, "needs a 'releases' list"), ({"releases": {}}, "releases must be a list"), ({"releases": ["x"]}, "releases must hold objects"),
    ({"releases": [{**GOOD, "extra": 1}]}, "needs exactly"), ({"releases": [{k: v for k, v in GOOD.items() if k != "reason"}]}, "needs exactly"), ({"releases": [{k: v for k, v in GOOD.items() if k != "holdId"}]}, "needs exactly"),
    ({"releases": [{k: v for k, v in GOOD.items() if k != "recordId"}]}, "needs exactly"), ({"releases": [{k: v for k, v in GOOD.items() if k != "decidedOn"}]}, "needs exactly"),
    ({"releases": [{**GOOD, "recordId": ""}]}, "non-empty text"), ({"releases": [{**GOOD, "recordId": 5}]}, "non-empty text"), ({"releases": [{**GOOD, "recordId": " x"}]}, "no surrounding spaces"), ({"releases": [{**GOOD, "holdId": None}]}, "non-empty text"), ({"releases": [{**GOOD, "reason": ""}]}, "non-empty text"),
    ({"releases": [{**GOOD, "decidedOn": "soon"}]}, "decidedOn"), ({"releases": [{**GOOD, "decidedOn": 20261101}]}, "decidedOn"), ({"releases": [{**GOOD, "decidedOn": "2999-01-01"}]}, "decidedOn"),
    ({"releases": [{**GOOD, "reason": "x" * 201}]}, "limited to 200"), ({"releases": [GOOD, dict(GOOD)]}, "more than once"),
]


class TheReleaseFile(Sandbox):
    def test_a_damaged_file_stops_the_run_for_its_own_reason_and_changes_nothing(self):
        for bad, reason in BAD_RELEASES:
            with self.subTest(bad=str(bad)[:70]):
                W(self.root, REL, bad if isinstance(bad, str) else bad)
                self.assertStopsWholeAndNamesIt(REL, str(bad)[:70], reason=reason)

    def test_a_binary_or_utf16_file_stops_the_run(self):
        for raw in (bytes(range(128, 200)), '{"releases": []}'.encode("utf-16")):
            (self.root / REL).write_bytes(raw)
            self.assertStopsWholeAndNamesIt(REL, "not UTF-8")

    def test_an_absent_file_means_no_releases(self):
        self.assertEqual(state_files.hold_releases(self.root), set())
        state_files.preflight(self.root)

    def test_a_sound_file_passes_and_means_exactly_what_it_says(self):
        for good, want in (({"releases": []}, set()), ({"comment": "x", "note": "y", "releases": [GOOD]}, {(GOOD["recordId"], GOOD["holdId"])}), ({"releases": [{**GOOD, "reason": "x" * 200}]}, {(GOOD["recordId"], GOOD["holdId"])}), ({"releases": [GOOD, {**GOOD, "holdId": "other"}]}, {(GOOD["recordId"], GOOD["holdId"]), (GOOD["recordId"], "other")})):
            with self.subTest(good=str(good)[:70]):
                W(self.root, REL, good)
                state_files.preflight(self.root)
                self.assertEqual(state_files.hold_releases(self.root), want)

    def test_a_byte_order_mark_is_accepted_as_it_is_hand_edited(self):
        (self.root / REL).write_bytes(b"\xef\xbb\xbf" + json.dumps({"releases": [GOOD]}).encode("utf-8"))
        state_files.preflight(self.root)
        self.assertEqual(len(state_files.hold_releases(self.root)), 1)

    def test_no_reader_treats_damage_as_no_releases(self):
        W(self.root, REL, "{bad")
        with self.assertRaises(state_files.DamagedFile):
            state_files.hold_releases(self.root)

    def test_the_repository_ships_no_release_until_the_owner_decides_one(self):
        from common import ENGINE
        self.assertFalse((ENGINE / "hold_releases.json").exists())


class ReportedAsCountsOnly(Case):
    def test_marks_awaiting_the_owner_are_counted_and_no_record_is_named(self):
        self.put({**trial(A), "topicHold": HOLD}, {**trial(B), "topicHold": HOLD})
        self.answers = {A: study(A), B: study(B)}
        self.go()
        st = self.status()
        self.assertEqual(st["holdMarksAwaitingOwner"], 2)
        self.assertNotIn("holdMarksCleared", st)
        text = json.dumps(st)
        for name in (A, B, "holdsClearedIds", "topicHold"):
            self.assertNotIn(name, text)

    def test_the_count_is_reported_as_zero_when_there_are_none(self):
        self.put(trial(A))
        self.answers = {A: study(A)}
        self.go()
        self.assertEqual(self.status()["holdMarksAwaitingOwner"], 0)

    def test_a_clear_is_counted_and_names_no_record_in_the_status_file_and_is_in_the_audit_log(self):
        self.put({**trial(A), "topicHold": HOLD}, {**trial(B), "topicHold": HOLD})
        self.answers = {A: study(A), B: study(B)}
        self.W(REL, {"releases": [release(trial(A)["id"])]})
        self.go()
        st = self.status()
        self.assertEqual((st["holdMarksCleared"], st["holdMarksAwaitingOwner"]), (1, 1))
        self.assertNotIn(trial(A)["id"], json.dumps({k: v for k, v in st.items() if k.startswith("hold") or k == "listings"}))
        rows = [json.loads(l) for l in (self.root / "engine/audit-log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(r["identifier"], r["reason"]) for r in rows if r["step"] == "hold-mark"], [(trial(A)["id"], "the owner released this record")])

    def test_a_lift_says_so_in_the_audit_log(self):
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: study(A)}
        self.W("engine/topic_holds.json", {"holds": [], "emptyOnPurpose": True})
        self.go()
        rows = [json.loads(l) for l in (self.root / "engine/audit-log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["reason"] for r in rows if r["step"] == "hold-mark"], ["the owner lifted the hold"])

    def test_nothing_from_the_automatic_clearing_rule_is_written(self):
        self.put(trial(A), {**trial(B), "topicHold": HOLD})
        self.answers = {A: study(A, detail="x\nLenire"), B: study(B)}
        self.go()
        keys = {k for i in self.J("data/review-queue/queue.json")["items"] for k in i}
        for gone in ("topicHoldClear", "topicHoldVersion", "topicHoldFields"):
            self.assertNotIn(gone, keys)

    def test_the_old_fields_are_ignored_not_trusted_if_a_queue_ever_held_them(self):
        self.put({**trial(A), "topicHold": HOLD, "topicHoldClear": {"firstClean": "2026-01-01"}, "topicHoldVersion": "2026-01-01", "topicHoldFields": ["a"]})
        self.answers = {A: study(A)}
        self.go()
        self.assertEqual(self.marks(), {trial(A)["id"]: HOLD})


class ThePublicRoute(Case):
    def test_a_marked_record_goes_to_no_public_file(self):
        self.put({**trial(A), "topicHold": HOLD})
        self.answers = {A: study(A)}
        self.go()
        from datetime import date
        for rel in ("data/listings.json", f"data/weekly/{date.today().isoformat()}.json"):
            self.assertNotIn(A, (self.root / rel).read_text(encoding="utf-8"))


REC = "\n".join(["SOURCE: simulated", "RECORD COMPLETENESS: COMPLETE - nothing was left out", "CRITICAL SECTIONS MISSING: no", "REGISTRY FIELD hasResults: FALSE (no results posted)", "---", "Title: A plain tinnitus trial", "NCT ID: NCT99000888"])
ONE = ctgov_item("NCT99000888", title="A plain tinnitus trial", source="ClinicalTrials.gov", date="2026-10-13")
AI = {"AI on, staged": {"enabled": True, "mode": "staged", "limitPerRun": 10}, "AI on, publish": {"enabled": True, "mode": "publish", "limitPerRun": 10}}


class TheEvaluatorPath(unittest.TestCase):
    """AI stays off in production. These run the real evaluator's code with the model stubbed, since this is required before AI can ever return."""

    def test_a_name_only_in_the_complete_record_never_reaches_the_ai_and_is_marked(self):
        for name, settings in AI.items():
            with self.subTest(name):
                run = run_scenario({"queue": [ONE], "records": {ONE["id"]: REC}, "fullRecords": {ONE["id"]: REC + "\nLocation: a Lenire clinic"}, "settings": settings, "paused": [], "runs": [{}]})["runs"][0]
                self.assertEqual(run["apiCalls"], {})
                self.assertEqual(run["marks"], {ONE["id"]: HOLD})
                self.assertEqual(run["staged"], {})
                self.assertNotIn("NCT99000888", json.dumps(run["reportItems"]))

    def test_the_control_the_same_record_without_the_name_reaches_the_ai(self):
        run = run_scenario({"queue": [ONE], "records": {ONE["id"]: REC}, "fullRecords": {ONE["id"]: REC + "\nLocation: a clinic"}, "settings": AI["AI on, staged"], "paused": [], "runs": [{}]})["runs"][0]
        self.assertEqual(run["apiCalls"], {ONE["id"]: 1})
        self.assertEqual(run["marks"], {})

    def test_a_mark_survives_runs_on_the_evaluator_path_whatever_the_record_says(self):
        run = run_scenario({"queue": [{**ONE, "topicHold": HOLD}], "records": {ONE["id"]: REC}, "settings": AI["AI on, staged"], "paused": [], "runs": [{}, {}]})["runs"]
        for r in run:
            self.assertEqual(r["apiCalls"], {})
            self.assertEqual(r["marks"], {ONE["id"]: HOLD})

    def test_a_mark_set_by_the_listing_step_is_not_lost_when_the_evaluator_runs_after_it(self):
        run = run_scenario({"queue": [ONE], "records": {ONE["id"]: REC}, "fullRecords": {ONE["id"]: REC + "\nLocation: a Lenire clinic"}, "settings": AI["AI on, staged"], "automation": {"listings": True, "updateHistory": True}, "paused": [], "runs": [{}, {}]})["runs"]
        for r in run:
            self.assertEqual(r["apiCalls"], {})
            self.assertEqual(r["marks"], {ONE["id"]: HOLD})

    def test_a_record_the_owner_released_is_evaluated_like_any_other(self):
        run = run_scenario({"queue": [{**ONE, "topicHold": HOLD}], "records": {ONE["id"]: REC}, "fullRecords": {ONE["id"]: REC + "\nLocation: in a tent-A shelter"}, "settings": AI["AI on, staged"], "paused": [], "holdReleases": {"releases": [release(ONE["id"])]}, "runs": [{}]})["runs"][0]
        self.assertEqual(run["apiCalls"], {ONE["id"]: 1})
        self.assertEqual(run["marks"], {})
        self.assertIn(ONE["id"], run["staged"])

    def test_a_record_whose_title_shows_the_hold_is_chosen_for_the_evaluator_once_released(self):
        it = {**ONE, "title": "A plain tinnitus trial in a tent-A shelter"}
        for name, releases, calls in (("released", {"releases": [release(ONE["id"])]}, {ONE["id"]: 1}), ("the control, not released", None, {})):
            with self.subTest(name):
                run = run_scenario({"queue": [it], "records": {ONE["id"]: REC}, "settings": AI["AI on, staged"], "paused": [], "holdReleases": releases, "runs": [{}]})["runs"][0]
                self.assertEqual(run["apiCalls"], calls)

    def test_a_release_for_another_hold_does_not_let_it_through(self):
        run = run_scenario({"queue": [ONE], "records": {ONE["id"]: REC}, "fullRecords": {ONE["id"]: REC + "\nLocation: a Lenire clinic"}, "settings": AI["AI on, staged"], "paused": [], "holdReleases": {"releases": [release(ONE["id"], "other-topic")]}, "runs": [{}]})["runs"][0]
        self.assertEqual(run["apiCalls"], {})
        self.assertEqual(run["marks"], {ONE["id"]: HOLD})


if __name__ == "__main__":
    unittest.main()

"""E1: a damaged protection or state file stops the REAL cycle whole. Nothing is scanned, published, deleted or written, no paid call is possible, and after a repair the next run goes on as if nothing had happened.
Run:  python -m unittest discover -s engine/tests -v"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, REPO, pubmed_item, run_scenario   # noqa: E402
from cycle_sandbox import (ALL, ARCHIVE, AUTO, BATCH, BENCH, DECISIONS, EVAL, EVIDENCE, HAND_EDITED, HASHES, HELD, HISTORY, HOLDS, INDEX, ITEM, KNOWN, LEDGER, LENIRE, LISTINGS, PAUSED, QUEUE, REGISTER, REQUIRED, RETRACTION, RULES,  # noqa: E402
                           SCANNED, SCAN_STATE, SOURCES, STAGED, STATUS, STUDIES, TODAY, TREATMENTS, TRIALS, Sandbox, W)

import state_files, topic_holds, triage, weekly_cycle, weekly_scan  # noqa: E402


DAMAGE = {"empty file": b"", "not JSON": b"{not json", "trailing comma": b'{"ids": ["a",], "items": [], "holds": [], "reports": []}', "binary garbage": bytes(range(128, 200)),
          "UTF-16, as PowerShell 5 can save": '{"ids": []}'.encode("utf-16"), "NaN": b"NaN", "null": b"null", "truncated": b'{"items": [{"id": "pubmed-1"'}


class EveryFileEveryDamage(Sandbox):
    def test_any_damage_to_any_file_stops_the_run_with_nothing_changed(self):
        for rel in ALL:
            for name, raw in DAMAGE.items():
                with self.subTest(file=rel, damage=name):
                    p = self.root / rel
                    keep = p.read_bytes() if p.exists() else None
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(raw)
                    self.assertStopsWholeAndNamesIt(rel, name)
                    if keep is None:
                        p.unlink()
                    else:
                        p.write_bytes(keep)

    def test_a_missing_required_file_stops_the_run_with_nothing_changed(self):
        for rel in REQUIRED:
            with self.subTest(file=rel):
                p = self.root / rel
                keep = p.read_bytes()
                p.unlink()
                self.assertStopsWholeAndNamesIt(rel, "missing")
                with self.assertRaises(state_files.DamagedFile) as e:
                    state_files.preflight(self.root)
                self.assertIn(f"{rel}: the file is missing", str(e.exception))
                p.write_bytes(keep)

    def test_a_file_that_cannot_be_read_stops_the_run(self):
        p = self.root / PAUSED
        keep = p.read_bytes()
        p.unlink()
        p.mkdir()                     # opening a directory as a file is an OS error on every platform, which is what an unreadable file gives
        self.assertStopsWholeAndNamesIt(PAUSED, "unreadable")
        p.rmdir()
        p.write_bytes(keep)

    def test_every_problem_is_named_at_once(self):
        W(self.root, PAUSED, "{bad")
        W(self.root, QUEUE, "{bad")
        (self.root / HOLDS).unlink()
        with self.assertRaises(state_files.DamagedFile) as e:
            state_files.preflight(self.root)
        for rel in (PAUSED, QUEUE, HOLDS):
            self.assertIn(rel, str(e.exception))

    def test_messages_name_the_file_but_never_repeat_its_contents(self):
        for rel, content in ((HELD, '{"items": [{"item": {"id": "PRIVATE-CONTENT"}}, "PRIVATE-CONTENT"]}'), (HELD, '{"PRIVATE-CONTENT": 1, "PRIVATE-CONTENT": 2}'), (STAGED, '{"PRIVATE-CONTENT": 1}'),
                             (STAGED, '{"items": [], "PRIVATE-CONTENT": {"PRIVATE-CONTENT": 1, "PRIVATE-CONTENT": 2}}'), (HELD, 'PRIVATE-CONTENT'), (HELD, '{"PRIVATE-CONTENT": [')):
            with self.subTest(content=content):
                W(self.root, rel, content)
                try:
                    state_files.preflight(self.root)
                except state_files.DamagedFile as e:
                    self.assertNotIn("PRIVATE-CONTENT", str(e))
                (self.root / rel).unlink()


WRONG_SHAPES = {
    PAUSED: [[], ["pubmed-1"], {"ids": "pubmed-1"}, {"ids": None}, {"ids": {"pubmed-1": 1}}, {"ID": ["pubmed-1"]}, {"id": ["pubmed-1"]}, {"ids": [1]}, {"ids": [None]}, {"ids": [" pubmed-1"]},
             {"ids": ["pubmed-1 "]}, {"ids": [""]}, {"ids": []}, {"ids": [], "emptyOnPurpose": "true"}, {"ids": ["pubmed-1"], "ID": ["x"]},
             {"ids": ["42861486"]}, {"ids": ["NCT01234567"]}, {"ids": ["pubmed-99999999"]}],
    HOLDS: [[], {"holds": {}}, {"hold": []}, {"holds": None}, {"holds": []}, {"holds": [], "emptyOnPurpose": 1}, {"holds": [None]}, {"holds": ["lenire"]}, {"holds": [{"patterns": ["x"]}]},
            {"holds": [{"id": "", "patterns": ["x"]}]}, {"holds": [{"id": "a"}]}, {"holds": [{"id": "a", "patterns": [], "idPrefixes": []}]}, {"holds": [{"id": "a", "patterns": "lenire"}]},
            {"holds": [{"id": "a", "idPrefixes": "pubmed-"}]}, {"holds": [{"id": "a", "pattern": ["lenire"]}]}, {"holds": [{"id": "a", "patterns": ["lenire"], "idPrefix": ["x"]}]},
            {"holds": [{"id": "a", "patterns": ["lenire "]}]}, {"holds": [{"id": "a", "patterns": [""]}]}, {"holds": [{"id": "a", "patterns": ["("]}]}, {"holds": [{"id": "a", "patterns": [1]}]},
            {"holds": [{"id": "a", "patterns": ["\blenire\b"]}]}, {"holds": [{"id": "a", "patterns": ["\\\\blenire\\\\b"]}]}, {"holds": [{"id": "a", "patterns": ["\\bleni\u200bre\\b"]}]},
            {"holds": [{"id": "a", "idPrefixes": ["pub\u200bmed-"]}]}, {"holds": [{"id": "a", "patterns": ["a{99999999999}"]}]}, {"holds": [{"id": "a", "patterns": ["(" * 20000 + ")" * 20000]}]},
            {"holds": [{"id": "a", "patterns": ["x"]}], "Holds": []}],
    QUEUE: [[], {"item": []}, {"items": {}}, {"items": None}, {"items": ["x"]}, {"items": [{}]}, {"items": [{"id": 1}]}, {"items": [{"id": ""}]}, {"items": [{"id": "a", "title": 5}]}, {"items": [{"id": "a", "url": []}]},
            {"items": [{"id": "a", "url": None}]}, {"items": [{"id": "a", "title": None}]}, {"items": [{"id": "a", "listed": True}]}, {"items": [{"id": "a", "listed": {"outcome": "Listed"}}]},
            {"items": [{"id": "a", "listed": {"outcome": "listed"}}]}, {"items": [{"id": "a", "listed": "listed"}]}, {"items": [{"id": "a", "listed": {"outcome": []}}]}, {"items": [{"id": "a", "listed": {"outcome": {}}}]}],
    KNOWN: [{}, '"abc"', [], [1], {"pubmed-1": 1}],
    REGISTER: [{}, '"abc"', [], [1]],
    SCAN_STATE: [[], {"pubmd": TODAY, "ctgov": TODAY}, {"pubmed": TODAY}, {"pubmed": "soon", "ctgov": TODAY}, {"pubmed": (date.today() + timedelta(days=30)).isoformat(), "ctgov": TODAY}, {"pubmed": 1, "ctgov": TODAY}],
    SOURCES: [[], {"feed": [], "newsIntel": [], "pages": []}, {"feeds": [{"name": "no url"}], "newsIntel": [], "pages": []}, {"feeds": [{"url": "no name"}], "newsIntel": [], "pages": []},
              {"feeds": [], "newsIntel": [{"name": "no query"}], "pages": []}, {"feeds": [], "newsIntel": []}],
    HASHES: [[]],
    RETRACTION: [[], {"lastrun": TODAY}, {"lastRun": (date.today() + timedelta(days=30)).isoformat()}],
    RULES: [[], {"alias": {}}, {"aliases": {}}, {"aliases": {"x": "y"}}, {"aliases": {"x": "y"}, "noticePubtypes": [], "priorityPubtypes": [], "catalogueMaxAbstractMentions": 2}, {"aliases": {"x": "y"}, "noticePubtypes": ["a"], "priorityPubtypes": ["b"]},
            {"aliases": {"x": "y"}, "noticePubtypes": ["a"], "priorityPubtypes": ["b"], "catalogueMaxAbstractMentions": True}],
    ARCHIVE: [[], {"item": []}, {"items": ["x"]}, {"items": [{"no": "item"}]}, {"items": []}],
    INDEX: [[], {"report": []}, {"reports": []}, {"reports": [{}]}],
    TRIALS: [{}, ["x"], [{"title": "no id"}]],
    STUDIES: [[], {"studies": []}, {"studies": [{"id": "s"}]}, ["x"], [{"title": "no id"}]],
    TREATMENTS: [[], {}, ["x"], [{"name": "no id"}]],
    LISTINGS: [[], {"item": []}, {"items": ["x"]}, {"items": [{"id": "no key"}]}],
    HISTORY: [[], {"entry": []}, {"entries": ["x"]}],
    HELD: [[], {"item": []}, {"items": ["x"]}],
    STAGED: [[], {"item": []}, {"items": [{}]}],
    DECISIONS: [[], {"decision": []}, {"decisions": ["x"]}],
    LEDGER: [[], {"run": []}, {"runs": ["x"]}],
    EVIDENCE: [[]], BENCH: [[]], BATCH: [[], {"note": "lost"}, {"batchId": "", "items": {}}, {"batchId": "b"}, {"batchId": "b", "items": []}, {"batchId": "b", "items": [1, 2]}], EVAL: [[]], AUTO: [[]], STATUS: [[]],
}


GOOD_RULES = {"aliases": {"x": "y"}, "noticePubtypes": ["a"], "priorityPubtypes": ["b"], "catalogueMaxAbstractMentions": 2}
GOOD_HOLD = {"id": "a", "patterns": ["\\blenire\\b"]}
# Each rule, reached by an input that is sound in every other way and stopped for that rule's own reason. A negative test that only asks "did it stop?" can pass because an earlier check stopped it, and then says nothing about the rule it is named for.
FOR_ITS_OWN_REASON = [
    (KNOWN, '"abc"', "must be a list"),
    (REGISTER, '"abc"', "must be a list"),
    (RULES, {**GOOD_RULES, "aliases": {"x": "("}}, "alias 'x' is not a valid regular expression"),
    (RULES, {**GOOD_RULES, "aliases": {"ok": "y", "x": "a{99999999999}"}}, "alias 'x' is not a valid regular expression"),
    (RULES, {**GOOD_RULES, "aliases": {}}, "needs an 'aliases' object"),
    (RULES, {k: v for k, v in GOOD_RULES.items() if k != "noticePubtypes"}, "needs 'noticePubtypes'"),
    (RULES, {**GOOD_RULES, "noticePubtypes": []}, "needs 'noticePubtypes'"),
    (RULES, {k: v for k, v in GOOD_RULES.items() if k != "priorityPubtypes"}, "needs 'priorityPubtypes'"),
    (RULES, {**GOOD_RULES, "catalogueMaxAbstractMentions": True}, "needs 'catalogueMaxAbstractMentions'"),
    (PAUSED, {"ids": "pubmed-1"}, "ids must be a list"),
    (PAUSED, {"ids": ["pubmed-1"], "ID": ["x"]}, "unknown key 'ID'"),
    (PAUSED, {"ids": ["pubmed-1 "]}, "no surrounding spaces"),
    (PAUSED, {"ids": []}, "ids is empty"),
    (PAUSED, {"ids": ["pubmed-99999999"]}, "never seen"),
    (HOLDS, {"holds": {}}, "holds must be a list"),
    (HOLDS, {"holds": []}, "holds is empty"),
    (HOLDS, {"holds": ["lenire"]}, "holds must hold objects"),
    (HOLDS, {"holds": [{"patterns": ["x"]}]}, "needs a text 'id'"),
    (HOLDS, {"holds": [{"id": "a"}]}, "would match nothing"),
    (HOLDS, {"holds": [{"id": "a", "patterns": "lenire"}]}, "patterns of hold 'a' must be a list"),
    (HOLDS, {"holds": [{"id": "a", "idPrefixes": "pubmed-"}]}, "idPrefixes of hold 'a' must be a list"),
    (HOLDS, {"holds": [{**GOOD_HOLD, "idPrefix": ["x"]}]}, "unknown key 'idPrefix'"),
    (HOLDS, {"holds": [{"id": "a", "patterns": ["lenire "]}]}, "no surrounding spaces"),
    (HOLDS, {"holds": [{"id": "a", "patterns": ["("]}]}, "not a valid regular expression"),
    (HOLDS, {"holds": [{"id": "a", "patterns": ["a{99999999999}"]}]}, "not a valid regular expression"),
    (HOLDS, {"holds": [{"id": "a", "patterns": ["\\\\blenire\\\\b"]}]}, "literal backslash"),
    (HOLDS, {"holds": [{"id": "a", "patterns": ["\blenire\b"]}]}, "control or invisible character"),
    (HOLDS, {"holds": [{"id": "a", "idPrefixes": ["pub​med-"]}]}, "control or invisible character"),
    (HOLDS, {"holds": [GOOD_HOLD], "Holds": []}, "unknown key 'Holds'"),
    (QUEUE, {"items": [ITEM, {"id": "a", "title": 5}]}, "'title' that is not text"),
    (QUEUE, {"items": [ITEM, {"id": "a", "url": None}]}, "'url' that is not text"),
    (QUEUE, {"items": [ITEM, {"id": "a", "listed": {"outcome": "Listed"}}]}, "'listed' mark that is not understood"),
    (QUEUE, {"items": [ITEM, {"id": "a", "listed": {"outcome": "listed"}}]}, "'listed' mark that is not understood"),
    (QUEUE, {"items": [ITEM, {"id": "a"}, {"id": "a"}]}, "appears more than once"),
    (QUEUE, {"items": [ITEM, {"id": "a", "topicHold": True}]}, "hold mark that is not understood"),
    (SCAN_STATE, {"pubmed": "soon", "ctgov": TODAY}, "needs a 'pubmed' date"),
    (SCAN_STATE, {"pubmed": TODAY, "ctgov": (date.today() + timedelta(days=30)).isoformat()}, "needs a 'ctgov' date"),
    (SOURCES, {"feeds": [{"name": "no url"}], "newsIntel": [], "pages": []}, "needs a text 'url'"),
    (SOURCES, {"feeds": [{"url": "no name"}], "newsIntel": [], "pages": []}, "needs a text 'name'"),
    (SOURCES, {"feeds": [], "newsIntel": [{"name": "no query"}], "pages": []}, "needs a text 'query'"),
    (SOURCES, {"feeds": [], "newsIntel": []}, "needs a 'pages' list"),
    (RETRACTION, {"lastRun": (date.today() + timedelta(days=30)).isoformat()}, "needs a 'lastRun' date"),
    (ARCHIVE, {"items": []}, "items is empty"),
    (ARCHIVE, {"items": [{"no": "item"}]}, "needs an 'item' object"),
    (INDEX, {"reports": []}, "reports is empty"),
    (INDEX, {"reports": [{}]}, "needs a text 'file'"),
    (LISTINGS, {"items": [{"id": "no key"}]}, "needs a text 'key'"),
    (BATCH, {"batchId": "b", "items": []}, "needs a 'batchId' and an 'items' object"),
]


class WrongStructure(Sandbox):
    def test_each_rule_stops_the_run_for_its_own_reason(self):
        for rel, s, reason in FOR_ITS_OWN_REASON:
            with self.subTest(file=rel, reason=reason):
                p = self.root / rel
                keep = p.read_bytes() if p.exists() else None
                W(self.root, rel, s)
                self.assertStopsWholeAndNamesIt(rel, json.dumps(s)[:70], reason=reason)
                if keep is None:
                    p.unlink()
                else:
                    p.write_bytes(keep)

    def test_the_sound_inputs_those_cases_are_built_from_pass(self):
        """The control: without it, a broken base would make every case above stop for the wrong reason."""
        for rel, s in ((RULES, GOOD_RULES), (HOLDS, {"holds": [GOOD_HOLD]})):
            with self.subTest(rel):
                W(self.root, rel, s)
                state_files.preflight(self.root)

    def test_valid_json_of_the_wrong_shape_stops_the_run_with_nothing_changed(self):
        for rel, shapes in WRONG_SHAPES.items():
            for s in shapes:
                with self.subTest(file=rel, shape=json.dumps(s)[:70]):
                    p = self.root / rel
                    keep = p.read_bytes() if p.exists() else None
                    W(self.root, rel, s)
                    self.assertStopsWholeAndNamesIt(rel, json.dumps(s)[:70])
                    if keep is None:
                        p.unlink()
                    else:
                        p.write_bytes(keep)

    def test_a_second_key_cannot_replace_the_first(self):
        W(self.root, PAUSED, '{"ids": ["%s"], "ids": []}' % ITEM["id"])
        self.assertStopsWholeAndNamesIt(PAUSED, "duplicate key, second empty")
        W(self.root, PAUSED, '{"ids": ["%s", "pubmed-1"], "ids": ["pubmed-1"]}' % ITEM["id"])    # the second list alone would pass: it drops one paused id without any other sign
        self.assertStopsWholeAndNamesIt(PAUSED, "duplicate key, second shorter")

    def test_a_value_json_does_not_allow_is_rejected(self):
        W(self.root, EVAL, '{"enabled": false, "x": NaN}')
        self.assertStopsWholeAndNamesIt(EVAL, "NaN")

    def test_today_s_report_is_checked_before_it_would_be_overwritten(self):
        W(self.root, f"data/weekly/{TODAY}.json", "{bad")
        self.assertStopsWholeAndNamesIt(f"data/weekly/{TODAY}.json")

    def test_an_encrypted_store_that_was_not_decrypted_stops_the_run(self):
        for name in ("held", "staged"):
            with self.subTest(store=name):
                plain = self.root / f"data/review-queue/{name}.json"
                plain.unlink(missing_ok=True)
                W(self.root, f"data/review-queue/{name}.json.enc", "not really encrypted")
                self.assertStopsWholeAndNamesIt(f"data/review-queue/{name}.json.enc")
                (self.root / f"data/review-queue/{name}.json.enc").unlink()
                W(self.root, HELD, {"items": []})

    def test_garbage_from_a_wrong_key_stops_the_run_and_the_encrypted_store_survives(self):
        W(self.root, "data/review-queue/held.json.enc", "the real store")
        (self.root / HELD).write_bytes(bytes(range(256)))
        self.assertStopsWholeAndNamesIt(HELD)
        self.assertEqual((self.root / "data/review-queue/held.json.enc").read_text(encoding="utf-8"), "the real store")


class WhatTheRealWritersProduce(Sandbox):
    """Validators must accept what the engine really writes. A check written from memory of a shape once rejected a real batch record, which would have stopped every run after a batch was submitted."""

    def test_the_batch_record_the_evaluator_writes_passes(self):
        import re
        src = (ENGINE / "evaluate_queue.py").read_text(encoding="utf-8")
        self.assertIn('"batchId": batch.id', src)
        self.assertIn('"items": entries}', src)
        self.assertIsNotNone(re.search(r"reqs, entries = \[\], \{\}", src), "the evaluator builds the batch items as an object")
        W(self.root, BATCH, {"version": 1, "batchId": "msgbatch_1", "model": "m", "promptHash": "h", "promptCaching": False, "submittedAt": "2026-11-02T00:00:00", "items": {"a": {"id": "pubmed-1", "recordHash": "x"}}})
        state_files.preflight(self.root)

    def test_every_outcome_the_listing_step_can_mark_passes(self):
        import re
        src = (ENGINE / "listings.py").read_text(encoding="utf-8")
        written = set(re.findall(r'"outcome": "([a-z-]+)"', src))
        self.assertEqual(written, state_files.LISTED_OUTCOMES)
        W(self.root, LISTINGS, {"version": 1, "count": 1, "items": [{"key": "PMID 2", "listedOn": "2026-01-01"}]})
        W(self.root, QUEUE, {"items": [ITEM] + [{"id": f"x-{o}", "listed": {"outcome": o, "key": "PMID 2"}} for o in sorted(written)]})
        W(self.root, KNOWN, [ITEM["id"]])
        state_files.preflight(self.root)

    def test_a_queue_item_may_simply_lack_a_field(self):
        W(self.root, QUEUE, {"items": [ITEM, {"id": "pubmed-5"}]})
        state_files.preflight(self.root)


class ValuesThatAreNotJson(Sandbox):
    def test_the_reader_refuses_every_non_finite_form(self):
        for raw in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '{"a": 1e999}', '{"a": -1e999}'):
            with self.subTest(raw=raw):
                W(self.root, EVIDENCE, raw)
                self.assertStopsWholeAndNamesIt(EVIDENCE, raw)
        (self.root / EVIDENCE).unlink()

    def test_ordinary_numbers_still_read(self):
        W(self.root, EVIDENCE, '{"a": 1.5, "b": 1e300, "c": 0, "d": -2.5e-3}')
        state_files.preflight(self.root)

    def test_the_engine_refuses_to_write_them_and_leaves_the_file_as_it_was(self):
        c = weekly_cycle.Cycle(self.root)
        before = (self.root / QUEUE).read_bytes()
        c.stage(QUEUE, {"items": [{"id": "a", "score": float("nan")}]})
        with self.assertRaises(ValueError):
            c.commit()
        self.assertEqual((self.root / QUEUE).read_bytes(), before)
        c = weekly_cycle.Cycle(self.root)
        c.stage(QUEUE, {"items": [{"id": "a", "score": float("inf")}]})
        with self.assertRaises(ValueError):
            c.commit()
        self.assertEqual((self.root / QUEUE).read_bytes(), before)

    def test_an_ai_answer_holding_them_is_held_as_unusable_and_stored_as_text_only(self):
        for bad in ("NaN", "Infinity", "1e999"):
            with self.subTest(bad=bad):
                r = run_scenario({"queue": [pubmed_item(990071)], "settings": {"enabled": True, "mode": "publish", "limitPerRun": 10}, "runs": [{}, {}],
                                  "rawAnswers": {"pubmed-990071": {"text": '{"whatIsNew": "x", "relevanceCategory": 1, "score": %s}' % bad}}})
                self.assertEqual([x["exitCode"] for x in r["runs"]], [0, 0], "the next run must not stop")
                self.assertIn("pubmed-990071", r["runs"][0]["held"])
                self.assertIn("unparseable", json.dumps(r["runs"][0]["status"]["evaluation"]["failureKinds"]))


class TheOptOutCannotStayArmed(Sandbox):
    def test_the_flag_on_a_list_with_entries_stops_the_run(self):
        real_holds = json.loads((self.root / HOLDS).read_text(encoding="utf-8"))
        for rel, value in ((PAUSED, {"ids": [ITEM["id"]], "emptyOnPurpose": True}), (HOLDS, {**real_holds, "emptyOnPurpose": True}),
                           (QUEUE, {"items": [ITEM], "emptyOnPurpose": True}), (ARCHIVE, {"items": [{"item": {"id": "a"}}], "emptyOnPurpose": True}),
                           (LISTINGS, {"version": 1, "count": 1, "items": [{"key": "k", "listedOn": "2026-01-01"}], "emptyOnPurpose": True})):
            with self.subTest(file=rel):
                keep = (self.root / rel).read_bytes()
                W(self.root, rel, value)
                self.assertStopsWholeAndNamesIt(rel, "flag on a list with entries")
                (self.root / rel).write_bytes(keep)

    def test_a_false_or_odd_flag_does_not_excuse_an_empty_list(self):
        for value in (False, "true", 1, None):
            W(self.root, PAUSED, {"ids": [], "emptyOnPurpose": value})
            self.assertStopsWholeAndNamesIt(PAUSED, f"flag {value}")

    def test_the_cycle_drops_the_flag_from_the_queue_and_listings_after_use(self):
        W(self.root, STATUS, {"evaluation": {"awaitingEvaluation": 2, "paused": 1}, "listings": {"total": 5}})
        W(self.root, QUEUE, {"items": [], "emptyOnPurpose": True})
        W(self.root, PAUSED, {"ids": [], "emptyOnPurpose": True})
        W(self.root, LISTINGS, {"version": 1, "count": 0, "items": [], "emptyOnPurpose": True})
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        self.assertNotIn("emptyOnPurpose", json.loads((self.root / QUEUE).read_text(encoding="utf-8")))
        self.assertNotIn("emptyOnPurpose", json.loads((self.root / LISTINGS).read_text(encoding="utf-8")))
        rc, out = self.run_main()
        self.assertEqual(rc, 0, "the next run must also pass: " + out[-300:])

    def test_the_archive_drops_the_flag_when_it_gains_an_entry(self):
        c = weekly_cycle.Cycle(self.root)
        c._effect("archive", "catalogued for a reason", ITEM, {}, {"items": []}, [], [], lambda it: None)
        self.assertNotIn("emptyOnPurpose", c.staged[ARCHIVE])
        c.commit()
        state_files.preflight(self.root)

    def test_a_later_accidental_wipe_of_a_refilled_list_is_caught(self):
        W(self.root, PAUSED, {"ids": [], "emptyOnPurpose": True})
        state_files.preflight(self.root)
        W(self.root, PAUSED, {"ids": [ITEM["id"]], "emptyOnPurpose": True})     # refilled, flag forgotten: stops now, so it cannot excuse the wipe below
        self.assertStopsWholeAndNamesIt(PAUSED, "refilled with the flag left")
        W(self.root, PAUSED, {"ids": [ITEM["id"]]})
        state_files.preflight(self.root)
        W(self.root, PAUSED, {"ids": []})
        self.assertStopsWholeAndNamesIt(PAUSED, "accidental wipe")


class ValidButEmptied(Sandbox):
    """Sound JSON, right shape, records gone: the last run's own status says otherwise."""

    def status(self, listings=0, awaiting=5, paused=1):
        W(self.root, STATUS, {"evaluation": {"awaitingEvaluation": awaiting, "paused": paused}, "listings": {"total": listings}})

    def test_an_emptied_queue_stops_the_run_when_the_last_run_left_records(self):
        W(self.root, QUEUE, {"items": []})
        self.status()
        self.assertStopsWholeAndNamesIt(QUEUE, "emptied")

    def test_a_queue_emptied_on_purpose_passes_once_and_the_flag_does_not_stay(self):
        W(self.root, QUEUE, {"items": [], "emptyOnPurpose": True})
        W(self.root, PAUSED, {"ids": [], "emptyOnPurpose": True})
        self.status()
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        self.assertNotIn("emptyOnPurpose", json.loads((self.root / QUEUE).read_text(encoding="utf-8")))

    def test_a_queue_the_last_run_emptied_passes(self):
        W(self.root, QUEUE, {"items": []})
        W(self.root, PAUSED, {"ids": [], "emptyOnPurpose": True})
        self.status(awaiting=0, paused=0)
        state_files.preflight(self.root)

    def test_emptied_listings_stop_the_run_when_the_last_run_counted_some(self):
        W(self.root, LISTINGS, {"version": 1, "count": 0, "items": []})
        self.status(listings=56)
        self.assertStopsWholeAndNamesIt(LISTINGS, "emptied")

    def test_a_lost_held_store_stops_the_run(self):
        (self.root / HELD).unlink()
        self.assertStopsWholeAndNamesIt("held.json.enc", "both absent")


class ValidFilesStillWork(Sandbox):
    def lists_and_keeps_out(self, control, *out_ids):
        listed = json.dumps(json.loads((self.root / LISTINGS).read_text(encoding="utf-8")))
        self.assertIn(control, listed, "the control record should have been listed, or the test proves nothing")
        for i in out_ids:
            self.assertNotIn(i, listed)

    def test_the_empty_protections_control_shows_these_records_would_otherwise_list(self):
        """Without this, a test that a protected record stays out could pass only because nothing can list."""
        W(self.root, QUEUE, {"items": [ITEM, LENIRE]})
        W(self.root, KNOWN, [ITEM["id"], LENIRE["id"]])
        W(self.root, PAUSED, {"ids": [], "emptyOnPurpose": True})
        W(self.root, HOLDS, {"holds": [], "emptyOnPurpose": True})
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        listed = json.dumps(json.loads((self.root / LISTINGS).read_text(encoding="utf-8")))
        self.assertIn("990001", listed)
        self.assertIn("990003", listed)

    def test_the_real_repository_files_pass(self):
        root = Path(tempfile.mkdtemp(prefix="te-fc-real-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        shutil.copytree(REPO / "data", root / "data", ignore=shutil.ignore_patterns("*.enc"))   # the undecrypted store is the one thing a working copy lacks
        shutil.copytree(REPO / "engine", root / "engine", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        W(root, HELD, {"items": []})
        state_files.preflight(root)
        self.assertGreaterEqual(len(state_files.paused_ids(root)), 1)
        self.assertGreaterEqual(len(topic_holds.load_holds(root / HOLDS)), 1)

    def test_the_ordinary_run_scans_lists_and_commits(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        self.assertIn("CYCLE OK", out)
        self.assertEqual(self.scans, 1)
        q = json.loads((self.root / QUEUE).read_text(encoding="utf-8"))["items"]
        self.assertIn(ITEM["id"], [i["id"] for i in q])           # the paused record is still queued
        self.assertIn(SCANNED["id"], json.loads((self.root / KNOWN).read_text(encoding="utf-8")))
        self.assertTrue((self.root / f"data/weekly/{TODAY}.json").exists())

    def test_a_byte_order_mark_is_accepted_and_the_protection_still_applies(self):
        for rel in HAND_EDITED:
            p = self.root / rel
            p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
        self.assertEqual(state_files.paused_ids(self.root), {ITEM["id"]})
        self.assertEqual(topic_holds.load_holds(self.root / HOLDS)[0]["id"], "lenire-neuromod")
        W(self.root, QUEUE, {"items": [ITEM, LENIRE]})
        W(self.root, KNOWN, [ITEM["id"], LENIRE["id"]])
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        q = [i["id"] for i in json.loads((self.root / QUEUE).read_text(encoding="utf-8"))["items"]]
        self.assertIn(ITEM["id"], q)
        self.assertIn(LENIRE["id"], q)
        self.lists_and_keeps_out("990002", "990001", "990003")      # the newly scanned control lists; the paused and the held do not

    def test_a_byte_order_mark_on_any_file_the_engine_writes_stops_with_a_clear_reason(self):
        for rel in (QUEUE, KNOWN, REGISTER, LISTINGS, HISTORY, SCAN_STATE, HASHES, RETRACTION, ARCHIVE, INDEX, HELD, TRIALS, STUDIES, TREATMENTS):
            with self.subTest(file=rel):
                p = self.root / rel
                keep = p.read_bytes()
                p.write_bytes(b"\xef\xbb\xbf" + keep)
                self.assertStopsWholeAndNamesIt(rel, "byte-order mark")
                with self.assertRaises(state_files.DamagedFile) as e:
                    state_files.preflight(self.root)
                self.assertIn("byte-order mark", str(e.exception))
                p.write_bytes(keep)

    def test_every_hand_edited_file_is_read_the_same_by_every_reader_with_a_mark(self):
        import evaluate_queue, staged_review
        for rel in HAND_EDITED:
            p = self.root / rel
            p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
        (self.root / EVAL).write_bytes(b"\xef\xbb\xbf" + b'{"enabled": false, "budget": {"monthlyUSD": 3}, "sourceVerifiedReleaseMaxPerRun": 7, "promptCaching": true}')
        state_files.preflight(self.root)
        keep = evaluate_queue.ROOT
        evaluate_queue.ROOT = self.root
        self.addCleanup(setattr, evaluate_queue, "ROOT", keep)
        self.assertEqual(evaluate_queue.load_budget(), 3.0)
        self.assertIs(evaluate_queue.load_flags()["promptCaching"], True)
        self.assertEqual(state_files.paused_ids(self.root), {ITEM["id"]})
        settings, _ = staged_review.release_context(self.root)
        self.assertEqual(settings["sourceVerifiedReleaseMaxPerRun"], 7)
        self.assertTrue(weekly_scan.load(self.root / SOURCES, {})["feeds"])

    def test_rules_with_a_byte_order_mark_still_load(self):
        p = ENGINE / "triage_rules.json"
        r = self.root / RULES
        r.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
        keep, saved = triage.RULES_PATH, dict(triage._RULES)
        triage.RULES_PATH = r
        triage._RULES.clear()
        try:
            self.assertTrue(triage.rules()["aliases"])
        finally:
            triage.RULES_PATH = keep
            triage._RULES.clear()
            triage._RULES.update(saved)

    def test_comments_and_notes_on_the_protection_files_are_fine(self):
        W(self.root, PAUSED, {"comment": "x", "note": "y", "ids": [ITEM["id"]]})
        h = json.loads((self.root / HOLDS).read_text(encoding="utf-8"))
        h["holds"][0].update(comment="x", note="y")
        h["note"] = "y"
        W(self.root, HOLDS, h)
        state_files.preflight(self.root)
        self.assertEqual(topic_holds.match_item(LENIRE, topic_holds.load_holds(self.root / HOLDS)), "lenire-neuromod")

    def test_a_watcher_emptied_on_purpose_is_fine(self):
        W(self.root, SOURCES, {"feeds": [], "newsIntel": [], "pages": []})
        state_files.preflight(self.root)

    def test_absent_optional_files_are_fine(self):
        for rel in (STAGED, DECISIONS, LEDGER, EVIDENCE, BENCH, BATCH, STATUS):
            self.assertFalse((self.root / rel).exists())
        (self.root / HELD).unlink()
        W(self.root, "data/review-queue/held.json.enc", "a store")
        with self.assertRaises(state_files.DamagedFile) as e:     # one or the other, and the store here is not decrypted
            state_files.preflight(self.root)
        self.assertIn("not decrypted", str(e.exception))
        W(self.root, HELD, {"items": []})
        state_files.preflight(self.root)

    def health(self):
        d = Path(tempfile.mkdtemp(prefix="te-fc-h-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "engine").mkdir()
        (d / "data").mkdir()
        shutil.copy(ENGINE / "check_evaluation_health.py", d / "engine")
        shutil.copy(self.root / STATUS, d / "data" / "engine-status.json")
        return subprocess.run([sys.executable, str(d / "engine/check_evaluation_health.py")], capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_absent_settings_mean_off_save_the_scan_and_turn_the_run_red(self):
        for gone in ((EVAL,), (AUTO,), (EVAL, AUTO)):
            with self.subTest(gone=gone):
                self.setUp()
                for rel in gone:
                    (self.root / rel).unlink()
                rc, out = self.run_main()
                self.assertEqual(rc, 0, out[-400:])             # the cycle finished and its results are saved
                st = json.loads((self.root / STATUS).read_text(encoding="utf-8"))
                self.assertEqual(st["evaluation"]["state"], "disabled")
                self.assertEqual(st["missingSettings"], list(gone) if gone != (EVAL, AUTO) else [EVAL, AUTO])
                self.assertIn(SCANNED["id"], json.loads((self.root / KNOWN).read_text(encoding="utf-8")))
                h = self.health()
                self.assertEqual(h.returncode, 1, "the run must end red")
                self.assertIn("Settings file(s) missing", h.stdout)

    def test_present_settings_do_not_turn_the_run_red(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        self.assertEqual(self.health().returncode, 0)
        self.assertNotIn("missingSettings", json.loads((self.root / STATUS).read_text(encoding="utf-8")))

    def test_values_other_than_exactly_true_stay_off(self):
        W(self.root, EVAL, {"enabled": "true", "mode": "publish"})
        W(self.root, AUTO, {"listings": "true", "updateHistory": 1})
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        st = json.loads((self.root / STATUS).read_text(encoding="utf-8"))
        self.assertEqual(st["evaluation"]["state"], "disabled")
        self.assertIsNone(st.get("listings"))

    def test_nothing_paused_on_purpose_is_allowed(self):
        W(self.root, PAUSED, {"ids": [], "emptyOnPurpose": True})
        W(self.root, HOLDS, {"holds": [], "emptyOnPurpose": True})
        state_files.preflight(self.root)

    def test_listings_may_be_absent_only_while_their_switch_is_off(self):
        (self.root / LISTINGS).unlink()
        (self.root / HISTORY).unlink()
        with self.assertRaises(state_files.DamagedFile):
            state_files.preflight(self.root)
        W(self.root, AUTO, {"listings": False, "updateHistory": False})
        state_files.preflight(self.root)

    def test_a_correctly_written_backslash_pattern_passes_and_matches(self):
        holds = topic_holds.load_holds(self.root / HOLDS)
        self.assertEqual(topic_holds.match_item(LENIRE, holds), "lenire-neuromod")
        self.assertIsNone(topic_holds.match_item(ITEM, holds))


class WhatTheCycleWritesPassesNextTime(Sandbox):
    """A false stop on the unattended run would be its own failure: everything a run writes must pass the next preflight."""

    def test_a_title_made_only_of_symbols_does_not_stop_the_next_run(self):
        W(self.root, REGISTER, ["", "somepublishedkey"])
        state_files.preflight(self.root)

    def test_three_runs_in_a_row_each_pass_the_next_preflight(self):
        for _ in range(3):
            rc, out = self.run_main()
            self.assertEqual(rc, 0, out[-400:])
            state_files.preflight(self.root)

    def test_entries_in_the_shapes_the_cycle_writes_pass(self):
        W(self.root, HELD, {"items": [{"heldAt": "x", "reason": "y", "item": {"id": "z"}}]})
        W(self.root, STAGED, {"items": [{"id": "a", "item": {"id": "a"}}]})
        W(self.root, DECISIONS, {"decisions": []})
        W(self.root, LEDGER, {"runs": []})
        state_files.preflight(self.root)


class Recovery(Sandbox):
    def test_after_a_repair_the_run_matches_one_that_never_stopped(self):
        clean = Path(tempfile.mkdtemp(prefix="te-fc-clean-"))
        self.addCleanup(shutil.rmtree, clean, ignore_errors=True)
        shutil.copytree(self.root, clean, dirs_exist_ok=True)
        damaged = self.root
        keep = (damaged / HOLDS).read_bytes()
        (damaged / HOLDS).write_text("{oops", encoding="utf-8")
        self.assertStopsWholeAndNamesIt(HOLDS)
        (damaged / HOLDS).write_bytes(keep)
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        self.root = clean
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        for rel in (QUEUE, KNOWN, REGISTER, LISTINGS, SCAN_STATE, INDEX, ARCHIVE):
            self.assertEqual(json.loads((damaged / rel).read_text(encoding="utf-8")), json.loads((clean / rel).read_text(encoding="utf-8")), rel)

    def test_stopping_many_times_loses_nothing(self):
        keep = (self.root / PAUSED).read_bytes()
        (self.root / PAUSED).write_text("{oops", encoding="utf-8")
        for _ in range(3):
            self.assertStopsWholeAndNamesIt(PAUSED)
        (self.root / PAUSED).write_bytes(keep)
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        q = [i["id"] for i in json.loads((self.root / QUEUE).read_text(encoding="utf-8"))["items"]]
        self.assertIn(ITEM["id"], q)
        self.assertIn(SCANNED["id"], q + json.dumps(json.loads((self.root / LISTINGS).read_text(encoding="utf-8"))).split('"'))


class DamageLaterInTheRun(Sandbox):
    """The preflight is the first line. Each reader also refuses, so damage appearing after it cannot be read as empty."""

    def test_the_readers_refuse_on_their_own(self):
        c = weekly_cycle.Cycle(self.root)
        W(self.root, HOLDS, "{bad")
        with self.assertRaises(state_files.DamagedFile):
            topic_holds.load_holds(self.root / HOLDS)
        W(self.root, PAUSED, "{bad")
        with self.assertRaises(state_files.DamagedFile):
            state_files.paused_ids(self.root)
        for rel in (QUEUE, KNOWN, ARCHIVE, INDEX, LISTINGS, HISTORY, HELD, STAGED):
            W(self.root, rel, "{bad")
            with self.assertRaises(state_files.DamagedFile, msg=rel):
                c.load(rel, {"items": []})
        W(self.root, REGISTER, [])
        with self.assertRaises(state_files.DamagedFile):
            c.published_register()

    def test_the_listing_step_does_not_swallow_damage(self):
        c = weekly_cycle.Cycle(self.root)
        W(self.root, LISTINGS, "{bad")
        with self.assertRaises(state_files.DamagedFile):
            c.phase1({"items": [dict(SCANNED)]})

    def test_the_scan_loader_refuses_damage_and_defaults_only_for_an_absent_file(self):
        bad = self.root / "engine" / "sources.json"
        bad.write_text("{bad", encoding="utf-8")
        with self.assertRaises(state_files.DamagedFile):
            weekly_scan.load(bad, {"feeds": []})
        self.assertEqual(weekly_scan.load(self.root / "engine" / "absent.json", {"feeds": []}), {"feeds": []})

    def test_the_scan_does_not_treat_damage_as_one_failed_source(self):
        c = weekly_cycle.Cycle(self.root)
        with self.assertRaises(state_files.DamagedFile):
            c.scan(fixtures=[("a source", lambda: (_ for _ in ()).throw(state_files.DamagedFile("sources.json: bad")))])

    def test_the_retraction_step_does_not_swallow_damage(self):
        c = weekly_cycle.Cycle(self.root)
        W(self.root, STUDIES, "{bad")
        W(self.root, RETRACTION, {"lastRun": "2000-01-01"})
        with self.assertRaises(state_files.DamagedFile):
            c.retraction_check({"items": []})

    def test_damage_after_the_preflight_stops_the_run_before_any_public_file_changes(self):
        """A file damaged while the cycle runs: the run stops at its next read, the public report is not written, and the workflow commits nothing because the step failed."""
        real = weekly_cycle.Cycle.published_register
        root = self.root

        def damaged_register(c):
            W(root, HOLDS, "{bad")   # the hold file goes bad between the preflight and the routing step
            return real(c)
        weekly_cycle.Cycle.published_register = damaged_register
        try:
            rc, out = self.run_main()
        finally:
            weekly_cycle.Cycle.published_register = real
        self.assertEqual(rc, 1)
        self.assertIn("CYCLE STOPPED", out)
        self.assertIn("commits nothing", out)
        self.assertNotIn("no data was changed", out)     # some state may be on the runner's disk by now: the workflow discards it
        self.assertFalse((self.root / f"data/weekly/{TODAY}.json").exists())

    def test_the_run_summary_says_the_health_below_is_from_the_previous_run(self):
        summary = self.root / "summary.md"
        os.environ["GITHUB_STEP_SUMMARY"] = str(summary)
        self.addCleanup(os.environ.pop, "GITHUB_STEP_SUMMARY", None)
        W(self.root, PAUSED, "{bad")
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertIn("previous run", summary.read_text(encoding="utf-8"))


class EvaluatorRefusesToo(unittest.TestCase):
    """AI stays off. These read the evaluator's own loaders only: no client is created and no call is possible."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="te-fc-eq-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "engine").mkdir()
        import evaluate_queue
        self.eq = evaluate_queue
        self.keep = evaluate_queue.ROOT
        evaluate_queue.ROOT = self.root
        self.addCleanup(setattr, evaluate_queue, "ROOT", self.keep)

    def test_a_damaged_pause_list_never_reads_as_nothing_paused(self):
        for bad in ("", "{bad", "[]", '{"ids": "pubmed-1"}', '{"ID": ["pubmed-1"]}'):
            with self.subTest(bad=bad):
                (self.root / "engine" / "paused_ids.json").write_text(bad, encoding="utf-8")
                with self.assertRaises(state_files.DamagedFile):
                    self.eq.load_paused()
        (self.root / "engine" / "paused_ids.json").unlink()
        with self.assertRaises(state_files.DamagedFile):
            self.eq.load_paused()

    def test_settings_with_a_byte_order_mark_are_read_not_defaulted(self):
        (self.root / "engine" / "eval_settings.json").write_bytes(b"\xef\xbb\xbf" + b'{"budget": {"monthlyUSD": 3}, "promptCaching": true}')
        self.assertEqual(self.eq.load_budget(), 3.0)
        self.assertIs(self.eq.load_flags()["promptCaching"], True)

    def test_a_good_pause_list_with_a_byte_order_mark_is_honoured(self):
        (self.root / "engine" / "paused_ids.json").write_bytes(b"\xef\xbb\xbf" + b'{"ids": ["pubmed-1"]}')
        self.assertEqual(self.eq.load_paused(), {"pubmed-1"})


class TheScheduledPath(unittest.TestCase):
    def test_the_workflow_runs_the_cycle_directly_with_no_way_around_the_preflight(self):
        wf = (REPO / ".github/workflows/weekly.yml").read_text(encoding="utf-8")
        self.assertIn("run: python engine/weekly_cycle.py\n", wf.replace("\r\n", "\n"))
        src = (ENGINE / "weekly_cycle.py").read_text(encoding="utf-8")
        start = src.index("def run(self, fixtures=None")
        self.assertLess(src.index("state_files.preflight(", start), src.index("self.scan(fixtures", start))
        self.assertNotIn("environ", (ENGINE / "state_files.py").read_text(encoding="utf-8"))   # no switch turns the check off

    def test_nothing_else_reads_the_protection_files_its_own_way(self):
        for f in list(ENGINE.glob("*.py")) + list((REPO / "tools").glob("*.py")):
            if f.name in ("state_files.py", "topic_holds.py"):
                continue
            t = f.read_text(encoding="utf-8")
            for name in ("paused_ids.json", "topic_holds.json"):
                for line in t.splitlines():
                    if name in line and ("read_text" in line or "json.load" in line or "open(" in line):
                        self.fail(f"{f.name} reads {name} directly: {line.strip()[:120]}")


class SimulateMode(unittest.TestCase):
    def test_a_simulation_uses_the_real_protections_and_touches_nothing(self):
        before = hashlib.sha256((REPO / QUEUE).read_bytes()).hexdigest()
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "STATE_KEY")}
        p = subprocess.run([sys.executable, "-X", "utf8", str(ENGINE / "weekly_cycle.py"), "--simulate", "--skip-eval"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, env=env)
        self.assertEqual(p.returncode, 0, p.stderr[-500:] + p.stdout[-500:])
        self.assertIn("CYCLE OK", p.stdout)
        self.assertEqual(hashlib.sha256((REPO / QUEUE).read_bytes()).hexdigest(), before)
        sandbox = Path(p.stdout.split("sandbox: ")[1].split(" (live data")[0])
        self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
        self.assertTrue((sandbox / PAUSED).exists() and (sandbox / HOLDS).exists())
        self.assertFalse((sandbox / "data/review-queue/held.json.enc").exists())


if __name__ == "__main__":
    unittest.main()

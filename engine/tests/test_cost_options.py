"""Offline tests for the two cost options (prompt caching, Message Batches). No network, no API key: a fake SDK stands in for `anthropic`, and the evaluator runs
from a temporary copy of data/ + engine/, so nothing in the repository is touched. Both options are OFF in the shipped settings; these tests pin that, and that with
them off the request is exactly what earlier versions sent."""
import contextlib, hashlib, importlib.util, io, json, re, shutil, sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

ENGINE = Path(__file__).resolve().parent.parent
REPO = ENGINE.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import evaluate_queue as EQ  # noqa: E402  (the repository copy: pure functions only)
import registry_record  # noqa: E402

PROMPT_HASH_PINNED = "c74dd6fcb01a5edc"                     # evaluator prompt fingerprint of the P3 prompt (benchmarked 8/8): caching/batch must not change it
OLD_PROMPT_SHA256 = "91467b131a7b88520c5048ac786026f35671d1be0785686d04b60f06a3700a94"   # sha256 of the single-string prompt the P3 prompt builds for the fixed inputs below (the prefix+suffix split must reproduce it exactly)
T_INDEX = [{"id": "a", "name": "A", "tier": 1, "evidenceScore": 2, "loudness": "x", "distress": "y"}]
S_INDEX = [{"id": "s", "title": "T", "year": 2020}]
ITEM_META = {"id": "pubmed-1", "kind": "study", "title": "A routine tinnitus trial", "source": "PubMed", "date": "2026 Oct 13", "url": "u", "summary": "s",
             "intelligenceOnly": False, "recordAvailable": True}


def _ev(item_id):
    return {"whatIsNew": "Routine finding reported in the record.", "relevanceCategory": 1, "notRelevant": False, "affectedTreatment": "cbt", "studyType": "RCT",
            "studyQuality": "moderate", "population": "Not reported", "sampleSize": "Not reported", "controlQuality": "active-control", "randomized": True, "blinded": "unclear",
            "primaryEndpoint": "Not reported", "secondaryEndpoints": "Not reported", "comparisonType": "between-group", "numericalResult": "none reported",
            "loudnessEffect": "none - not measured", "distressEffect": "none", "otherOutcomes": "Not reported", "clinicalSignificance": "Not reported",
            "safetyObservations": "Not reported", "safetySignal": False, "mainLimitations": ["Not reported"], "conflictOfInterest": "unclear",
            "regulatorySource": "authoritative (FDA/EMA/registry record)", "evidenceDirection": "no-meaningful-change", "changeClass": "routine",
            "proposedScoreChange": None, "proposedRankChange": None, "importance": "Does Not Change Current Evidence", "weeklyTitle": "Routine update",
            "whyMatters": "x " + item_id, "factuallyVerified": True, "factuallyVerifiedReason": "stated in the record", "summaryForAdmin": "admin " + item_id,
            "confidence": "high", "duplicateOf": None}


def _usage(inp=100, out=50, write=0, read=0):
    return types.SimpleNamespace(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=write, cache_read_input_tokens=read)


def _msg(item_id, usage=None):
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(_ev(item_id)))], usage=usage or _usage(), stop_reason="end_turn", model="claude-opus-5")


class _Status(Exception):
    def __init__(self, code, message):
        super().__init__(message); self.status_code = code; self.message = message


class FakeSDK:
    """Stands in for the `anthropic` module: messages.create (sync path + preflight) and messages.batches.{create,retrieve,results}."""
    def __init__(self, batch_status="ended", results=None, create_error=None, retrieve_error=None):
        self.calls, self.batch_creates, self.retrieves, self.results_calls = [], [], 0, 0
        self.batch_status, self.results, self.create_error, self.retrieve_error = batch_status, results or [], create_error, retrieve_error
        self.APIStatusError, self.RateLimitError = _Status, type("RateLimitError", (_Status,), {})
        sdk = self

        class Batches:
            def create(self, requests):
                if sdk.create_error:
                    raise sdk.create_error
                sdk.batch_creates.append(requests)
                return types.SimpleNamespace(id="msgbatch_TEST1", processing_status="in_progress")

            def retrieve(self, bid):
                sdk.retrieves += 1
                if sdk.retrieve_error:
                    raise sdk.retrieve_error
                return types.SimpleNamespace(id=bid, processing_status=sdk.batch_status)

            def results(self, bid):
                sdk.results_calls += 1
                return iter(sdk.results)

        class Msgs:
            batches = Batches()

            def create(self, **kw):
                if kw.get("max_tokens") == 1:
                    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")])
                sdk.calls.append(kw)
                m = re.search(r"NEW ITEM METADATA:\n(\{.*?\})\n\n", _flat(kw["messages"][0]["content"]), re.S)
                return _msg(json.loads(m.group(1))["id"], _usage(1000, 500, **sdk.usage_kw))

        self.usage_kw = {}
        self.Anthropic = lambda *a, **k: types.SimpleNamespace(messages=Msgs())

    def module(self):
        m = types.ModuleType("anthropic")
        m.Anthropic, m.APIStatusError, m.RateLimitError = self.Anthropic, self.APIStatusError, self.RateLimitError
        return m


def _flat(content):
    return content if isinstance(content, str) else "".join(b["text"] for b in content)


def _result(cid, kind="succeeded", item_id="x", usage=None):
    if kind == "succeeded":
        return types.SimpleNamespace(custom_id=cid, result=types.SimpleNamespace(type="succeeded", message=_msg(item_id, usage)))
    return types.SimpleNamespace(custom_id=cid, result=types.SimpleNamespace(type=kind))


class Sandbox:
    """A temp copy of data/ + engine/ with the evaluator loaded from it (its ROOT is the temp dir), a stubbed record fetch and a 3-item queue."""
    def __init__(self, settings, n_items=3):
        self.tmp = Path(tempfile.mkdtemp(prefix="te-cost-"))
        shutil.copytree(REPO / "data", self.tmp / "data")
        shutil.copytree(ENGINE, self.tmp / "engine", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        (self.tmp / "engine" / "eval_settings.json").write_text(json.dumps(settings), encoding="utf-8")
        (self.tmp / "engine" / "paused_ids.json").write_text(json.dumps({"ids": []}), encoding="utf-8")
        q = json.loads((self.tmp / "data/review-queue/queue.json").read_text(encoding="utf-8"))
        q["items"] = [common.pubmed_item(900000 + i, title=f"A routine tinnitus trial {i}") for i in range(n_items)]
        (self.tmp / "data/review-queue/queue.json").write_text(json.dumps(q), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("evaluate_queue_cost_sandbox", self.tmp / "engine" / "evaluate_queue.py")
        self.eq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.eq)
        self.record_suffix = ""

        def fake_fetch(item):
            self.eq.RECORD_META.pop(item["id"], None)
            pmid = item["id"].split("-", 1)[1]
            return registry_record.finish_pubmed_record(f"Title: {item.get('title', '')}\nPMID: {pmid}\nRecord id {item['id']}{self.record_suffix}", pmid)[0]
        self.eq.fetch_context = fake_fetch

    def queue(self):
        return json.loads((self.tmp / "data/review-queue/queue.json").read_text(encoding="utf-8"))

    def snapshot(self, sub="data"):
        return {str(p.relative_to(self.tmp)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((self.tmp / sub).rglob("*")) if p.is_file()}

    def run(self, sdk, limit=10):
        with mock.patch.dict(sys.modules, {"anthropic": sdk.module()}), mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-SIMULATED"}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self.eq.main(limit=limit)

    def state(self):
        p = self.tmp / "engine" / "batch-state.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Shipped(unittest.TestCase):
    def test_both_options_are_off_in_the_shipped_settings(self):
        s = json.loads((ENGINE / "eval_settings.json").read_text(encoding="utf-8"))
        self.assertIs(s["enabled"], False)
        self.assertIs(s["promptCaching"], False)
        self.assertIs(s["useBatch"], False)
        self.assertEqual(s["mode"], "staged")

    def test_prompt_fingerprint_is_unchanged(self):
        self.assertEqual(EQ.prompt_hash(), PROMPT_HASH_PINNED)

    def test_prompt_text_is_byte_identical_to_the_previous_version(self):
        prefix, suffix = EQ.build_prompt_parts(T_INDEX, S_INDEX, ITEM_META, "CTX line 1\nline 2")
        self.assertEqual(hashlib.sha256((prefix + suffix).encode("utf-8")).hexdigest(), OLD_PROMPT_SHA256)

    def test_the_stable_prefix_does_not_depend_on_the_item(self):
        p1, s1 = EQ.build_prompt_parts(T_INDEX, S_INDEX, ITEM_META, "record one")
        p2, s2 = EQ.build_prompt_parts(T_INDEX, S_INDEX, {**ITEM_META, "id": "pubmed-2", "title": "other"}, "a different, longer record " * 50)
        self.assertEqual(p1, p2)
        self.assertNotEqual(s1, s2)
        self.assertTrue(s1.startswith("NEW ITEM METADATA:"))

    def test_the_real_prefix_is_well_above_the_cache_minimum(self):
        t = json.loads((REPO / "data" / "treatments.json").read_text(encoding="utf-8"))
        s = json.loads((REPO / "data" / "studies.json").read_text(encoding="utf-8"))
        s = s["studies"] if isinstance(s, dict) else s
        ti = [{"id": x["id"], "name": x["name"], "tier": x["tier"], "evidenceScore": x["evidenceScore"], "loudness": x["loudness"]["level"], "distress": x["distress"]["level"]} for x in t]
        si = [{"id": x["id"], "title": x["title"], "year": x["year"]} for x in s]
        prefix, _ = EQ.build_prompt_parts(ti, si, ITEM_META, "x")
        self.assertGreater(len(prefix) / 4, EQ.CACHE_MIN_TOKENS * 4)   # even at an (optimistic) 4 characters per token: > 2,000 tokens against a 512 minimum


class Flags(unittest.TestCase):
    def _flags(self, content):
        sb = Sandbox({"enabled": False})
        try:
            p = sb.tmp / "engine" / "eval_settings.json"
            if content is None:
                p.unlink()
            else:
                p.write_text(content, encoding="utf-8")
            return sb.eq.load_flags()
        finally:
            sb.close()

    def test_fail_closed(self):
        off = {"promptCaching": False, "useBatch": False}
        for bad in (None, "", "not json", "[]", "{}", '{"promptCaching": "true", "useBatch": "true"}', '{"promptCaching": 1, "useBatch": 1}',
                    '{"promptCaching": "yes"}', '{"useBatch": null}', '{"promptCaching": false, "useBatch": false}'):
            self.assertEqual(self._flags(bad), off, repr(bad))

    def test_only_exact_true_turns_an_option_on(self):
        self.assertEqual(self._flags('{"promptCaching": true}'), {"promptCaching": True, "useBatch": False})
        self.assertEqual(self._flags('{"useBatch": true}'), {"promptCaching": False, "useBatch": True})


class Content(unittest.TestCase):
    def test_off_is_the_plain_string(self):
        prefix, suffix = EQ.build_prompt_parts(T_INDEX, S_INDEX, ITEM_META, "CTX")
        c = EQ.request_content(prefix, suffix, False)
        self.assertIsInstance(c, str)
        self.assertEqual(c, prefix + suffix)
        self.assertNotIn("cache_control", json.dumps(c))

    def test_on_is_two_blocks_with_one_breakpoint_and_the_same_characters(self):
        prefix, suffix = EQ.build_prompt_parts(T_INDEX, S_INDEX, ITEM_META, "CTX")
        c = EQ.request_content(prefix, suffix, True)
        self.assertEqual(len(c), 2)
        self.assertEqual(c[0]["cache_control"], {"type": "ephemeral"})   # default 5-minute lifetime; no 1-hour TTL
        self.assertNotIn("cache_control", c[1])
        self.assertEqual("".join(b["text"] for b in c), prefix + suffix)


class Cost(unittest.TestCase):
    M = "claude-opus-5"

    def usd(self, model=M, batch=False, **kw):
        return EQ.usage_cost(model, _usage(**kw), batch)[2]

    def test_plain_request_costs_what_it_always_did(self):
        self.assertAlmostEqual(self.usd(inp=2700, out=2350), (2700 * 5 + 2350 * 25) / 1e6, places=9)

    def test_cache_write_is_1_25x_and_read_is_the_documented_read_price(self):
        self.assertAlmostEqual(self.usd(inp=0, out=0, write=1_000_000), 5 * 1.25, places=9)
        self.assertAlmostEqual(self.usd(inp=0, out=0, read=1_000_000), 0.50, places=9)
        self.assertAlmostEqual(self.usd("claude-opus-5-5", inp=0, out=0, read=1_000_000), 0.20, places=9)

    def test_miss_then_hit(self):
        miss = self.usd(inp=2500, out=2350, write=5000)
        hit = self.usd(inp=2500, out=2350, read=5000)
        uncached = self.usd(inp=7500, out=2350)
        self.assertGreater(miss, uncached)        # the first request pays the write premium
        self.assertLess(hit, uncached)
        self.assertAlmostEqual(uncached - hit, 5000 * (5 - 0.5) / 1e6, places=9)

    def test_batch_halves_every_component(self):
        kw = dict(inp=2500, out=2350, read=5000)
        self.assertAlmostEqual(self.usd(batch=True, **kw), self.usd(**kw) / 2, places=9)
        kw = dict(inp=2500, out=2350, write=5000)
        self.assertAlmostEqual(self.usd(batch=True, **kw), self.usd(**kw) / 2, places=9)

    def test_unknown_model_and_missing_usage(self):
        self.assertEqual(EQ.usage_cost("some-future-model", _usage(), False)[2], 0.0)
        self.assertEqual(EQ.usage_cost(self.M, None, False), (0, 0, 0.0))
        # a model without a documented cache-read price is charged its full input price (never under-counted)
        self.assertAlmostEqual(EQ.usage_cost("claude-haiku-5-5", _usage(inp=0, out=0, read=1_000_000), False)[2], 0.10, places=9)


class SyncPath(unittest.TestCase):
    def _run(self, settings, **usage_kw):
        sb = Sandbox(settings)
        sdk = FakeSDK()
        sdk.usage_kw = usage_kw
        n, why = sb.run(sdk)
        return sb, sdk, n, why

    def test_options_off_sends_the_plain_string_and_never_touches_batches(self):
        sb, sdk, n, why = self._run({"enabled": True, "mode": "staged", "promptCaching": False, "useBatch": False})
        try:
            self.assertEqual((n, why), (3, None))
            self.assertEqual(len(sdk.calls), 3)
            for kw in sdk.calls:
                self.assertIsInstance(kw["messages"][0]["content"], str)
                self.assertNotIn("cache_control", json.dumps(kw))
            self.assertEqual((sdk.retrieves, sdk.results_calls, len(sdk.batch_creates)), (0, 0, 0))
            self.assertIsNone(sb.state())
            self.assertTrue(all("promptCaching" not in i["evalInput"] and "batch" not in i["evalInput"] for i in sb.queue()["items"]))
            self.assertEqual(sb.eq.LAST_RUN["cacheReadTokens"] + sb.eq.LAST_RUN["cacheWriteTokens"], 0)
        finally:
            sb.close()

    def test_caching_on_sends_the_breakpoint_and_the_same_text(self):
        sb, sdk, n, why = self._run({"enabled": True, "mode": "staged", "promptCaching": True}, write=0, read=5000)
        try:
            self.assertEqual((n, why), (3, None))
            for kw in sdk.calls:
                blocks = kw["messages"][0]["content"]
                self.assertIsInstance(blocks, list)
                self.assertEqual([("cache_control" in b) for b in blocks], [True, False])
                self.assertEqual(kw["thinking"], {"type": "adaptive"})     # same thinking and sampling settings as without caching
                self.assertEqual((kw["model"], kw["max_tokens"]), ("claude-opus-5", 4000))
            self.assertTrue(all(i["evalInput"].get("promptCaching") is True for i in sb.queue()["items"]))
            self.assertEqual(sb.eq.LAST_RUN["cacheReadTokens"], 15000)
            expect = 3 * (1000 * 5 + 5000 * 0.5 + 500 * 25) / 1e6
            self.assertAlmostEqual(sb.eq.LAST_RUN["costUSD"], round(expect, 4), places=4)
            # the same checks and fields as the plain path
            self.assertTrue(all("sourceChecks" in i["evaluation"] and "escalation" in i["evaluation"] for i in sb.queue()["items"]))
        finally:
            sb.close()

    def test_prompt_text_is_identical_with_caching_on_and_off(self):
        texts = {}
        for flag in (False, True):
            sb, sdk, *_ = self._run({"enabled": True, "mode": "staged", "promptCaching": flag})
            texts[flag] = [_flat(kw["messages"][0]["content"]) for kw in sdk.calls]
            sb.close()
        self.assertEqual(texts[False], texts[True])
        self.assertEqual(len(texts[True]), 3)


class BatchPath(unittest.TestCase):
    SET = {"enabled": True, "mode": "staged", "useBatch": True}

    def _submit(self, **kw):
        sb = Sandbox({**self.SET, **kw})
        sdk = FakeSDK()
        before = sb.snapshot("data")
        n, why = sb.run(sdk)
        return sb, sdk, before, n, why

    def test_submit_sends_one_batch_evaluates_nothing_and_changes_no_data(self):
        sb, sdk, before, n, why = self._submit(promptCaching=True)
        try:
            self.assertEqual((n, why), (0, None))
            self.assertEqual(len(sdk.batch_creates), 1)
            reqs = sdk.batch_creates[0]
            self.assertEqual(len(reqs), 3)
            for r in reqs:
                self.assertRegex(r["custom_id"], r"^[A-Za-z0-9_-]{1,64}$")
                p = r["params"]
                self.assertEqual((p["model"], p["max_tokens"], p["thinking"]), ("claude-opus-5", 4000, {"type": "adaptive"}))
                self.assertEqual([("cache_control" in b) for b in p["messages"][0]["content"]], [True, False])   # caching composes with the batch
            self.assertEqual(len({r["custom_id"] for r in reqs}), 3)
            self.assertEqual(sdk.calls, [])                                    # no per-item request was made
            st = sb.state()
            self.assertEqual((st["batchId"], st["promptHash"], st["model"]), ("msgbatch_TEST1", PROMPT_HASH_PINNED, "claude-opus-5"))
            self.assertEqual(set(st["items"]), {r["custom_id"] for r in reqs})
            self.assertNotIn("SECRET", json.dumps(st))
            self.assertEqual(sb.snapshot("data"), before)                      # nothing in data/ changed (queue untouched, nothing evaluated)
            lr = sb.eq.LAST_RUN
            self.assertEqual((lr["attempted"], lr["succeeded"], lr["failed"], lr["submitted"], lr["fatal"]), (0, 0, 0, 3, None))   # weekly_cycle maps this to "idle", not "failed"
            self.assertEqual(lr["batch"]["state"], "submitted")
        finally:
            sb.close()

    def test_pending_batch_submits_nothing_new(self):
        sb, sdk, before, *_ = self._submit()
        try:
            sdk2 = FakeSDK(batch_status="in_progress")
            n, why = sb.run(sdk2)
            self.assertEqual((n, why), (0, None))
            self.assertEqual((len(sdk2.batch_creates), sdk2.results_calls, sdk2.retrieves), (0, 0, 1))
            self.assertEqual(sb.eq.LAST_RUN["batch"]["state"], "pending")
            self.assertIsNotNone(sb.state())
            self.assertEqual(sb.snapshot("data"), before)
        finally:
            sb.close()

    def test_collect_round_trip_out_of_order_with_errored_expired_and_missing(self):
        sb, sdk, before, *_ = self._submit()
        try:
            st = sb.state()
            cids = list(st["items"])
            ids = {c: st["items"][c]["id"] for c in cids}
            self.assertEqual(len(cids), 3)
            # 3 requests were sent; results: one succeeded, one errored; the third has NO result (missing); plus an unknown custom_id; delivered in reverse order
            results = [_result("it-unknown0000000000", "succeeded", "zzz"), _result(cids[1], "errored"), _result(cids[0], "succeeded", ids[cids[0]], _usage(1000, 500, read=5000))]
            sdk2 = FakeSDK(batch_status="ended", results=results)
            n, why = sb.run(sdk2)
            self.assertEqual((n, why), (1, None))
            items = {i["id"]: i for i in sb.queue()["items"]}
            self.assertIn("evaluation", items[ids[cids[0]]])
            self.assertNotIn("evaluation", items[ids[cids[1]]])               # errored: stays queued
            self.assertNotIn("evaluation", items[ids[cids[2]]])               # no result: stays queued
            ev = items[ids[cids[0]]]
            self.assertTrue(ev["evalInput"]["batch"] and ev["evalInput"]["batchId"] == "msgbatch_TEST1")
            self.assertIn("sourceChecks", ev["evaluation"])                   # same deterministic checks as a normal answer
            self.assertIn("escalation", ev["evaluation"])
            lr = sb.eq.LAST_RUN
            self.assertEqual((lr["attempted"], lr["succeeded"], lr["failed"]), (2, 1, 1))
            self.assertEqual(lr["errorClasses"].get("batch_errored"), 1)
            self.assertEqual(lr["batchCollected"]["counts"].get("missing"), 1)
            self.assertEqual(lr["batchCollected"]["counts"].get("unmatched"), 1)
            self.assertAlmostEqual(lr["costUSD"], round(0.5 * (1000 * 5 + 5000 * 0.5 + 500 * 25) / 1e6, 4), places=4)   # batch discount applied, once
            # the old state was consumed; the state now on disk is the NEW batch holding exactly the two unresolved items
            self.assertEqual({e["id"] for e in sb.state()["items"].values()}, {ids[cids[1]], ids[cids[2]]})
            self.assertEqual([len(r) for r in sdk2.batch_creates], [2])       # the two unresolved items go into a NEW batch in the same run; nothing is evaluated by it
        finally:
            sb.close()

    def test_collect_then_resubmit_the_unresolved_items_in_the_same_run(self):
        sb, sdk, before, *_ = self._submit()
        try:
            st = sb.state()
            cids = list(st["items"])
            results = [_result(cids[0], "expired"), _result(cids[1], "canceled"), _result(cids[2], "succeeded", st["items"][cids[2]]["id"])]
            sdk2 = FakeSDK(batch_status="ended", results=results)
            n, why = sb.run(sdk2)
            self.assertEqual(n, 1)
            lr = sb.eq.LAST_RUN
            self.assertEqual((lr["errorClasses"].get("batch_expired"), lr["errorClasses"].get("batch_canceled")), (1, 1))
            self.assertEqual(len(sdk2.batch_creates), 1)                      # the two unresolved items go into a new batch (and are not evaluated now)
            self.assertEqual(len(sdk2.batch_creates[0]), 2)
            self.assertEqual(sb.state()["batchId"], "msgbatch_TEST1")
            self.assertEqual(sb.eq.LAST_RUN["batch"]["state"], "submitted")
        finally:
            sb.close()

    def test_results_are_discarded_if_the_prompt_changed_while_the_batch_ran(self):
        sb, sdk, before, *_ = self._submit()
        try:
            st = sb.state()
            st["promptHash"] = "0000000000000000"
            (sb.tmp / "engine" / "batch-state.json").write_text(json.dumps(st), encoding="utf-8")
            cids = list(st["items"])
            sdk2 = FakeSDK(batch_status="ended", results=[_result(c, "succeeded", st["items"][c]["id"]) for c in cids])
            n, why = sb.run(sdk2)
            self.assertEqual(n, 0)
            self.assertFalse(any("evaluation" in i for i in sb.queue()["items"]))
            self.assertEqual(sb.eq.LAST_RUN["errorClasses"].get("batch_discarded_prompt_changed"), 3)
            self.assertGreater(sb.eq.LAST_RUN["costUSD"], 0)                   # the discarded answers were still billed, and that is recorded
        finally:
            sb.close()

    def test_results_are_discarded_if_the_record_changed(self):
        sb, sdk, before, *_ = self._submit()
        try:
            st = sb.state()
            cids = list(st["items"])
            sb.record_suffix = "\nA CORRECTED ABSTRACT"
            sdk2 = FakeSDK(batch_status="ended", results=[_result(c, "succeeded", st["items"][c]["id"]) for c in cids])
            n, why = sb.run(sdk2)
            self.assertEqual(n, 0)
            self.assertEqual(sb.eq.LAST_RUN["errorClasses"].get("batch_record_changed"), 3)
            self.assertFalse(any("evaluation" in i for i in sb.queue()["items"]))
        finally:
            sb.close()

    def test_unreadable_batch_keeps_state_and_submits_nothing(self):
        sb, sdk, before, *_ = self._submit()
        try:
            sdk2 = FakeSDK(retrieve_error=RuntimeError("network down"))
            n, why = sb.run(sdk2)
            self.assertEqual(n, 0)
            self.assertIn("could not be read", why)
            self.assertEqual(sdk2.batch_creates, [])
            self.assertIsNotNone(sb.state())
        finally:
            sb.close()

    def test_failed_submission_leaves_items_queued_and_writes_no_state(self):
        sb = Sandbox(self.SET)
        try:
            sdk = FakeSDK(create_error=_Status(529, "overloaded"))
            before = sb.snapshot("data")
            n, why = sb.run(sdk)
            self.assertEqual(n, 0)
            self.assertIn("batch submission failed (server)", why)
            self.assertIsNone(sb.state())
            self.assertEqual(sb.snapshot("data"), before)
            self.assertEqual(sb.eq.LAST_RUN["failed"], 1)
        finally:
            sb.close()

    def test_billing_error_on_submission_is_fatal_class(self):
        sb = Sandbox(self.SET)
        try:
            n, why = sb.run(FakeSDK(create_error=_Status(400, "Your credit balance is too low")))
            self.assertEqual(sb.eq.LAST_RUN["fatal"], "billing")
        finally:
            sb.close()

    def test_flags_off_means_a_leftover_state_file_is_ignored(self):
        sb = Sandbox({"enabled": True, "mode": "staged", "useBatch": False})
        try:
            (sb.tmp / "engine" / "batch-state.json").write_text(json.dumps({"batchId": "msgbatch_OLD", "items": {}}), encoding="utf-8")
            sdk = FakeSDK()
            n, why = sb.run(sdk)
            self.assertEqual((n, sdk.retrieves, len(sdk.batch_creates)), (3, 0, 0))
        finally:
            sb.close()


class DryRunWritesNothingToData(unittest.TestCase):
    def test_the_repository_is_untouched_by_the_whole_suite_of_runs(self):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((REPO / "data").rglob("*")) if p.is_file()}
        sb = Sandbox({"enabled": True, "mode": "staged", "useBatch": True, "promptCaching": True})
        try:
            sb.run(FakeSDK())
        finally:
            sb.close()
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((REPO / "data").rglob("*")) if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((REPO / "engine" / "batch-state.json").exists())


if __name__ == "__main__":
    unittest.main()

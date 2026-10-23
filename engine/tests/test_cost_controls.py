"""Offline tests for the evaluator's cost controls: request ceiling, SDK retry and timeout limits, per-item attempt limit, monthly budget guard (sync and batch), near-miss tracking and the alerts in
the health check. No network, no API key: a fake SDK stands in for `anthropic`. Run:  python -m unittest discover -s engine/tests -v"""
import json, re, subprocess, sys, tempfile, types, unittest, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402,F401
import gold_score as gsc  # noqa: E402
from common import run_scenario, ctgov_item, pubmed_item  # noqa: E402
from test_cost_options import Sandbox, FakeSDK, _msg, _result, _usage, _flat, _Status  # noqa: E402

ENGINE = Path(__file__).resolve().parent.parent
SETTINGS = {"enabled": True, "mode": "staged", "promptCaching": False, "useBatch": False}


def write_ledger(sb, runs):
    (sb.tmp / "engine" / "usage-ledger.json").write_text(json.dumps({"runs": runs}), encoding="utf-8")


def sdk_with(reply):
    """FakeSDK whose messages.create is `reply(kw, item_id, call_number)`: return a message, or raise."""
    sdk = FakeSDK(); n = {"i": 0}

    class Msgs:
        batches = sdk.Anthropic().messages.batches

        def create(self, **kw):
            if kw.get("max_tokens") == 1:
                return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")])
            sdk.calls.append(kw)
            iid = json.loads(re.search(r"NEW ITEM METADATA:\n(\{.*?\})\n\n", _flat(kw["messages"][0]["content"]), re.S).group(1))["id"]
            n["i"] += 1
            return reply(kw, iid, n["i"])
    sdk.client_kwargs = []
    sdk.Anthropic = lambda *a, **k: (sdk.client_kwargs.append(k), types.SimpleNamespace(messages=Msgs()))[1]
    return sdk


def priced(out_tokens):
    return lambda kw, iid, n: _msg(iid, _usage(1000, out_tokens))


class Ceiling(unittest.TestCase):
    def test_the_request_ceiling_is_8000_and_the_client_has_explicit_retry_and_timeout_limits(self):
        sb = Sandbox(SETTINGS, n_items=1)
        try:
            sdk = sdk_with(priced(500))
            sb.run(sdk)
            self.assertEqual(sb.eq.MAX_OUTPUT_TOKENS, 8000)
            self.assertEqual([c["max_tokens"] for c in sdk.calls], [8000])
            self.assertEqual(sdk.client_kwargs, [{"max_retries": 1, "timeout": 480.0}])      # the SDK default is 2 retries and no explicit timeout
        finally:
            sb.close()

    def test_the_8000_ceiling_stays_below_the_sdk_guard_for_non_streaming_requests(self):
        # the pinned SDK (1.15.0) refuses non-streaming requests it expects to take over 10 minutes: 21,333 tokens; 8,000 and the 16,000 fallback are well under
        self.assertLess(16000, 21333)


class Budget(unittest.TestCase):
    def test_budget_setting_is_validated_and_cannot_be_switched_off_by_a_typo(self):
        sb = Sandbox(SETTINGS, n_items=0)
        try:
            def with_budget(b):
                (sb.tmp / "engine" / "eval_settings.json").write_text(json.dumps({**SETTINGS, **({} if b is None else {"budget": b})}), encoding="utf-8")
                return sb.eq.load_budget()
            self.assertEqual(with_budget({"monthlyUSD": 7.5}), 7.5)
            self.assertEqual(with_budget({"monthlyUSD": 30}), 30.0)
            for bad in (None, {}, {"monthlyUSD": 0}, {"monthlyUSD": -5}, {"monthlyUSD": "20"}, {"monthlyUSD": True}, {"monthlyUSD": None}, {"monthlyUSD": 10 ** 9}, "20", [1]):
                self.assertEqual(with_budget(bad), 20.0, bad)
            (sb.tmp / "engine" / "eval_settings.json").write_text("not json", encoding="utf-8")
            self.assertEqual(sb.eq.load_budget(), 20.0)
        finally:
            sb.close()

    def test_month_spend_comes_from_the_ledger_and_an_unreadable_ledger_counts_as_spent(self):
        sb = Sandbox(SETTINGS, n_items=0)
        try:
            self.assertEqual(sb.eq.month_spent_usd("2026-11-15"), 0.0)                       # no ledger yet
            write_ledger(sb, [{"date": "2026-10-31", "estimatedCostUSD": 9.0}, {"date": "2026-11-01", "estimatedCostUSD": 1.25}, {"date": "2026-11-15", "estimatedCostUSD": 2.0}])
            self.assertEqual(sb.eq.month_spent_usd("2026-11-20"), 3.25)                       # only this calendar month
            st = sb.eq.budget_status(extra=1.0, today="2026-11-20")
            self.assertEqual((st["monthlyUSD"], st["spentUSD"], st["fraction"]), (20.0, 4.25, 0.212))
            (sb.tmp / "engine" / "usage-ledger.json").write_text("{broken", encoding="utf-8")
            self.assertIsNone(sb.eq.month_spent_usd())
            self.assertEqual(sb.eq.budget_status()["fraction"], 1.0)
        finally:
            sb.close()

    def test_a_spent_budget_stops_everything_before_any_paid_call(self):
        sb = Sandbox(SETTINGS)
        try:
            write_ledger(sb, [{"date": time_month(), "estimatedCostUSD": 20.0}])
            sdk = sdk_with(priced(500))
            n, why = sb.run(sdk)
            self.assertEqual((n, sdk.calls), (0, []))
            self.assertEqual(sb.eq.LAST_RUN["fatal"], "budget")
            self.assertIn("monthly evaluation budget reached", why)
            self.assertTrue(all(not i.get("evaluation") and not i.get("evalAttempts") for i in sb.queue()["items"]))      # untouched, will be evaluated next month
        finally:
            sb.close()

    def test_an_unreadable_ledger_pauses_evaluation_rather_than_spending_blind(self):
        sb = Sandbox(SETTINGS)
        try:
            (sb.tmp / "engine" / "usage-ledger.json").write_text("{broken", encoding="utf-8")
            sdk = sdk_with(priced(500))
            n, why = sb.run(sdk)
            self.assertEqual((n, sdk.calls, sb.eq.LAST_RUN["fatal"]), (0, [], "budget"))
            self.assertIn("could not be read", why)
        finally:
            sb.close()

    def test_the_run_stops_when_the_next_call_could_take_the_month_over_budget(self):
        sb = Sandbox({**SETTINGS, "budget": {"monthlyUSD": 1.7}})
        try:
            sdk = sdk_with(priced(30000))             # each (fake) answer is billed at about $0.75
            n, why = sb.run(sdk)
            self.assertEqual(len(sdk.calls), 2)       # call 3 would need 1.5 spent + a worst case of about 0.3
            self.assertEqual(n, 2)
            self.assertEqual(sb.eq.LAST_RUN["fatal"], "budget")
            items = sb.queue()["items"]
            self.assertEqual([bool(i.get("evaluation")) for i in items], [True, True, False])
            self.assertIn("monthly evaluation budget would be exceeded", sb.eq.LAST_RUN["reason"])
        finally:
            sb.close()

    def test_a_run_inside_the_budget_is_unaffected(self):
        sb = Sandbox(SETTINGS)
        try:
            sdk = sdk_with(priced(800))
            n, why = sb.run(sdk)
            self.assertEqual((n, why, len(sdk.calls)), (3, None, 3))
            self.assertIsNone(sb.eq.LAST_RUN["fatal"])
        finally:
            sb.close()

    def test_the_batch_route_plans_requests_only_while_they_fit_the_budget(self):
        probe = Sandbox({**SETTINGS, "useBatch": True}, n_items=3)
        try:
            sdk = FakeSDK(); probe.run(sdk)
            self.assertEqual(len(sdk.batch_creates[0]), 3)
            chars = len(_flat(sdk.batch_creates[0][0]["params"]["messages"][0]["content"]))
            self.assertNotIn("_chars", sdk.batch_creates[0][0])                      # internal bookkeeping never reaches the API
            w = probe.eq.worst_case_usd(chars)
        finally:
            probe.close()
        sb = Sandbox({**SETTINGS, "useBatch": True, "budget": {"monthlyUSD": round(w * 2.5, 4)}}, n_items=3)
        try:
            sdk = FakeSDK(); sb.run(sdk)
            self.assertEqual(len(sdk.batch_creates[0]), 2)                           # the third would not fit
            self.assertEqual(sb.eq.LAST_RUN["fatal"], "budget")
            self.assertEqual(sorted(i.get("evalAttempts") or 0 for i in sb.queue()["items"]), [0, 0, 0])      # submission leaves the queue untouched
        finally:
            sb.close()


def time_month():
    import time
    return time.strftime("%Y-%m-%d")


class BatchAttempts(unittest.TestCase):
    def test_provider_side_failures_count_as_attempts_and_the_item_is_given_up_after_two(self):
        sb = Sandbox({**SETTINGS, "useBatch": True}, n_items=2)
        try:
            sb.run(FakeSDK())                                                      # submit both items
            for results in (lambda c: [_result(c[0], "errored"), _result(c[1], "expired")],      # collect (both fail; the same run resubmits them)
                            lambda c: [_result(c[0], "errored")]):                                # collect again: one fails, the other gets no result at all
                cids = list(sb.state()["items"])
                sb.run(FakeSDK(batch_status="ended", results=results(cids)))
            items = sb.queue()["items"]
            self.assertEqual([i.get("evalAttempts") for i in items], [2, 2])
            sdk3 = FakeSDK(); sb.run(sdk3)                                         # third run: both are given up, nothing is submitted
            self.assertEqual(sdk3.batch_creates, [])
            self.assertEqual([i["evaluation"]["failureKind"] for i in sb.queue()["items"]], ["attempts-exhausted", "attempts-exhausted"])
        finally:
            sb.close()


class Attempts(unittest.TestCase):
    def failing(self, status=500):
        def reply(kw, iid, n):
            if iid.endswith("900000"):
                raise _Status(status, "boom")
            return _msg(iid)
        return sdk_with(reply)

    def test_an_item_that_keeps_failing_is_given_up_after_two_paid_attempts_and_listed_without_ai(self):
        sb = Sandbox(SETTINGS)
        try:
            sdk = self.failing()
            sb.run(sdk)                                              # run 1: item 0 errors, the other two are evaluated
            first = sb.queue()["items"][0]
            self.assertEqual((first.get("evalAttempts"), bool(first.get("evaluation"))), (1, False))
            self.assertEqual(sb.eq.LAST_RUN["errorClasses"], {"server": 1})
            sb.run(sdk)                                              # run 2: second and last attempt
            second = sb.queue()["items"][0]
            self.assertEqual((second.get("evalAttempts"), bool(second.get("evaluation"))), (2, False))
            calls = len(sdk.calls)
            sb.run(sdk)                                              # run 3: given up, no call
            third = sb.queue()["items"][0]
            self.assertEqual(len(sdk.calls), calls)
            self.assertEqual((third["evaluation"]["failureKind"], third["evaluation"]["parseError"]), ("attempts-exhausted", True))
            self.assertEqual(gsc.causes(third["evaluation"]), ["evaluation-failure:attempts-exhausted"])
            self.assertEqual(sb.eq.LAST_RUN["failureKinds"], {"attempts-exhausted": 1})
            self.assertEqual(sb.eq.LAST_RUN["parseErrors"], 1)
            sb.run(sdk)                                              # and never again
            self.assertEqual(len(sdk.calls), calls)
        finally:
            sb.close()

    def test_a_rate_limit_or_a_key_problem_is_not_counted_against_the_item(self):
        RL = type("RateLimitError", (_Status,), {})
        for exc in (lambda: RL(429, "slow down"), lambda: _Status(429, "slow down"), lambda: _Status(401, "invalid x-api-key"), lambda: _Status(400, "Your credit balance is too low to access the Anthropic API.")):
            sb = Sandbox(SETTINGS, n_items=2)
            try:
                def reply(kw, iid, n):
                    raise exc()
                sdk = sdk_with(reply)
                sdk.module = lambda sdk=sdk, RL=RL: self._module(sdk, RL)
                sb.run(sdk)
                self.assertEqual([i.get("evalAttempts") or 0 for i in sb.queue()["items"]], [0, 0])
                self.assertEqual(len(sdk.calls), 1)                  # the run stops at once: no second doomed call
            finally:
                sb.close()

    @staticmethod
    def _module(sdk, RL):
        m = types.ModuleType("anthropic")
        m.Anthropic, m.APIStatusError, m.RateLimitError = sdk.Anthropic, _Status, RL
        return m

    def test_the_attempt_is_on_disk_before_the_call_returns(self):
        sb = Sandbox(SETTINGS, n_items=1)
        try:
            seen = {}

            def reply(kw, iid, n):
                seen["attempts_on_disk"] = sb.queue()["items"][0].get("evalAttempts")      # read the queue file while the call is in flight
                return _msg(iid)
            sb.run(sdk_with(reply))
            self.assertEqual(seen["attempts_on_disk"], 1)
        finally:
            sb.close()


class NearMiss(unittest.TestCase):
    def test_answers_close_to_the_ceiling_are_counted_and_the_largest_is_reported(self):
        sb = Sandbox(SETTINGS, n_items=3)
        try:
            sizes = {1: 500, 2: 7000, 3: 6100}
            sdk = sdk_with(lambda kw, iid, n: _msg(iid, _usage(1000, sizes[n])))
            sb.run(sdk)
            self.assertEqual((sb.eq.LAST_RUN["nearMisses"], sb.eq.LAST_RUN["maxOutputTokens"]), (2, 7000))      # over 75 % of 8,000 = 6,000
            self.assertEqual(sorted(i["evalInput"]["outputTokens"] for i in sb.queue()["items"]), [500, 6100, 7000])
            self.assertEqual(sb.eq.LAST_RUN["failureKinds"], {})                                               # near misses are complete answers
        finally:
            sb.close()


class Health(unittest.TestCase):
    def run_health(self, ev, errors=()):
        d = Path(tempfile.mkdtemp(prefix="te-health-"))
        try:
            (d / "engine").mkdir(); (d / "data").mkdir()
            shutil.copy(ENGINE / "check_evaluation_health.py", d / "engine" / "check_evaluation_health.py")
            (d / "data" / "engine-status.json").write_text(json.dumps({"evaluation": {"state": "ok", "attempted": 5, "failed": 0, "awaitingEvaluation": 0, **ev}, "errors": list(errors)}), encoding="utf-8")
            p = subprocess.run([sys.executable, str(d / "engine" / "check_evaluation_health.py")], capture_output=True, text=True, encoding="utf-8", errors="replace")
            return p.returncode, p.stdout + p.stderr
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_clean_run_is_green(self):
        self.assertEqual(self.run_health({})[0], 0)

    def test_a_truncated_answer_is_red(self):
        rc, out = self.run_health({"state": "degraded", "parseErrors": 1, "failureKinds": {"truncated": 1}})
        self.assertEqual(rc, 1); self.assertIn("cut off at the output ceiling", out)

    def test_one_other_unusable_answer_is_a_warning_two_are_red(self):
        rc, out = self.run_health({"state": "degraded", "parseErrors": 1, "failureKinds": {"unparseable": 1}})
        self.assertEqual(rc, 0); self.assertIn("unusable", out)
        rc, out = self.run_health({"state": "degraded", "parseErrors": 2, "failureKinds": {"unparseable": 1, "refused": 1}})
        self.assertEqual(rc, 1)
        rc, out = self.run_health({"state": "degraded", "parseErrors": 1, "failureKinds": {"attempts-exhausted": 1}})
        self.assertEqual(rc, 0)

    def test_near_misses_warn(self):
        rc, out = self.run_health({"nearMisses": 2, "maxOutputTokens": 7000})
        self.assertEqual(rc, 0); self.assertIn("over 75 %", out)

    def test_budget_thresholds(self):
        self.assertEqual(self.run_health({"budget": {"monthlyUSD": 20, "spentUSD": 5, "fraction": 0.25}})[0], 0)
        rc, out = self.run_health({"budget": {"monthlyUSD": 20, "spentUSD": 12.5, "fraction": 0.625}})
        self.assertEqual(rc, 0); self.assertIn("63 % of the monthly AI budget", out.replace("62 %", "63 %"))
        rc, out = self.run_health({"budget": {"monthlyUSD": 20, "spentUSD": 20.1, "fraction": 1.005}})
        self.assertEqual(rc, 1); self.assertIn("budget is used up", out)

    def test_a_budget_stop_is_red_through_the_failed_state(self):
        rc, out = self.run_health({"state": "failed", "fatal": "budget", "reason": "monthly evaluation budget reached ($20.00 of $20.00 estimated)"})
        self.assertEqual(rc, 1); self.assertIn("budget reached", out)


class WeeklyCycle(unittest.TestCase):
    ON = {"enabled": True, "mode": "staged", "limitPerRun": 10}

    def test_the_status_reports_budget_near_misses_and_failures_for_the_digest_and_alerts(self):
        A, B = pubmed_item(910001, "A routine tinnitus trial A"), pubmed_item(910002, "A routine tinnitus trial B")
        run = run_scenario({"queue": [A, B], "settings": {**self.ON, "budget": {"monthlyUSD": 10}}, "runs": [{}],
                            "rawAnswers": {"pubmed-910002": {"text": '{"relevanceCategory": 1, "summaryForAdmin": "cut', "stopReason": "max_tokens", "outputTokens": 8000}}})["runs"][0]
        ev = run["status"]["evaluation"]
        self.assertEqual(ev["budget"]["monthlyUSD"], 10.0)
        self.assertTrue(0 < ev["budget"]["spentUSD"] < 1.0 and ev["budget"]["fraction"] < 0.1)
        self.assertEqual((ev["state"], ev["failureKinds"], ev["maxOutputTokens"], ev["nearMisses"]), ("degraded", {"truncated": 1}, 8000, 1))
        self.assertEqual(run["ledger"]["runs"][-1]["attempted"], 2)

    def test_an_older_registry_update_waiting_for_its_paused_sibling_is_not_a_backlog(self):
        old, new = ctgov_item("NCT09999991", "2026-10-13", "Registry update"), ctgov_item("NCT09999991", "2026-10-20", "Registry update")
        run = run_scenario({"queue": [old, new], "settings": self.ON, "paused": [new["id"]], "runs": [{}]})["runs"][0]
        ev = run["status"]["evaluation"]
        self.assertEqual((ev["paused"], ev["awaitingEvaluation"]), (1, 0))
        self.assertEqual(sorted(run["queue"]), sorted([old["id"], new["id"]]))      # both kept, nothing lost, nothing evaluated
        self.assertEqual(run["totalApiCalls"], 0)


if __name__ == "__main__":
    unittest.main()

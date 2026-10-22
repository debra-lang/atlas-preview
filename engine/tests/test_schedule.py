"""The research cycle runs on the 1st and 15th of each month (owner decision, 21 Oct 2026). Offline."""
import re, sys, unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import weekly_cycle, weekly_scan  # noqa: E402
from datetime import timezone  # noqa: E402
try:
    from zoneinfo import ZoneInfo
    LA = ZoneInfo("America/Los_Angeles")
except Exception:   # no tz database (a plain Windows Python): the date logic does not depend on daylight saving, so a fixed offset tests the same thing
    LA = timezone(timedelta(hours=-8))


class Workflow(unittest.TestCase):
    def test_exactly_one_schedule_on_the_1st_and_15th_at_6_pacific(self):
        t = (REPO / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
        crons = re.findall(r'^\s*-\s*cron:\s*"([^"]+)"', t, re.M)
        self.assertEqual(crons, ["0 6 1,15 * *"])
        self.assertRegex(t, r'timezone:\s*"America/Los_Angeles"')
        self.assertIn("workflow_dispatch", t)                                           # a manual run stays possible

    def test_the_scan_window_covers_the_longest_gap_between_runs_with_room_for_a_delay(self):
        gaps, d = [], date(2026, 1, 1)
        runs = []
        while d < date(2045, 1, 1):
            if d.day in (1, 15):
                runs.append(d)
            d += timedelta(days=1)
        gaps = [(b - a).days for a, b in zip(runs, runs[1:])]
        self.assertEqual(max(gaps), 17)                                                 # 15 January to 1 February
        self.assertGreaterEqual(weekly_scan.DAYS, max(gaps) + 3)                        # a delayed or failed run must still be covered
        self.assertEqual(weekly_scan.DAYS, 20)


class NextRun(unittest.TestCase):
    def nxt(self, y, mo, d, h=12, mi=0):
        return weekly_cycle.next_scheduled(datetime(y, mo, d, h, mi, tzinfo=LA)).strftime("%Y-%m-%d %H:%M")

    def test_dates(self):
        self.assertEqual(self.nxt(2026, 10, 21), "2026-11-01 06:00")
        self.assertEqual(self.nxt(2026, 10, 31, 23, 59), "2026-11-01 06:00")
        self.assertEqual(self.nxt(2026, 11, 1, 5, 0), "2026-11-01 06:00")             # before the run on the day: today
        self.assertEqual(self.nxt(2026, 11, 1, 7, 0), "2026-11-15 06:00")             # after it: the 15th
        self.assertEqual(self.nxt(2026, 11, 15, 6, 0), "2026-12-01 06:00")            # at the instant: the next one
        self.assertEqual(self.nxt(2026, 12, 15, 12), "2027-01-01 06:00")              # year boundary
        self.assertEqual(self.nxt(2027, 2, 15, 12), "2027-03-01 06:00")               # short February
        self.assertEqual(self.nxt(2026, 12, 20), "2027-01-01 06:00")

    def test_the_status_text_names_the_new_schedule(self):
        self.assertIn("1st and 15th", weekly_cycle.SCHEDULE_TEXT); self.assertNotIn("Monday", weekly_cycle.SCHEDULE_TEXT)
        self.assertRegex(weekly_cycle.next_run_6am(), r"^\d{4}-\d{2}-(01|15) 06:00 America/Los_Angeles$")


class WorkflowsPinTheTestedSdk(unittest.TestCase):
    def test_the_workflows_that_call_the_api_install_exactly_the_sdk_version_every_paid_test_used(self):
        for wf in ("weekly.yml", "benchmark.yml"):
            t = (REPO / ".github" / "workflows" / wf).read_text(encoding="utf-8")
            installs = re.findall(r"pip install\s+\"?([^\s\"#]+)", t)
            self.assertIn("anthropic==1.15.0", installs, wf)
            self.assertNotIn("anthropic", [i for i in installs if "==" not in i], wf)     # never an unpinned install


class DaylightSavingTime(unittest.TestCase):
    """06:00 Pacific on the 1st and 15th is never inside a daylight-saving gap or repeated hour (the changes happen at 02:00 on Sundays), so the schedule is unambiguous in every month through 2035.
    Sunday 1 November 2026 is the day the clocks go back: 06:00 that day is already standard time (14:00 UTC), unlike 15 October (13:00 UTC)."""
    @classmethod
    def setUpClass(cls):
        try:
            from zoneinfo import ZoneInfo
            cls.LA, cls.UTC = ZoneInfo("America/Los_Angeles"), ZoneInfo("UTC")
        except Exception:
            raise unittest.SkipTest("no tz database on this Python")

    def test_known_instants(self):
        at = lambda y, m, d: datetime(y, m, d, 6, 0, tzinfo=self.LA).astimezone(self.UTC).strftime("%Y-%m-%d %H:%M")
        self.assertEqual(at(2026, 10, 15), "2026-10-15 13:00")
        self.assertEqual(at(2026, 11, 1), "2026-11-01 14:00")      # the clocks went back at 02:00 that morning
        self.assertEqual(at(2026, 11, 15), "2026-11-15 14:00")
        self.assertEqual(at(2027, 3, 1), "2027-03-01 14:00")
        self.assertEqual(at(2027, 3, 15), "2027-03-15 13:00")      # the clocks went forward on Sunday 14 March
        self.assertEqual(date(2026, 11, 1).weekday(), 6)            # a Sunday: the change day itself

    def test_never_ambiguous_and_never_in_a_gap(self):
        for y in range(2026, 2036):
            for m in range(1, 13):
                for d in (1, 15):
                    t0 = datetime(y, m, d, 6, 0, tzinfo=self.LA)
                    t1 = datetime(y, m, d, 6, 0, tzinfo=self.LA, fold=1)
                    self.assertEqual(t0.utcoffset(), t1.utcoffset(), (y, m, d))                      # not in a repeated hour
                    self.assertEqual(t0.astimezone(self.UTC).astimezone(self.LA).hour, 6, (y, m, d))  # not in a skipped hour
                    self.assertEqual(t0.replace(hour=2).utcoffset() is not None, True)

    def test_the_workflow_uses_the_named_timezone_not_a_fixed_utc_hour(self):
        t = (REPO / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
        self.assertRegex(t, r'cron:\s*"0 6 1,15 \* \*"')
        self.assertRegex(t, r'timezone:\s*"America/Los_Angeles"')

    def test_the_documentation_does_not_promise_a_start_time_or_a_deployment_window(self):
        readme = (ENGINE / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("05:45-07:00", readme)
        self.assertIn("no cycle run is queued or in progress", readme)
        self.assertIn("hours late", weekly_cycle.SCHEDULE_TEXT)


if __name__ == "__main__":
    unittest.main()

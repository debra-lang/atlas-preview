"""The smallest repository the real cycle runs on, for tests that run the whole cycle with every scanner and fetch stubbed."""
import hashlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, REPO, pubmed_item, run_scenario   # noqa: E402

import registry_record, topic_holds, triage, weekly_cycle, weekly_scan, check_retractions  # noqa: E402

PAUSED, HOLDS = "engine/paused_ids.json", "engine/topic_holds.json"
QUEUE, KNOWN, REGISTER = "data/review-queue/queue.json", "engine/known_ids.json", "engine/published_ids.json"
SCAN_STATE, SOURCES, HASHES, RETRACTION, RULES = "engine/scan-state.json", "engine/sources.json", "engine/page-hashes.json", "engine/retraction-state.json", "engine/triage_rules.json"
ARCHIVE, INDEX, TRIALS, STUDIES, TREATMENTS = "data/review-queue/archive.json", "data/weekly/index.json", "data/trials.json", "data/studies.json", "data/treatments.json"
LISTINGS, HISTORY = "data/listings.json", "data/update-history.json"
HELD, STAGED, DECISIONS = "data/review-queue/held.json", "data/review-queue/staged.json", "data/review-queue/decisions.json"
LEDGER, EVIDENCE, BENCH, BATCH = "engine/usage-ledger.json", "engine/triage-evidence.json", "engine/benchmark-report.json", "engine/batch-state.json"
EVAL, AUTO, STATUS = "engine/eval_settings.json", "engine/automation_settings.json", "data/engine-status.json"
HAND_EDITED = ("engine/paused_ids.json", "engine/topic_holds.json", "engine/eval_settings.json", "engine/automation_settings.json", "engine/sources.json", "engine/triage_rules.json")
REQUIRED = [PAUSED, HOLDS, QUEUE, KNOWN, REGISTER, SCAN_STATE, SOURCES, HASHES, RETRACTION, RULES, ARCHIVE, INDEX, TRIALS, STUDIES, TREATMENTS, LISTINGS, HISTORY]
OPTIONAL = [HELD, STAGED, DECISIONS, LEDGER, EVIDENCE, BENCH, BATCH, EVAL, AUTO, STATUS]
ALL = REQUIRED + OPTIONAL

FACTS = {"tinAbs": 4, "tinMesh": True, "tracked": [], "safety": [], "safetyWeak": [], "animalOnly": False, "hasAbstract": True}
ITEM = pubmed_item(990001, "A routine tinnitus trial", source="J Audiol", triage=FACTS)
SCANNED = pubmed_item(990002, "A newly scanned tinnitus trial", source="J Audiol", triage=FACTS)
LENIRE = pubmed_item(990003, "Lenire bimodal stimulation for tinnitus", source="J Audiol", triage=FACTS)
TODAY = date.today().isoformat()


def W(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def record(item):
    n = item["id"].split("-", 1)[1]
    return registry_record.finish_pubmed_record(f"Title: {item.get('title', '')}\nPMID: {n}\nAbstract: Methods: randomized controlled trial; 83 participants were randomized.\nResults: the mean score fell by 6.5 points (95% CI 2.1 to 10.9; p=0.004).", n)[0]


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


class Sandbox(unittest.TestCase):
    """The smallest repository the real cycle runs on: every required file, sound, with the real hold and pause rules."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="te-fc-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        r = self.root
        W(r, PAUSED, {"comment": "x", "ids": [ITEM["id"]]})
        W(r, HOLDS, json.loads((ENGINE / "topic_holds.json").read_text(encoding="utf-8")))
        W(r, QUEUE, {"items": [ITEM]})
        W(r, KNOWN, [ITEM["id"], "pubmed-1"])
        W(r, REGISTER, ["somepublishedkey"])
        W(r, SCAN_STATE, {"pubmed": TODAY, "ctgov": TODAY})
        W(r, SOURCES, {"feeds": [{"name": "a", "url": "https://example.invalid/a"}], "newsIntel": [{"name": "n", "query": "tinnitus"}], "pages": [{"name": "b", "url": "https://example.invalid/b"}]})
        W(r, HASHES, {"https://example.invalid/b": "abc"})
        W(r, RETRACTION, {"lastRun": TODAY})
        W(r, RULES, json.loads((ENGINE / "triage_rules.json").read_text(encoding="utf-8")))
        W(r, ARCHIVE, {"items": [], "emptyOnPurpose": True})
        W(r, HELD, {"items": []})
        W(r, INDEX, {"reports": [{"date": "2026-01-01", "file": "2026-01-01.json", "title": "x"}]})
        W(r, "data/weekly/2026-01-01.json", {"items": []})
        W(r, TRIALS, [])
        W(r, STUDIES, [{"id": "s1", "title": "A study", "year": 2020}])
        W(r, TREATMENTS, [{"id": "cbt", "name": "CBT"}])
        W(r, EVAL, {"enabled": False, "mode": "staged"})
        W(r, AUTO, {"listings": True, "updateHistory": True})
        W(r, LISTINGS, {"version": 1, "count": 0, "items": []})
        W(r, HISTORY, {"version": 1, "entries": []})
        self.scans = 0

    def scanner(self):
        self.scans += 1
        return [dict(SCANNED)]

    def run_main(self):
        """The real main() against the sandbox with every scanner, network path and fetch stubbed. Returns (exit code, output)."""
        saved = {n: getattr(weekly_scan, n) for n in ("scan_pubmed", "scan_ctgov", "scan_feeds", "scan_fda", "scan_news_intel", "scan_pages")}
        for n in saved:
            setattr(weekly_scan, n, self.scanner if n == "scan_pubmed" else (saved[n] if n in getattr(self, "keep_real", ()) else (lambda: [])))
        due, eng, argv = check_retractions.due, weekly_cycle.ENGINE, sys.argv
        fetch, enrich = weekly_cycle.evaluate_queue.fetch_context, triage.fetch_xml
        check_retractions.due = lambda *a, **k: False
        weekly_cycle.ENGINE, sys.argv = self.root / "engine", ["weekly_cycle.py"]
        weekly_cycle.evaluate_queue.fetch_context = getattr(self, "fetch", record)
        triage.fetch_xml = lambda ids: None     # no network from a test
        out, err = io.StringIO(), io.StringIO()
        rc = 0
        try:
            import contextlib
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                weekly_cycle.main()
        except SystemExit as e:
            rc = e.code or 0
        finally:
            for n, f in saved.items():
                setattr(weekly_scan, n, f)
            check_retractions.due, weekly_cycle.ENGINE, sys.argv = due, eng, argv
            weekly_cycle.evaluate_queue.fetch_context, triage.fetch_xml = fetch, enrich
        return rc, out.getvalue() + err.getvalue()

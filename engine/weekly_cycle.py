#!/usr/bin/env python3
"""Tinnitus Evidence — automated weekly research cycle.

scan -> AI evaluation -> deterministic verification gates -> routing:
  CLASS A (routine, verified)  -> publishes automatically to This Week in Tinnitus Research
  CLASS B (major / uncertain)  -> data/review-queue/held.json ("Major Evidence Changes — Held")
                                  the public assessment stays unchanged until resolved;
                                  if the underlying FACT is verified, a weekly item may still
                                  publish flagged "Impact on rating: Under evaluation".
Also: refreshes tracked trial statuses directly from ClinicalTrials.gov (registry-verified,
Class A), appends a full audit trail (engine/audit-log.jsonl), and maintains
data/engine-status.json for the admin status board.

Guarantees:
  * All public-data writes are staged in memory and committed only after the whole cycle
    succeeds — a failed scan can never corrupt or partially update the site.
  * Evidence scores, tiers, rankings, loudness/distress ratings, safety assessments and
    treatment regulatory statuses are NEVER changed by this script. Ever.
  * A quiet week publishes an honest "no evidence-changing research identified" note —
    dates are never bumped to fake freshness.

Usage:
  python engine/weekly_cycle.py                 # real weekly run
  python engine/weekly_cycle.py --simulate      # full end-to-end test in a sandbox copy
  python engine/weekly_cycle.py --skip-eval     # scan + deterministic steps only
"""
import json, re, shutil, sys, tempfile, urllib.request, urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
import weekly_scan  # noqa: E402  (scan_pubmed / scan_ctgov / scan_feeds)
import evaluate_queue  # noqa: E402

SCHEDULE_TEXT = "Every Monday 06:00 America/Los_Angeles (timezone-aware — stays 6 AM Pacific through PST/PDT) via GitHub Actions (.github/workflows/weekly.yml); local Task Scheduler task disabled"
TRUSTED_DOMAINS = (
    "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "clinicaltrials.gov", "fda.gov",
    "accessdata.fda.gov", "nih.gov", "nidcd.nih.gov", "cochranelibrary.com", "cochrane.org",
    "ema.europa.eu", "diga.bfarm.de", "nature.com", "jamanetwork.com", "sciencedirect.com",
    "springer.com", "link.springer.com", "tandfonline.com", "frontiersin.org", "plos.org",
    "journals.plos.org", "bmj.com", "doi.org", "science.org", "ata.org", "entnet.org", "jmir.org",
)
COMPANY_HINTS = ("businesswire", "prnewswire", "globenewswire", "press-release", "press_release", "investor")


def next_monday_6am():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except Exception:  # tz database unavailable (some Windows setups) — PST approximation
        from datetime import timezone
        tz = timezone(timedelta(hours=-8))
    now = datetime.now(tz)
    d = now + timedelta(days=((7 - now.weekday()) % 7) or 7)
    return d.strftime("%Y-%m-%d") + " 06:00 America/Los_Angeles"


class Cycle:
    def __init__(self, root, simulate=False, skip_eval=False, days=7):
        self.root, self.simulate, self.skip_eval, self.days = Path(root), simulate, skip_eval, days
        self.staged = {}          # path -> obj (committed only on success)
        self.audit = []           # audit-log entries for this run
        self.status = {
            "schedule": SCHEDULE_TEXT, "nextScheduled": next_monday_6am(),
            "lastAttempt": datetime.now().isoformat(timespec="seconds"),
            "sources": [], "examined": 0, "newItems": 0, "published": 0,
            "rejectedDuplicates": 0, "rejectedIrrelevant": 0, "held": 0,
            "publishedUnderEvaluation": 0, "heldAwaitingEvaluation": 0, "trialStatusUpdates": 0, "errors": [],
        }

    # ---------- io ----------
    def load(self, rel, default):
        p = self.root / rel
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default

    def stage(self, rel, obj):
        self.staged[rel] = obj

    def commit(self):
        for rel, obj in self.staged.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)  # atomic on same volume
        if self.audit:
            with open(self.root / "engine" / "audit-log.jsonl", "a", encoding="utf-8") as f:
                for e in self.audit:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self.staged, self.audit = {}, []  # committed — never write the same entries twice

    def log(self, **kw):
        kw.setdefault("date", datetime.now().isoformat(timespec="seconds"))
        kw.setdefault("simulate", self.simulate)
        self.audit.append(kw)

    # ---------- steps ----------
    def scan(self, fixtures=None):
        queue = self.load("data/review-queue/queue.json", {"items": []})
        known = set(self.load("engine/known_ids.json", []))
        existing = {it["id"] for it in queue["items"]}
        new = []
        scanners = fixtures if fixtures is not None else [
            ("PubMed", weekly_scan.scan_pubmed), ("ClinicalTrials.gov", weekly_scan.scan_ctgov),
            ("Watched feeds (FDA, NIH/NIDCD, journals, EMA…)", weekly_scan.scan_feeds)]
        for name, fn in scanners:
            src = {"name": name, "checked": True, "count": 0, "error": None}
            try:
                items = fn()
                src["count"] = len(items)
                self.status["examined"] += len(items)
                new += [it for it in items if it["id"] not in known and it["id"] not in existing]
            except Exception as e:
                src["error"] = str(e)[:200]
                self.status["errors"].append(f"source '{name}' failed: {e}")
            self.status["sources"].append(src)
        # cross-source duplicate-title collapse
        seen, dedup = set(), []
        for it in new:
            k = re.sub(r"\W+", "", it["title"].lower())[:80]
            if k and k in seen:
                continue
            seen.add(k)
            dedup.append(it)
        self.status["newItems"] = len(dedup)
        queue["items"] = dedup + queue["items"]
        queue["lastScan"] = date.today().isoformat()
        self.stage("data/review-queue/queue.json", queue)
        self.stage("engine/known_ids.json", sorted(known | {it["id"] for it in dedup}))
        return queue

    def refresh_trials(self, fixture=None):
        """Registry-verified status refresh for tracked NCTs — the one deterministic Class A
        auto-update to structured data (trial status only; nothing evidence-rated)."""
        trials = self.load("data/trials.json", [])
        changed = []
        for tr in trials:
            try:
                if fixture is not None:
                    new_status = fixture.get(tr["nctId"])
                else:
                    q = urllib.parse.urlencode({"fields": "OverallStatus", "format": "json"})
                    req = urllib.request.Request(
                        f"https://clinicaltrials.gov/api/v2/studies/{tr['nctId']}?{q}",
                        headers={"User-Agent": "TinnitusEvidence-weekly/1.0"})
                    with urllib.request.urlopen(req, timeout=45) as r:
                        new_status = json.loads(r.read())["protocolSection"]["statusModule"]["overallStatus"]
                    new_status = {  # registry enum -> our display wording
                        "RECRUITING": "Recruiting", "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
                        "NOT_YET_RECRUITING": "Not yet recruiting", "COMPLETED": "Completed",
                        "ENROLLING_BY_INVITATION": "Enrolling by invitation", "TERMINATED": "Terminated",
                        "WITHDRAWN": "Withdrawn", "SUSPENDED": "Suspended", "UNKNOWN": "Unknown status",
                    }.get(new_status, new_status)
                if not new_status:
                    continue
                cur_key = re.sub(r"\W+", "", (tr["status"] or "").lower())
                if re.sub(r"\W+", "", new_status.lower()) not in cur_key:
                    old = tr["status"]
                    tr["status"] = f"{new_status} (verified at ClinicalTrials.gov {date.today().isoformat()})"
                    changed.append((tr, old, new_status))
                    self.log(step="trial-status", identifier=tr["nctId"], source="ClinicalTrials.gov API v2",
                             previous=old, new=tr["status"], reason="registry-verified status change",
                             published=True, held=False)
            except Exception as e:
                self.status["errors"].append(f"trial refresh {tr['nctId']}: {e}")
        if changed:
            self.status["trialStatusUpdates"] = len(changed)
            self.stage("data/trials.json", trials)
        return [{
            "kind": "trial", "treatment": tr.get("treatment", ""),
            "title": f"Trial status change: {tr['nctId']} is now '{new}'",
            "importance": "Does Not Change Current Evidence",
            "whyMatters": f"The registry entry for this trial moved from '{old}' to '{new}'. Status changes are verified directly against ClinicalTrials.gov.",
            "summary": f"{tr['title']} — sponsor {tr['sponsor']}. Status verified at the registry on {date.today().isoformat()}.",
            "url": f"https://clinicaltrials.gov/study/{tr['nctId']}",
            "detail": {"identifier": tr["nctId"], "source": "ClinicalTrials.gov (authoritative registry)",
                       "changesAssessment": "No — trial status only."},
        } for tr, old, new in changed]

    # ---------- verification gates (deterministic) ----------
    def published_register(self):
        reg = self.load("engine/published_ids.json", None)
        if reg is None:  # build once from the existing archive
            reg = []
            for rep in self.load("data/weekly/index.json", {"reports": []})["reports"]:
                for it in self.load(f"data/weekly/{rep['file']}", {"items": []})["items"]:
                    for key in (it.get("url"), it.get("title")):
                        if key:
                            reg.append(re.sub(r"\W+", "", key.lower())[:90])
        return set(reg)

    def route(self, item, register, study_ids):
        """Returns (route, reason). Routes: publish · publish-under-eval · hold · dup · irrelevant · awaiting-eval."""
        keys = [re.sub(r"\W+", "", (item.get(k) or "").lower())[:90] for k in ("url", "title")]
        if any(k and k in register for k in keys):
            return "dup", "already published in the weekly feed"
        ev = item.get("evaluation")
        if not ev:
            return "awaiting-eval", "no AI evaluation available yet (evaluation pending or credentials missing)"
        if ev.get("parseError"):
            return "hold", "evaluation could not be parsed — uncertainty hold"
        if ev.get("duplicateOf"):
            return "dup", f"re-reports existing study record '{ev['duplicateOf']}'"
        if ev.get("notRelevant") or ev.get("affectedTreatment") == "none" and ev.get("importance") is None:
            return "irrelevant", "not relevant to tinnitus evidence"
        url = item.get("url", "")
        host = urllib.parse.urlparse(url).netloc.lower()
        trusted = any(host == d or host.endswith("." + d) for d in TRUSTED_DOMAINS)
        has_id = bool(re.search(r"pubmed-\d+|NCT\d{8}", item.get("id", "") + " " + url))
        major = (ev.get("changeClass") == "major" or ev.get("proposedScoreChange")
                 or ev.get("proposedRankChange") or ev.get("safetySignal"))
        verified_fact = ev.get("factuallyVerified") and ev.get("confidence") in ("moderate", "high")
        company = ev.get("regulatorySource") == "company announcement"
        if not (trusted or has_id):
            if company and verified_fact and not major:
                # the reported fact IS the announcement; publishes labeled "Company-reported development"
                return "publish", "company announcement — publishes with company-reported label; never treated as evidence"
            return "hold", f"source '{host or 'unknown'}' is not on the trusted list and no PMID/NCT identifier — uncertainty hold"
        if major:
            return ("publish-under-eval" if verified_fact else "hold"), \
                   "possible major evidence change — held; public assessment unchanged"
        if not verified_fact:
            return "hold", f"factual report not sufficiently verified (confidence: {ev.get('confidence')}) — uncertainty hold"
        return "publish", "routine research update, verified"

    def weekly_item(self, item, ev, under_eval=False):
        nr = "Not reported"
        d = {
            "studyType": ev.get("studyType", nr), "population": ev.get("population", nr),
            "sampleSize": ev.get("sampleSize", nr), "control": ev.get("controlQuality", nr),
            "primaryEndpoint": ev.get("primaryEndpoint", nr), "secondaryEndpoints": ev.get("secondaryEndpoints", nr),
            "comparisonType": ev.get("comparisonType", nr),
            "loudnessOutcome": ev.get("loudnessEffect", nr), "distressOutcome": ev.get("distressEffect", nr),
            "otherOutcomes": ev.get("otherOutcomes", nr), "safety": ev.get("safetyObservations", nr),
            "limitations": ev.get("mainLimitations", []), "funding": ev.get("conflictOfInterest", nr),
            "identifier": item.get("id", ""), "source": item.get("source", ""),
            "changesAssessment": "Under evaluation — a possible change to our assessment is held for deeper review; the current rating stands." if under_eval else "No — this does not change our current evidence assessment.",
        }
        kind_map = {"press release": "news", "regulatory record": "regulatory", "registry update": "trial"}
        w = {
            "kind": kind_map.get(ev.get("studyType", ""), item.get("kind", "study")),
            "treatment": ev.get("affectedTreatment", "") if ev.get("affectedTreatment") not in ("none", "new-treatment-candidate") else "",
            "title": ev.get("weeklyTitle") or item.get("title", ""),
            "importance": ev.get("importance", "Does Not Change Current Evidence"),
            "whyMatters": ev.get("whyMatters", ""),
            "summary": (ev.get("whatIsNew", "") + (" " + ev["numericalResult"] if ev.get("numericalResult") not in (None, "none reported", nr) else "")).strip(),
            "url": item.get("url", ""), "detail": d,
        }
        if under_eval:
            w["underEvaluation"] = True
        if ev.get("safetySignal"):
            w["safetySignal"] = True
        if ev.get("regulatorySource") == "company announcement":
            w["title"] = "Company-reported development: " + w["title"]
        return w

    # ---------- main ----------
    def run(self, fixtures=None, trial_fixture=None):
        queue = self.scan(fixtures=fixtures)
        # The review queue is engine working state (not public site data): commit it to disk NOW
        # so newly scanned items can never be lost, and so the evaluator (which reads the disk
        # file) sees them. Public data stays staged-only until the end.
        self.commit()

        trial_items = self.refresh_trials(fixture=trial_fixture if self.simulate else None)

        if not self.skip_eval and fixtures is None:
            # limit 60 drains any backlog (e.g. weeks that ran before the API key existed)
            n, skip = evaluate_queue.main(limit=60)
            if skip:
                self.status["errors"].append(f"AI evaluation skipped: {skip}")
            queue = self.load("data/review-queue/queue.json", queue)  # evaluate_queue writes directly

        register = self.published_register()
        study_ids = {s["id"] for s in self.load("data/studies.json", [])}
        held = self.load("data/review-queue/held.json", {"items": []})
        publish, remaining = list(trial_items), []
        for item in queue["items"]:
            r, reason = self.route(item, register, study_ids)
            ev = item.get("evaluation", {})
            self.log(step="route", identifier=item.get("id"), source=item.get("source"),
                     title=item.get("title", "")[:120], route=r, reason=reason,
                     classification=ev.get("importance"), changeClass=ev.get("changeClass"),
                     published=r.startswith("publish"), held=r in ("hold", "publish-under-eval", "awaiting-eval"))
            if r == "dup":
                self.status["rejectedDuplicates"] += 1
            elif r == "irrelevant":
                self.status["rejectedIrrelevant"] += 1
            elif r == "awaiting-eval":
                self.status["heldAwaitingEvaluation"] += 1
                remaining.append(item)
            elif r in ("hold", "publish-under-eval"):
                self.status["held"] += 1
                held["items"].insert(0, {
                    "heldAt": datetime.now().isoformat(timespec="seconds"), "reason": reason,
                    "item": item, "proposedChange": {
                        "scoreChange": ev.get("proposedScoreChange"), "rankChange": ev.get("proposedRankChange"),
                        "safetySignal": ev.get("safetySignal", False), "direction": ev.get("evidenceDirection"),
                        "adminSummary": ev.get("summaryForAdmin", "")},
                    "resolution": "unresolved — public assessment unchanged"})
                if r == "publish-under-eval":
                    publish.append(self.weekly_item(item, ev, under_eval=True))
                    self.status["publishedUnderEvaluation"] += 1
            else:
                publish.append(self.weekly_item(item, ev))
                self.status["published"] += 1
        queue["items"] = remaining
        self.stage("data/review-queue/queue.json", queue)
        self.stage("data/review-queue/held.json", held)

        # ---- publish the weekly report (quiet weeks stay honest) ----
        today = date.today().isoformat()
        index = self.load("data/weekly/index.json", {"reports": []})
        rep_rel = f"data/weekly/{today}.json"
        existing_rep = self.load(rep_rel, None)
        if not publish and not existing_rep:  # honest quiet week — never bump dates to fake freshness
            publish = [{"kind": "news", "treatment": "", "importance": "Does Not Change Current Evidence",
                        "title": "No evidence-changing tinnitus research identified in this week's scan",
                        "whyMatters": "Quiet weeks happen. The sources below were checked; nothing met the bar for a meaningful update, and we would rather say so than manufacture a story.",
                        "summary": "Sources checked: " + ", ".join(s["name"] for s in self.status["sources"]) + ".",
                        "url": "", "detail": {"changesAssessment": "No."}}]
        if existing_rep:  # idempotent same-day rerun: merge items, keep the report's own title/headline
            titles = {i["title"] for i in publish}
            merged = publish + [i for i in existing_rep["items"] if i["title"] not in titles]
            rep = dict(existing_rep)
            rep["items"] = merged
            rep["automated"] = rep.get("automated", False) or bool(publish)
            title = rep.get("title", f"Weekly scan — {len(merged)} update(s)")
        else:
            title = f"Automated weekly scan — {len(publish)} update(s)"
            rep = {"date": today, "title": title, "automated": True, "items": publish}
        self.stage(rep_rel, rep)
        if not any(r["file"] == f"{today}.json" for r in index["reports"]):
            index["reports"].insert(0, {"date": today, "file": f"{today}.json", "title": title})
        self.stage("data/weekly/index.json", index)
        reg2 = self.published_register() | {re.sub(r"\W+", "", (i.get(k) or "").lower())[:90]
                                            for i in publish for k in ("url", "title") if i.get(k)}
        self.stage("engine/published_ids.json", sorted(reg2))

        # routine 'latest' note on affected treatments (news feed only — never ratings)
        treatments = self.load("data/treatments.json", [])
        tmap = {t["id"]: t for t in treatments}
        touched = False
        for w in publish:
            t = tmap.get(w.get("treatment"))
            if t and w.get("url"):
                t.setdefault("latest", []).insert(0, {"date": today, "text": w["title"], "url": w["url"]})
                touched = True
        if touched:
            self.stage("data/treatments.json", treatments)

        return self.status  # lastSuccess is set by main() only AFTER commit() succeeds


def write_status(root, status):
    p = Path(root) / "data" / "engine-status.json"
    prev = {}
    try:
        prev = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    if "lastSuccess" not in status and "lastSuccess" in prev:
        status["lastSuccess"] = prev["lastSuccess"]  # a failed run never claims freshness
    p.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    simulate = "--simulate" in sys.argv
    root = ENGINE.parent
    if simulate:
        sandbox = Path(tempfile.mkdtemp(prefix="te-sim-"))
        shutil.copytree(root / "data", sandbox / "data")
        (sandbox / "engine").mkdir()
        for f in ("known_ids.json", "published_ids.json"):
            if (root / "engine" / f).exists():
                shutil.copy(root / "engine" / f, sandbox / "engine" / f)
        root = sandbox
        print(f"SIMULATION — sandbox: {sandbox} (live data untouched)")
    c = Cycle(root, simulate=simulate, skip_eval="--skip-eval" in sys.argv)
    try:
        fixtures = trial_fixture = None
        if simulate:
            import sim_fixtures
            fixtures, trial_fixture = sim_fixtures.SCANNERS, sim_fixtures.TRIAL_FIXTURE
        status = c.run(fixtures=fixtures, trial_fixture=trial_fixture)
        c.commit()
        status["lastSuccess"] = status["lastAttempt"]  # only a fully committed cycle counts as success
        write_status(root, status)
        print(json.dumps({k: v for k, v in status.items() if k != "sources"}, indent=1))
        print("sources:", [(s["name"], s["count"], s["error"]) for s in status["sources"]])
        print("CYCLE OK")
    except Exception as e:
        c.status["errors"].append(f"FATAL: {e}")
        write_status(root, c.status)  # record failure; staged writes are discarded — no partial publish
        print(f"CYCLE FAILED (no public data was modified): {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

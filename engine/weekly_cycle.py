#!/usr/bin/env python3
"""Tinnitus Evidence — automated research cycle (runs on the 1st and 15th of each month).

scan -> AI evaluation -> deterministic verification gates -> routing:
  CLASS A (routine, verified)  -> publishes automatically to Latest Tinnitus Research
  CLASS B (major / uncertain)  -> data/review-queue/held.json ("Major Evidence Changes — Held")
                                  the public assessment stays unchanged until resolved;
                                  if the underlying FACT is verified, a research-update item may still
                                  publish flagged "Impact on rating: Under evaluation".
Also: refreshes tracked trial statuses directly from ClinicalTrials.gov (registry-verified,
Class A), appends a full audit trail (engine/audit-log.jsonl), and maintains
data/engine-status.json for the admin status board.

Guarantees:
  * All public-data writes are staged in memory and committed only after the whole cycle
    succeeds — a failed scan can never corrupt or partially update the site.
  * Evidence scores, tiers, rankings, loudness/distress ratings, safety assessments and
    treatment regulatory statuses are NEVER changed by this script. Ever.
  * A quiet scan publishes an honest "no evidence-changing research identified" note —
    dates are never bumped to fake freshness.

Usage:
  python engine/weekly_cycle.py                 # real scheduled run
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
import grounding, notices, staged_review, topic_holds, triage, listings  # noqa: E402  (deterministic helpers: no network, no AI)

SCHEDULE_TEXT = "The 1st and 15th of every month, scheduled for 06:00 America/Los_Angeles (timezone-aware — stays 6 AM Pacific through PST/PDT); GitHub often starts scheduled runs hours late, so a run may begin any time that day, via GitHub Actions (.github/workflows/weekly.yml); local Task Scheduler task disabled"
TRUSTED_DOMAINS = (
    "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "clinicaltrials.gov", "fda.gov",
    "accessdata.fda.gov", "nih.gov", "nidcd.nih.gov", "cochranelibrary.com", "cochrane.org",
    "ema.europa.eu", "diga.bfarm.de", "nature.com", "jamanetwork.com", "sciencedirect.com",
    "springer.com", "link.springer.com", "tandfonline.com", "frontiersin.org", "plos.org",
    "journals.plos.org", "bmj.com", "doi.org", "science.org", "ata.org", "entnet.org", "jmir.org",
)
# Sources whose date-window queries are recovered after a skipped or failed run: the look-back grows to the time since the source last SUCCEEDED (state in engine/scan-state.json, committed with the queue).
# RSS/news feeds are not in this list: they only list recent entries, so what has scrolled off a feed during a long outage cannot be recovered, and that is said plainly in the documentation.
STATE_SOURCES = {"PubMed (title/abstract + MeSH)": "pubmed", "ClinicalTrials.gov (condition + full-text)": "ctgov"}
LOOKBACK_OVERLAP_DAYS, LOOKBACK_MAX_DAYS = 3, 180
COMPANY_HINTS = ("businesswire", "prnewswire", "globenewswire", "press-release", "press_release", "investor")


def next_run_6am():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except Exception:  # tz database unavailable (some Windows setups) — PST approximation
        from datetime import timezone
        tz = timezone(timedelta(hours=-8))
    now = datetime.now(tz)
    return next_scheduled(now).strftime("%Y-%m-%d") + " 06:00 America/Los_Angeles"


def next_scheduled(now):
    """The next run on the 1st or 15th at 06:00 (the zone of `now`): today's run if it has not happened yet, otherwise the next one."""
    from datetime import datetime as _dt
    for add_month in range(0, 3):
        y, m = now.year + (now.month - 1 + add_month) // 12, (now.month - 1 + add_month) % 12 + 1
        for day in (1, 15):
            cand = _dt(y, m, day, 6, 0, tzinfo=now.tzinfo)
            if cand > now:
                return cand
    raise RuntimeError("no scheduled date found")


class Cycle:
    def __init__(self, root, simulate=False, skip_eval=False, days=7, staged=None):
        self.root, self.simulate, self.skip_eval, self.days = Path(root), simulate, skip_eval, days
        self._staged_override = staged   # None = decide from engine/eval_settings.json ("mode"); tests and simulations may force True/False
        self.staged = {}          # path -> obj (committed only on success)
        self.auto, self.listing_counts = {"listings": False, "updateHistory": False}, None   # Phase 1 (listings.py): set by phase1() from engine/automation_settings.json
        self.audit = []           # audit-log entries for this run
        self.status = {
            "schedule": SCHEDULE_TEXT, "nextScheduled": next_run_6am(),
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
    def lookback_days(self, key, state, name, today=None):
        """Days to look back for one source: at least the standard window, longer after a gap. Returns (days, coverage_gap_message or None)."""
        today = today or date.today()
        base = weekly_scan.DAYS
        try:
            gap = (today - date.fromisoformat(str(state.get(key)))).days
        except (TypeError, ValueError):
            return base, None                      # no usable record of a previous success: the standard window
        if gap < 0:
            return base, None
        want = gap + LOOKBACK_OVERLAP_DAYS
        if want > LOOKBACK_MAX_DAYS:
            return LOOKBACK_MAX_DAYS, (f"source '{name}' last succeeded {gap} days ago; the look-back is limited to {LOOKBACK_MAX_DAYS} days, so records from the earliest {want - LOOKBACK_MAX_DAYS} day(s) of the gap "
                                       "may have been missed (coverage gap: check the source by hand)")
        return max(base, want), None

    def scan(self, fixtures=None):
        queue = self.load("data/review-queue/queue.json", {"items": []})
        known = set(self.load("engine/known_ids.json", []))
        existing = {it["id"] for it in queue["items"]}
        new = []
        scanners = fixtures if fixtures is not None else [
            ("PubMed (title/abstract + MeSH)", weekly_scan.scan_pubmed),
            ("ClinicalTrials.gov (condition + full-text)", weekly_scan.scan_ctgov),
            ("Watched feeds (FDA press, NIH, journals)", weekly_scan.scan_feeds),
            ("FDA databases (510k/PMA/MAUDE — openFDA)", weekly_scan.scan_fda),
            ("News-wire intelligence (labeled, never evidence)", weekly_scan.scan_news_intel),
            ("Guideline page watcher (AAO-HNSF, NICE)", weekly_scan.scan_pages)]
        use_state = fixtures is None
        state = self.load("engine/scan-state.json", {}) if use_state else {}
        base_days = weekly_scan.DAYS
        for name, fn in scanners:
            src = {"name": name, "checked": True, "count": 0, "error": None}
            key = STATE_SOURCES.get(name) if use_state else None
            try:
                if key:
                    days, gap_msg = self.lookback_days(key, state, name)
                    weekly_scan.DAYS = days
                    src["lookbackDays"] = days
                    if gap_msg:
                        self.status["errors"].append(gap_msg)
                items = fn()
                src["count"] = len(items)
                self.status["examined"] += len(items)
                new += [it for it in items if it["id"] not in known and it["id"] not in existing]
                if key:
                    state[key] = date.today().isoformat()          # only a source that answered completely advances its own clock
            except Exception as e:
                src["error"] = str(e)[:200]
                self.status["errors"].append(f"source '{name}' failed: {e}")
            finally:
                weekly_scan.DAYS = base_days
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
        if use_state:      # staged LAST on purpose: commit() writes in this order, so an interruption can leave new records without an advanced clock (they are simply deduplicated next time), never an advanced clock without its records
            self.stage("engine/scan-state.json", state)
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

    def retraction_check(self, held):
        """Monthly retraction/erratum/expression-of-concern back-check over every CITED
        PMID/DOI in studies.json (fixes the audit's grade-D retraction resilience: nothing
        previously linked notices back to cited records). Findings are CLASS B — held for
        review; the public assessment stays unchanged. For retraction/EoC severities the
        study record gets a visible factual integrity flag (like registry-verified trial
        status, this states a documented fact — it changes no rating)."""
        import check_retractions as cr
        if self.simulate or not cr.due(self.root / "engine" / "retraction-state.json"):
            return
        try:
            data = self.load("data/studies.json", [])
            slist = data["studies"] if isinstance(data, dict) else data
            findings = cr.run(slist, self.root / "engine" / "retraction-state.json")
        except Exception as e:
            self.status["errors"].append(f"retraction check failed: {e}")
            return
        self.status["retractionFindings"] = len(findings)
        if not findings:
            self.log(step="retraction-check", result="no notices found for any cited PMID/DOI",
                     published=False, held=False)
            return
        flagged = False
        smap = {s["id"]: s for s in slist}
        for f in findings:
            if f["severity"] == "erratum":
                # a published correction (erratum) is routine and says nothing about the evidence: it is recorded in the audit log and counted, never queued for a reviewer and never shown as a notice
                self.status["retractionErrata"] = self.status.get("retractionErrata", 0) + 1
                self.log(step="retraction-check", identifier=f["identifier"], severity="erratum", studyIds=f["studyIds"], notices=f["notices"], published=False, held=False,
                         note="correction notice (erratum): recorded; no review item and no public change")
                continue
            already = any(h.get("item", {}).get("id") == "retraction-" + f["identifier"]
                          for h in held["items"])
            if not already:
                held["items"].insert(0, {
                    "heldAt": datetime.now().isoformat(timespec="seconds"),
                    "reason": f"{f['severity']} notice detected for cited {f['identifier']} — "
                              f"affects study record(s) {', '.join(f['studyIds'])}; evidence impact needs review",
                    "item": {"id": "retraction-" + f["identifier"], "kind": "integrity",
                             "title": f"Research-integrity notice: {f['severity']} for {f['identifier']}",
                             "source": f["source"], "url": "", "notices": f["notices"]},
                    "proposedChange": {"scoreChange": None, "rankChange": None, "safetySignal": False,
                                       "direction": "weakens",
                                       "adminSummary": "A " + f["severity"] + " notice exists for a cited paper. "
                                       "Review whether any treatment rating rests on it."},
                    "resolution": "handled automatically: a factual notice is shown on the study and the treatments citing it are marked provisional; no rating was changed"})
                self.status["held"] += 1
            self.log(step="retraction-check", identifier=f["identifier"], severity=f["severity"],
                     studyIds=f["studyIds"], notices=f["notices"], published=False, held=True)
            if f["severity"] in ("retracted", "partially-retracted", "expression-of-concern"):
                for sid in f["studyIds"]:
                    s = smap.get(sid)
                    if s and not s.get("integrityNotice"):
                        s["integrityNotice"] = {
                            "severity": f["severity"], "detected": date.today().isoformat(),
                            "text": "A " + f["severity"].replace("-", " ") + " notice has been "
                            "detected for this publication (source: " + f["source"] + "). Treat this study's results with caution. "
                            "No rating has been changed because of this notice; treatments that cite this study are marked as having a provisional rating "
                            "until their next scheduled reassessment.",
                            "notices": f["notices"]}
                        flagged = True
        if flagged:
            self.stage("data/studies.json", data)

    # ---------- Phase 1: automatic listings and update history (no AI; both OFF unless engine/automation_settings.json says exactly true) ----------
    def phase1(self, queue):
        self.auto = listings.load_settings(self.load("engine/automation_settings.json", None))
        self.listing_counts = None
        if not self.auto["listings"]:
            return
        paused = set(self.load("engine/paused_ids.json", {"ids": []}).get("ids", []))
        holds = topic_holds.load_holds(self.root / "engine" / "topic_holds.json")
        try:
            new, counts = listings.process(
                queue["items"], self.load(listings.LISTINGS_REL, {"items": []}), today=date.today().isoformat(),
                fetch_context=evaluate_queue.fetch_context, record_meta=lambda i: evaluate_queue.RECORD_META.pop(i, None),
                excluded=lambda it: it["id"] in paused or bool(topic_holds.match_item(it, holds)), enrich=triage.enrich)
        except Exception as e:   # a listing problem must never stop the cycle: the queue is untouched on failure
            self.status["errors"].append(f"listings step failed: {type(e).__name__}: {str(e)[:120]}")
            return
        self.listing_counts = counts
        self.status["listings"] = {**counts, "total": new["count"]}
        self.stage(listings.LISTINGS_REL, new)
        self.stage("data/review-queue/queue.json", queue)
        self.commit()   # the evaluator reads the queue from disk
        if counts.get("failedVerification"):
            self.status["errors"].append(f"{counts['failedVerification']} item(s) failed source verification and were not listed (kept in the queue)")

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

    def verified(self, ev):
        """Publication gate. The model's own factuallyVerified / confidence are SELF-ASSESSMENTS: they are necessary but NEVER sufficient.
        Code-verifiable source checks (engine/grounding.py) must also pass. Returns (ok, why-not)."""
        ok, why = grounding.source_checks_pass(ev)
        if not ok:
            return False, why
        if not ev.get("factuallyVerified"):
            return False, "the evaluation does not assert that its facts are stated in the record"
        if ev.get("confidence") not in ("moderate", "high"):
            return False, f"confidence after the automated checks is '{ev.get('confidence')}'"
        return True, ""

    def route(self, item, register, study_ids):
        """Returns (route, reason). Routes: publish · publish-under-eval · hold · dup · irrelevant · archive · awaiting-eval · paused ·
        notice-cited · notice-uncited · notice-unresolved."""
        keys = [re.sub(r"\W+", "", (item.get(k) or "").lower())[:90] for k in ("url", "title")]
        if any(k and k in register for k in keys):
            return "dup", "already published in the research-updates feed"
        if item.get("id") in getattr(self, "paused_ids", ()):
            return "paused", "paused by the owner (engine/paused_ids.json): not evaluated, not published, not lost"
        hold_id = item.get("topicHold") or topic_holds.match_item(item, getattr(self, "topic_hold_list", None))
        if hold_id:
            return "paused", f"topic hold '{hold_id}' (engine/topic_holds.json): not evaluated, not published, not lost"
        nt = item.get("notice")
        if nt:   # correction / retraction / expression of concern: never research evidence, never discarded silently
            return "notice-" + nt.get("resolution", "unresolved"), f"{nt.get('kind')} notice: " + {
                "cited": "concerns a study cited on this site - held privately for review", "uncited": "concerns an article we do not cite - archived as context",
                "unresolved": "could not tell which article it concerns - held privately for a manual check"}.get(nt.get("resolution"), "needs a manual check")
        ct = item.get("catalogued")
        if ct:   # triage rule C1: preserved in the archive with its reason, listed in the digest, never lost, promotable by the owner
            return "archive", f"catalogued without AI evaluation (rule {ct.get('rule')}): {ct.get('reason')}"
        lh = item.get("languageHold")
        if lh:   # R4: the abstract is not clearly English; never sent to the AI, never published, held for a person to read
            return "hold", "R4 - " + (lh.get("reason") or "the abstract is not in English: held for a person to read")
        if notices.looks_like_notice(item):   # title says notice but no notice analysis exists yet (evaluation off, or an older evaluation): never publish it as research
            if not item.get("evaluation"):
                return "awaiting-eval", "notice not yet screened"
            return "notice-unresolved", "notice evaluated as research by an older version - held privately"
        if item.get("id") in getattr(self, "superseded", ()):
            return "dup", "superseded by a newer update of the same registry record (the evaluator reads the current record)"
        ev = item.get("evaluation")
        if not ev:
            return "awaiting-eval", "no AI evaluation available yet (evaluation pending or credentials missing)"
        if ev.get("parseError"):
            why = {"truncated": "the AI answer was cut off at the output limit", "refused": "the AI declined to answer", "empty": "the AI returned no text",
                   "unexpected-stop": "the AI stopped unexpectedly",
                   "attempts-exhausted": "the AI could not be reached for this item after repeated attempts"}.get(ev.get("failureKind"), "the AI answer could not be parsed")
            return "hold", f"evaluation unusable ({why}) — uncertainty hold"
        if ev.get("duplicateOf"):
            return "dup", f"re-reports existing study record '{ev['duplicateOf']}'"
        if ev.get("notRelevant") or ev.get("affectedTreatment") == "none" and ev.get("importance") is None:
            return "irrelevant", "not relevant to tinnitus evidence"
        rc = ev.get("relevanceCategory")
        try:
            rc = int(rc)
        except (TypeError, ValueError):
            rc = None
        if rc in (5, 6):  # incidental mention / false positive — never reaches the public feed
            return "irrelevant", f"relevance category {rc} (incidental/false-positive) — excluded from the public feed"
        if rc in (3, 4):  # secondary-outcome or adjacent-condition context — archived, never treatment evidence
            return "archive", f"relevance category {rc} (secondary-outcome/adjacent context) — archived as context; never treated as tinnitus treatment evidence"
        if ev.get("studyType") == "other" and ev.get("studyQuality") == "not-a-study":
            return "archive", "no scientific content (not a study) — archived as context; never published as research"
        l3 = [e for e in (ev.get("escalation") or []) if e.get("tier") == "level3"]
        if l3:   # deterministic Level 3 triggers (safety terms in the record; evidence bearing on a tracked treatment): never published automatically
            return "hold", "Level 3 trigger (needs a person): " + "; ".join(f"{e['kind']} ({e['detail']})" for e in l3)
        url = item.get("url", "")
        host = urllib.parse.urlparse(url).netloc.lower()
        trusted = any(host == d or host.endswith("." + d) for d in TRUSTED_DOMAINS)
        verified_fact, why_not = self.verified(ev)
        if item.get("intelligenceOnly"):
            # news-wire watch: intelligence, never evidence. Publishable ONLY as a labeled
            # company-reported development; anything major or unverified is held.
            major2 = (ev.get("changeClass") == "major" or ev.get("proposedScoreChange")
                      or ev.get("proposedRankChange") or ev.get("safetySignal"))
            if verified_fact and not major2:
                ev["regulatorySource"] = "company announcement"  # forces the label in weekly_item
                return "publish", "news-wire intelligence — publishes labeled 'Company-reported development'; never treated as evidence"
            return "hold", f"news-wire intelligence not verified ({why_not or 'possibly major'}) — held"
        has_id = bool(re.search(r"pubmed-\d+|NCT\d{8}", item.get("id", "") + " " + url))
        major = (ev.get("changeClass") == "major" or ev.get("proposedScoreChange")
                 or ev.get("proposedRankChange") or ev.get("safetySignal"))
        company = ev.get("regulatorySource") == "company announcement"
        if not (trusted or has_id):
            if company and verified_fact and not major:
                # the reported fact IS the announcement; publishes labeled "Company-reported development"
                return "publish", "company announcement — publishes with company-reported label; never treated as evidence"
            return "hold", f"source '{host or 'unknown'}' is not on the trusted list and no PMID/NCT identifier — uncertainty hold"
        if (item.get("evalInput") or {}).get("hasResults"):
            return "hold", "the registry record has posted results: held for human review (results are never summarised and published automatically)"
        if major:
            return ("publish-under-eval" if verified_fact else "hold"), \
                   "possible major evidence change — held; public assessment unchanged"
        if not verified_fact:
            return "hold", f"not sufficiently verified: {why_not} — uncertainty hold"
        return "publish", "routine research update (passed the automated source checks)"

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
        if item.get("releasedAfterSourceCheck"):
            w["reviewNote"] = "Reviewed by the site editor against the source record. This is an editorial check, not a clinical review."
        if ev.get("safetySignal"):
            w["safetySignal"] = True
        if ev.get("regulatorySource") == "company announcement":
            w["title"] = "Company-reported development: " + w["title"]
        return w

    # ---------- staged review + shared route effects ----------
    def load_staged(self):
        plain, enc = self.root / staged_review.STAGED_REL, self.root / (staged_review.STAGED_REL + ".enc")
        if enc.exists() and not plain.exists():
            raise RuntimeError("data/review-queue/staged.json.enc exists but was not decrypted (STATE_KEY missing, or the restore step failed): refusing to run so staged items cannot be lost")
        d = self.load(staged_review.STAGED_REL, {"items": []})
        d.setdefault("items", [])
        return d

    def stage_item(self, staged, item, r, reason):
        import copy
        ev = item["evaluation"]
        preview = self.weekly_item(item, ev, under_eval=(r == "publish-under-eval")) if r in ("publish", "publish-under-eval") else None
        staged["items"] = [x for x in staged["items"] if x["id"] != item["id"]]
        staged["items"].insert(0, staged_review.make_entry(copy.deepcopy(item), r, reason, preview))
        self.status.setdefault("staged", {}).setdefault("new", 0)
        self.status["staged"]["new"] += 1
        self.log(step="stage", identifier=item.get("id"), source=item.get("source"), title=item.get("title", "")[:120], route="staged",
                 reason="evaluated and staged for owner review; nothing published", published=False, held=False)

    def apply_decisions(self, staged, queue, register, held, publish, remember):
        """Apply the owner's recorded decisions (data/review-queue/decisions.json) to the staged items. A decision applies only if its hash matches the staged evaluation."""
        dec = self.load(staged_review.DECISIONS_REL, {"decisions": []})
        todo = dec.get("decisions") or []
        if not todo:
            return
        out = {"applied": 0, "rejected": 0, "requeued": 0, "blocked": 0, "stale": 0, "invalid": 0, "alreadyPublished": 0, "sourceVerifiedReleases": 0}
        keep = []
        import source_release
        rel_settings = self.load("engine/eval_settings.json", {})
        rel_tracked = {t["id"] for t in self.load("data/treatments.json", [])}
        released = [0]

        def release_check(dd, ee):
            return source_release.release(dd, ee, rel_tracked, rel_settings, released[0])
        for d in todo:
            e = next((x for x in staged["items"] if x["id"] == d.get("id")), None)
            blocked = None
            if e and (e["item"]["id"] in self.paused_ids or topic_holds.match_item(e["item"], self.topic_hold_list)):
                blocked = "the item is paused or topic-held: release the pause first"
            if d.get("decision") == "release" and e and released[0] >= source_release.max_per_run(rel_settings):
                out["blocked"] += 1          # over the per-run limit: the decision is kept for the next run, not dropped
                keep.append(d)
                continue
            r = staged_review.resolve(d, e, blocked, release_check=release_check)
            if r["status"] == "blocked":
                out["blocked"] += 1
                keep.append(d)
                continue
            if r["status"] in ("stale", "invalid"):
                out[r["status"]] += 1
                self.log(step="owner-decision", identifier=d.get("id"), decision=d.get("decision"), result=r["status"], reason=r["message"][:160], published=False, held=False)
                continue
            action, item = r["action"], r["item"]
            staged["items"] = [x for x in staged["items"] if x["id"] != d["id"]]
            if action == "reject":
                out["rejected"] += 1
            elif action == "requeue":
                for k in ("evaluation", "evalInput", "why", "treatment", "scoreChange", "rankChange", "proposal"):
                    item.pop(k, None)
                item["summary"] = "Returned to the queue by the owner for a fresh evaluation."
                queue["items"].insert(0, item)
                out["requeued"] += 1
            else:
                keys = [re.sub(r"\W+", "", (item.get(k) or "").lower())[:90] for k in ("url", "title")]
                if action.startswith("publish") and any(k and k in register for k in keys):
                    out["alreadyPublished"] += 1
                    self.log(step="owner-decision", identifier=d["id"], decision=d["decision"], result="already published; not published again", published=False, held=False)
                    continue
                if d.get("decision") == "release":
                    released[0] += 1
                    out["sourceVerifiedReleases"] += 1
                self._effect(action, ("released after documented source verification (editorial check, not clinical review)" if d.get("decision") == "release"
                                      else "approved by the owner" + (" with corrections" if item.get("ownerCorrected") else "")), item, item["evaluation"], held, publish, [], remember)
                out["applied"] += 1
            self.log(step="owner-decision", identifier=d["id"], decision=d["decision"], result=action, corrected=item.get("ownerCorrected") if isinstance(item, dict) else None,
                     published=action.startswith("publish"), held=action in ("hold", "publish-under-eval"))
        self.status.setdefault("staged", {})["decisions"] = out
        self.stage(staged_review.DECISIONS_REL, {"decisions": keep})

    def _effect(self, r, reason, item, ev, held, publish, remaining, remember):
        """What a routing outcome DOES (shared by the normal path and by owner-approved staged items)."""
        if r == "dup":
            self.status["rejectedDuplicates"] += 1
        elif r == "irrelevant":
            self.status["rejectedIrrelevant"] += 1
        elif r == "archive" or r == "notice-uncited":
            # context material (secondary-outcome / adjacent-condition / a notice about an article we do not cite): preserved, never in
            # the public feed, never treatment evidence. Raw AI evaluation output is NOT stored here (the archive file is public in the repo).
            self.status["archived"] = self.status.get("archived", 0) + 1
            if str(reason).startswith("catalogued"):
                self.status.setdefault("triage", {})["catalogued"] = self.status.setdefault("triage", {}).get("catalogued", 0) + 1
            archive = self.staged.get("data/review-queue/archive.json") or self.load("data/review-queue/archive.json", {"items": []})
            entry = {"archivedAt": datetime.now().isoformat(timespec="seconds"), "reason": reason,
                     "relevanceCategory": ev.get("relevanceCategory"),
                     "item": {k: item.get(k) for k in ("id", "kind", "title", "source", "date", "url")}}
            if item.get("notice"):
                entry["notice"] = item["notice"]
                self.status.setdefault("notices", {"cited": 0, "uncited": 0, "unresolved": 0})["uncited"] += 1
            archive["items"].insert(0, entry)
            self.stage("data/review-queue/archive.json", archive)
        elif r == "paused":
            self.status["paused"] = self.status.get("paused", 0) + 1
            remaining.append(item)
        elif r == "awaiting-eval":
            self.status["heldAwaitingEvaluation"] += 1
            remaining.append(item)
        elif r in ("notice-cited", "notice-unresolved"):
            nt = item.get("notice") or {}
            cited = r == "notice-cited"
            self.status.setdefault("notices", {"cited": 0, "uncited": 0, "unresolved": 0})["cited" if cited else "unresolved"] += 1
            self.status["held"] += 1
            held["items"].insert(0, {
                "heldAt": datetime.now().isoformat(timespec="seconds"),
                "reason": (f"{nt.get('kind', 'notice')} notice found by the scan concerns a study cited on this site ({', '.join(nt.get('studyIds', []))}); evidence impact needs review"
                           if cited else f"{nt.get('kind', 'notice')} notice found by the scan: could not determine which article it concerns; check manually"),
                "item": {"id": item.get("id"), "kind": "integrity", "title": item.get("title"), "source": item.get("source"), "url": item.get("url"), "notice": nt},
                "proposedChange": {"scoreChange": None, "rankChange": None, "safetySignal": False, "direction": "weakens" if cited else None,
                                   "adminSummary": "A notice about a cited publication was found in the scan. Review whether any treatment rating rests on it. No record was changed." if cited
                                   else "A correction/retraction-type notice could not be matched to a cited study. Check which article it concerns."},
                "resolution": "unresolved — public assessment unchanged"})
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
                remember(item)
                self.status["publishedUnderEvaluation"] += 1
        else:
            publish.append(self.weekly_item(item, ev))
            remember(item)
            self.status["published"] += 1

    # ---------- main ----------
    def run(self, fixtures=None, trial_fixture=None):
        self.load_staged()   # fail BEFORE any scan or paid API call if staged.json.enc exists but was not decrypted (staged items must never be lost)
        queue = self.scan(fixtures=fixtures)
        # The review queue is engine working state (not public site data): commit it to disk NOW
        # so newly scanned items can never be lost, and so the evaluator (which reads the disk
        # file) sees them. Public data stays staged-only until the end.
        self.commit()

        trial_items = self.refresh_trials(fixture=trial_fixture if self.simulate else None)
        self.phase1(queue)

        evaluation = {"state": "not-run"}   # recorded in engine-status.json so a failed evaluation can never look like a successful one
        # MASTER SWITCH (fail-closed): the scheduled cycle sends items to the AI evaluator ONLY when engine/eval_settings.json says "enabled": true.
        # A missing, unreadable or malformed file means OFF. Scanning, trial-status refresh, retraction checks and queue preservation all continue.
        _settings = self.load("engine/eval_settings.json", None)
        eval_enabled = isinstance(_settings, dict) and _settings.get("enabled") is True
        # STAGED MODE (fail-closed): evaluated items are written to a private, encrypted review store and NOTHING from them is published until the owner
        # records a decision. Only an explicit "mode": "publish" in engine/eval_settings.json restores automatic publication. --simulate keeps the publish path.
        if self._staged_override is not None:
            staged_mode = self._staged_override
        elif fixtures is not None:
            staged_mode = False
        else:
            staged_mode = not (isinstance(_settings, dict) and _settings.get("mode") == "publish")
        if not self.skip_eval and fixtures is None and not eval_enabled:
            evaluation = {"state": "disabled", "reason": "automated evaluation is switched off in engine/eval_settings.json (it runs only when \"enabled\" is true)",
                          "disabledSince": (_settings or {}).get("disabledSince") if isinstance(_settings, dict) else None}
        if not self.skip_eval and fixtures is None and eval_enabled:
            # LAUNCH GATE (research-integrity requirement): no AI-evaluated research may publish
            # until the frozen production benchmark has PASSED (engine/run_benchmark.py, exit 0).
            # Until then items simply accumulate as awaiting-evaluation — nothing is lost.
            bench = self.load("engine/benchmark-report.json", None)
            stale_prompt = bool(bench) and bench.get("promptHash") != evaluate_queue.prompt_hash()
            if not (bench and bench.get("passed") == bench.get("cases") and bench.get("cases")) or stale_prompt:
                self.status["errors"].append(
                    ("AI evaluation skipped: the benchmark report was produced with a different evaluator prompt (or has no prompt fingerprint); " if stale_prompt
                     else "AI evaluation skipped: production benchmark gate not passed yet ")
                    + "(run engine/run_benchmark.py with ANTHROPIC_API_KEY configured; items held as awaiting-evaluation)")
                evaluation = {"state": "blocked-gate"}
            else:
                # limit 60 drains any backlog (e.g. weeks that ran before the API key existed)
                try:  # engine/eval_settings.json {"limitPerRun": N} lets the owner throttle a backlog into small batches (default 60 = previous behaviour)
                    per_run = max(1, min(100, int(self.load("engine/eval_settings.json", {}).get("limitPerRun", 60))))
                except (TypeError, ValueError):
                    per_run = 60
                n, skip = evaluate_queue.main(limit=per_run)
                if skip:
                    self.status["errors"].append(f"AI evaluation skipped: {skip}")
                queue = self.load("data/review-queue/queue.json", queue)  # evaluate_queue writes directly
                lr = dict(getattr(evaluate_queue, "LAST_RUN", {}) or {})
                if lr.get("fatal") or (lr.get("attempted", 0) > 0 and lr.get("succeeded", 0) == 0):
                    state = "failed"
                elif lr.get("failed", 0) > 0 or lr.get("recordUnavailable", 0) > 0 or lr.get("parseErrors", 0) > 0:
                    state = "degraded"
                elif lr.get("attempted", 0) == 0:
                    state = "idle"
                else:
                    state = "ok"
                evaluation = {"state": state, "attempted": lr.get("attempted", 0), "succeeded": lr.get("succeeded", 0), "failed": lr.get("failed", 0),
                              "parseErrors": lr.get("parseErrors", 0), "failureKinds": lr.get("failureKinds", {}), "nearMisses": lr.get("nearMisses", 0), "maxOutputTokens": lr.get("maxOutputTokens", 0), "errorClasses": lr.get("errorClasses", {}), "fatal": lr.get("fatal"), "reason": lr.get("reason"),
                              "screenedWithoutAI": lr.get("screened", 0), "recordUnavailable": lr.get("recordUnavailable", 0),
                              "usage": {"inputTokens": lr.get("inputTokens", 0), "outputTokens": lr.get("outputTokens", 0), "estimatedCostUSD": lr.get("costUSD", 0.0), "model": evaluate_queue.MODEL}}
                if lr.get("batch"):   # only present when the useBatch option is on: submitted / pending / collected, with counts
                    evaluation["batch"] = lr["batch"]
                if lr.get("batchCollected"):
                    evaluation["batchCollected"] = lr["batchCollected"]
                if lr.get("cacheReadTokens") or lr.get("cacheWriteTokens"):
                    evaluation["usage"].update({"cacheReadTokens": lr.get("cacheReadTokens", 0), "cacheWriteTokens": lr.get("cacheWriteTokens", 0)})
                if state in ("failed", "degraded") and not skip:
                    self.status["errors"].append(f"AI evaluation {state}: " + (lr.get("reason") or (f"{lr.get('parseErrors')} AI answer(s) unusable {lr.get('failureKinds') or ''}; those items are held for a person" if lr.get("parseErrors") else "no reason recorded")))
        evaluation["mode"] = "staged" if staged_mode else "publish"
        self.status["evaluation"] = evaluation
        if evaluation.get("usage") and evaluation.get("attempted"):   # cost ledger: one line per run that called the model (public: dates, token counts, estimated dollars)
            ledger = self.load("engine/usage-ledger.json", {"runs": []})
            ledger["runs"].append({"date": date.today().isoformat(), "model": evaluation["usage"].get("model"), "attempted": evaluation["attempted"], "inputTokens": evaluation["usage"]["inputTokens"],
                                   "outputTokens": evaluation["usage"]["outputTokens"], "estimatedCostUSD": evaluation["usage"]["estimatedCostUSD"],
                                   **({"cacheReadTokens": evaluation["usage"]["cacheReadTokens"], "cacheWriteTokens": evaluation["usage"]["cacheWriteTokens"]} if "cacheReadTokens" in evaluation["usage"] else {}),
                                   **({"batch": True} if evaluation.get("batchCollected") else {})})
            self.stage("engine/usage-ledger.json", ledger)
        ran = evaluation["usage"].get("estimatedCostUSD", 0.0) if (evaluation.get("usage") and evaluation.get("attempted")) else 0.0   # this run's cost is in the staged ledger but not on disk yet
        evaluation["budget"] = evaluate_queue.budget_status(extra=ran)

        register = self.published_register()
        study_ids = {s["id"] for s in self.load("data/studies.json", [])}
        held = self.load("data/review-queue/held.json", {"items": []})
        self.retraction_check(held)  # monthly; findings go to held (Class B) — ratings untouched
        publish, remaining = list(trial_items), []
        def remember(it):  # an item published (or held under evaluation) in THIS run must also block later duplicates in the same run
            register.update(re.sub(r"\W+", "", (it.get(k) or "").lower())[:90] for k in ("url", "title") if it.get(k))
        self.paused_ids = set(self.load("engine/paused_ids.json", {"ids": []}).get("ids", []))
        self.topic_hold_list = topic_holds.load_holds(self.root / "engine" / "topic_holds.json")
        by_id = {it["id"]: it for it in queue["items"]}
        self.superseded = {old for old, new in evaluate_queue.superseded_map(queue["items"]).items()
                           if by_id[new].get("evaluation") or by_id[new].get("notice") or by_id[new].get("topicHold")}   # preserved until its newer sibling is processed
        staged = self.load_staged()
        self.apply_decisions(staged, queue, register, held, publish, remember)
        for item in queue["items"]:
            r, reason = self.route(item, register, study_ids)
            ev = item.get("evaluation", {})
            if (item.get("triageAudit") or item.get("triageShadow")) and ev:      # a catalogue candidate that was evaluated anyway: would the AI have recommended it for the feed?
                t = self.status.setdefault("triage", {})
                t["auditEvaluated"] = t.get("auditEvaluated", 0) + 1
                fed = r in ("publish", "publish-under-eval")
                if fed:
                    t["auditWouldFeed"] = t.get("auditWouldFeed", 0) + 1
                evid = self.staged.get("engine/triage-evidence.json") or self.load("engine/triage-evidence.json", {"evaluated": 0, "wouldFeed": 0, "wouldHold": 0, "misses": []})
                evid["evaluated"] += 1
                if fed:
                    evid["wouldFeed"] += 1
                    evid["misses"].append({"id": item.get("id"), "title": item.get("title", "")[:140], "route": r, "date": date.today().isoformat()})
                elif r == "hold":
                    evid["wouldHold"] += 1
                self.stage("engine/triage-evidence.json", evid)
            if staged_mode and ev and r in staged_review.STAGEABLE and not (r == "dup" and reason.startswith("already published")):
                self.stage_item(staged, item, r, reason)   # evaluated, but NOT acted on: private review only
                continue
            self.log(step="route", identifier=item.get("id"), source=item.get("source"),
                     title=item.get("title", "")[:120], route=r, reason=reason,
                     classification=ev.get("importance"), changeClass=ev.get("changeClass"),
                     published=r.startswith("publish"), held=r in ("hold", "publish-under-eval", "awaiting-eval"))
            self._effect(r, reason, item, ev, held, publish, remaining, remember)
        queue["items"] = remaining
        # an older update of a registry record whose newer update is paused or held is preserved, but it cannot be evaluated until its sibling is: not a backlog
        waiting_on_sibling = set(evaluate_queue.superseded_map(remaining))
        self.status["evaluation"]["awaitingEvaluation"] = len(remaining) - self.status.get("paused", 0) - len(waiting_on_sibling)
        self.status["evaluation"]["paused"] = self.status.get("paused", 0)
        self.stage("data/review-queue/queue.json", queue)
        self.stage("data/review-queue/held.json", held)
        self.stage(staged_review.STAGED_REL, staged)   # always staged (even empty): the workflow encrypts it when it holds items and removes it otherwise
        st = self.status.setdefault("staged", {})
        st["pending"] = len(staged["items"])
        st.setdefault("new", 0)
        if staged["items"]:
            try:
                oldest = min(datetime.fromisoformat(e["stagedAt"]) for e in staged["items"])
                st["oldestDays"] = (datetime.now() - oldest).days
            except (KeyError, ValueError):
                pass

        # ---- publish the research-update report (quiet scans stay honest) ----
        today = date.today().isoformat()
        index = self.load("data/weekly/index.json", {"reports": []})
        rep_rel = f"data/weekly/{today}.json"
        existing_rep = self.load(rep_rel, None)
        awaiting = (self.status.get("evaluation") or {}).get("awaitingEvaluation", 0)   # excludes owner-paused items
        ev_state = (self.status.get("evaluation") or {}).get("state")
        eval_down = ev_state in ("disabled", "failed", "degraded", "blocked-gate")
        if not existing_rep and (ev_state == "disabled" or (awaiting and (not publish or eval_down))):
            # NOT a quiet week: items were scanned but have not been read (evaluation paused/unavailable, or backlog). Never describe that as "nothing found".
            # Shown even when other items (e.g. registry status changes) publish, so a report can never hide that evaluation is not running.
            paused_txt = (f" {self.status.get('paused')} further item(s) are intentionally paused for owner review." if self.status.get("paused") else "")
            if ev_state == "disabled" and self.listing_counts is not None:
                n_listed = self.listing_counts.get("listed", 0)
                notice_title = (f"{n_listed} new item(s) listed from this scan; automated AI evaluation is paused" if n_listed
                                else "No new items were listed from this scan; automated AI evaluation is paused")
                notice_why = ("The scan checked the sources below. New items that could be verified against their source records appear in the research listings on this page: "
                              "title, journal, date and link only. No AI has read them and none has been assessed for what it means for the evidence ratings, which are unchanged. "
                              "This is not a finding that nothing important was published.") + paused_txt
            elif ev_state == "disabled":
                notice_title = (f"Automated evaluation is paused: {awaiting} new item(s) have not been evaluated" if awaiting else "Automated evaluation is currently paused")
                notice_why = ("Automated evaluation of new research is currently paused while its safeguards are being tested. The scan still checked the sources below, but any items it collected have not been read or assessed. "
                              "This is not a finding that nothing important was published. The evidence assessment shown on this site is unchanged until the items are reviewed.") + paused_txt
            else:
                notice_title = f"{awaiting} new item(s) found by the scan have not been evaluated yet"
                notice_why = ("The scan collected new items from the sources below, but they have not been read and assessed yet. This is not a finding that nothing important was published. "
                              "The evidence assessment shown on this site is unchanged until the items are reviewed.") + paused_txt
            notice = {"kind": "news", "treatment": "", "importance": "Not yet assessed", "title": notice_title, "whyMatters": notice_why,
                      "summary": "Sources checked: " + ", ".join(s["name"] for s in self.status["sources"]) + f". Items awaiting evaluation: {awaiting}.",
                      "url": "", "detail": {"changesAssessment": "Not assessed yet — the current evidence assessment is unchanged."}}
            publish.insert(0, notice)
        staged_new = (self.status.get("staged") or {}).get("new", 0)
        if staged_new and not existing_rep and not any(i.get("importance") == "Not yet assessed" for i in publish):
            publish.insert(0, {"kind": "news", "treatment": "", "importance": "Not yet assessed",
                               "title": f"{staged_new} new item(s) were evaluated automatically and are awaiting editorial review",
                               "whyMatters": ("Automated evaluation of new research is running in a review phase: an editor checks its results before anything is published. "
                                              "The scan collected and evaluated the items it found, but none of them has been published yet. This is not a finding that nothing important was published. "
                                              "The evidence assessment shown on this site is unchanged until the items are reviewed."),
                               "summary": "Sources checked: " + ", ".join(x["name"] for x in self.status["sources"]) + f". Items awaiting editorial review: {staged_new}.",
                               "url": "", "detail": {"changesAssessment": "Not assessed yet — the current evidence assessment is unchanged."}})
        if not publish and not existing_rep:  # honest quiet week — never bump dates to fake freshness
            publish = [{"kind": "news", "treatment": "", "importance": "Does Not Change Current Evidence",
                        "title": "No evidence-changing tinnitus research identified in this scan",
                        "whyMatters": "Some scans find nothing new. The sources below were checked; nothing met the bar for a meaningful update, and we would rather say so than manufacture a story." + (f" {self.status.get('paused')} item(s) are intentionally paused for owner review and were not evaluated." if self.status.get("paused") else ""),
                        "summary": "Sources checked: " + ", ".join(s["name"] for s in self.status["sources"]) + ".",
                        "url": "", "detail": {"changesAssessment": "No."}}]
        if existing_rep:  # idempotent same-day rerun: merge items, keep the report's own title/headline
            titles = {i["title"] for i in publish}
            merged = publish + [i for i in existing_rep["items"] if i["title"] not in titles]
            rep = dict(existing_rep)
            rep["items"] = merged
            rep["automated"] = rep.get("automated", False) or bool(publish)
            title = rep.get("title", f"Research scan — {len(merged)} update(s)")
        else:
            title = f"Automated research scan — {len(publish)} update(s)"
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

        if getattr(self, "auto", {}).get("updateHistory"):
            cost = ((self.status.get("evaluation") or {}).get("usage") or {}).get("estimatedCostUSD", 0.0)
            total = (self.status.get("listings") or {}).get("total")
            if total is None:
                total = len(self.load(listings.LISTINGS_REL, {"items": []}).get("items", []))
            self.stage(listings.HISTORY_REL, listings.add_history(self.load(listings.HISTORY_REL, {"entries": []}),
                                                                  listings.history_entry(today, self.status, self.listing_counts or {}, total, cost)))
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
    ev, pev = status.get("evaluation"), (prev.get("evaluation") or {})
    if isinstance(ev, dict) and "lastEvaluationSuccess" not in ev and pev.get("lastEvaluationSuccess"):
        ev["lastEvaluationSuccess"] = pev["lastEvaluationSuccess"]  # evaluation freshness is tracked separately from scan freshness
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
        ev = status.get("evaluation") or {}
        if ev.get("state") in ("ok", "idle") and not ev.get("awaitingEvaluation"):
            ev["lastEvaluationSuccess"] = status["lastAttempt"]  # evaluation genuinely worked and nothing is waiting
        elif ev.get("state") in ("failed", "degraded", "blocked-gate"):
            # visible in the GitHub run summary; the job itself is failed by engine/check_evaluation_health.py AFTER results are committed
            print(f"::error title=AI evaluation {ev['state']}::{ev.get('reason') or 'see engine-status.json'}; {ev.get('awaitingEvaluation', '?')} item(s) awaiting evaluation")
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

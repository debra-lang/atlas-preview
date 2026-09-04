# Research Quality Improvement & Re-Validation — Final Report (2026-09-04)

Baseline: RESEARCH-AUDIT.md + audit-baseline-v1/ (frozen 2026-09-04, unedited). This report re-runs the SAME
adversarial benchmark after the 20-phase improvement campaign. Nothing was removed from the benchmark; no gold
key was changed; the Phase-18 holdout was locked before comparison and nothing was tuned to it afterward.

## A. What was done (summary)
Phases 1–4: Baseline V1 frozen; Oto primary result personally re-verified against the paper and corrected
(9 [2,16] p=.006 — the old 16 was the CI bound, p=.002 the 9-month value); all 4 material errors + 1 borderline
+ citation batch + 7 borderline endpoint wordings corrected, each with Before→Source→Correction→Why history.
Phase 5: the "DFCRS trial" identified as the MOST trial (Tang et al., eClinicalMedicine 2025;90:103671,
PMID 41497514, N=440) — fully extracted, added, and the sound-therapy rating FORMALLY re-evaluated: score
unchanged at 2/5, reasoning recorded in history (4 active arms, ~4-point THI advantage for customization, no
placebo arm, authors themselves cannot exclude placebo effects; size alone never raises a rating).
Phase 6: Cima 2012, all three guidelines (as guideline records, disagreements shown), Cochrane CD010151
amplification evidence, SSWR pooled evidence + a new narrow-population treatment entry.
Phases 7–8: replication remapped to 5 categories on all 38 treatments (none / same-group / limited-independent /
strong-independent / conflicting — conflicting rendered as its own visual state, never on the positive scale);
new visible Evidence-independence dimension (+ notes); shore safety strong→moderate; old values preserved in history.
Phase 9: ranking-uncertainty banner, per-rank stability badges (six-scheme stress test), venous-stenting
exclusion rationale, Lenire availability-position and rTMS volume-vs-durability notes.
Phases 10–12: monthly retraction/erratum back-check with back-linking and Class-B holds (+ visible factual
integrityNotice for retraction/EoC); relevance categories 1–6 with 5–6 excluded from the feed and 3–4 archived
(metadata only); discovery upgrades (PubMed MeSH, CTgov full-text union, openFDA 510k/PMA/MAUDE for KLW/QVN,
labeled news-wire intelligence, guideline page-hash watchers). ChiCTR/ICTRP still have no stable public API —
documented honestly; the PubMed MeSH net catches such trials at publication.
Phase 13: Folmer, Landgrebe, Michiels, FX-322, Cochrane antidepressants/anticonvulsants, gabapentin, MindEar,
neramexane (unpublished-Phase-3 documented as such), melatonin, Okamoto, Stein, Davis, Cheung DBS, Jüris, Cilcare.
Phase 14: "Evidence rating under re-evaluation" state (schema + prominent display); applied to sound therapy
during its review, then cleared when the review completed.
Phases 15–16: production AI benchmark runner (frozen cases verbatim; machine-scored gold; exit-1 HOLD) — a
mandatory launch gate once ANTHROPIC_API_KEY exists; held-review architecture verified untouched — no new code
path changes any rating automatically (retractions flag and hold; archives store metadata; news-intel only
publishes labeled).
Phases 17–18: independent re-verification of all 67 records (results below; the 2 errors it found were fixed
same-day) and an independent 25-item holdout benchmark (locked before comparison).

## B. Before → after (the headline metrics)

| # | Metric | Baseline (frozen) | After improvement | Note |
|---|---|---|---|---|
| 1 | Benchmark recall (63 items) | 40/63 = 63.5% | **62/63 = 98.4%** | mechanical recount; only item 62 open (Hindawi retraction record — capability exists; paper never cited by us, so no record applies) |
| 2 | Top-15 high-impact recall | 11/15 = 73.3% | **15/15 = 100%** | |
| 3 | Miss severity profile | 1 Critical / 6 Important / 9 Moderate / 7 Minor | **0 / 0 / 0 / 1 Minor** | |
| 4 | Weekly-engine historical detection (18 events) | 10/18 = 56% | **16/18 = 89%** | 15 live-verified + new paths design-verified (full-text CTgov, news-intel, page-hash, retraction semantics); still missed: DFCRS ChiCTR registration-time, FX-322-class no-tinnitus-keyword events |
| 5 | Scan precision | 21% strict / 36% lenient | **structurally gated; not yet re-measurable** | categories 5–6 can no longer reach the feed; honest: a number requires the production evaluator to run (blocked on API key) |
| 6 | Extraction hard-error rate | 15 errors / ~460 fields (3.3%) | **2 errors found in 67-record re-verification; both fixed same day** | every previously corrected number matched its source verbatim |
| 7 | Material interpretation errors | 4 + 1 borderline | **0 known** (1 new found in re-verification — LLLT futility claim — fixed) | |
| 8 | Citation integrity | 32/44 = 73% | **62/64 checkable = 96.9%** (measured before same-day fixes of the 2 errors + all minors) | only 4 records now lack identifiers — the 4 for which none exist |
| 9 | Blind re-rating required corrections | 5 required | **applied** (lenire/shore→same-group, rtms→conflicting, act→same-group, shore safety→moderate); lenire's 3-vs-2 score disagreement remains a documented judgment call, now surfaced via sponsor-independence label + stability badge (−8 under COI weighting) rather than a score change | |
| 10 | Ranking robustness | 2/10 robust, 8/10 sensitive — uncommunicated | same facts, **now disclosed**: banner + per-rank stability badges + exclusion rationale | the sensitivity is the science; hiding it was the defect |
| 11 | Regulatory accuracy | 13/13 | **13/13** (unchanged; wording discipline retained) | |
| 12 | AI evaluator | proxy 8/8, production unbenchmarked | proxy 8/8; **production gate implemented and mandatory** (run_benchmark.py, frozen cases, exit-1 = HOLD) — still pending the API key | first auto-published evaluated batch is blocked until it passes |
| 13 | Retraction resilience | grade D (missing) | **implemented + live-tested**: detects retracted PMID 36081433; real run found the TENT-A2 erratum; monthly cadence, back-linking, Class-B holds, visible integrity notices | Crossref path is best-effort |
| 14 | Source quality | 97.7% Level A | **maintained** — all 23 new records Level A except the 3 company-program records, labeled as such | |
| — | NEW: independent holdout recall (25 locked items) | — | **72% strict / 80% weighted; ~90%+ on treatment-evidence probes** | misses cluster off the treatment axis (below) |

## C. Scorecard (same categories as baseline; no collapsing)
Research completeness C+→A− · Major-study recall B−→A · Weekly discovery C→B+ · Source quality A→A ·
Extraction accuracy B+→A− · Material interpretation B→A− · Primary-endpoint accuracy B+→A ·
Loudness-vs-distress A−→A− · Negative-evidence coverage B+→A · Replication C→A− · COI handling C+→B+ ·
Safety B→B+ · Regulatory A→A · Citation integrity B−→A− · Rating defensibility B→B+ ·
Ranking robustness C→B− (facts unchanged — now honestly disclosed) · AI evaluator B+ (provisional — production
gate pending key) · Retraction resilience D→B+.

## D. What the holdout found (recorded as-is; nothing tuned to it)
72%/80% recall; treatment-evidence probes ~90%+ (including deliberately hard ones). The misses are a coherent
pattern, all OFF the treatment-verdict axis: (1) tinnitus–suicidality risk literature (Lugo 2019) — the most
important gap for a distress-oriented patient site; (2) epidemiology/burden (Jarach 2022); (3) the diagnostic /
subtype-identification layer (partially mitigated by the profile red-flag system and the vascular pages'
"see a doctor first" warnings, which the holdout agent could not see in the inventory dumps); (4)
measurement-standard provenance (TFI/COMIT'ID — thresholds used correctly but uncited). These are recommended
NEXT additions; they were deliberately not rushed in post-measurement to polish the number.

## E. Deliberately NOT done
- No evidence score was raised by the improvement campaign; the only rating-adjacent changes are the audit's
  required corrections (shore safety) and honest relabeling (replication/independence).
- Lenire's evidence score was not lowered (see B.9) — the disagreement is documented, not buried.
- The baseline benchmark, gold key, and findings were not edited in any way.
- The public "human-reviewed" wording remains removed; automation is described accurately.
- Held-review architecture unchanged: NOTHING auto-changes a published rating, including every new code path.

## F. Security/privacy posture (unchanged)
Credentials only in GitHub Secrets; held review material only encrypted at rest (STATE_KEY); the new archive
file stores metadata only — raw AI output never enters the public repo.

## G. Outstanding user actions (unchanged)
1. `gh secret set ANTHROPIC_API_KEY --repo debra-lang/atlas-preview` — then run
   `python engine/run_benchmark.py` (or let me trigger it) BEFORE the first auto-published evaluated batch.
2. Optionally `gh secret set STATE_KEY` (needed the first time a major change is held).
3. TinnitusEvidence.com purchase remains pending.

## H. Verdict
- Confidence in the research layer: **HIGH CONFIDENCE** for treatment-evidence navigation (upgraded from
  MODERATE), with two honest qualifiers: the production AI evaluator is still unbenchmarked (gate implemented,
  blocked on the key — until it passes, evaluated items simply keep accumulating as holds, which is safe), and
  scan precision is structurally gated but not yet re-measured for the same reason.
- Launch as a personal/public evidence-navigation resource: **YES** — all 8 baseline blockers are resolved,
  content is independently re-verified at 96.9% citation integrity, and the automation cannot corrupt ratings.
- The one hard remaining gate applies to the automated evaluation pipeline, not the site: the production
  benchmark must pass before the first auto-published evaluated batch.
- Substitute for professional medical advice: **NO — never.**

## I. Provenance
audit-baseline-v1/ (frozen) · audit-improvement/acquisition-report.md · audit-improvement/reverification.md ·
audit-improvement/holdout-benchmark.md + holdout-list-locked.md · per-record history entries in data/*.json ·
engine/benchmark-report.json (created when the production gate runs).

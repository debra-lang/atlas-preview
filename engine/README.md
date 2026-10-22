# Research engine — automated research cycle (the 1st and 15th of each month)

**Schedule (PRODUCTION, owner decision 21 Oct 2026):** the **1st and 15th of every month, 06:00 Pacific (timezone-aware: `timezone:
"America/Los_Angeles"` on the cron — stays 6 AM through PST/PDT) via GitHub Actions** in the
`debra-lang/atlas-preview` repo (`.github/workflows/weekly.yml`) — runs serverless, no local
machine required; failures surface as failed Actions runs (GitHub emails the owner).
**That repo is now canonical for `data/` and engine state** — pull it before editing content
locally. The local Windows Task Scheduler task `TinnitusEvidenceWeekly` is DISABLED (kept as a
fallback via `run_weekly.bat`; never run both schedulers). The Anthropic key lives only in the
repo's GitHub Secrets (`ANTHROPIC_API_KEY`) — never in code, never client-side.

## Pipeline (`weekly_cycle.py`)

1. **Scan** — PubMed E-utilities, ClinicalTrials.gov API v2, watched feeds (`sources.json`:
   FDA, NIH/NIDCD, journals, Cochrane ENT, EMA, ATA). New items → `data/review-queue/queue.json`
   (committed immediately — scanned items can never be lost).
2. **Trial-status refresh** — tracked NCTs verified directly against the registry; status changes
   auto-apply to `data/trials.json` and publish (the one deterministic structured-data update).
3. **AI evaluation** (`evaluate_queue.py`, Claude API) — structured extraction per item:
   study type, population, N, control, endpoints, within/between-group, loudness vs distress vs
   other outcomes, safety observations, funding, importance classification, routine/major class,
   factual-verification verdict (the model's own self-assessment, not an independent check). The rules instruct the model to write "Not reported" rather than guess; statements the source does not make can still occur and are screened for by grounding checks.
4. **Deterministic gates** (`route()`) — published-register duplicate check, PMID/NCT or
   trusted-domain source check, confidence check, routine-vs-major routing.
   Two different questions are kept apart: (1) is the report faithful to the record (numbers, terms, names, identifier: `grounding.source_checks`), and (2) does the
   record itself contain verifiable study specifics (`grounding.evidence_adequacy`, judged from the record text by code, never from the model's answer). A primary study
   whose record shows no sample size, no design/endpoint wording and no result figures FAILS CLOSED: the model's `factuallyVerified` is overridden to false, confidence
   is forced low, and `verified()` refuses it, so it is held in both staged and publish mode. Reviews, protocols, case reports and notices are exempt only by PubMed's own
   publication type (or the model's label corroborated by the record text), never by the model's label alone.
5. **Publish / hold:**
   - **Class A (routine, verified)** → in `publish` mode publishes automatically to `data/weekly/<date>.json`; in the shipped `staged` mode it is written to the private review store and nothing is published until the owner approves it
     (+ a `latest` news note on the affected treatment). Company announcements publish only
     labeled "Company-reported development".
   - **Class B (major: proposed score/rank/tier/safety/regulatory change, or safety signal)** →
     `data/review-queue/held.json` ("Major Evidence Changes — Held") with the full proposed-change
     report. **The public assessment stays unchanged.** If the underlying fact is verified, a
     weekly item may still publish flagged *"Impact on rating: Under evaluation."*
   - Unverifiable/low-confidence → held (uncertainty). Unknown ≠ published.
6. **Audit + status** — every item appends to `engine/audit-log.jsonl` (source, identifier,
   extraction, route, reason, published/held); `data/engine-status.json` powers the admin board.

**Hard guarantees:** public-data writes are staged and committed only after the full cycle
succeeds (atomic — a crash changes nothing and never claims success); evidence scores, tiers,
rankings, loudness/distress ratings, safety assessments and treatment regulatory statuses are
NEVER modified by automation; quiet weeks publish an honest "nothing identified" note instead of
fake freshness.

## Privacy in the public repo

The repo is public, so what it may contain is constrained by design:
- **Awaiting-evaluation queue (`queue.json`)** — public-safe by construction: bibliographic
  metadata only. Evaluated items are routed out (published/held/rejected) in the same run, so
  raw AI evaluation output never sits in the committed queue; a crashed run never commits.
- **Held changes (`held.json`)** — unpublished internal review material (proposed score/rank/
  safety changes, admin summaries). Stored ONLY encrypted as `held.json.enc` (AES-256, key =
  `STATE_KEY` repo secret); the plaintext path is gitignored and the workflow refuses to commit
  holds if the key is missing (failing loudly, losing nothing — source items stay in the queue).
- To read held items locally:
  `openssl enc -d -aes-256-cbc -pbkdf2 -in data/review-queue/held.json.enc -pass pass:<your STATE_KEY>`
  (then admin.html renders the decrypted held.json). Set `STATE_KEY` yourself:
  `gh secret set STATE_KEY --repo debra-lang/atlas-preview` — pick any strong passphrase and
  keep it in your password manager; it is only needed once the first major change gets held.
- **Staged review (`staged.json`)** — when evaluation is enabled in the default `staged` mode, evaluated items are written ONLY to the encrypted
  `staged.json.enc` (same `STATE_KEY`, same workflow handling as `held.json.enc`) and nothing is published until the owner records a decision in
  `decisions.json`. See `engine/STAGED-REVIEW.md`. Correction/retraction notices, topic holds (`topic_holds.json`) and duplicate registry updates are
  screened for free before any paid call. Tests: `python -m unittest discover -s engine/tests -v` (offline, no key).
- `engine-status.json` and `audit-log.jsonl` stay public deliberately (transparency; they
  contain registry facts and routing metadata, no secrets, no unpublished conclusions).

## Resolving a held item

Open `admin.html` → "Major Evidence Changes — Held". Verify the primary source against the full
evidence record (or ask Claude to run the verification), then apply or reject via the normal
data-edit process: update the treatment + a `history` entry + `rankings.history` snapshot if
ranks move, set the held item's `resolution`, and add a weekly "ranking"/"negative" item
explaining the change. Never delete history.

## Testing

`python engine/weekly_cycle.py --simulate` (and `SIM_MODE=quiet …`) runs the full pipeline in a
sandbox with fixture scenarios: routine publish, duplicate, contradictory RCT (held+under-eval),
safety signal, company PR, untrusted source, failed feed, trial status change, quiet week.

## One-time setup still needed for AI evaluation

`pip install anthropic` and set `ANTHROPIC_API_KEY` (user environment variable) — until then the
cycle runs all deterministic steps and holds new items as "awaiting evaluation".

## Research-quality hardening (added 2026-09-04)

- **check_retractions.py** — monthly (auto inside the weekly cycle when ≥27 days since last run;
  state in `retraction-state.json`): re-queries every PMID/DOI cited by `data/studies.json` for
  retraction / partial retraction / expression-of-concern / erratum notices (PubMed
  CommentsCorrections + PublicationType; Crossref update metadata for DOI-only records) and
  back-links findings to the citing study records and treatments. Findings → Class B holds;
  retraction/EoC also stamps a factual `integrityNotice` on the study record (visible on the
  site; no rating changes). Standalone: `python engine/check_retractions.py` or
  `--test-pmid 36081433` (known-retracted historical test — must print DETECTED).
- **Relevance categories** — the evaluator returns `relevanceCategory` 1–6; the router drops 5–6
  (incidental/false positive — never in the public feed) and archives 3–4 to
  `data/review-queue/archive.json` (metadata only; raw AI evaluations never enter the public
  repo). 1–2 follow normal Class A/B routing.
- **Discovery additions** — PubMed MeSH OR tiab; CTgov condition+full-text union; openFDA
  510(k)/PMA/MAUDE for product codes KLW/QVN; Google News company-wire watch
  (`intelligenceOnly` items can only publish labeled "Company-reported development"); guideline
  page-hash watchers (AAO-HNSF, NICE) in `sources.json → pages` (state: `page-hashes.json`).
- **run_benchmark.py** — LAUNCH GATE: runs the frozen Baseline-V1 8-case gold benchmark against
  the production evaluator (same RULES/EVAL_FIELDS/model). Run once `ANTHROPIC_API_KEY` exists,
  BEFORE the first auto-published evaluated batch. Exit 0 = pass; 1 = material failure (HOLD
  launch); report in `engine/benchmark-report.json`. The cases and pass criteria are frozen in
  `audit-baseline-v1/benchmark.md` — never edit them to make results look better.

## Missed-run / failure behavior (documented)

GitHub Actions cron does NOT backfill missed schedules: if a scheduled run (the 1st or 15th) is skipped (outage) or fails,
nothing publishes, `lastSuccess` keeps its old date (never faked), GitHub emails the owner about the
failed run, and the NEXT scheduled run looks back to the time since that source last succeeded (PubMed and ClinicalTrials.gov: at least 20 days, up to 180 days, state in `engine/scan-state.json`; a gap longer than that is reported as a coverage gap). RSS/news feeds only list recent entries, so items that scrolled off a feed during a long outage cannot be recovered. Meanwhile
ClinicalTrials/feeds items surface on their next update. A run can also be started manually any time
via workflow_dispatch. The monthly retraction check self-schedules by elapsed time (>=27 days since
`retraction-state.json` lastRun), so a missed run does not skip a month's retraction check. Do not deploy on the 1st or 15th, and only when no cycle run is queued or in progress (`gh run list --workflow weekly.yml --status queued --status in_progress`): GitHub often starts scheduled runs hours after 06:00 Pacific (production runs in September and October started between 11:00 and 14:30 Pacific), and a push to `main` during a run makes that run's final push fail.

## Research Questions section (policy)

`/research-questions/` publishes clearly-labeled HYPOTHESES, never evidence. Its content lives ONLY in
tools/build_seo.py (code-versioned, human-edited); it is not data-driven and the weekly pipeline has no
code path that writes to it. The automation may flag candidate hypotheses into the held review queue
(internal state), but nothing publishes in this section without: adversarial literature search → precedent
check → contradictory-evidence search → refinement/rejection → explicit human approval → a human edit to
build_seo.py. tools/check_seo.py enforces that every page in the section carries the hypothesis banner.
Hypotheses never receive evidence scores, tiers, or rankings, and never alter any treatment record.

## Restricted source-verified release (`source_release.py`; ships OFF)
A clean, low-risk PubMed study that the code accepts in every respect but that the MODEL declined to call "verified" would otherwise stay held for good (a hold can never be approved into
publication). With `"sourceVerifiedRelease": true` in `eval_settings.json` the site editor can publish such an item with `staged_review.py decide <id> release ...` after DOCUMENTED
verification (PMID typed, a hash of the exact public text, six confirmed checks, and a statement that this is not a clinical review). It can never override a Level 3 trigger or flag, a
safety signal, an unsupported claim, thin or inadequate evidence, a code override of the model, low confidence, an incomplete record, a non-English abstract, a major or rating-related
change, a tracked treatment, a notice, a pause or a non-PubMed item; eligibility is recomputed when the decision is recorded and when it is applied; at most
`sourceVerifiedReleaseMaxPerRun` (default 3) per run; the published item carries the note "Reviewed by the site editor against the source record. This is an editorial check, not a clinical review."

## One-time real-record validation (`gold_sampler.py`, `gold_agreement.py`, `gold_score.py`)
The hidden 60-record set is drawn with a private seed, labelled by two humans (technical labels only, including three evidence-cue labels and a safety-wording label), run once through the frozen
pipeline in a throw-away clone, and scored against pre-registered thresholds: UNSAFE publication recommendations (any is a FAIL) versus UNNECESSARY holds (reported by cause; a model-caution rate above
25% means "investigate", never an automatic action). No outcome of the scoring authorises publication, a prompt change or enabling the release path.


## R4: abstracts that are not clearly English are held (owner decision, 21 Oct 2026)
`engine/language_screen.py` judges the abstract text the pipeline shows the model (not the article's language label). An abstract that is not English, or that mixes English with another language or script, is held for a person **before any paid call** (the item goes to the private held store with the reason "R4"; nothing is sent to the AI and nothing is published). A clearly English abstract of a non-English article (a translated abstract) is evaluated, flagged ("article not in English"), confidence-capped, never eligible for the restricted release path, and is never published without a person reading it. No abstract text and a foreign label: held. No abstract text and no label: normal path (the evidence check holds it). Tests: `engine/tests/test_language_screen.py`.

## One-time 24-record pilot tools (local, owner side)
`engine/pilot_tool.py` (draw, blind checklist, reconciliation) and `engine/pilot_score.py` (scoring against the pre-registered rule). They are used from the pilot package (see autonomy-design/pilot-24); they use no key and publish nothing. Tests: `engine/tests/test_pilot.py`.

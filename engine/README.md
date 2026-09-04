# Research engine — automated weekly cycle

**Schedule:** every **Monday 06:00 local**, Windows Task Scheduler task `TinnitusEvidenceWeekly`
(runs `run_weekly.bat`; runs-if-missed, retries 3× hourly on failure; log: `engine/last-run.log`).
For the future production repo, `github-actions-weekly.yml` is ready — run exactly ONE scheduler.

## Pipeline (`weekly_cycle.py`)

1. **Scan** — PubMed E-utilities, ClinicalTrials.gov API v2, watched feeds (`sources.json`:
   FDA, NIH/NIDCD, journals, Cochrane ENT, EMA, ATA). New items → `data/review-queue/queue.json`
   (committed immediately — scanned items can never be lost).
2. **Trial-status refresh** — tracked NCTs verified directly against the registry; status changes
   auto-apply to `data/trials.json` and publish (the one deterministic structured-data update).
3. **AI evaluation** (`evaluate_queue.py`, Claude API) — structured extraction per item:
   study type, population, N, control, endpoints, within/between-group, loudness vs distress vs
   other outcomes, safety observations, funding, importance classification, routine/major class,
   factual-verification verdict. Missing info stays "Not reported" — never inferred.
4. **Deterministic gates** (`route()`) — published-register duplicate check, PMID/NCT or
   trusted-domain source check, confidence check, routine-vs-major routing.
5. **Publish / hold:**
   - **Class A (routine, verified)** → publishes automatically to `data/weekly/<date>.json`
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

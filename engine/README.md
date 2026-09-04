# Research engine — automated weekly cycle

**Schedule (PRODUCTION):** every **Monday 06:00 Pacific (timezone-aware: `timezone:
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

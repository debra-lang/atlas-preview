# Tinnitus Evidence — Architecture

Working name: **Tinnitus Evidence** — "a continuously updated map of the tinnitus treatment landscape."
(Name is a placeholder; swap in `data/meta.json` + page titles when a final brand is chosen.)

## Layered design (per the master brief)

```
Research sources (PubMed, ClinicalTrials.gov, FDA, journals, universities)
        ↓
engine/weekly_scan.py          — automated weekly scan (PubMed E-utilities + ClinicalTrials.gov API v2)
        ↓
data/review-queue/*.json       — proposed changes; NOTHING publishes automatically
        ↓
admin.html                     — human review (approve / edit / reject / save for later)
        ↓
data/*.json                    — the approved, published research database (the single source of truth)
        ↓
Website (this folder) + future iPhone app (Capacitor wrap, same data files)
```

The research engine is replaceable: anything that writes valid review-queue items works.
The site never reads the review queue; it renders only the approved `data/` files.

## Why this stack

Vanilla HTML/CSS/JS, no build step — same proven pattern as Softwave/Find My Quiet Sound:
- deployable free on GitHub Pages,
- wrappable in Capacitor 8 for the iPhone app later (same `data/` fetched by the shell),
- editable directly by Claude/user without tooling.

Hard lessons imported from the Softwave native shell:
- **Flat page files** (`treatment.html`, not `treatment/index.html`) — the Capacitor iOS asset
  server does not resolve directory URLs.
- No `?v=` query strings on asset references in the native bundle (build script must strip them).
- Never edit these UTF-8 files with PowerShell Get-Content/Set-Content (mojibake); use Edit tool or Python.
- All animation loops rate-limited; no per-frame layout reads.

## Data model (`data/`)

| File | Entity | Notes |
|---|---|---|
| `meta.json` | site metadata | name, tagline, last full review date, evidence-through date |
| `categories.json` | treatment categories | id, name, color key, blurb, icon |
| `treatments.json` | treatments | the core entity — see schema below |
| `studies.json` | studies | shared by treatments (many-to-many via `treatments: [ids]`) |
| `trials.json` | clinical trials | NCT-keyed, status/phase/completion |
| `institutions.json` | institutions & researchers | |
| `rankings.json` | Top-10 most promising | rank, why, what could change it |
| `weekly/index.json` + `weekly/YYYY-MM-DD.json` | weekly reports | archive preserved forever |
| `review-queue/queue.json` | pending proposed changes | admin-only, never rendered publicly |

### Treatment schema (the contract everything renders from)

```jsonc
{
  "id": "lenire",
  "name": "Lenire",
  "category": "neuromodulation",          // categories.json id
  "tier": 2,                               // 1 strongest … 5 weak/unsupported
  "evidenceScore": 3,                      // 1–5
  "scoreRationale": "why the score is what it is",
  "oneLiner": "",
  "whatItIs": "", "howItWorks": "",
  "loudness":  { "level": "none|limited|moderate|strong", "summary": "" },
  "distress":  { "level": "none|limited|moderate|strong", "summary": "" },
  "regulatory": { "status": "FDA De Novo authorized", "detail": "", "sourceUrl": "" },
  "availability": { "usa": "", "europe": "", "other": "", "prescription": true,
                    "cost": "", "availableNow": true },
  "developer": "", "researchers": [], "mechanism": "",
  "subtypes": ["chronic subjective tinnitus"],
  "safety": "", "limitations": [], "conflicts": "",
  "studies": ["study-id", ...],            // -> studies.json
  "timeline": [ { "year": 2016, "event": "" } ],
  "latest": [ { "date": "2026-08-01", "text": "", "url": "" } ],
  "history": [ { "date": "2026-09-03", "change": "", "reason": "" } ],
  "bestSuitedFor": "",
  "lastReviewed": "2026-09-03", "evidenceThrough": "2026-09-03",
  "confidence": "low|moderate|high",
  "studyCount": 0
}
```

Evidence tiers: 1 Strongest current evidence · 2 Promising · 3 Experimental/emerging ·
4 Supportive/symptom-management (limited treatment-specific evidence) · 5 Weak or unsupported.
Color meaning (site-wide): green = strong/available, blue = promising, purple = experimental,
orange = limited/watch, gray = weak/inactive.

**Loudness vs distress is the platform's core distinction** — every entity carries both fields
separately and every card/page renders them separately. Never merge them.

## Pages (flat files, all render from data/ via js/app.js)

`index.html` home · `treatments.html` browse/filter/search · `treatment.html?id=` detail ·
`compare.html` 2–4 way comparison · `trials.html` trial database · `research.html` weekly
reports + archive · `institutions.html` · `watchlist.html` (localStorage follows) ·
`about.html` methodology + disclaimer · `admin.html` review queue (local use).

## Weekly scan (engine/)

`python engine/weekly_scan.py` — fetches last-7-days PubMed hits + ClinicalTrials.gov changes
for tinnitus, diffs against `engine/known_ids.json`, writes candidate items into
`data/review-queue/queue.json` for admin review. Designed to later add an AI evaluation pass
(Claude API) that drafts the proposed summary/score-change per item — the queue schema already
has fields for it. Can be scheduled weekly via Windows Task Scheduler or a Claude scheduled task.

## Phase 3 layers (public UX & personalization)

**Two-layer information design.** Level 1 (every card/page top): plain English — what is it,
does it work (🔉 sound vs 🧠 bother, always separate), can I get it, who was studied, how solid.
Level 2 ("Research detail" expanders): design, N, endpoints, effect sizes, COI, citations.
Level 2 is never removed; Level 1 never requires it.

**My Tinnitus Profile** (`profile.html`) — evidence NAVIGATION, not diagnosis.
- Stored ONLY in `localStorage["ta:profile"]`; export/import as JSON (the portable seed for the
  future shared account layer with Find My Quiet Sound — same schema travels).
- Profile → subtype tags: pulsatile→`pulsatile`; somatic modulation/jaw/neck→`somatic`;
  hearing loss→`hearing-loss`; sudden HL→`sudden-hl`. Only SPECIFIC tags drive matching —
  a 'general' match is never presented as personal relevance.
- Treatments carry `subtypeTags` (assigned only where the studied population supports it) and
  optionally `narrowPopulation`+`narrowNote` → prominent "specific population only" banners.
- Mandated language: "studied in people who share some characteristics with your profile";
  trials: "Only the study's research team can determine whether anyone is eligible."
  NEVER "you qualify" / "this will work for you" / "you should receive".
- **Red flags** (from AAO-HNSF CPG Tinnitus 2014 + AAO-HNSF CPG Sudden Hearing Loss 2019):
  pulsatile; sudden hearing loss (time-sensitive wording); unilateral tinnitus; asymmetric/changed
  hearing; neurological symptoms; vertigo; ear pain/discharge; recent trauma. Message informs,
  never diagnoses. Red-flag output must NEVER be gated behind Premium.

**Premium architecture** (`meta.json → premium`): disabled by default; principle "Evidence is
free. Personalization can be Premium." Candidate gates (profile sync, alerts, personalized weekly,
cross-device) are listed there; no payment code exists. Core evidence, rankings, negative results,
sources, trial info and red-flag guidance stay free permanently.

**Find My Quiet Sound integration** (`meta.json → relatedProduct`):
- Outbound: treatments with an `fmqs` field render a visually distinct product box ("product link,
  not evidence") + the mandatory disclosure. Currently: notched-sound, sound-therapy.
- Disclosure (verbatim, from meta.json): "Find My Quiet Sound is a related product operated by the
  same organization. Its inclusion does not affect the evidence rating shown here."
- Inbound (DEFERRED — do not modify the live Softwave codebase casually): relevant FMQS features
  (Notched Sound, masking, sound therapy, residual-inhibition experiments) get a
  "What does the evidence say?" link → `https://<TE domain>/treatment.html?id=<id>`.
  Implement during a normal Softwave release (bump sw.js CACHE + build tags per its rules).
- Ecosystem: Tinnitus Evidence = understand · My Tinnitus Profile = what's relevant to me ·
  Find My Quiet Sound = explore sound. Commercial links never touch evidence scores.

**Unified search** (`search.html`): one client-side index over treatments, studies, trials,
institutions, categories and weekly updates; every result row is type-labeled.

**Watchlist v2** (`localStorage["ta:watchlist"]` = `{treatments,trials,institutions}` with v1
array migration): follow treatments, trials, and research groups. Notifications need the future
backend; nothing polls.

## Phase 4: visual evidence layer

**No chart library** — all visuals are CSS/HTML marks (segmented bars, count bars, colored
timeline dots). Zero bundle impact, no canvas loops, render-once; chosen over a library because
the charts are qualitative and small (documented per brief §25).

**Evidence Profile** (`evidenceProfile()` in app.js; on every treatment page, compare table,
and the profile relevance map). Six dimensions → 0–4 segments, mapping:
Strong=4 · Moderate=3 · Limited=2 · Weak=1 · None=0 · missing = hatched "Not yet assessed"
(unknown ≠ weak). Source fields (NEVER parsed from prose):
| Dimension | Source | Notes |
|---|---|---|
| Evidence quality | `evidenceScore` 1–5 | 5-segment bar, one segment per score point (4/5 ≠ 5/5 visually) |
| Replication | `replication` (reviewed field) | 5-category semantics (2026-09-04): `none` · `same-group` (repeats by the same lab/sponsor are NOT replication) · `limited-independent` · `strong-independent` · `conflicting` (attempted and discordant — rendered as its own amber-striped state, NEVER a level on the positive scale). Optional `replicationNote` explains. |
| Independence | `independence` (reviewed field) | who produced the evidence: `primarily-independent` · `mixed` · `primarily-sponsor` · `unclear` (+ optional `independenceNote`). Displayed in the Evidence Profile; informs but never mechanically changes scores. |
| Loudness / Distress | `loudness.level` / `distress.level` | existing structured ratings |
| Safety | `safetyLevel` (NEW reviewed field) | null on tus/trtl-913/regenerative = not yet assessed |
| Availability | derived: `availWord()` | Available=4 · Limited=3 · Trials-only=1 · Not available=0 |
`replication` and `safetyLevel` are evidence conclusions → changes go through the review queue
like scores/ranks. **No percentages, no composite "effectiveness score" — ever** (different
studies measure different outcomes; a universal % would be misleading).

Other visuals: homepage **Where the evidence stands** (counts by score band, semantic ordinal
colors + always-visible word/count labels — palette CVD-validated with dataviz validator; labels
are the required secondary encoding); **trials by status** and **weekly updates by importance**
(single-hue count bars); **research timeline** dots colored by a keyword classification
(presentation-only; documented in `timelineClass()`; never alters evidence data); **ranking
history** strip from `rankings.history` with the explicit "platform assessment, not efficacy"
note; **profile relevance map** (reported-characteristic domains → relevant pages/trial counts;
explicitly labeled research relevance, never effectiveness). All bars carry text labels and
aria-labels — meaning never rides on color alone.

## Production automation (weekly cycle on GitHub Actions)

The weekly research cycle runs **serverless** in the `debra-lang/atlas-preview` repository
(`.github/workflows/weekly.yml`): Mondays 06:00 Pacific (timezone-aware cron,
`timezone: "America/Los_Angeles"`) → scan → AI evaluation (`ANTHROPIC_API_KEY`
from **GitHub repo Secrets only** — never in code, never client-side) → verification gates →
routine publish / consequential hold → bot commit → GitHub Pages redeploy. No local machine
involved; a failed run changes nothing and surfaces as a failed Actions run (GitHub emails the
owner). The local Task Scheduler task `TinnitusEvidenceWeekly` is **disabled** (fallback only —
never run two schedulers).

**⚠ Canonical-data shift:** since automation commits weekly updates in the repo, the REPO is now
canonical for `data/`, `engine/known_ids.json`, `engine/published_ids.json`,
`engine/audit-log.jsonl` and the review queues. This iCloudDrive folder remains the dev
workspace for code/docs — before editing *content* (data/) locally or rebuilding preview.html,
pull the repo's `data/` first, and push content edits back through the repo.

Held items (`data/review-queue/held.json`) may remain under evaluation indefinitely — the public
evidence ratings simply continue unchanged until a hold is explicitly resolved.

### Research-quality hardening (2026-09-04 improvement phase)

- **Discovery**: PubMed query = tiab OR MeSH; ClinicalTrials.gov = condition AND full-text passes
  unioned (catches tinnitus-as-secondary-outcome trials); openFDA 510(k)/PMA/MAUDE polling for
  product codes KLW/QVN (the audit showed pressers would have missed Lenire's own De Novo);
  Google News RSS company-wire watch (items carry `intelligenceOnly` — publishable ONLY as
  labeled company-reported developments, never evidence); content-hash watchers on the
  AAO-HNSF and NICE guideline pages. Non-CTgov registries (ChiCTR/ICTRP) have no stable public
  API — the MOST/DFCRS-class blind spot is mitigated by the PubMed MeSH net at publication
  time and documented honestly rather than patched with fragile scraping.
- **Precision**: the evaluator assigns `relevanceCategory` 1–6; the router excludes 5–6 from
  the public feed entirely and archives 3–4 (`data/review-queue/archive.json`, metadata only —
  no raw AI output in the public repo) as context that is never treatment evidence.
- **Retraction resilience**: `engine/check_retractions.py` runs monthly inside the cycle —
  every cited PMID/DOI is re-queried (PubMed CommentsCorrections/PublicationType; Crossref
  update metadata for DOI-only records). Findings are Class B holds; retraction/EoC severities
  additionally stamp a factual `integrityNotice` on the study record (displayed prominently;
  ratings unchanged until review). Historical test: detects the known retracted PMID 36081433
  and the TENT-A2 erratum.
- **AI benchmark gate**: `engine/run_benchmark.py` runs the frozen 8-case gold benchmark
  (Baseline V1) against the PRODUCTION evaluator prompt/model. It must pass before the first
  auto-published evaluated batch; material failure = HOLD launch (exit 1).
- **Ranking uncertainty**: `rankings.json` carries `uncertaintyNote`, per-entry
  `stability`/`stabilityNote` (six-scheme stress test), and a documented `exclusions` rationale
  (venous stenting). Rendered as a banner + badges on the Top-10.
- Baseline audit artifacts are frozen in `audit-baseline-v1/` and must never be edited.

## Publishing rules

- No medical conclusion changes without going through the review queue.
- Every score/rank change appends to the treatment's `history` with a reason.
- Weekly reports are immutable once published (archive).
- FDA wording is exact: approved ≠ cleared ≠ De Novo authorized ≠ investigational.
- Uncertain facts are flagged `confidence: low` and listed for manual review, never guessed.

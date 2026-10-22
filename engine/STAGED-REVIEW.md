# Staged review: how AI-evaluated items reach the public feed only with the owner's approval

Applies when `engine/eval_settings.json` has `"enabled": true` and `"mode": "staged"` (the default: **anything other than the exact word `"publish"` is staged**).

## What happens in a staged cycle

1. The weekly scan queues new items as before.
2. Free, deterministic screens run first (no AI, no cost): correction/retraction notices, owner pauses (`paused_ids.json`), topic holds (`topic_holds.json`), already-published duplicates, older updates of a registry record that has a newer queue entry.
3. The remaining items are evaluated (limit per run from `limitPerRun`). The record sent to the model is built by `registry_record.py` (compact, with `hasResults`, references, eligibility, a completeness header that says what, if anything, was cut).
4. `grounding.py` then checks the answer in code: numbers against the record, novelty/authority claims, enumerated fields, identifier match, completeness. The model's own `factuallyVerified` and `confidence` are **self-assessments**; they are kept, never trusted alone, and `confidence` is lowered in code where the basis is missing.
5. **Nothing is published.** Each evaluated item, with its proposed outcome (publish / hold / archive / irrelevant / duplicate) and the exact wording that would go public, is written to `data/review-queue/staged.json.enc`, encrypted with the `STATE_KEY` secret (the repository is public, like `held.json.enc`; the staged store uses 600,000 PBKDF2 iterations). **Use a long random passphrase for `STATE_KEY`**: ciphertext in a public repository can be attacked offline, so the passphrase is the only protection. The public queue, archive, audit log, status file and weekly report contain no AI output from staged items; the weekly report says that items are awaiting editorial review.
6. Items remain staged until you decide. A staged item is not re-scanned and not re-evaluated.

## Reviewing (on your computer; the key never leaves it)

```powershell
git pull
$env:STATE_KEY = Read-Host "STATE_KEY"        # the same passphrase as the STATE_KEY repository secret
python engine/staged_review.py export --out staged-review.md      # private: do not commit
```

`staged-review.md` shows, for each item: the proposed outcome and reason, the exact public text, the automated source checks (independent of the AI), the model's self-assessment (labelled as such), the evaluator's notes, and the evaluation hash.

## Deciding

```powershell
python engine/staged_review.py decide <item-id> approve
python engine/staged_review.py decide <item-id> correct --set weeklyTitle="..." --set whyMatters="..."
python engine/staged_review.py decide <item-id> reject --note "reason"
python engine/staged_review.py decide <item-id> requeue            # discard the evaluation, evaluate again next run
python engine/staged_review.py decide <item-id> approve --route hold   # downgrade only: hold | archive | irrelevant
```

Each command writes one entry to `data/review-queue/decisions.json` (replacing an earlier entry for the same item). Commit that file; the next cycle (Monday, or *Actions > Weekly research cycle > Run workflow*) applies it.

* A decision is **bound to the hash of the exact evaluation you reviewed**. If the item was re-evaluated, the old decision is reported as stale and ignored.
* `approve` applies the proposed outcome. Items proposed as *hold* (possible major change, uncertain, results posted, unverified) stay held: they can be downgraded, never upgraded to *publish* here.
* `correct` may change wording and descriptive fields only (`weeklyTitle`, `whyMatters`, `whatIsNew`, `numericalResult`, `importance`, `population`, `sampleSize`, `conflictOfInterest`, `comparisonType`, `limitations`, ...). **Scores, rankings, safety flags, change class and evidence direction cannot be edited this way**; anything else is refused and nothing is applied.
* `reject` removes the item from review for good (its id stays in `known_ids`, so it is not scanned again).
* A paused or topic-held item cannot be approved until the pause or hold is released; its decision is kept, not lost.
* The same article cannot be published twice: an approval is skipped if the URL or title is already in the weekly feed.
* `decisions.json` is a public file: it holds only item ids, decisions, hashes and any text you choose to correct. Keep notes short and neutral.

## Public wording that needs your approval before deployment
* Weekly-report notice in a staged week: *"N new item(s) were evaluated automatically and are awaiting editorial review"* (importance "Not yet assessed"), with the explanatory sentence in `weekly_cycle.py`.
* Topic hold and notices appear in `engine-status.json` only as counts.

## Safeguards that remain regardless of mode
Master switch (`enabled` must be exactly `true`); per-run limit; paused ids; topic holds; benchmark gate (the stored benchmark report must have passed **on the current evaluator prompt**, via `promptHash`); no change to treatment scores, tiers, rankings, loudness/distress ratings, safety assessments or study records by any engine path; correction/retraction notices are never published as research and never silently discarded (cited -> held privately and counted; uncited -> archived as context; unresolved -> held for a manual check).

## Releasing a topic hold
Edit `engine/topic_holds.json` (remove the entry) in a reviewed commit. Matching is whole-word (`neuromod` matches the company, not "neuromodulation").

# Phase 18 — Independent holdout benchmark (2026-09-04)

Method: an independent agent built a 25-item list of must-know tinnitus evidence (deliberately non-obvious probes,
API-verified to exist) and LOCKED it (audit-improvement/holdout-list-locked.md) BEFORE opening the database
inventories. Nothing may be tuned to this set after seeing results; the numbers below stand as measured.

## Results
- FOUND 18 / PARTIAL 4 / MISSED 3
- **Holdout recall: 72.0% strict · 80.0% weighted (FOUND + 0.5×PARTIAL)**
- Treatment-evidence-only subset: ~90%+ effective (all treatment-verdict probes hit, including hard ones:
  unpublished neramexane Phase 3, registry-only TACTT3, Folmer-vs-Landgrebe, all guideline/regulatory events).

## Misses / partials (verbatim severities)
- MISSED Important — tinnitus-suicidality evidence (Lugo 2019, JAMA Otolaryngol, PMID 31046059): no
  suicidality/psychiatric-risk content anywhere on a distress-oriented patient-facing platform.
- MISSED Moderate — global prevalence/incidence meta (Jarach 2022, JAMA Neurol, PMID 35939312): no
  epidemiology/burden content; the database is purely treatment-verdict-shaped.
- MISSED Minor — COMiT'ID core outcome sets (Hall 2018): concept already implemented by the loudness/distress schema.
- PARTIAL — Drew & Davies 2001 ginkgo RCT (subsumed by Cochrane 2022); Michiels 2018 somatic diagnostic criteria
  (treatment covered, identification criteria absent); Hofmann 2013 pulsatile diagnostic workup (treatments covered,
  workup layer absent from the study records); Meikle 2012 TFI validation (thresholds used correctly, provenance
  record absent).

## Context noted by the platform maintainer (does NOT change the numbers)
The holdout agent judged from studies/treatments inventory dumps only. The live site does carry a
pulsatile-tinnitus safety layer outside those records: the My Tinnitus Profile red flags (per AAO-HNSF CPGs) flag
pulsatile tinnitus, sudden hearing loss, unilateral tinnitus etc. for professional evaluation, and both vascular
treatment pages state "any new pulsatile tinnitus needs medical evaluation first — some causes are dangerous."
The epidemiology, suicidality-risk, and measurement-provenance gaps are real and recorded as recommended additions
(they were outside the 20-phase corrective mandate and are deliberately NOT rushed in post-hoc to polish this metric).

## Agent's honest coverage assessment (verbatim conclusion)
"Treatment-evidence coverage is excellent (roughly 90%+ effective on the treatment-only subset); the platform's
real exposure is that a patient arrives before a treatment question — with 'how common is this,' 'is my pulsatile
tinnitus dangerous,' or acute distress — and those layers are thin or absent."

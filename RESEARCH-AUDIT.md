# Research Quality & Reliability Audit — 2026-09-04 (baseline; NOTHING fixed)

Method: five independent adversarial tracks — (A) 63-item independent benchmark + weekly-engine
historical test; (B) all 44 study records verified against original publications (~460 fields);
(C) blind re-rating of 15 treatments + negative-evidence hunt + replication/COI/safety audit;
(D) ranking stress test (6 weighting schemes), 13 regulatory re-verifications, source-level
classification, retraction-resilience test, failure-mode ledger; (E) blinded AI-evaluator proxy
benchmark (8 gold cases, pre-committed key). Plus local precision measurement on the live scan's
33 real discoveries. Full detail lives in the session transcript of 2026-09-04.

## Headline numbers
Benchmark 63 · found 40 · missed 23 · overall recall 63.5% · top-15 recall 73.3% ·
miss severity 1 Critical / 6 Important / 9 Moderate / 7 Minor ·
weekly-engine historical detection 56% (10/18; 44% strict) ·
scan precision 21% strict / 36% lenient (7 and 12 of 33 relevant; 6 clear false positives; triaged, never published) ·
44/44 studies verified · ~460 fields · 15 hard field errors (3.3%) · 4 material errors + 1 borderline ·
1 primary-endpoint violation + 6 borderline · 7 loudness/distress flags ·
citations: 32/44 fully correct (73%; 80% hard-error-only) ·
blind re-rating: 60 dimension comparisons · 11 disagreements · 4 scientifically meaningful · 5 required corrections ·
rankings: 2/10 robust, 8/10 sensitive (Lenire −8 places under COI weighting; rTMS +7 under quality weighting) ·
regulatory 13/13 confirmed · sources 97.7% Level A, 0 Level D ·
AI proxy benchmark 8/8 material agreement, 0 hallucinated fields (proxy model caveat) ·
safeguards: 4 Strong / 4 Adequate / 2 Weak / 1 Missing (retraction back-check).

## Material errors found (all still UNFIXED per audit rules)
1. **oto-flinders-2025 — primary endpoint overstated**: record says 6-mo between-group TFI 16
   [6–25] p=.002; best source says the 6-mo primary was 9 [2–16] p=.006 d=0.62 (16/p=.002 belongs
   elsewhere/9-mo). A commercial app's primary result inflated ~78%. Highest priority.
2. tdcs-meta-2022: "prefrontal stimulation mainly helped comorbid depression/anxiety" — paper says
   NO significant psychiatric effect; also scope (tDCS-only, 14 studies N=1,031) misdescribed.
3. acupuncture-sr-2020: "18 RCTs" → actually 8 RCTs/504; year 2021; significant secondary THI
   omitted entirely (conservative-direction but incomplete).
4. tavns-sr-2023: "narrative synthesis only" is false — a 4-study meta-analysis exists with a
   pooled positive disability effect of low clinical relevance.
5. (borderline) physio-2022-somatic: hides that PT was ADDED to photobiomodulation (N=40 RCT);
   "43% vs 12%" TMJ claim lives in the treatment record citing Tullberg 2006 but the study record
   is under-specified.
Plus citation-hygiene errors: phantom author "Cabrera A" (Cochrane CBT); wrong authors on
guillard-2023 (actually Jensen et al.) and acupuncture-umbrella (actually Xu et al.); wrong
initials on kasper-2026; QUIET-1 year 2018→2019; ~12 blank-but-knowable DOIs/PMIDs; Neosensory
−17.9/−7.5 numbers unverifiable in accessible text.

## Critical/Important coverage misses (still unadded per audit rules)
CRITICAL: DFCRS 4-arm double-blind sound-therapy RCT, N=440, eClinicalMedicine 2025 (ChiCTR-registered
— invisible to CTgov-only engine); could change the sound-therapy rating.
IMPORTANT: Cima 2012 Lancet stepped-care CBT (N=492, largest CBT trial, absent behind #1);
AAO-HNS 2014 guideline, NICE NG155, EU multidisciplinary guideline (zero guideline documents in DB);
amplification-specific hearing-aid evidence records (HA #6 is supported only by UNITI+Sereda);
sigmoid sinus wall reconstruction (whole surgical alternative to stenting absent).
MODERATE (headliners): Folmer 2015 + Landgrebe 2017 rTMS landmarks; Cochrane antidepressants;
gabapentin RCT/Cochrane anticonvulsants; neramexane record; Michiels cervical physio RCT; FX-322
failure as a study record; MindEar RCT; Cilcare CIL001 program.

## Structural findings
- **Replication semantics**: blind audit requires lenire limited→none, shore limited→none (same
  lab/sponsor ≠ replication), rtms strong→limited (replication *attempted and discordant*),
  act moderate→limited. Definition must be published.
- **COI does not propagate to ratings/rankings** — the single biggest conceptual exposure;
  Lenire #2 rests entirely on sponsor-controlled evidence and moves −8 under COI weighting.
- **Ranking uncertainty uncommunicated**: only digital-CBT and CBT-I are robust across reasonable
  weightings; CBT is #1 in 5/6 schemes; venous-stenting's Top-10 exclusion rationale undocumented.
- **Retraction/correction resilience effectively MISSING**: detection requires 'tinnitus' in the
  notice title within one 7-day window; nothing back-links to cited records; a retracted
  foundational study would persist until manual audit.
- **Weekly-engine blind spots**: company wires, FDA databases (would have missed Lenire's own
  De Novo), non-US registries (ChiCTR/ISRCTN/EU-CTR), secondary-outcome trials under other
  conditions, guideline bodies, preprints/university channels.
- Safety: shore-bimodal "strong" overstated (≈120 humans, ≤12 wks) → moderate; caveats due for
  lenire/tdcs/tavns consumer use.
- Loudness/distress core discipline verified as exemplary at record level; 7 labeling flags
  (TLQ instrument unnamed; SPI-1005 L:limited rests on PRO severity; VAS constructs).

## Scorecard
Research completeness C+ · Major-study recall B− · Weekly discovery coverage C ·
Source quality A · Study extraction accuracy B+ · Material interpretation accuracy B ·
Primary-endpoint accuracy B+ · Loudness-vs-distress accuracy A− · Negative-evidence coverage B+ ·
Replication accuracy C · COI handling C+ · Safety accuracy B · Regulatory accuracy A ·
Citation integrity B− · Evidence-rating defensibility B · Ranking robustness C ·
AI evaluator reliability B+ (provisional — proxy only; production model unbenchmarked) ·
Retraction/correction resilience D.

## Verdict: MODERATE CONFIDENCE
Launch in CURRENT state: NO (blockers below — est. ~1–2 days of work).
Suitable as public evidence-navigation resource (after blockers): YES.
Substitute for professional medical advice: NO — never.

REQUIRED BEFORE PUBLIC LAUNCH:
1. Correct the Oto primary-endpoint misstatement (verify against the paper itself).
2. Fix the other 3 material extraction errors + author/year/count citation errors; fill knowable IDs.
3. Ingest & evaluate the DFCRS N=440 RCT through the held/review process; re-review the
   sound-therapy rating.
4. Apply replication corrections (lenire/shore→none, rtms/act→limited) + publish the replication
   definition; shore safety→moderate.
5. Ranking-uncertainty communication (banner + stability notes + venous-stenting exclusion
   rationale + Lenire availability-driven-position note); surface COI flags on lenire/shore/digital-cbt.
6. Add the 3 guidelines + Cima 2012 + amplification-specific HA evidence records.
7. Minimal retraction back-check: monthly re-query of all cited PMIDs/DOIs for
   Retracted/EoC/Erratum publication types.
8. Run the real AI-evaluator benchmark (the 8 gold cases) once ANTHROPIC_API_KEY exists, BEFORE
   the first auto-published evaluated batch.

OPTIONAL / POST-LAUNCH: engine coverage upgrades (business wires, FDA De Novo/510(k) polling,
WHO ICTRP/ChiCTR, CTgov conditions Meniere/SSNHL/hyperacusis, guideline feeds, preprints);
moderate-tier study additions (Folmer, Landgrebe, neramexane, Cochrane antidepressants/
anticonvulsants, Michiels, FX-322 record, MindEar, melatonin, Okamoto/Stein, Davis 2007);
SSWR treatment entry + Cilcare trial; COI as a 7th Evidence Profile dimension; score-staleness
trigger; publish ranking weighting rubric; CTgov protocol-diff detection.

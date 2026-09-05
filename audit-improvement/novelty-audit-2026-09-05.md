# Novelty/precedent audit: somatic-modulation capacity as treatment-response predictor (2026-09-05)

Two independent adversarial search agents (broad precedent hunt + Shore/Lenire program deep dive); full
reproducible search logs and per-study evidence tables in the session transcript 2026-09-05 (agents
a2f03429/a4dbae86). Access routes: PubMed E-utilities, Europe PMC (incl. CITES trails + fullTextXML),
ClinicalTrials.gov API v2 (verbatim eligibility/outcomes), Crossref, OpenAlex, FDA accessdata. ~39 PubMed
queries + ~20 EPMC queries + registry pulls; ~20 full texts read. Coverage caveats: Semantic Scholar
rate-limited (no citation-graph sweep); Michiels 2017 full predictor list and TENT-A1 STM supplement
paywalled; Chinese-database taVNS literature unsearched.

## VERDICT
- Classification: **C — partially tested / closely related work exists** (the SIMPLE binary form — presence
  of baseline modulation predicts response — has been directly tested at least 3 times and NOT supported,
  i.e., pattern B for that form).
- Novelty confidence for the hypothesis as originally written: **LOW**.
- Disposition: **MODIFY** (wording below).

## Decisive precedents
AGAINST novelty / against the simple form:
- van der Wal 2020 (PMID 33041758, N=101, orofacial treatment): stated our hypothesis verbatim as their
  prior ("we expect patients with a stronger somatic influence... to have a larger treatment effect"),
  tested modulation items as prognostic indicators → "ability to modulate tinnitus was not identified as a
  prognostic indicator." Predictors instead: shorter duration, TQ somatic subscale, painful TMJ palpation,
  female, younger, lower pressure-pain thresholds.
- Spencer 2022 (PMID 36090280, N=29, bimodal auditory+TENS, Marks-protocol): baseline modulation ability
  tested as predictor → null ("no apparent predictors of outcome"); 6 modulators — underpowered.
- Lee 2020 (PMID 32784160, N=81 retrospective): modulation unrelated to improvement; only age predicted.
- Low 2017 (PMID 28736590, N=27 electroacupuncture): no somatic vs non-somatic outcome difference
  (positive refined signal: CONSISTENT maneuver responders improved more, 62.5% vs 22.0%, post-hoc).
- Vanneste 2010 (PMID 20505927, N=240 C2 TENS, all selected modulators): only 17.9% responded — modulator
  status alone guarantees nothing.
- Prevalence 56–80% across series (Levine 2007; Sanchez 2002 65.3%; Won 2013 57.1%; Theodoroff 2022 56%)
  → binary capacity discriminates poorly, consistent with the null results.
FOR the refined/graded form:
- Shore/Jones 2023 (PMID 37266943) eFigure 7: TFI improvement correlated with NUMBER of effective maneuvers
  during active bisensory treatment only (r_ITT=0.292 p=.011; r_PP=0.33 p=.010) — post-hoc, correlational,
  within an all-modulator cohort (modulation was an eligibility criterion; 19/337 screenees could not
  modulate), maneuver counts partly concurrent rather than strictly baseline.
- Rocha & Sanchez 2012 (PMID 23306563, RCT N=71): DIRECTION of palpation-induced modulation (temporary
  decrease) predicted persistent relief after trigger-point therapy (p=0.002).
- Yu 2024 (PMID 38930025): history-based somatic-association score correlated with PT response (r≈0.7) —
  related construct, not maneuver capacity.
Proposals predating ours: Levine 2007 (PMID 17956783, somatic testing "to identify subgroups... who may
respond to a particular treatment modality"); Won 2013 (PMID 23881235, modulation characteristics "to
select optimal candidates for somatosensory-based tinnitus therapies").

## The Lenire finding (notable)
TENT-A1 (protocol PMID 29074518) measured baseline modulation in ALL 326 participants (25-maneuver
physiotherapist battery; Table 1: somatic tinnitus ≥1 maneuver = 56.8%; a graded "degree of somatic
modulation" variable exists in the dataset) and PRESPECIFIED an efficacy analysis "by presence of a somatic
tinnitus," deferred to "a subsequent publication" — which, through Sept 2026, has never appeared. TENT-A2
carried forward hyperacusis/severity subgroups instead; TENT-A3 collected no somatic data. The prespecified
somatic analysis of the largest bimodal dataset is unpublished; the data exist inside Neuromod.

## Audit-question answers (Q1–Q10)
Q1 prospectively tested: YES (Low 2017; van der Wal 2020; Spencer 2022) — all null for the binary form;
none adequately powered for bimodal devices. Q2 retrospectively: YES (Lee 2020 null; Shore eFig7 positive
post-hoc). Q3 separate modulator/non-modulator outcomes: YES ×3 (Low, Spencer, Lee) — no difference.
Q4 proposed without testing: YES since 2007 (quotes above). Q5 Shore analyzed capacity→response: YES,
post-hoc dose–response among modulators; nothing prespecified; no responder stratification. Q6 Lenire:
collected the data (A1/A2), prespecified the subgroup (A1), never published it; response moderator actually
reported = baseline THI severity. Q7 cervical/TMJ predictors: co-varying neck-tinnitus complaints,
low-pitch/posture influence (Michiels 2017), duration/TQ-somatic/TMJ-palpation-pain/sex/age/PPT (van der
Wal), fluctuating tinnitus (Tullberg), HCFA history score (Yu) — self-reported somatic INFLUENCE beats
maneuver capacity. Q8 conflation: pervasive (Ward 2015 defines diagnosis AS capacity; Shore trials
operationalize diagnosis BY capacity; Delphi 2018 warns modulation is not specific). Q9 prevalence 56–80% →
poor binary discrimination. Q10 direct contradiction: yes — the three null direct tests + Vanneste 17.9%.

## Corrections to our own prior statements (2026-09-05 analysis)
- WRONG: "the field has inexplicably never run it." It has been run (small/post-hoc/underpowered) at least
  three times, with null results for the binary form.
- "No bimodal device trial has stratified treatment response by baseline somatic-modulation capacity":
  DEFENSIBLE ONLY WITH CAVEATS; replaced by: "No bimodal device trial has PUBLISHED a prespecified
  stratification of treatment response by baseline somatic-modulation capacity. The nearest analyses are a
  post-hoc within-modulator correlation in the Michigan trial (positive), an underpowered post-hoc predictor
  test in an independent feasibility study (null), and a prespecified somatic-subtype analysis in TENT-A1
  whose results were never published."
- Lenire De Novo = DEN210033 (database already correct; DEN230081 = Apple hearing-aid feature).

## MODIFIED HYPOTHESIS (replacing the original)
"In interventions engaging auditory–somatosensory integration, GRADED features of baseline somatic
modulation — the number of effective maneuvers, the direction of induced change, and its test–retest
consistency — may predict treatment response, whereas the mere presence of any modulation (56–80% of
patients) likely does not, having failed as a binary predictor in three small studies. This refined form is
supported only by post-hoc signals (Shore 2023 eFigure 7; Rocha & Sanchez 2012) and remains without an
adequately powered, prespecified test. The definitive experiment is unchanged: a bimodal-stimulation trial
enrolling across the full modulation range with a standardized baseline maneuver battery, a prespecified
capacity × treatment interaction, and a percept-level co-primary endpoint. The cheapest first step is no
longer a new trial: it is the publication (or independent reanalysis) of TENT-A1's prespecified but
unreported somatic-subtype analysis, for which graded baseline data on 326 participants already exist."

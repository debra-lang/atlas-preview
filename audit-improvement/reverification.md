# Phase 17 — Independent citation/extraction re-verification (2026-09-04)

An independent adversarial agent verified all 67 study records against real sources (PubMed efetch/esummary,
Europe PMC, Crossref, Semantic Scholar, ClinicalTrials.gov API v2): identifier resolution, authors, journal/year,
N, and every headline number reachable in an abstract or registry.

## Measured result (BEFORE the post-verification fixes below)
- Fully CLEAN: 35 · MINOR only: 27 · ERROR: 2 · NOT-CHECKABLE (company/registry-only, no identifier possible): 3
- **Citation integrity: 62/64 checkable = 96.9%** (baseline: 73%)
- Every previously corrected headline number matched its source verbatim — including the Oto correction
  ("mean decrease = 9 points, p = .006, 95% CI [2, 16]" verbatim in the abstract), MOST/DFCRS (−4.37 [−6.25, −2.48]),
  Cima 2012, Folmer/Landgrebe, and the TACTT registry numbers.

## The 2 remaining errors found (both fixed same day, with history entries)
E1. atipas-2021-notched — first author miscredited: the paper is Therdphaothai J et al. (Atipas S is 2nd author).
    Fixed: full author list; also added the abstract's follow-up-period nuance.
E2. lllt-meta-2020 — the summary attributed a futility conclusion to trial sequential analysis that the abstract
    does not contain; the authors actually conclude the value of LLLT "remains unclear" and call for larger studies.
    Fixed: TSA claim removed, replaced with the authors' actual conclusion + exact MD −2.85 [−8.99, 3.28] p=0.362;
    PMID/DOI/authors filled. (This error survived an earlier "soften the claim" fix that should have removed it.)

## Minor issues (all fixed same day)
~20 fillable PMIDs/DOIs added (uniti, beukes, tent-a1/a3, shore, marks-2018, ci-meta, rtms-meta, tyler, three
Cochranes, kyorin, physio, mazurek, lenire-realworld, tavns, acupuncture-umbrella, stenting-pooled, guillard/Jensen);
9 blank author fields filled; uniti author-order styling corrected; ci-meta spurious "et al." removed; tdcs
loudness nuance corrected (overall pooled effect significant SMD −0.35, LTA is the subgroup localization);
Jensen/Guillard slug-confusion note added.

After fixes, the only records without identifiers are the four for which none exist:
tactt-trials (registry-results record), stopmd3-2024, fx322-2023, cilcare-cil001 (company-reported programs,
labeled as such).

Full per-record verdict table: session transcript 2026-09-04 (agent report).

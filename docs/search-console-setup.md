# Search engine setup runbook (post-launch)

Prerequisites (in order): (1) production AI benchmark gate passed; (2) SEO gate passed (tools/check_seo.py);
(3) TinnitusEvidence.com connected to GitHub Pages with HTTPS enforced; (4) robots.txt block removed
(deploy robots-production.txt as robots.txt) — the FINAL indexing action.

## Google Search Console
1. Add property → **Domain** property `tinnitusevidence.com` (covers www/non-www, http/https). Verify via the
   DNS TXT record your registrar UI provides. (Do not add verification meta tags to the site until the method
   is chosen — DNS verification needs none.)
2. Submit the sitemap: `https://tinnitusevidence.com/sitemap.xml` (145 URLs).
3. URL-inspect `https://tinnitusevidence.com/` — confirm "URL can be indexed".
4. Inspect `https://tinnitusevidence.com/treatments/`.
5. Inspect several major treatment pages (lenire, cbt, rtms, hearing-aids, shore-bimodal).
6. Request indexing only for the homepage, /treatments/, and a handful of key pages — the sitemap handles the rest.
7. Over the following weeks: Page Indexing report (watch for "Duplicate without user-selected canonical" —
   should not appear given self-canonicals), then Core Web Vitals, then Performance (queries/impressions).
8. Do NOT make major SEO changes based on only a few days of data.

## Bing Webmaster Tools (optional)
Bing accepts the same sitemap.xml (standard protocol — no changes needed). Easiest path: "Import from Google
Search Console" after GSC is verified. No extra tracking software is needed or wanted.

## Ongoing
- `site:tinnitusevidence.com` is a quick sanity check, not an index audit — Search Console is authoritative.
- The weekly workflow regenerates the static pages and runs tools/check_seo.py; a red run means a data update
  would have broken SEO invariants and nothing was deployed.
- No analytics beyond Search Console at launch (privacy posture); revisit only with a privacy-respecting choice.

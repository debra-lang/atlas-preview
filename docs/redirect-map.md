# Redirect / canonical map (prepared 2026-09-04)

Preferred host: **https://tinnitusevidence.com** (non-www). At DNS setup: configure `www.tinnitusevidence.com` -> 301 -> `tinnitusevidence.com`,
HTTP -> HTTPS (GitHub Pages custom-domain HTTPS enforcement), one hostname only.

| Old URL | New canonical | Mechanism |
|---|---|---|
| https://debra-lang.github.io/atlas-preview/* | https://tinnitusevidence.com/* | GitHub Pages serves one site; after custom domain is set, github.io URLs 301 to the domain automatically |
| /treatment.html?id=&lt;id&gt; | /treatments/&lt;id&gt;/ | JS-injected rel=canonical (app.js) + internal links point to clean URLs |
| /treatments.html | /treatments/ | rel=canonical (interactive browser remains linked as a tool) |
| /trials.html | /trials/ | rel=canonical |
| /index.html | / | rel=canonical |
| trailing-slash variants /x/ vs /x/index.html | /x/ | rel=canonical on every generated page |
| Tinnitus Atlas-era URLs | none existed publicly (repo was always atlas-preview; only the github.io preview circulated) | covered by the github.io redirect row |

No redirect chains: every mapping is one hop. Never redirect unrelated missing pages to the homepage (404.html serves real 404s).

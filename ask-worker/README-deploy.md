# Deploying the Ask Tinnitus Evidence worker (one-time, ~5 minutes)

The Ask feature is a Cloudflare Worker: the API key lives in a Worker secret (never in browser
JS), the worker only READS the site's published data (no write path exists), and the page ships
disabled until the endpoint is configured AND the quality benchmark has passed.

## Steps (Cloudflare dashboard)
1. dash.cloudflare.com → Workers & Pages → Create → Worker. Name it `ask-tinnitusevidence`. Deploy the hello-world.
2. Open the worker → Edit code → replace ALL code with the contents of `ask-worker/worker.js` from this repo → Deploy.
3. Worker → Settings → Variables and Secrets → Add → type **Secret**, name `ANTHROPIC_API_KEY`, value = your Anthropic key → Save.
4. Copy the worker URL (looks like `https://ask-tinnitusevidence.<your-subdomain>.workers.dev`).
5. Tell Claude the URL (or edit `ask-config.js` at the repo/site root yourself:
   `window.ASK_ENDPOINT = "https://ask-tinnitusevidence.<your-subdomain>.workers.dev";` and push).

That's it. The /ask/ page detects the endpoint and goes live; with an empty endpoint it shows a
graceful "temporarily unavailable" message with search links.

## Safeguards baked into the worker
- Question length ≤ 350 chars · answer ≤ 1400 tokens · retrieval ≤ 12 records · 45 s model timeout
- Per-IP best-effort rate limit (10 questions / 10 min per isolate) + Anthropic account spend limits apply
- CORS restricted to tinnitusevidence.com / www / github.io preview
- Retrieval-first: "not covered" and crisis-safety answers never call the model at all
- Mechanical citation validation: tokens not present in the retrieved pack are stripped, so the
  page can never show a citation that isn't a real database record
- Read-only by construction: the worker only GETs public JSON; it has no credentials for the repo
  and no code path that writes anything

## Quality gate (must pass BEFORE enabling the endpoint)
GitHub → Actions → "Ask Tinnitus Evidence benchmark (quality gate)" → Run workflow.
It runs the 15-question test set through the exact shipping pipeline against the production model
and commits `ask-worker/benchmark-report.json`. Enable the endpoint only on a green run.

## Cost expectations
claude-sonnet-5, ~6–10k input + ≤1.4k output tokens per question ≈ **$0.02–0.05 per question**.
Set a monthly spend limit in the Anthropic console as the final backstop.

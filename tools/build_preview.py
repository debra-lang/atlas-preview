#!/usr/bin/env python3
"""Build preview.html — the whole site as ONE self-contained file.

Inlines styles + app.js, embeds the entire data/ database, and packages every page's
<main> as a <template> driven by app.js's hash router (window.__TA_SINGLE__ mode).
Used for hosted previews (e.g., publishing as a Claude artifact). Excludes admin.html.

Usage: python tools/build_preview.py   → writes preview.html at the repo root.
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["index", "treatments", "treatment", "compare", "trials", "research",
         "institutions", "watchlist", "about", "search", "profile"]

def esc_json(s: str) -> str:
    # inside a JSON string literal, <\/ is a legal escape for </ — blocks </script> injection
    return s.replace("</", "<\\/")

def esc_js(s: str) -> str:
    # JS source: only the literal </script sequence is dangerous; a blanket </ replace
    # would corrupt regexes like /</g
    return re.sub(r"</script", "<\\/script", s, flags=re.I)

def main():
    meta = json.loads((ROOT / "data" / "meta.json").read_text(encoding="utf-8"))
    css = (ROOT / "css" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "js" / "app.js").read_text(encoding="utf-8")

    data = {}
    for name in ["meta", "categories", "treatments", "studies", "trials",
                 "institutions", "rankings"]:
        data[name] = json.loads((ROOT / "data" / f"{name}.json").read_text(encoding="utf-8"))
    data["weeklyIndex"] = json.loads((ROOT / "data" / "weekly" / "index.json").read_text(encoding="utf-8"))
    data["weeklyAll"] = {}
    for rep in data["weeklyIndex"]["reports"]:
        data["weeklyAll"][rep["file"]] = json.loads(
            (ROOT / "data" / "weekly" / rep["file"]).read_text(encoding="utf-8"))
    data["weekly"] = data["weeklyAll"][data["weeklyIndex"]["reports"][0]["file"]] if data["weeklyIndex"]["reports"] else None

    templates = []
    for page in PAGES:
        html = (ROOT / f"{page}.html").read_text(encoding="utf-8")
        m = re.search(r"<main[^>]*>[\s\S]*?</main>", html)
        if not m:
            raise SystemExit(f"No <main> found in {page}.html")
        templates.append(f'<template id="page-{page}">{m.group(0)}</template>')

    out = f"""<meta charset="utf-8">
<meta name="robots" content="noindex">
<title>{meta['name']}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
{css}
</style>
<div id="app"></div>
{''.join(templates)}
<script>
window.__TA_SINGLE__ = true;
window.__TA_DATA__ = {esc_json(json.dumps(data, ensure_ascii=False, separators=(',', ':')))};
</script>
<script>
{esc_js(js)}
</script>
"""
    dest = ROOT / "preview.html"
    dest.write_text(out, encoding="utf-8")
    print(f"Wrote {dest} ({dest.stat().st_size / 1024:.0f} KB) — "
          f"{len(PAGES)} pages, {len(data['treatments'])} treatments embedded.")

if __name__ == "__main__":
    main()

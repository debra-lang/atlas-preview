"""Shared helpers for the offline tests (no network, no API key)."""
import json, os, subprocess, sys, tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ENGINE = TESTS.parent
REPO = ENGINE.parent
FIX = TESTS / "fixtures"
sys.path.insert(0, str(ENGINE))


def fixture(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def real_queue():
    return json.loads((REPO / "data" / "review-queue" / "queue.json").read_text(encoding="utf-8"))["items"]


def real_studies():
    s = json.loads((REPO / "data" / "studies.json").read_text(encoding="utf-8"))
    return s["studies"] if isinstance(s, dict) else s


def run_scenario(spec):
    d = Path(tempfile.mkdtemp(prefix="te-p2-spec-"))
    (d / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    p = subprocess.run([sys.executable, "-X", "utf8", str(TESTS / "run_scenario.py"), str(REPO), str(d / "spec.json"), str(d / "out.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert p.returncode == 0, (p.stdout[-1500:] + p.stderr[-2500:])
    return json.loads((d / "out.json").read_text(encoding="utf-8"))


def pubmed_item(n, title="A routine tinnitus trial", **kw):
    it = {"id": f"pubmed-{n}", "kind": "study", "title": title, "source": "PubMed", "date": "2026 Oct 13", "url": f"https://pubmed.ncbi.nlm.nih.gov/{n}/",
          "summary": "New PubMed item - needs evaluation (design, N, outcomes, COI, loudness vs distress)."}
    it.update(kw)
    return it


def ctgov_item(nct, date="2026-10-13", title="A registry update", **kw):
    it = {"id": f"ctgov-{nct}-{date}", "kind": "trial", "title": title, "source": "ClinicalTrials.gov", "date": date, "url": f"https://clinicaltrials.gov/study/{nct}",
          "summary": "Registry update - needs evaluation."}
    it.update(kw)
    return it


def news_item(slug, title, **kw):
    it = {"id": f"newsintel-{slug}", "kind": "news", "title": title, "source": "Google News", "date": "2026-10-19", "intelligenceOnly": True,
          "url": f"https://news.google.com/rss/articles/{slug}",
          "summary": "Company/news-wire intelligence item. NOT evidence - publishable only as a labeled company-reported development after verification."}
    it.update(kw)
    return it

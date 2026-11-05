"""One simulated scheduled run in a throwaway copy, following .github/workflows/weekly.yml step by step, except that nothing is decrypted and nothing is pushed.
Usage: simulate_run.py <fresh production clone> <commit> <name> [plant.json]. Python 3.12, as the workflow uses."""
import json, os, shutil, subprocess, sys
from pathlib import Path

FRESH, COMMIT, NAME = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
PLANT = sys.argv[4:] and [str(Path(sys.argv[4]).resolve())] or []
HERE = Path(__file__).resolve().parent
COPY, CACHE, LOG, TMP = HERE / "sim" / NAME, HERE / "sim" / "cache", HERE / "logs" / f"sim-{NAME}.txt", HERE / "tmp"
if COPY.exists():
    sys.exit(f"{COPY} already exists")
TMP.mkdir(exist_ok=True); LOG.parent.mkdir(exist_ok=True); COPY.parent.mkdir(exist_ok=True)
env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("ANTHROPIC", "API_KEY", "STATE_KEY", "TOKEN", "SECRET", "YOUTUBE", "GH_", "GITHUB"))}
env.update({"TEMP": str(TMP), "TMP": str(TMP), "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "GIT_TERMINAL_PROMPT": "0"})
log = open(LOG, "w", encoding="utf-8")


def say(t):
    print(t, flush=True); log.write(t + "\n"); log.flush()


def run(*a, check=True, cwd=COPY):
    p = subprocess.run(a, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    log.write(f"$ {' '.join(map(str, a))}\n{p.stdout}{p.stderr}\n[exit {p.returncode}]\n"); log.flush()
    if check and p.returncode:
        raise SystemExit(f"step failed: {a[:4]} -> {p.returncode}\n{(p.stdout + p.stderr)[-800:]}")
    return p


run("git", "clone", "-q", "--config", "remote.origin.pushurl=no-push://disabled", str(FRESH), str(COPY), cwd=HERE)
run("git", "checkout", "-q", "--detach", COMMIT)
head = run("git", "rev-parse", "HEAD", "HEAD^{tree}").stdout.split()
say(f"{NAME}: running from commit {head[0]}, tree {head[1]}")
enc_before = run("git", "rev-parse", "HEAD:data/review-queue/held.json.enc").stdout.strip()
# "Restore private held-state": not decrypted here. The real store stays as it is and the cycle starts from an empty stand-in
(COPY / "data/review-queue/held.json").write_text('{"items": []}\n', encoding="utf-8")
# "Run weekly cycle"
p = run(sys.executable, "-X", "utf8", str(HERE / "sealed_cycle.py"), str(COPY), str(CACHE), str(HERE / "logs" / f"sim-{NAME}-net.txt"), *PLANT, check=False)
say("cycle exit " + str(p.returncode) + "; " + next((l for l in p.stdout.splitlines() if l.startswith("SEALED")), "no seal line"))
say("cycle: " + ("CYCLE OK" if "CYCLE OK" in p.stdout else "NOT OK: " + (p.stdout + p.stderr)[-500:]))
for l in p.stdout.splitlines():
    if l.startswith("sources:") or "blocked:" in l:
        say(l[:1500])
# "Protect private held-state": the stand-in goes, the real store is untouched
(COPY / "data/review-queue/held.json").unlink(missing_ok=True)
(COPY / "data/review-queue/staged.json").unlink(missing_ok=True)
# "Regenerate SEO static pages + regression checks"
a = run(sys.executable, "-X", "utf8", "tools/build_seo.py", check=False)
b = run(sys.executable, "-X", "utf8", "tools/check_seo.py", check=False)
say(f"build_seo exit {a.returncode}; check_seo exit {b.returncode}: " + (b.stdout.strip().splitlines() or ["?"])[-1][:150])
# "Commit results": the same paths and identity, dated inside the 15 November window so the verifier sees a realistic history; never pushed
run("git", "config", "user.name", "tinnitus-evidence-bot")
run("git", "config", "user.email", "actions@users.noreply.github.com")
run("git", "add", "-A", "data", "engine", "treatments", "trials", "research", "guides", "ask", "research-questions", "sitemap.xml", "index.html", "about.html")
quiet = run("git", "diff", "--cached", "--quiet", check=False).returncode == 0
if quiet:
    say("no changes to commit (quiet cycle)")
else:
    env.update({"GIT_COMMITTER_DATE": "2026-11-15T14:20:00Z", "GIT_AUTHOR_DATE": "2026-11-15T14:20:00Z"})
    run("git", "commit", "-q", "-m", "Automated weekly research update")
tip = run("git", "rev-parse", "HEAD").stdout.strip()
say(f"simulated new main {tip}; quiet={quiet}")
# "Fail loudly if the AI evaluation did not work"
c = run(sys.executable, "-X", "utf8", "engine/check_evaluation_health.py", check=False)
say(f"check_evaluation_health exit {c.returncode}: " + ((c.stdout + c.stderr).strip().splitlines() or [""])[-1][:200])
say("held.json.enc unchanged: " + str(run("git", "rev-parse", "HEAD:data/review-queue/held.json.enc").stdout.strip() == enc_before))
status = json.loads((COPY / "data/engine-status.json").read_text(encoding="utf-8"))
say("evaluation state: " + str((status.get("evaluation") or {}).get("state")) + "; listings: " + json.dumps(status.get("listings")) + "; errors: " + json.dumps(status.get("errors"))[:600])
changed = run("git", "diff", "--name-status", COMMIT, "HEAD").stdout
say(f"files changed by the run: {len(changed.splitlines())}")
(HERE / "logs" / f"sim-{NAME}-files.txt").write_text(changed, encoding="utf-8")

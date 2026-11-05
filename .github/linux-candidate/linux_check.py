"""Checks one release candidate on Linux: the exact candidate tree, the full test suite, the rating and ranking locks through the real tools, failure detection, and whole research cycles with live public sources.
Everything happens in throwaway copies on this machine. Nothing is decrypted: the private store is left alone and an empty stand-in is used. There is no credential to push with, no AI key, and every cycle is sealed (sealed_cycle.py). The log gives counts and results, and names no record.
Usage on GitHub: linux_check.py. Usage for a local rehearsal: linux_check.py --local <repo> <1|2> <work folder>"""
import json, os, shutil, stat, subprocess, sys
from datetime import date, datetime, timezone
from pathlib import Path

CANDIDATES = {"1": ("f29f97f7d92d6b4be4b1322b6286141f9412e7d1", "6259530265f5d91069ce1a66a48602f66afa1f58", 665),
              "2": ("34983b6dd2abcd2e262720a5f8826cd80de40193", "b872a9b954b1fb504c95f9d7071dc6f0f8d69608", 849)}
BASE = "af6e1b537b91ee13d37f3ad1b225fee0c3a7115d"
HOLD = "lenire-neuromod"
GROUPS = {"hold protections": {"1": ["test_hold_cycle", "test_hold_text", "test_listing_hold", "test_listing_paused", "test_trial_status_hold"],
                               "2": ["test_hold_marks", "test_listing_atomic", "test_trial_status_on_hold", "test_routing_order"]},
          "rating and ranking locks": {"1": ["test_run_reliability", "test_phase2_regressions", "test_disclosure_pages"], "2": []},
          "failure detection": {"1": ["test_failure_handling", "test_evaluation_failures", "test_run_reliability"], "2": ["test_fail_closed", "test_wrong_key"]}}
HERE = Path(__file__).resolve().parent
LOCAL = sys.argv[1:2] == ["--local"]
if LOCAL:
    REPO, RELEASE, WORK = Path(sys.argv[2]).resolve(), sys.argv[3], Path(sys.argv[4]).resolve()
else:
    REPO, RELEASE, WORK = Path(os.environ["GITHUB_WORKSPACE"]), os.environ["GITHUB_REF_NAME"].rsplit("-", 1)[1], Path(os.environ["RUNNER_TEMP"]) / "lc"
SHA, TREE, MIN_TESTS = CANDIDATES[RELEASE]
R2 = RELEASE == "2"
if WORK.exists():
    sys.exit(f"{WORK} exists")
BOX = WORK / "h"
BOX.mkdir(parents=True)
for f in ("simulate_run.py", "sealed_cycle.py"):
    shutil.copy(HERE / f, BOX / f)
SECRETS = ("STATE_KEY", "ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "GITHUB_TOKEN", "GH_TOKEN")
ENV = {k: v for k, v in os.environ.items() if k not in SECRETS and k != "TMPDIR"}
ENV.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "GIT_TERMINAL_PROMPT": "0", "TEMP": str(WORK / "tmp"), "TMP": str(WORK / "tmp")})
(WORK / "tmp").mkdir()
PY = sys.executable
bad, good = [], 0


def check(ok, text):
    global good
    good += bool(ok)
    if not ok:
        bad.append(text)
    print(("PASS  " if ok else "FAIL  ") + text, flush=True)


def git(*a, cwd=REPO, ok=True):
    p = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
    if ok and p.returncode:
        sys.exit(f"git {a[:3]} failed: {p.stderr[-300:]}")
    return p.stdout.strip() if ok else p


def run(*a, cwd):
    return subprocess.run([PY, "-X", "utf8", *map(str, a)], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)


class Sim:
    """One simulated scheduled run, following the workflow's steps, sealed. Files are read only when asked for: a stopped run may leave a damaged one."""

    def __init__(self, name, fresh, commit, plant=None):
        args = [BOX / "simulate_run.py", fresh, commit, name] + ([plant] if plant else [])
        p = run(*args, cwd=BOX)
        self.text = p.stdout
        for line in p.stdout.splitlines():
            print("      " + line[:240], flush=True)
        if p.returncode:
            print("      harness problem: " + p.stderr[-400:], flush=True)
        self.copy = BOX / "sim" / name
        seal = next((l for l in p.stdout.splitlines() if "SEALED: " in l), "SEALED: {}")
        self.seal = json.loads(seal.split("SEALED: ", 1)[1])

    def read(self, rel):
        return json.loads((self.copy / rel).read_text(encoding="utf-8"))

    def item(self, rid):
        return next(i for i in self.read("data/review-queue/queue.json")["items"] if i["id"] == rid)

    def listed(self, key):
        return any(e["key"] == key for e in self.read("data/listings.json")["items"])

    def tip(self):
        return git("rev-parse", "HEAD", cwd=self.copy)

    @property
    def completed(self):
        return "CYCLE OK" in self.text

    @property
    def stopped_untouched(self):
        return "CYCLE STOPPED" in self.text and self.seal.get("replayed", 1) == 0 and self.seal.get("fetched", 1) == 0

    def sound(self):
        return self.completed and self.seal.get("blocked") == 0 and "check_seo exit 0" in self.text and "held.json.enc unchanged: True" in self.text and "evaluation state: disabled" in self.text


def seeded(name, fresh, commit, files):
    """A throwaway commit holding these files, for one case to run from."""
    seed = WORK / "seeds" / name
    seed.parent.mkdir(exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--config", "remote.origin.pushurl=no-push://disabled", str(fresh), str(seed)], check=True, env=ENV)
    git("checkout", "-q", "--detach", commit, cwd=seed)
    for rel, text in files.items():
        (seed / rel).write_text(text, encoding="utf-8")
        git("add", rel, cwd=seed)
    git("-c", "user.name=linux-check", "-c", "user.email=linux-check@users.noreply.github.com", "commit", "-q", "-m", "test case, in a throwaway copy", cwd=seed)
    return seed, git("rev-parse", "HEAD", cwd=seed)


print(f"=== Release {RELEASE}: which code this is, and what it cannot do")
if not LOCAL:
    check(not any(os.environ.get(k) for k in SECRETS), "no key or token is available to this check")
    check(git("rev-parse", "HEAD^") == SHA, "the test commit sits directly on the release candidate")
    extra = git("diff", "--name-only", "HEAD^", "HEAD").splitlines()
    check(all(f.startswith(".github/") or f == "vercel.json" for f in extra), f"the test commit changes only {len(extra)} test-only file(s), and no code or data")
    check(not git("config", "--get-regexp", r"^http\..*extraheader", ok=False).stdout.strip(), "the checkout kept no push credentials")
    check(git("push", "--dry-run", "origin", "HEAD:refs/heads/linux-test/probe", ok=False).returncode != 0, "a trial push is refused")
    check(sorted(p.name for p in (REPO / ".github/workflows").iterdir()) == ["linux-candidate-check.yml"], "this branch carries no other workflow, so nothing else can start from it")
cand = WORK / "cand"
git("worktree", "add", "-q", "--detach", str(cand), SHA)
check(git("rev-parse", "HEAD^{tree}", cwd=cand) == TREE, f"testing the exact candidate tree {TREE[:7]}")
check(git("merge-base", "--is-ancestor", BASE, SHA, ok=False).returncode == 0, f"built on production {BASE[:7]}")
changed = git("diff", "--name-only", BASE, SHA).splitlines()
protected = ("engine/topic_holds.json", "engine/paused_ids.json", "engine/eval_settings.json", "engine/automation_settings.json", "engine/hold_releases.json", ".github/workflows/weekly.yml", "data/review-queue/held.json.enc")
check(not [f for f in changed if f.startswith("data/") or f in protected], "the candidate changes no research data, hold, pause, AI setting or the scheduled workflow")
settings = json.loads((cand / "engine/eval_settings.json").read_text(encoding="utf-8"))
check(settings.get("enabled") is not True, "AI evaluation is off in the candidate")

print("=== the full test suite", flush=True)
results = WORK / "suite.json"
p = run(HERE / "suite_runner.py", results, cwd=cand)
suite = json.loads(results.read_text(encoding="utf-8"))
rows = suite["rows"]
print(f"      {suite['ran']} ran; {sum(r[1] == 'skipped' for r in rows)} skipped; {sum(r[1] == 'failed' for r in rows)} failed", flush=True)
for name, outcome, why in rows:
    if outcome == "failed":
        print("      failed: " + name[:160], flush=True)
if not suite["successful"]:
    print(p.stderr[-3000:], flush=True)
check(suite["successful"], "every test passes")
check(suite["ran"] >= MIN_TESTS, f"at least the {MIN_TESTS} tests counted on Windows ran")
reasons = sorted({why[:70] for _, outcome, why in rows if outcome == "skipped"})
print("      skip reasons: " + ("; ".join(reasons) or "none"), flush=True)
check(all(why.startswith("Release A is in production") or LOCAL for _, outcome, why in rows if outcome == "skipped"), "the only skips are the retired Release A checks")
for group, mods in GROUPS.items():
    wanted = mods["1"] + (mods["2"] if R2 else [])
    for mod in wanted:
        mine = [r for r in rows if r[0].startswith(mod + ".") or f"({mod}." in r[0]]
        n = sum(r[1] == "ok" for r in mine)
        check(n > 0 and not any(r[1] == "failed" for r in mine) and not any(r[1] == "skipped" for r in mine), f"{group}: {mod}, {n} passed, none skipped")

print("=== rating and ranking locks, through the real check", flush=True)
copy = WORK / "lock"
subprocess.run(["git", "clone", "-q", "--config", "remote.origin.pushurl=no-push://disabled", str(REPO), str(copy)], check=True, env=ENV)
git("checkout", "-q", "--detach", SHA, cwd=copy)


def seo():
    return run("tools/check_seo.py", cwd=copy)


r = seo()
check(r.returncode == 0 and "rating lock: checked against the last commit" in r.stdout, "with no change it passes, and says it checked")
T = copy / "data/treatments.json"
original = T.read_bytes()


def planted(label, change):
    data = json.loads(original)
    rows_ = data if isinstance(data, list) else data["treatments"]
    change(next(t for t in rows_ if t.get("loudness") and t.get("distress")))
    T.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = seo()
    check(r.returncode == 1 and "rating lock" in r.stdout, f"a changed {label} is stopped")
    T.write_bytes(original)


planted("tier", lambda t: t.__setitem__("tier", 99))
planted("evidence score", lambda t: t.__setitem__("evidenceScore", 99))
planted("loudness level", lambda t: t["loudness"].__setitem__("level", "planted"))
planted("distress level", lambda t: t["distress"].__setitem__("level", "planted"))
for rel in ("data/rankings.json", "data/claims.json"):
    f = copy / rel
    was = f.read_bytes()
    f.write_text(was.decode("utf-8").replace("1", "2", 1), encoding="utf-8")
    r = seo()
    check(r.returncode == 1 and rel in r.stdout, f"a changed {rel} is stopped")
    f.write_bytes(was)
check(seo().returncode == 0 and git("status", "--short", cwd=copy) == "", "restored, it passes and the copy is clean")

print("=== failure detection, through the real check", flush=True)
S = copy / "data/engine-status.json"
status_was = S.read_bytes()


def health(change):
    d = json.loads(status_was)
    change(d)
    S.write_text(json.dumps(d), encoding="utf-8")
    code = run("engine/check_evaluation_health.py", cwd=copy).returncode
    S.write_bytes(status_was)
    return code


check(health(lambda d: None) == 0, "a healthy status passes")
check(health(lambda d: d.__setitem__("errors", ["source 'PubMed' failed: timeout"])) != 0, "a failed source turns the run red")
check(health(lambda d: d.__setitem__("errors", ["coverage gap: news look-back exceeded"])) != 0, "a coverage gap turns the run red")
check(health(lambda d: d.__setitem__("errors", ["something nobody expected"])) != 0, "an unknown error turns the run red")
check(health(lambda d: d.__setitem__("errors", [f"trial refresh {i} failed" for i in range(5)])) != 0, "many failed trial refreshes turn the run red")
check(health(lambda d: d.__setitem__("errors", ["1 record failed source verification"])) == 0, "one record that failed verification stays a warning, for the report")
if R2:
    check(health(lambda d: d.__setitem__("listingsFailed", True)) != 0, "a failed listing step turns the run red")
    check(health(lambda d: d.__setitem__("missingSettings", ["engine/eval_settings.json"])) != 0, "a missing settings file turns the run red")

print("=== a whole cycle, live public sources", flush=True)
base = Sim("base", REPO, SHA)
check(base.sound(), "the cycle completes, nothing is blocked, the page checks pass, the private store is untouched, AI stays off")
check(base.seal.get("fetched", 0) > 0, f"it really read the network: {base.seal.get('fetched')} answers")
status = base.read("data/engine-status.json")
for e in status.get("errors") or []:       # an outside source failing on the day is expected, and is reported; the health check below judges whether it should turn the run red
    print("      recorded: " + str(e)[:160], flush=True)
feeds =next((s.get("feeds") for s in status.get("sources", []) if s.get("name", "").startswith("Watched feeds")), None)
if feeds is not None:
    print("      feeds with entries: " + ", ".join(f"{f.get('entries')}" + (" (error)" if f.get("error") else "") for f in feeds), flush=True)
check(bool(feeds) and any(f.get("entries") for f in feeds), "the watched feeds are read, with entries")
health_after = run("engine/check_evaluation_health.py", cwd=base.copy)
check(health_after.returncode == 0, "the health check passes on the run's results")
sys.path.insert(0, str(cand / "tools"))
sys.dont_write_bytecode = True
import rating_lock   # noqa: E402


def lock_files(read):
    return {f: json.loads(read(f)) for f in ("data/treatments.json", "data/studies.json") + rating_lock.WHOLE_FILES}


stopped = rating_lock.compare(lock_files(lambda f: git("show", f"{SHA}:{f}")), lock_files(lambda f: (base.copy / f).read_text(encoding="utf-8")))
check(not stopped, "the run changed no rating, tier, score, level, ranking or claim")

print("=== hold protection: a hidden device name in a real record", flush=True)
before = json.loads(git("show", f"{SHA}:data/listings.json"))
known = {e["key"] for e in before.get("items", [])}
fresh = [i for i in base.read("data/review-queue/queue.json")["items"] if i["id"].startswith("ctgov-") and isinstance(i.get("listed"), dict) and i["listed"].get("outcome") == "listed" and i["listed"].get("key") not in known]
check(bool(fresh), f"the live run listed a new registry record to test with ({len(fresh)} available)")
if fresh:
    rid, key = fresh[0]["id"], fresh[0]["listed"]["key"]
    plant_file = WORK / "plant.json"
    plant_file.write_text(json.dumps({key: "Device used:\nLenire"}), encoding="utf-8")
    marked = Sim("plant", REPO, SHA, plant_file)
    check(marked.seal.get("planted", 0) > 0 and marked.seal.get("blocked") == 0, "the same run with the name hidden deep in that record's complete text")
    check(marked.item(rid).get("topicHold") == HOLD, "the record is held, with the hold's mark")
    check(not marked.listed(key), "it does not reach the public listings")
    if R2:
        check(marked.read("data/engine-status.json").get("holdMarksAwaitingOwner") == 1, "the status file counts one mark awaiting the owner")
        tip = marked.tip()
        again = Sim("again", marked.copy, tip)
        check(again.completed and again.item(rid).get("topicHold") == HOLD and not again.listed(key), "with the name gone from the source, the mark stays: a source cannot clear it")

        def release(name, entry):
            seed, commit = seeded(name, marked.copy, tip, {"engine/hold_releases.json": json.dumps({"releases": [entry]})})
            return Sim(name, seed, commit, plant_file)

        today = datetime.now(timezone.utc).date().isoformat() if not LOCAL else date.today().isoformat()
        entry = {"recordId": rid, "holdId": HOLD, "decidedOn": today, "reason": "Linux check of the release route."}
        one = release("rel-good", entry)
        check(one.completed and "topicHold" not in one.item(rid) and one.listed(key), "the owner's release of that exact record and hold lets it list, after it is read again")
        st = one.read("data/engine-status.json")
        check(st.get("holdMarksCleared") == 1 and st.get("holdMarksAwaitingOwner") == 0, "the status file counts it")
        check("the owner released this record" in (one.copy / "engine/audit-log.jsonl").read_text(encoding="utf-8"), "the audit log says the owner decided")
        other = release("rel-other", {**entry, "recordId": rid + "-another"})
        check(other.completed and other.item(rid).get("topicHold") == HOLD and not other.listed(key), "a release of another record changes nothing")
        future = release("rel-future", {**entry, "decidedOn": "2099-01-01"})
        check(future.stopped_untouched, "a release dated in the future stops the run before it reads anything")
        damaged = release("rel-damaged", {"recordId": rid})
        check(damaged.stopped_untouched, "a damaged release file stops the run before it reads anything")

if R2:
    print("=== failure detection: damaged protection files stop the run", flush=True)
    for name, rel, text in (("dmg-hold", "engine/topic_holds.json", '{"holds": ['), ("dmg-pause", "engine/paused_ids.json", '{"ids": "not a list"}'), ("dmg-queue", "data/review-queue/queue.json", "not json")):
        seed, commit = seeded(name, REPO, SHA, {rel: text})
        run_ = Sim(name, seed, commit)
        check(run_.stopped_untouched, f"damaged {rel}: stops before it reads or writes anything")

print(f"=== RESULT, Release {RELEASE}, {SHA[:7]}: {good} passed, {len(bad)} failed", flush=True)
for b in bad:
    print("  FAILED: " + b, flush=True)
print("LINUX CHECK: " + ("PASS" if not bad else "FAIL"), flush=True)
sys.exit(1 if bad else 0)

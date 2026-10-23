#!/usr/bin/env python3
"""Compare the Ask worker code that is live in Cloudflare with this repository. READ-ONLY: it changes nothing and contacts nothing.

How to get the live code (no secrets are in it; the API key is a separate Worker secret): Cloudflare dashboard -> Workers & Pages -> the Ask worker -> Edit code -> select all, copy,
paste into a text file, save it (for example Downloads\\live-worker.js).

  python tools/compare_worker.py <saved-file> [--repo-file ask-worker/worker.js]

Reports (1) whether the saved code equals the repository's current worker.js (ignoring line endings and trailing spaces), (2) otherwise which earlier committed version of
worker.js it equals, if any, and (3) otherwise a unified diff against the current file and against the closest committed version, so any uncommitted edit is visible
before the repository's version is pasted over it. Exit code: 0 identical to the current repository version, 2 equals an older committed version, 3 matches no committed version.
"""
import argparse, difflib, hashlib, subprocess, sys
from pathlib import Path


def norm(text):
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").strip("\n").split("\n")) + "\n"


def sha(text):
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()


def git(root, *args):
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout if p.returncode == 0 else ""


def history(root, rel):
    """[(commit, date, subject, text)] of every committed version of the file, newest first."""
    out = []
    for line in git(root, "log", "--format=%H|%ad|%s", "--date=short", "--", rel).splitlines():
        h, d, subj = line.split("|", 2)
        text = git(root, "show", f"{h}:{rel}")
        if text:
            out.append((h, d, subj, text))
    return out


def compare(saved_text, root, rel):
    """Returns (code, message, diff_lines)."""
    current = (Path(root) / rel).read_text(encoding="utf-8")
    if norm(saved_text) == norm(current):
        return 0, "IDENTICAL: the live code equals the repository's current worker.js. Nothing would be lost by pasting the repository version.", []
    hist = history(root, rel)
    for h, d, subj, text in hist:
        if norm(text) == norm(saved_text):
            return 2, f"The live code equals an OLDER committed version: {h[:7]} ({d}) {subj[:80]}. It has no uncommitted edits; it is simply behind the repository.", \
                list(difflib.unified_diff(norm(saved_text).splitlines(), norm(current).splitlines(), "live", "repository-current", lineterm="", n=2))
    best = max(hist, key=lambda x: difflib.SequenceMatcher(None, norm(x[3]), norm(saved_text)).quick_ratio(), default=None)
    msg = "NO COMMITTED VERSION MATCHES the live code: it contains edits that were never committed. Do not paste the repository version until they are reviewed or saved."
    base = norm(best[3]) if best else norm(current)
    if best:
        msg += f" Closest committed version: {best[0][:7]} ({best[1]}) {best[2][:80]}."
    return 3, msg, list(difflib.unified_diff(base.splitlines(), norm(saved_text).splitlines(), "closest-committed", "live", lineterm="", n=2))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("saved")
    ap.add_argument("--repo-file", default="ask-worker/worker.js")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    a = ap.parse_args(argv)
    saved = Path(a.saved).read_text(encoding="utf-8-sig", errors="replace")
    if "export default" not in saved and "addEventListener" not in saved:
        print("The saved file does not look like a Cloudflare Worker (no 'export default' and no 'addEventListener'). Check that the whole code was copied.")
        return 4
    code, msg, diff = compare(saved, a.root, a.repo_file)
    print(msg)
    if diff:
        print(f"\n--- {len(diff)} diff line(s), first 80 shown ---")
        print("\n".join(diff[:80]))
    return code


if __name__ == "__main__":
    sys.exit(main())

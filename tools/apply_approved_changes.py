"""Apply the owner-approved held-review record changes (engine/approved-record-changes.json) to data/treatments.json, data/studies.json and
data/rankings.json — exactly those edits, nothing else. Idempotent check: refuses to run if the data does not match the approved 'from' values.
Usage: python tools/apply_approved_changes.py [--check]   (--check: verify the files already contain exactly the approved changes)"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import approved_changes as ac

FILES = ("data/treatments.json", "data/studies.json", "data/rankings.json")
cur = [json.loads((ROOT / f).read_text(encoding="utf-8")) for f in FILES]
if "--check" in sys.argv:
    ac.revert(*cur)          # raises if any approved change is missing or altered
    print("ok: the approved changes are present exactly as approved")
    sys.exit(0)
new = ac.apply(*cur)
for f, obj in zip(FILES, new):
    (ROOT / f).write_text(ac.dump(obj), encoding="utf-8", newline="")
print("applied:", ", ".join(c["id"] for c in ac.load()["treatments"]), "+", len(ac.load()["studiesAdded"]), "study records + rankings wording")

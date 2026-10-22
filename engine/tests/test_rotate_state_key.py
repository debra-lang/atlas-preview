"""Rehearsal tests for engine/rotate_state_key.py with FAKE keys in a temp copy of the layout. Needs OpenSSL (skipped without it). No network, no real secret."""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import rotate_state_key as rk  # noqa: E402

OLD, NEW = "OLD-fake-passphrase-for-tests-1234567890", "NEW-Fake-Passphrase-For-Tests-0987654321"
SECRET_MARK = "UNPUBLISHED-AI-EVALUATION-TEXT-SECRET"


def enc(plain, path, iters, key):
    c = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2"] + (["-iter", iters] if iters else []) + ["-salt", "-out", str(path), "-pass", "env:K"]
    subprocess.run(c, input=plain.encode(), check=True, env={**os.environ, "K": key}, capture_output=True)


def run_cli(args, old=OLD, new=NEW):
    env = dict(os.environ); env.pop("OLD_STATE_KEY", None); env.pop("NEW_STATE_KEY", None)
    if old is not None: env["OLD_STATE_KEY"] = old
    if new is not None: env["NEW_STATE_KEY"] = new
    p = subprocess.run([sys.executable, "-X", "utf8", str(ENGINE / "rotate_state_key.py")] + args, capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


@unittest.skipUnless(shutil.which("openssl"), "openssl not available")
class RotationRehearsal(unittest.TestCase):
    def setUp(self):
        os.environ["OLD_STATE_KEY"], os.environ["NEW_STATE_KEY"] = OLD, NEW        # for the in-process decrypt() calls only; the CLI tests set their own environment
        self.base = Path(tempfile.mkdtemp(prefix="te-rotate-"))
        self.root, self.backup = self.base / "repo", self.base / "backup"
        d = self.root / "data" / "review-queue"; d.mkdir(parents=True)
        self.held = json.dumps({"items": [{"id": "h1", "note": SECRET_MARK}, {"id": "h2"}]})
        self.staged = json.dumps({"items": [{"id": "s1", "note": SECRET_MARK}]})
        enc(self.held, d / "held.json.enc", None, OLD)              # held: OpenSSL default iterations (what weekly.yml uses)
        enc(self.staged, d / "staged.json.enc", "600000", OLD)      # staged: 600,000
        self.files = {n: (d / n) for n in ("held.json.enc", "staged.json.enc")}
        self.before = {n: p.read_bytes() for n, p in self.files.items()}

    def tearDown(self):
        os.environ.pop("OLD_STATE_KEY", None); os.environ.pop("NEW_STATE_KEY", None)
        shutil.rmtree(self.base, ignore_errors=True)

    def test_plan_changes_nothing_and_proves_the_migration_would_work(self):
        rc, out = run_cli(["plan", "--backup-dir", str(self.backup), "--root", str(self.root)])
        self.assertEqual(rc, 0, out)
        self.assertIn("plan verified", out); self.assertIn("nothing was changed", out)
        self.assertEqual({n: p.read_bytes() for n, p in self.files.items()}, self.before)
        self.assertFalse(self.backup.exists())

    def test_apply_backs_up_replaces_and_both_new_files_open_only_with_the_new_key(self):
        rc, out = run_cli(["apply", "--backup-dir", str(self.backup), "--root", str(self.root)])
        self.assertEqual(rc, 0, out)
        m = json.loads((self.backup / "manifest.json").read_text(encoding="utf-8"))
        for n, p in self.files.items():
            self.assertNotEqual(p.read_bytes(), self.before[n])                                        # replaced
            self.assertEqual(Path(m["files"][n]["backup"]).read_bytes(), self.before[n])               # backup is the original, byte for byte
            self.assertFalse(rk.opens(p, rk.FILES[n], "OLD_STATE_KEY"))                                 # the old key no longer opens it (a wrong key can return garbage by chance, so check for a valid store)
            self.assertIsNotNone(rk.decrypt(p, rk.FILES[n], "NEW_STATE_KEY"))                           # the new key does
        # the exact commands weekly.yml runs (held: default iterations; staged: -iter 600000) work with the new key
        d = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-in", str(self.files["held.json.enc"]), "-pass", "env:K"], capture_output=True, env={**os.environ, "K": NEW})
        self.assertEqual(json.loads(d.stdout)["items"][0]["id"], "h1")
        d = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-in", str(self.files["staged.json.enc"]), "-pass", "env:K"], capture_output=True, env={**os.environ, "K": NEW})
        self.assertEqual(json.loads(d.stdout)["items"][0]["id"], "s1")
        rc, out = run_cli(["verify", "--manifest", str(self.backup / "manifest.json"), "--root", str(self.root)], old=None)
        self.assertEqual(rc, 0, out); self.assertIn("matches the manifest", out)

    def test_rollback_restores_the_original_files_byte_for_byte(self):
        run_cli(["apply", "--backup-dir", str(self.backup), "--root", str(self.root)])
        rc, out = run_cli(["rollback", "--backup-dir", str(self.backup), "--root", str(self.root)], new=None)
        self.assertEqual(rc, 0, out)
        self.assertEqual({n: p.read_bytes() for n, p in self.files.items()}, self.before)

    def test_a_wrong_old_key_stops_everything_before_any_write(self):
        rc, out = run_cli(["apply", "--backup-dir", str(self.backup), "--root", str(self.root)], old="not-the-old-key-at-all-0000000000")
        self.assertNotEqual(rc, 0); self.assertIn("cannot be decrypted with OLD_STATE_KEY", out)
        self.assertEqual({n: p.read_bytes() for n, p in self.files.items()}, self.before)
        self.assertFalse(self.backup.exists())

    def test_bad_inputs_are_refused(self):
        for old, new, msg in ((OLD, OLD, "identical"), (OLD, "short", "weak"), (OLD, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "weak"), (None, NEW, "set OLD_STATE_KEY")):
            rc, out = run_cli(["plan", "--backup-dir", str(self.backup), "--root", str(self.root)], old=old, new=new)
            self.assertNotEqual(rc, 0); self.assertIn(msg, out)
        rc, out = run_cli(["plan", "--backup-dir", str(self.root / "inside"), "--root", str(self.root)])
        self.assertNotEqual(rc, 0); self.assertIn("outside the repository", out)

    def test_a_store_that_decrypts_to_the_wrong_structure_is_refused(self):
        enc(json.dumps({"nope": 1}), self.files["held.json.enc"], None, OLD)
        rc, out = run_cli(["plan", "--backup-dir", str(self.backup), "--root", str(self.root)])
        self.assertNotEqual(rc, 0); self.assertIn("not a review store", out)

    def test_no_key_or_plaintext_leaks_anywhere(self):
        rc, out = run_cli(["apply", "--backup-dir", str(self.backup), "--root", str(self.root)])
        self.assertEqual(rc, 0, out)
        blob = out + (self.backup / "manifest.json").read_text(encoding="utf-8")
        for secret in (OLD, NEW, SECRET_MARK):
            self.assertNotIn(secret, blob)
        for f in list(self.base.rglob("*")):                                              # no plaintext file exists anywhere in the rehearsal tree
            if f.is_file():
                self.assertNotIn(SECRET_MARK.encode(), f.read_bytes(), str(f))

    def test_nothing_to_migrate_is_fine(self):
        for p in self.files.values():
            p.unlink()
        rc, out = run_cli(["plan", "--backup-dir", str(self.backup), "--root", str(self.root)])
        self.assertEqual(rc, 0); self.assertIn("nothing to migrate", out)

    def test_the_workflow_files_use_the_same_iteration_counts_as_the_tool(self):
        wf = (REPO / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
        self.assertIn("-iter 600000 -in data/review-queue/staged.json.enc", wf)
        self.assertNotIn("-iter 600000 -in data/review-queue/held.json.enc", wf)           # held stays at the default; changing it needs a workflow change in the same deploy
        v = (REPO / ".github" / "workflows" / "verify-state-key.yml").read_text(encoding="utf-8")
        self.assertIn('("staged.json.enc", "600000")', v); self.assertIn("contents: read", v)


class WrongKeyGarbage(unittest.TestCase):
    def test_a_wrong_key_that_passes_the_padding_check_and_returns_garbage_does_not_count_as_opening_the_file(self):
        import unittest.mock as um
        with um.patch.object(rk, "decrypt", lambda *a, **k: b"\x8f\x02garbage-that-is-not-json"):
            self.assertFalse(rk.opens("x", None, "OLD_STATE_KEY"))
        with um.patch.object(rk, "decrypt", lambda *a, **k: b'{"nothing": 1}'):
            self.assertFalse(rk.opens("x", None, "OLD_STATE_KEY"))                                      # valid JSON, not a review store
        with um.patch.object(rk, "decrypt", lambda *a, **k: b'{"items": []}'):
            self.assertTrue(rk.opens("x", None, "NEW_STATE_KEY"))
        with um.patch.object(rk, "decrypt", lambda *a, **k: None):
            self.assertFalse(rk.opens("x", None, "OLD_STATE_KEY"))


if __name__ == "__main__":
    unittest.main()

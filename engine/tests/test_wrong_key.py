"""A wrong key has two possible outcomes: OpenSSL refuses it, or, about once in 256 tries, it passes the padding check and returns garbage. Every reader must stop the same way on both, and no test may depend on which one chance picks. Both outcomes are pinned here with fixed ciphertext made with throwaway keys. Needs OpenSSL (skipped without it).
Run:  python -m unittest discover -s engine/tests -v"""
import base64, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, FIX   # noqa: E402

import rotate_state_key as rk, staged_review, state_files, weekly_digest as wd   # noqa: E402

F = json.loads((FIX / "wrong_key_cases.json").read_text(encoding="utf-8"))
RIGHT, WRONG, MARK = F["rightKey"], F["wrongKey"], F["plaintextMark"]
OUTCOMES = ("wrongKeyFailsPadding", "wrongKeyGivesGarbage")
NEW = "Zq7-fixture-New-Key-For-Rotation-9xW2Lm"
STORES = {"held.json.enc": "default", "staged.json.enc": "600000"}


def raw(store, outcome):
    return base64.b64decode(F["cases"][STORES[store]][outcome])


def iters(store):
    return None if STORES[store] == "default" else "600000"


def openssl(path, store, key):
    c = ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2"] + (["-iter", iters(store)] if iters(store) else []) + ["-in", str(path), "-pass", "env:K"]
    return subprocess.run(c, env={**os.environ, "K": key}, capture_output=True)


@unittest.skipUnless(shutil.which("openssl"), "openssl not available")
class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="te-wk-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.q = self.root / "data" / "review-queue"
        self.q.mkdir(parents=True)

    def place(self, store, outcome):
        p = self.q / store
        p.write_bytes(raw(store, outcome))
        return p

    def cli(self, args, old=None, new=None):
        env = {k: v for k, v in os.environ.items() if k not in ("OLD_STATE_KEY", "NEW_STATE_KEY")}
        env["PYTHONUTF8"] = "1"
        if old is not None:
            env["OLD_STATE_KEY"] = old
        if new is not None:
            env["NEW_STATE_KEY"] = new
        p = subprocess.run([sys.executable, str(ENGINE / "rotate_state_key.py"), *args, "--root", str(self.root)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        return p.returncode, p.stdout + p.stderr


class TheFixturesBehaveAsLabelled(Base):
    def test_each_case(self):
        for store in STORES:
            for outcome in OUTCOMES:
                with self.subTest(store=store, outcome=outcome):
                    p = self.place(store, outcome)
                    self.assertIn(MARK.encode(), openssl(p, store, RIGHT).stdout)            # the right key always opens it
                    w = openssl(p, store, WRONG)
                    self.assertEqual(w.returncode != 0, outcome == "wrongKeyFailsPadding")
                    if outcome == "wrongKeyGivesGarbage":
                        self.assertNotIn(MARK.encode(), w.stdout)
                        with self.assertRaises(ValueError):
                            json.loads(w.stdout.decode("utf-8"))


class Rotation(Base):
    def test_a_wrong_old_key_stops_with_one_message_and_writes_nothing(self):
        for store in STORES:
            for outcome in OUTCOMES:
                for cmd in ("plan", "apply"):
                    with self.subTest(store=store, outcome=outcome, cmd=cmd):
                        for f in self.q.glob("*"):
                            f.unlink()
                        p = self.place(store, outcome)
                        before = p.read_bytes()
                        backup = self.root.parent / (self.root.name + "-backup")
                        self.addCleanup(shutil.rmtree, backup, ignore_errors=True)
                        rc, out = self.cli([cmd, "--backup-dir", str(backup)], old=WRONG, new=NEW)
                        self.assertEqual(rc, 2, out)
                        self.assertIn("cannot be decrypted with OLD_STATE_KEY", out)
                        self.assertIn("Nothing was changed", out)
                        self.assertNotIn("Traceback", out)
                        self.assertNotIn(MARK, out)
                        self.assertEqual(p.read_bytes(), before)
                        self.assertFalse(backup.exists())

    def test_a_right_key_with_the_wrong_structure_still_says_so(self):
        p = self.q / "held.json.enc"
        subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-out", str(p), "-pass", "env:K"], input=b'{"nope": 1}', env={**os.environ, "K": RIGHT}, check=True, capture_output=True)
        rc, out = self.cli(["plan", "--backup-dir", str(self.root.parent / (self.root.name + "-b"))], old=RIGHT, new=NEW)
        self.assertEqual(rc, 2, out)
        self.assertIn("not a review store", out)

    def test_verify_with_a_wrong_new_key_reports_failure_cleanly(self):
        for outcome in OUTCOMES:
            with self.subTest(outcome=outcome):
                self.place("held.json.enc", outcome)
                m = self.root / "manifest.json"
                m.write_text(json.dumps({"files": {"held.json.enc": {"plainJsonSha256": "x", "items": 1}}}), encoding="utf-8")
                rc, out = self.cli(["verify", "--manifest", str(m)], new=WRONG)
                self.assertEqual(rc, 1, out)
                self.assertIn("FAIL held.json.enc", out)
                self.assertNotIn("Traceback", out)
                self.assertNotIn(MARK, out)

    def test_rollback_with_a_wrong_old_key_restores_nothing(self):
        for outcome in OUTCOMES:
            with self.subTest(outcome=outcome):
                bd = self.root / "b"
                bd.mkdir(exist_ok=True)
                back = bd / "held.json.enc"
                back.write_bytes(raw("held.json.enc", outcome))
                (bd / "manifest.json").write_text(json.dumps({"files": {"held.json.enc": {"backup": str(back), "oldCiphertextSha256": rk.sha(back), "plainJsonSha256": "x", "items": 1}}}), encoding="utf-8")
                current = self.q / "held.json.enc"
                current.write_bytes(b"the current file")
                rc, out = self.cli(["rollback", "--backup-dir", str(bd)], old=WRONG)
                self.assertEqual(rc, 2, out)
                self.assertIn("Nothing was restored", out)
                self.assertNotIn("Traceback", out)
                self.assertEqual(current.read_bytes(), b"the current file")


class Readers(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(os.environ.pop, "STATE_KEY", None)

    def test_the_review_tool_raises_one_clear_error(self):
        for outcome in OUTCOMES:
            with self.subTest(outcome=outcome):
                self.place("staged.json.enc", outcome)
                os.environ["STATE_KEY"] = WRONG
                with self.assertRaises(RuntimeError) as e:
                    staged_review.load_staged(self.root)
                self.assertIn("wrong STATE_KEY", str(e.exception))
                self.assertIsNone(e.exception.__cause__)
                os.environ["STATE_KEY"] = RIGHT
                self.assertEqual(staged_review.load_staged(self.root)["items"][0]["id"], "fixture-1")

    def test_the_digest_raises_one_clear_error(self):
        for store in STORES:
            for outcome in OUTCOMES:
                with self.subTest(store=store, outcome=outcome):
                    p = self.place(store, outcome)
                    os.environ["STATE_KEY"] = WRONG
                    with self.assertRaises(RuntimeError) as e:
                        wd._load_enc(p, iters(store))
                    self.assertIn("wrong STATE_KEY", str(e.exception))
                    os.environ["STATE_KEY"] = RIGHT
                    self.assertEqual(wd._load_enc(p, iters(store))["items"][0]["id"], "fixture-1")

    def test_the_engines_check_refuses_what_the_workflow_step_would_have_written(self):     # the whole cycle on such a file: test_fail_closed.py and verification/v_audit_stop.py
        p = self.place("held.json.enc", "wrongKeyGivesGarbage")
        w = openssl(p, "held.json.enc", WRONG)
        self.assertEqual(w.returncode, 0)                            # the workflow's decrypt step would succeed
        g = self.q / "held.json"
        g.write_bytes(w.stdout)
        with self.assertRaises(state_files.DamagedFile):
            state_files.checked(g, state_files._items())


if __name__ == "__main__":
    unittest.main()

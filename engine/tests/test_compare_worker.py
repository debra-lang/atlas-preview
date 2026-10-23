"""Tests for tools/compare_worker.py (read-only comparison of the live Cloudflare worker code with the repository). Uses a throw-away git repository."""
import subprocess, sys, tempfile, unittest, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import compare_worker as cw  # noqa: E402

V1 = "export default {\n  async fetch(request, env) { return new Response('v1'); },\n};\n"
V2 = "export default {\n  async fetch(request, env) { return new Response('v2'); },\n};\n"


class Compare(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="te-cw-"))
        run = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.d, capture_output=True, text=True, check=True)
        run("init", "-q"); (self.d / "ask-worker").mkdir()
        (self.d / "ask-worker" / "worker.js").write_text(V1, encoding="utf-8"); run("add", "."); run("commit", "-qm", "first version")
        (self.d / "ask-worker" / "worker.js").write_text(V2, encoding="utf-8"); run("add", "."); run("commit", "-qm", "second version")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def saved(self, text, name="live.js"):
        p = self.d / name
        p.write_bytes(text.encode("utf-8"))
        return str(p)

    def test_identical_ignoring_line_endings_and_trailing_spaces(self):
        self.assertEqual(cw.main([self.saved(V2.replace("\n", "\r\n")), "--root", str(self.d)]), 0)
        self.assertEqual(cw.main([self.saved(V2.replace(";\n", ";   \n")), "--root", str(self.d)]), 0)

    def test_an_older_committed_version_is_recognised(self):
        code, msg, diff = cw.compare(V1, self.d, "ask-worker/worker.js")
        self.assertEqual(code, 2); self.assertIn("OLDER committed version", msg); self.assertIn("first version", msg)
        self.assertTrue(any("v2" in l for l in diff))

    def test_an_uncommitted_edit_is_reported_with_a_diff(self):
        edited = V2.replace("'v2'", "'v2 plus a hand edit'")
        code, msg, diff = cw.compare(edited, self.d, "ask-worker/worker.js")
        self.assertEqual(code, 3); self.assertIn("NO COMMITTED VERSION MATCHES", msg); self.assertIn("second version", msg)
        self.assertTrue(any(l.startswith("+") and "hand edit" in l for l in diff))

    def test_a_file_that_is_not_a_worker_is_refused(self):
        self.assertEqual(cw.main([self.saved("hello world"), "--root", str(self.d)]), 4)

    def test_the_repository_file_is_never_modified(self):
        before = (self.d / "ask-worker" / "worker.js").read_bytes()
        cw.main([self.saved(V1), "--root", str(self.d)])
        self.assertEqual((self.d / "ask-worker" / "worker.js").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

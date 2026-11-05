"""Runs the engine's test suite from the current folder and writes each test's outcome to a file. Usage: suite_runner.py <out.json>"""
import json, sys, unittest


class Recording(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rows = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append((test.id(), "ok", ""))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append((test.id(), "failed", ""))

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append((test.id(), "failed", ""))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.rows.append((test.id(), "skipped", reason))

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.rows.append((test.id(), "ok", "expected failure"))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.rows.append((test.id(), "failed", "unexpected success"))

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.rows.append((subtest.id(), "failed", ""))


suite = unittest.defaultTestLoader.discover("engine/tests")
result = unittest.TextTestRunner(resultclass=Recording, verbosity=0, stream=sys.stderr).run(suite)
json.dump({"ran": result.testsRun, "successful": result.wasSuccessful(), "rows": result.rows}, open(sys.argv[1], "w", encoding="utf-8"))
sys.exit(0 if result.wasSuccessful() else 1)

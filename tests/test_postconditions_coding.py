"""P0-02 slice 2 red tests: concrete postcondition checks for coding tasks."""

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PC_PATH = ROOT / "scripts" / "postconditions.py"
pc_spec = importlib.util.spec_from_file_location("postconditions", PC_PATH)
pc = importlib.util.module_from_spec(pc_spec)
sys.modules["postconditions"] = pc
pc_spec.loader.exec_module(pc)

CODING_PATH = ROOT / "scripts" / "postconditions_coding.py"
coding_spec = importlib.util.spec_from_file_location("postconditions_coding", CODING_PATH)
coding = importlib.util.module_from_spec(coding_spec)
sys.modules["postconditions_coding"] = coding
coding_spec.loader.exec_module(coding)


def _run(cmd, cwd):
    """Helper: run a shell command for test setup."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=False)


class BuildExitZeroTests(unittest.TestCase):
    def test_pass_when_command_returns_zero(self):
        check = coding.build_exit_zero([sys.executable, "-c", "pass"])
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator({}, Path(td))
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.evidence["returncode"], 0)

    def test_fail_when_command_returns_nonzero(self):
        check = coding.build_exit_zero([sys.executable, "-c", "raise SystemExit(2)"])
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator({}, Path(td))
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.evidence["returncode"], 2)

    def test_captures_stdout_and_stderr(self):
        check = coding.build_exit_zero([sys.executable, "-c",
                                        "import sys; print('hi'); sys.stderr.write('bye')"])
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator({}, Path(td))
        self.assertIn("hi", result.evidence["stdout_tail"])
        self.assertIn("bye", result.evidence["stderr_tail"])


class TestsExitZeroTests(unittest.TestCase):
    def test_pass_when_tests_exit_zero(self):
        check = coding.tests_exit_zero([sys.executable, "-c", "pass"])
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator({}, Path(td))
        self.assertEqual(result.status, "pass")

    def test_fail_when_tests_exit_nonzero(self):
        check = coding.tests_exit_zero([sys.executable, "-c", "raise SystemExit(1)"])
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator({}, Path(td))
        self.assertEqual(result.status, "fail")


class FilesChangedMatchDeclaredTests(unittest.TestCase):
    def _init_repo(self, td):
        _run(["git", "init", "-q", "-b", "main"], cwd=td)
        _run(["git", "config", "user.email", "t@test"], cwd=td)
        _run(["git", "config", "user.name", "t"], cwd=td)
        (td / "seed.txt").write_text("seed", encoding="utf-8")
        _run(["git", "add", "."], cwd=td)
        _run(["git", "commit", "-q", "-m", "seed"], cwd=td)

    def test_pass_when_declared_matches_actual(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            self._init_repo(td)
            (td / "a.py").write_text("a", encoding="utf-8")
            check = coding.files_changed_match_declared()
            result = check.evaluator({"files_changed": ["a.py"]}, td)
        self.assertEqual(result.status, "pass")

    def test_fail_when_undeclared_file_was_modified(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            self._init_repo(td)
            (td / "a.py").write_text("a", encoding="utf-8")
            (td / "b.py").write_text("b", encoding="utf-8")  # not declared
            check = coding.files_changed_match_declared()
            result = check.evaluator({"files_changed": ["a.py"]}, td)
        self.assertEqual(result.status, "fail")
        self.assertIn("b.py", result.evidence["undeclared"])

    def test_fail_when_declared_file_was_not_modified(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            self._init_repo(td)
            check = coding.files_changed_match_declared()
            result = check.evaluator({"files_changed": ["a.py"]}, td)
        self.assertEqual(result.status, "fail")
        self.assertIn("a.py", result.evidence["missing"])


class LintCleanTests(unittest.TestCase):
    def test_pass_when_lint_exits_zero(self):
        check = coding.lint_clean([sys.executable, "-c", "pass"])
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator({}, Path(td))
        self.assertEqual(result.status, "pass")

    def test_fail_when_lint_exits_nonzero(self):
        check = coding.lint_clean([sys.executable, "-c", "raise SystemExit(1)"])
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator({}, Path(td))
        self.assertEqual(result.status, "fail")


class NoConcealedUnresolvedTests(unittest.TestCase):
    def test_pass_when_no_markers_present(self):
        check = coding.no_concealed_unresolved()
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator({"output": "clean output", "unresolved_stages": []}, Path(td))
        self.assertEqual(result.status, "pass")

    def test_pass_when_all_markers_declared(self):
        check = coding.no_concealed_unresolved()
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator(
                {"output": "TODO: finish the parser", "unresolved_stages": ["parser"]},
                Path(td))
        self.assertEqual(result.status, "pass")

    def test_fail_when_undeclared_marker_in_output(self):
        """Closes D-09 at the shape layer: a candidate whose output has an
        unresolved marker not reflected in unresolved_stages conceals the issue."""
        check = coding.no_concealed_unresolved()
        with tempfile.TemporaryDirectory() as td:
            result = check.evaluator(
                {"output": "all green, but TODO: refactor later", "unresolved_stages": []},
                Path(td))
        self.assertEqual(result.status, "fail")
        self.assertIn("TODO", result.evidence["markers_found"][0])

    def test_fail_also_on_fixme_and_unresolved_markers(self):
        check = coding.no_concealed_unresolved()
        for marker in ("FIXME: hack", "UNRESOLVED: see later"):
            with tempfile.TemporaryDirectory() as td:
                result = check.evaluator({"output": marker, "unresolved_stages": []}, Path(td))
            self.assertEqual(result.status, "fail", marker)


if __name__ == "__main__":
    unittest.main()

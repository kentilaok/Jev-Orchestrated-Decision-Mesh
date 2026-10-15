"""Harden ~/.jev and runs/ to the current user only (P0-06 slice 3).

Tests the planning + application layers of `scripts/harden_jev_permissions.py`
on POSIX directly and the Windows path through a stub runner. The real smoke
check (does Windows actually tighten the ACL?) happens on the operator's
workstation; here we verify the script issues the right calls.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harden_jev_permissions as hjp  # type: ignore  # noqa: E402


def _record_runner():
    """Return (runner, calls) where calls accumulates every subprocess invocation."""
    calls = []

    def runner(argv, **kwargs):
        calls.append({"argv": list(argv), "kwargs": {k: v for k, v in kwargs.items() if k != "input"}})
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    return runner, calls


def _failing_runner(returncode=1, stderr="icacls_denied"):
    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(args=argv, returncode=returncode, stdout="", stderr=stderr)
    return runner


def _silent_log(_message):
    pass


class IterTreeTests(unittest.TestCase):
    def test_yields_root_and_all_descendants_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as tds:
            root = Path(tds)
            (root / "a").mkdir()
            (root / "a" / "deep").mkdir()
            (root / "a" / "deep" / "secret.txt").write_text("x", encoding="utf-8")
            (root / "b.json").write_text("{}", encoding="utf-8")
            paths = set(hjp._iter_tree(root))
            self.assertIn(root, paths)
            self.assertIn(root / "a", paths)
            self.assertIn(root / "a" / "deep", paths)
            self.assertIn(root / "a" / "deep" / "secret.txt", paths)
            self.assertIn(root / "b.json", paths)
            self.assertEqual(len(paths), 5)

    def test_missing_root_yields_nothing(self):
        with tempfile.TemporaryDirectory() as tds:
            missing = Path(tds) / "does_not_exist"
            self.assertEqual(list(hjp._iter_tree(missing)), [])


class IcaclsArgvTests(unittest.TestCase):
    def test_directory_gets_object_and_container_inherit_full(self):
        p = Path("C:/foo")
        argv = hjp._icacls_argv(p, "KEN", is_dir=True)
        self.assertEqual(argv, ["icacls", str(p), "/inheritance:r", "/grant:r", "KEN:(OI)(CI)F"])

    def test_file_gets_full_only(self):
        p = Path("C:/foo/bar.json")
        argv = hjp._icacls_argv(p, "KEN", is_dir=False)
        self.assertEqual(argv, ["icacls", str(p), "/inheritance:r", "/grant:r", "KEN:F"])


@unittest.skipIf(sys.platform == "win32", "POSIX chmod semantics")
class PosixHardenTests(unittest.TestCase):
    def test_dir_gets_0700_and_file_gets_0600(self):
        with tempfile.TemporaryDirectory() as tds:
            root = Path(tds)
            os.chmod(root, 0o777)
            (root / "a").mkdir()
            os.chmod(root / "a", 0o755)
            (root / "a" / "note.txt").write_text("x", encoding="utf-8")
            os.chmod(root / "a" / "note.txt", 0o644)
            result = hjp.harden_tree(root, user="irrelevant", dry_run=False, verbose=False,
                                     platform="linux", runner=lambda *a, **k: None, log=_silent_log)
            self.assertEqual(result["errors"], 0)
            self.assertFalse(result["skipped"])
            self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(os.stat(root / "a").st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(os.stat(root / "a" / "note.txt").st_mode), 0o600)

    def test_dry_run_does_not_change_mode(self):
        with tempfile.TemporaryDirectory() as tds:
            root = Path(tds)
            os.chmod(root, 0o755)
            hjp.harden_tree(root, user="irrelevant", dry_run=True, verbose=False,
                            platform="linux", runner=lambda *a, **k: None, log=_silent_log)
            self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o755)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tds:
            root = Path(tds)
            (root / "a.json").write_text("{}", encoding="utf-8")
            first = hjp.harden_tree(root, user="irrelevant", dry_run=False, verbose=False,
                                    platform="linux", runner=lambda *a, **k: None, log=_silent_log)
            second = hjp.harden_tree(root, user="irrelevant", dry_run=False, verbose=False,
                                     platform="linux", runner=lambda *a, **k: None, log=_silent_log)
            self.assertEqual(first["errors"], 0)
            self.assertEqual(second["errors"], 0)
            self.assertEqual(stat.S_IMODE(os.stat(root / "a.json").st_mode), 0o600)


class WindowsHardenTests(unittest.TestCase):
    def test_dir_and_file_each_get_one_icacls_call_with_correct_argv(self):
        with tempfile.TemporaryDirectory() as tds:
            root = Path(tds)
            (root / "secret.json").write_text("{}", encoding="utf-8")
            runner, calls = _record_runner()
            result = hjp.harden_tree(root, user="KEN", dry_run=False, verbose=False,
                                     platform="win32", runner=runner, log=_silent_log)
            self.assertEqual(result["errors"], 0)
            invocations = [c["argv"] for c in calls]
            self.assertEqual(len(invocations), 2)
            # Order is "root then children"; the file is the second.
            self.assertEqual(invocations[0][-1], "KEN:(OI)(CI)F")  # root dir
            self.assertEqual(invocations[1][-1], "KEN:F")  # file inside
            for argv in invocations:
                self.assertEqual(argv[0], "icacls")
                self.assertIn("/inheritance:r", argv)
                self.assertIn("/grant:r", argv)

    def test_dry_run_does_not_invoke_runner(self):
        with tempfile.TemporaryDirectory() as tds:
            root = Path(tds)
            (root / "a").mkdir()
            runner, calls = _record_runner()
            hjp.harden_tree(root, user="KEN", dry_run=True, verbose=False,
                            platform="win32", runner=runner, log=_silent_log)
            self.assertEqual(calls, [])

    def test_runner_failure_is_counted_as_error_but_continues(self):
        with tempfile.TemporaryDirectory() as tds:
            root = Path(tds)
            (root / "a.json").write_text("x", encoding="utf-8")
            (root / "b.json").write_text("x", encoding="utf-8")
            runner = _failing_runner()
            result = hjp.harden_tree(root, user="KEN", dry_run=False, verbose=False,
                                     platform="win32", runner=runner, log=_silent_log)
            # Three paths (root, a.json, b.json) all fail.
            self.assertEqual(result["errors"], 3)
            self.assertEqual(result["processed"], 0)


class MissingRootTests(unittest.TestCase):
    def test_missing_root_is_skipped_not_errored(self):
        with tempfile.TemporaryDirectory() as tds:
            missing = Path(tds) / "nope"
            runner, _calls = _record_runner()
            result = hjp.harden_tree(missing, user="KEN", dry_run=False, verbose=False,
                                     platform="win32", runner=runner, log=_silent_log)
            self.assertTrue(result["skipped"])
            self.assertEqual(result["processed"], 0)
            self.assertEqual(result["errors"], 0)


class CliEntryTests(unittest.TestCase):
    def test_dry_run_prints_json_summary_and_returns_zero(self):
        from io import StringIO
        import contextlib

        with tempfile.TemporaryDirectory() as tds:
            root = Path(tds)
            (root / "a.json").write_text("{}", encoding="utf-8")
            out = StringIO()
            err = StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = hjp.main(["--jev-root", str(root), "--runs-root", str(root),
                               "--user", "KEN", "--dry-run"])
            self.assertEqual(rc, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["user"], "KEN")
            self.assertTrue(payload["dry_run"])
            self.assertEqual(len(payload["roots"]), 2)

    def test_errors_return_nonzero_exit(self):
        from io import StringIO
        import contextlib
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as tds:
            root = Path(tds)
            (root / "x.json").write_text("{}", encoding="utf-8")
            out = StringIO()
            err = StringIO()
            with mock.patch.object(hjp, "subprocess") as fake_subprocess, \
                 mock.patch.object(hjp, "sys") as fake_sys:
                fake_sys.platform = "win32"
                fake_sys.stderr = err
                fake_subprocess.run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=5, stdout="", stderr="boom")
                with contextlib.redirect_stdout(out):
                    rc = hjp.main(["--jev-root", str(root), "--runs-root", str(tds) + "/missing",
                                   "--user", "KEN"])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()

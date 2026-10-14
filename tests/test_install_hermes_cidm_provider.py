"""Slice 5 tests: scripts/install_hermes_cidm_provider.py renders, installs and
removes the CIDM provider block in a Hermes config.yaml file. Everything is
exercised against a temp copy; the real Hermes config is untouched by tests."""

import importlib.util
import os
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "install_hermes_cidm_provider.py"
spec = importlib.util.spec_from_file_location("install_hermes_cidm_provider", MODULE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


SEED_CONFIG = """\
# Hermes Agent CLI Configuration
_config_version: 50

database:
  journal_mode: "wal"

runtime:
  nofile_soft_limit: 4096
"""


class InstallerTests(unittest.TestCase):
    def _tmp_config(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
        tmp.write(SEED_CONFIG)
        tmp.close()
        return Path(tmp.name)

    def test_renders_cidm_provider_block_with_markers(self):
        block = installer.render_block()
        self.assertIn(installer.BEGIN_MARKER, block)
        self.assertIn(installer.END_MARKER, block)
        self.assertIn("cidm:", block)
        self.assertIn("base_url:", block)
        self.assertIn("127.0.0.1:8765/v1", block)
        self.assertIn("key_env:", block)
        self.assertIn("CIDM_API_KEY", block)
        self.assertIn("api_mode: chat_completions", block)
        self.assertIn("cidm-jev", block)

    def test_install_appends_block_and_creates_backup(self):
        path = self._tmp_config()
        try:
            result = installer.install(path)
            self.assertTrue(result["changed"])
            self.assertTrue(Path(result["backup"]).is_file())
            content = path.read_text(encoding="utf-8")
            self.assertIn(installer.BEGIN_MARKER, content)
            self.assertIn("cidm:", content)
            # The seed content survives.
            self.assertIn("nofile_soft_limit: 4096", content)
        finally:
            path.unlink(missing_ok=True)

    def test_install_is_idempotent(self):
        path = self._tmp_config()
        try:
            installer.install(path)
            # Re-running must not duplicate the block.
            second = installer.install(path)
            self.assertFalse(second["changed"],
                             "second install should report no change on already-installed config")
            content = path.read_text(encoding="utf-8")
            self.assertEqual(content.count(installer.BEGIN_MARKER), 1)
            self.assertEqual(content.count(installer.END_MARKER), 1)
        finally:
            path.unlink(missing_ok=True)

    def test_install_replaces_an_outdated_block(self):
        path = self._tmp_config()
        try:
            # Simulate a stale CIDM block pointing at the wrong port.
            with path.open("a", encoding="utf-8") as fh:
                fh.write("\n" + installer.BEGIN_MARKER + "\n"
                         "providers:\n  cidm:\n    base_url: http://127.0.0.1:9999/v1\n"
                         + installer.END_MARKER + "\n")
            result = installer.install(path)
            self.assertTrue(result["changed"])
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("9999", content)
            self.assertIn("8765", content)
            self.assertEqual(content.count(installer.BEGIN_MARKER), 1)
        finally:
            path.unlink(missing_ok=True)

    def test_uninstall_removes_the_block_only(self):
        path = self._tmp_config()
        try:
            installer.install(path)
            result = installer.uninstall(path)
            self.assertTrue(result["changed"])
            content = path.read_text(encoding="utf-8")
            self.assertNotIn(installer.BEGIN_MARKER, content)
            self.assertNotIn(installer.END_MARKER, content)
            # Seed content survives.
            self.assertIn("nofile_soft_limit: 4096", content)
        finally:
            path.unlink(missing_ok=True)

    def test_uninstall_on_absent_block_is_a_noop(self):
        path = self._tmp_config()
        try:
            result = installer.uninstall(path)
            self.assertFalse(result["changed"])
        finally:
            path.unlink(missing_ok=True)

    def test_dry_run_does_not_write(self):
        path = self._tmp_config()
        try:
            before = path.read_text(encoding="utf-8")
            result = installer.install(path, dry_run=True)
            self.assertTrue(result["would_change"])
            after = path.read_text(encoding="utf-8")
            self.assertEqual(before, after)
        finally:
            path.unlink(missing_ok=True)

    def test_install_refuses_when_active_providers_block_exists(self):
        """If a user already has an uncommented top-level providers: block,
        the installer refuses rather than silently merge or clobber."""
        path = self._tmp_config()
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write("\nproviders:\n  openrouter:\n    base_url: https://x/v1\n")
            with self.assertRaises(installer.InstallerError):
                installer.install(path)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

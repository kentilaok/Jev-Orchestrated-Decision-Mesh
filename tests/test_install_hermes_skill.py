"""Hermes wrapper skill installer: path rewriting and idempotent config edit (offline)."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from install_hermes_skill import register_external_dir, render_wrapper

CONFIG = """# Hermes
skills:
  # Nudge
  creation_nudge_interval: 15

  # external_dirs:
  #   - ~/.agents/skills

agent:
  max_turns: 500
"""


class InstallerTests(unittest.TestCase):
    def test_wrapper_uses_absolute_repo_paths(self):
        text = render_wrapper(ROOT)
        self.assertTrue(text.startswith('---\nname: caber-interstitial-decision-mesh'))
        self.assertNotIn('<skill>', text)
        self.assertIn('](' + (ROOT / 'docs' / 'ARCHITECTURE.md').as_posix() + ')', text)
        self.assertIn('scripts/network_run.py', text)

    def test_external_dir_is_added_once_with_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.yaml'
            config.write_text(CONFIG, encoding='utf-8')
            target = Path(temp) / 'cidm-skills'
            self.assertEqual(register_external_dir(config, target), 'added')
            text = config.read_text(encoding='utf-8')
            self.assertIn('  external_dirs:\n    - "' + target.as_posix() + '"\n', text)
            self.assertLess(text.index('external_dirs:\n'), text.index('agent:'))
            self.assertEqual(register_external_dir(config, target), 'present')
            self.assertEqual(len(list(Path(temp).glob('config.yaml.bak-cidm-*'))), 1)
            other = Path(temp) / 'second'
            self.assertEqual(register_external_dir(config, other), 'added')
            self.assertEqual(config.read_text(encoding='utf-8').count('\n  external_dirs:\n'), 1)


if __name__ == '__main__':
    unittest.main()

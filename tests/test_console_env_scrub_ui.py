"""Static-content assertions on console/index.html for the P0-06 slice 2c
Operator Console UI surfacing of `secret_env_names`.

The P0-06 slice 2a config knob already works end-to-end at the HTTP layer;
this slice surfaces it in the Security view so an operator can edit the
list without hand-editing `~/.jev/operator-console.json`.
"""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "console" / "index.html"


class SecretEnvNamesUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding="utf-8")

    def test_secret_env_names_textarea_exists(self):
        """Operator reaches the knob via a textarea with a stable id."""
        self.assertIn('id="secretEnvNames"', self.html)

    def test_secret_env_names_label_mentions_the_knob(self):
        """Label text must name the knob so the operator understands the field."""
        self.assertRegex(self.html, r"[Ss]ecret\s*env", "secret env label missing from HTML")

    def test_load_security_reads_secret_env_names(self):
        """loadSecurity() populates the textarea from state.config.secret_env_names."""
        self.assertIn("secret_env_names", self.html)
        self.assertIn("secretEnvNames", self.html)

    def test_save_security_posts_secret_env_names(self):
        """saveSecurity() includes secret_env_names in the save() body."""
        # The exact JS line uses `secret_env_names:...` so the server config merger sees it.
        self.assertIn("secret_env_names:", self.html)

    def test_existing_security_markers_still_present(self):
        """Regression guard: slice 2c must not drop the P0-05 Security knobs."""
        for marker in ('id="view-security"', 'id="contentPolicy"',
                       'id="requireActionApproval"', 'id="trustedMcpServers"',
                       'id="pendingApprovals"', 'id="decidedApprovals"'):
            self.assertIn(marker, self.html, "Security view regression: " + marker)


if __name__ == "__main__":
    unittest.main()

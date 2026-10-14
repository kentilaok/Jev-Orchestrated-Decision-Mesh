"""Static-content assertions on console/index.html so the P0-05 security
knobs + approvals surface stays wired. We cannot run a browser from the
suite, but we can verify the HTML carries the expected ids, nav entry,
and fetch URLs.
"""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "console" / "index.html"


class SecurityViewMarkersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding="utf-8")

    def test_nav_button_exists(self):
        self.assertIn('data-view="security"', self.html)
        self.assertIn('Security', self.html)

    def test_security_section_exists(self):
        self.assertIn('id="view-security"', self.html)

    def test_three_config_field_controls_exist(self):
        # content_policy as a <select>; the id must be stable so the JS can bind.
        self.assertIn('id="contentPolicy"', self.html)
        # require_action_approval checkbox.
        self.assertIn('id="requireActionApproval"', self.html)
        # trusted_mcp_servers textarea (comma-separated).
        self.assertIn('id="trustedMcpServers"', self.html)

    def test_approvals_region_exists(self):
        self.assertIn('id="pendingApprovals"', self.html)
        self.assertIn('id="decidedApprovals"', self.html)

    def test_fetches_security_state_and_approvals(self):
        # The JS fetches /api/approvals and reads the security fields from
        # /api/state.config (already fetched by refresh()).
        self.assertIn("'/api/approvals'", self.html)

    def test_approve_and_reject_buttons_target_approvals_api(self):
        self.assertIn("/api/approvals/", self.html)


if __name__ == "__main__":
    unittest.main()

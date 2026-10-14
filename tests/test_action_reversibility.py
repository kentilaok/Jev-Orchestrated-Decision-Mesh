"""P0-05 slice 2 red tests: non-reversible-action gate.

The production handoff §P0-05 requires that non-reversible or non-allowlisted
external actions be refused until an operator explicitly approves them.
Standard capability permits bind scope and single-use; they do not express
whether the action can be undone. A `delete_file` call that passes a
'mutate'-tier permit is still non-reversible and should require an extra
approval beyond the permit itself.
"""

import importlib.util
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "action_reversibility", ROOT / "scripts" / "action_reversibility.py")
ar = importlib.util.module_from_spec(spec)
sys.modules["action_reversibility"] = ar
spec.loader.exec_module(ar)


class ClassifyActionTests(unittest.TestCase):
    def test_reversible_read_actions(self):
        for name in ("read_file", "list_files", "search_code", "get_user", "fetch_page"):
            self.assertEqual(ar.classify_action(name, {}), "reversible", name)

    def test_non_reversible_destructive_actions(self):
        for name in ("delete_file", "drop_table", "rm_dir", "destroy_vm", "purge_cache"):
            self.assertEqual(ar.classify_action(name, {}), "non_reversible", name)

    def test_external_side_effects_are_non_reversible(self):
        for name in ("send_email", "post_webhook", "charge_card", "publish_tweet",
                     "deploy_service", "post_slack"):
            self.assertEqual(ar.classify_action(name, {}), "non_reversible", name)

    def test_write_actions_default_to_non_reversible(self):
        """A pure 'write' is non-reversible unless the operator classifies
        otherwise. Over-restriction forces an explicit decision; under-
        restriction silently loses the gate."""
        for name in ("write_file", "update_row", "patch_config", "put_object"):
            self.assertEqual(ar.classify_action(name, {}), "non_reversible", name)

    def test_unknown_actions_classify_as_unknown(self):
        self.assertEqual(ar.classify_action("mystery_action", {}), "unknown")

    def test_unknown_is_treated_as_non_reversible_at_gate(self):
        """is_blocked() must treat 'unknown' as non-reversible: safe-by-default
        when the classifier cannot decide."""
        self.assertTrue(ar.is_blocked_without_approval("mystery_action", {},
                                                      approval=None))

    def test_explicit_reversible_override_via_annotations(self):
        """A tool annotation can declare an action reversible; the operator
        must have approved the annotation shape at ingest time (slice-1 trust
        gate still applies to the server, so this is only honored on trusted
        servers; the classifier itself is annotation-only, trust is enforced
        at the caller)."""
        access = ar.classify_action("transient_cache_put",
                                    {"reversibility_hint": "reversible"})
        self.assertEqual(access, "reversible")

    def test_explicit_non_reversible_override_wins(self):
        """A reversible-looking name with an explicit non_reversible annotation
        is non-reversible. The stricter direction always wins."""
        access = ar.classify_action("read_file",
                                    {"reversibility_hint": "non_reversible"})
        self.assertEqual(access, "non_reversible")


class ApprovalGateTests(unittest.TestCase):
    def test_reversible_action_requires_no_approval(self):
        self.assertFalse(ar.is_blocked_without_approval("read_file", {}, approval=None))

    def test_non_reversible_action_without_approval_is_blocked(self):
        self.assertTrue(ar.is_blocked_without_approval("delete_file", {}, approval=None))

    def test_non_reversible_action_with_approved_approval_passes(self):
        approval = {"status": "approved", "operator": "ken@local",
                    "action": "delete_file"}
        self.assertFalse(ar.is_blocked_without_approval("delete_file", {},
                                                       approval=approval))

    def test_non_reversible_action_with_pending_approval_is_blocked(self):
        approval = {"status": "pending", "operator": None, "action": "delete_file"}
        self.assertTrue(ar.is_blocked_without_approval("delete_file", {},
                                                      approval=approval))

    def test_non_reversible_action_with_rejected_approval_is_blocked(self):
        approval = {"status": "rejected", "operator": "ken", "action": "delete_file"}
        self.assertTrue(ar.is_blocked_without_approval("delete_file", {},
                                                      approval=approval))

    def test_approval_for_different_action_does_not_authorise_this_one(self):
        """An approval bound to 'delete_file' cannot authorise 'drop_table'."""
        approval = {"status": "approved", "operator": "ken", "action": "delete_file"}
        self.assertTrue(ar.is_blocked_without_approval("drop_table", {},
                                                      approval=approval))

    def test_require_approval_raises_when_blocked(self):
        with self.assertRaises(ar.NonReversibleActionError):
            ar.require_approval("delete_file", {}, approval=None)

    def test_require_approval_returns_classification_when_ok(self):
        info = ar.require_approval("read_file", {}, approval=None)
        self.assertEqual(info["classification"], "reversible")
        self.assertFalse(info["approval_required"])

    def test_require_approval_returns_approved_detail(self):
        approval = {"status": "approved", "operator": "ken@local", "action": "delete_file"}
        info = ar.require_approval("delete_file", {}, approval=approval)
        self.assertEqual(info["classification"], "non_reversible")
        self.assertTrue(info["approval_required"])
        self.assertEqual(info["approved_by"], "ken@local")


if __name__ == "__main__":
    unittest.main()

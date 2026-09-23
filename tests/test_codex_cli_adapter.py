"""Offline checks for the read-only Codex CLI worker boundary."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from codex_cli_adapter import CodexCliAdapter, CodexCliError


SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "minLength": 1, "maxLength": 80},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "required": ["answer", "score"],
    "additionalProperties": False,
}


def stream(answer=None, *, usage=None, item_type="agent_message", completed=True,
           model=None, effort=None):
    answer = answer if answer is not None else json.dumps({"answer": "done", "score": 5})
    usage = usage if usage is not None else {"input_tokens": 20, "cached_input_tokens": 4,
                                           "output_tokens": 12, "reasoning_output_tokens": 3}
    first = {"type": "thread.started", "thread_id": "thread-test"}
    if model is not None:
        first["model"] = model
    if effort is not None:
        first["model_reasoning_effort"] = effort
    events = [first, {"type": "turn.started"},
              {"type": "item.completed", "item": {"id": "item_1", "type": item_type,
                                                    "text": answer}}]
    if completed:
        events.append({"type": "turn.completed", "usage": usage})
    return "\n".join(json.dumps(event) for event in events).encode("utf-8") + b"\n"


class FakeProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode

    def poll(self):
        return self.returncode


class CodexCliAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.calls = []
        self.schemas = []
        self.prompts = []

    def invoke(self, output=None, *, returncode=0, adapter=None):
        output = stream() if output is None else output

        def fake_popen(argv, **kwargs):
            self.calls.append((argv, kwargs))
            self.schemas.append(json.loads(Path(argv[argv.index("--output-schema") + 1]).read_text(
                encoding="utf-8")))
            self.prompts.append(kwargs["stdin"].read().decode("utf-8"))
            kwargs["stdout"].write(output)
            kwargs["stdout"].flush()
            return FakeProcess(returncode)

        with patch("codex_cli_adapter.subprocess.Popen", side_effect=fake_popen):
            return (adapter or CodexCliAdapter()).run("gpt-6-luna", "low", "Summarize the bounded input.",
                                                     SCHEMA, self.workspace)

    def test_valid_documented_stream_uses_exact_bounded_read_only_route(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "private-jev-token",
                                          "OPENAI_API_KEY": "private-openai-token",
                                          "CODEX_API_KEY": "private-codex-token",
                                          "TASK_INTERNAL_TOKEN": "private-task-token"}):
            value = self.invoke(adapter=CodexCliAdapter(secret_env_names=("TASK_INTERNAL_TOKEN",)))
        self.assertEqual(value["artifact"], {"answer": "done", "score": 5})
        self.assertEqual(value["usage"], {"input_tokens": 20, "output_tokens": 12,
                                           "cached_input_tokens": 4, "reasoning_output_tokens": 3})
        self.assertEqual((value["requested_model"], value["requested_effort"]),
                         ("gpt-6-luna", "low"))
        self.assertEqual((value["actual_model"], value["actual_effort"]), (None, None))
        self.assertEqual(value["identity_verification"], "requested_only")
        self.assertEqual([event["type"] for event in value["events"]],
                         ["thread.started", "turn.started", "item.completed", "turn.completed"])
        self.assertNotIn("done", repr(value["events"]))
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[:4], ["codex", "exec", "--json", "--ephemeral"])
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--skip-git-repo-check", argv)
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-luna")
        self.assertEqual(argv[argv.index("-c") + 1], "model_reasoning_effort=low")
        self.assertEqual(argv[argv.index("-C") + 1], str(self.workspace.resolve()))
        self.assertEqual(argv[-1], "-")
        self.assertFalse(kwargs["shell"])
        self.assertNotIn("OPENROUTER_API_KEY", kwargs["env"])
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
        self.assertNotIn("CODEX_API_KEY", kwargs["env"])
        self.assertNotIn("TASK_INTERNAL_TOKEN", kwargs["env"])
        self.assertNotIn("private-jev-token", repr(argv))
        self.assertEqual(self.schemas[0], SCHEMA)
        self.assertIn("Do not call tools", self.prompts[0])
        self.assertTrue(self.prompts[0].endswith("Summarize the bounded input."))

    def test_reported_identity_match_and_conflict(self):
        good = self.invoke(stream(model="gpt-6-luna", effort="low"))
        self.assertEqual(good["identity_verification"], "reported_match")
        self.assertEqual((good["actual_model"], good["actual_effort"]), ("gpt-6-luna", "low"))
        with self.assertRaisesRegex(CodexCliError, "model_identity_conflict"):
            self.invoke(stream(model="gpt-6-sol", effort="low"))
        with self.assertRaisesRegex(CodexCliError, "effort_identity_conflict"):
            self.invoke(stream(model="gpt-6-luna", effort="high"))

    def test_any_tool_action_or_failed_turn_is_rejected(self):
        for item_type in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
            with self.subTest(item_type=item_type), self.assertRaisesRegex(CodexCliError,
                                                                           "unexpected_codex_action"):
                self.invoke(stream(item_type=item_type))
        with self.assertRaisesRegex(CodexCliError, "missing_turn_completed"):
            self.invoke(stream(completed=False))
        with self.assertRaisesRegex(CodexCliError, "codex_nonzero_exit"):
            self.invoke(returncode=2)

    def test_schema_json_and_usage_fail_closed(self):
        for answer, code in (("not json", "invalid_json"),
                             ('{"answer":"done","score":6}', "artifact_schema_mismatch"),
                             ('{"answer":"done","answer":"other","score":5}', "duplicate_json_key"),
                             ('{"answer":"done","score":5,"extra":1}', "artifact_schema_mismatch")):
            with self.subTest(answer=answer), self.assertRaisesRegex(CodexCliError, code):
                self.invoke(stream(answer=answer))
        with self.assertRaisesRegex(CodexCliError, "invalid_cached_usage"):
            self.invoke(stream(usage={"input_tokens": 2, "output_tokens": 1,
                                      "cached_input_tokens": 3}))
        with self.assertRaisesRegex(CodexCliError, "invalid_usage_counter"):
            self.invoke(stream(usage={"input_tokens": True, "output_tokens": 1}))

    def test_limits_and_unapproved_models(self):
        with self.assertRaisesRegex(CodexCliError, "codex_output_limit"):
            self.invoke(adapter=CodexCliAdapter(max_stdout_bytes=64))
        with patch("codex_cli_adapter.subprocess.Popen") as popen:
            with self.assertRaisesRegex(CodexCliError, "worker_route_not_permitted"):
                CodexCliAdapter().run("gpt-6-astra", "low", "x", SCHEMA, self.workspace)
            with self.assertRaisesRegex(CodexCliError, "worker_route_not_permitted"):
                CodexCliAdapter().run("gpt-5.6-sol", "high", "x", SCHEMA, self.workspace)
            with self.assertRaisesRegex(CodexCliError, "astra_effort_not_permitted"):
                CodexCliAdapter(astra_explicitly_authorized=True).run(
                    "gpt-6-astra", "high", "x", SCHEMA, self.workspace)
            with self.assertRaisesRegex(CodexCliError, "unsupported_schema"):
                CodexCliAdapter().run("gpt-6-luna", "low", "x", {**SCHEMA, "oneOf": []}, self.workspace)
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

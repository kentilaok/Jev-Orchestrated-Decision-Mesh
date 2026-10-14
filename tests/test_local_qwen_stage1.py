import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capability_permits import PermitAuthority, audit_permit_ledger
from ollama_provider import LocalModelError, LocalOllamaTransport, OllamaLocalProvider, READONLY_SCHEMA
from local_qwen_run import run_local

MODEL = "example-qwen:4b-q4"
DIGEST = "sha256:" + "a" * 64


class FakeTransport:
    def __init__(self, artifact=None, digest=DIGEST):
        self.calls = []
        self.digest = digest
        self.artifact = artifact or {"answer": "needs checks", "evidence_ids": [],
                                     "unresolved": ["unverified"]}
    def request(self, route, payload=None):
        self.calls.append((route, payload))
        if route == "/api/tags":
            return {"models": [{"name": MODEL, "digest": self.digest}]}
        if route == "/api/chat":
            return {"model": MODEL, "message": {"content": json.dumps(self.artifact)},
                    "prompt_eval_count": 23, "eval_count": 11}
        raise AssertionError(route)


class LocalQwenStage1Tests(unittest.TestCase):
    def test_local_only_returns_unverified_proposal_and_valid_receipts(self):
        transport = FakeTransport()
        authority = PermitAuthority()
        result = run_local("Explain the error.", model=MODEL, model_digest=DIGEST,
                           authority=authority, transport=transport)
        self.assertEqual(result["status"], "unverified_proposal")
        self.assertEqual(result["remote_worker_calls"], 0)
        self.assertTrue(result["permit_audit"]["valid"])
        self.assertEqual(result["usage"]["input_tokens"], 23)
        self.assertEqual([c[0] for c in transport.calls], ["/api/tags", "/api/chat"])
        self.assertNotIn("tools", transport.calls[1][1])
        self.assertTrue(audit_permit_ledger(authority.events())["valid"])

    def test_mismatched_digest_aborts_before_inference(self):
        transport = FakeTransport(digest="sha256:" + "b" * 64)
        with self.assertRaisesRegex(LocalModelError, "local_model_digest_mismatch"):
            run_local("test", model=MODEL, model_digest=DIGEST, transport=transport)
        self.assertEqual([c[0] for c in transport.calls], ["/api/tags"])

    def test_invalid_schema_is_not_released(self):
        transport = FakeTransport(artifact={"answer": "invented"})
        with self.assertRaisesRegex(LocalModelError, "local_schema_mismatch"):
            run_local("test", model=MODEL, transport=transport)

    def test_remote_http_endpoints_rejected(self):
        for endpoint in ("https://example.com", "http://localhost:11434", "http://127.0.0.1:11500"):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(ValueError, "ollama_loopback_only"):
                    LocalOllamaTransport(endpoint)

    def test_provider_status_uses_local_models(self):
        provider = OllamaLocalProvider(PermitAuthority(), allowed_model=MODEL, transport=FakeTransport())
        self.assertTrue(provider.status()["available"])
        self.assertEqual(provider.list_models()["models"][0]["digest"], DIGEST)
        self.assertTrue(provider.capabilities()["tools_disabled"])

    def test_read_only_proposal_never_carries_commit_authority(self):
        result = run_local("Summarise", model=MODEL, transport=FakeTransport())
        self.assertEqual(result["authority"], "operator_read_only_not_jev_release")
        self.assertNotIn("accepted", result["status"])

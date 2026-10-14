"""Explicit local-only, read-only CIDM worker pilot; not the Jev-governed broker."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

from capability_permits import PermitAuthority, audit_permit_ledger
from frontier_providers import _request_scope
from ollama_provider import OllamaLocalProvider, READONLY_SCHEMA


def run_local(prompt, *, model, model_digest=None, authority=None, transport=None,
              context_tokens=4096, output_tokens=512):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt_required")
    authority = authority or PermitAuthority()
    provider = OllamaLocalProvider(authority, allowed_model=model, model_digest=model_digest,
                                   transport=transport, context_tokens=context_tokens,
                                   output_tokens=output_tokens)
    with tempfile.TemporaryDirectory(prefix="cidm-local-only-") as workspace:
        request = {"model": model, "effort": "low", "prompt": prompt,
                   "schema": READONLY_SCHEMA, "workspace": workspace}
        basis = {"kind": "operator", "operator": "local-only-pilot",
                 "reason": "read-only local model proposal; no state transition"}
        permit = authority.issue("frontier.run", _request_scope(provider.provider_id, request), basis)
        reply = provider.run(request, permit)
    audit = audit_permit_ledger(authority.events())
    if not audit["valid"]:
        raise ValueError("local_permit_audit_failed")
    return {"status": "unverified_proposal", "provider": provider.provider_id,
            "mode": "local_only", "remote_worker_calls": 0, "jev_calls": 0,
            "authority": "operator_read_only_not_jev_release", "artifact": reply["artifact"],
            "usage": reply.get("usage"), "model_identity": reply.get("identity_verification"),
            "permit_audit": audit}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", required=True, help="exact installed Ollama tag")
    p.add_argument("--digest", help="expected installed model digest; recommended")
    p.add_argument("--prompt", required=True, help="bounded prompt text (no shell execution)")
    p.add_argument("--live-local", action="store_true", help="explicitly contact local Ollama")
    p.add_argument("--context-tokens", type=int, default=4096)
    args = p.parse_args(argv)
    if not args.live_local:
        print(json.dumps({"status": "preview_only", "mode": "local_only",
                          "model": args.model, "remote_worker_calls": 0, "jev_calls": 0}))
        return 0
    result = run_local(args.prompt, model=args.model, model_digest=args.digest,
                       context_tokens=args.context_tokens)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

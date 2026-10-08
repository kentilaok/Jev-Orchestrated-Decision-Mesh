# Stage 4 handoff — provider selection policy and Console local-only controls

**Date:** 9 October 2026. **Status:** local-only Console run supported; auto fallback / simultaneous teacher integration **not yet active**.

## Built

- `scripts/local_continuity_policy.py`: explicit `frontier_only`, `local_only`, `dual_shadow`, `auto_fallback` route decisions and strict fallback classifier. Only preclassified and trusted quota/rate-limit errors, an immutable snapshot, **verified checkpoint** and explicit fallback enablement can permit a local route decision. Safety/credential/unknown errors do not trigger fallback.
- Operator Console: new **Qwen local** tab with locally detected models, policy preview, project scope and task input, and user-confirmed **Local Only** read-only pipeline launch. Runs launch a Python job, record proposals, and never send them to the live Jev broker.
- `tests/test_local_qwen_stage4.py`: modes, quota guards, safety denial, read-only prohibition and job command isolation.

## What's *not* yet wired

- The Console selects all four modes for inspection. **Dual teacher + student is available only through the explicitly approved `dual_shadow_runner.py` CLI (Stage 3 extension), not through the Console.** Automatic frontier quota failover is still blocked. Existing Claude/Codex native broker and recovery checkpoint cannot be safely switched to an unsupported local route by changing a dropdown.
- Provider adapters must emit **trusted typed quota/error events**; text-searching stderr or model output is unacceptable.
- Reusing native broker checkpoints with a new model route needs a proper fresh Jev decision or a narrowly approved deterministic continuity policy. This is a separate production acceptance gate.
- Operator Console does not make Hermes a Jev-governed dispatch worker; that earlier V1 task remains open.

## Windows verification

```powershell
cd 'D:\Hermes Jev CIDM'
git pull --ff-only origin feature/local-continuity-split-context-plan
py -3.11 -m unittest discover -s tests -p 'test_local_qwen_stage4.py' -v
py -3.11 scripts/operator_console.py
# Open http://127.0.0.1:8765 and choose Qwen local tab.
```

Use fictional tasks. Local-only output is **unverified**; the pipeline does not execute returned commands or commit changes.

**Next stage:** bounded retrieval scale, model-session resource governance, and pilot measurements.

# Handoff — Hermes dispatch adapter, slice 6 (14 October 2026)

**Branch:** `feature/hermes-dispatch-adapter`.
**Parent gate:** [P0-04 Governed Hermes integration](PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md). Final of six slices. Closes P0-04 at the broker-V1 scope (live frontier execution still gated by P0-03).
**Evidence level:** offline tests + a real Hermes `config.yaml` edit (reversible). No model calls.

## 1. What this slice delivers

The P0-04 pass condition and the operator-facing documentation.

- `tests/test_hermes_dispatch_adversarial.py`: nine adversarial tests covering the bypass vectors a hostile client (or a buggy integration) would try.
- `docs/HERMES-DISPATCH-ADAPTER.md`: single operator doc covering architecture, install/uninstall, auth and transport, strong-permit flow, threads, adversarial table, rollback, known limitations, verification snapshot.

### Adversarial vectors proven blocked

| Vector | Expected | Pass? |
|---|---|---|
| A1 No bearer token | 401 | yes |
| A2 Wrong bearer token | 401 | yes |
| B Rebound Host header | 403 | yes |
| C Console-CSRF header without bearer | 401 | yes |
| D Unknown model id | 400 invalid_request_error | yes |
| E Strong request as "normal" | pending_approval, record stays pending on disk | yes |
| F Approval POST without CSRF | 403, record stays pending | yes |
| G Re-decide a decided token | 400 "already rejected" | yes |
| H GET on dispatch path | no broker run, no 500 | yes |

## 2. Code changes

| File | Change |
|---|---|
| `tests/test_hermes_dispatch_adversarial.py` | New, 170 lines. Nine HTTP integration tests on a real `Handler` behind an ephemeral port. |
| `docs/HERMES-DISPATCH-ADAPTER.md` | New, operator-facing (~180 lines). Replaces no existing file; linked from the parent handoff. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-6 adversarial tests | 9/9 pass |
| Full offline suite | 375/375 pass, 1 opt-in Docker skip |
| Regressions on 366-test post-slice-5 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. P0-04 status

P0-04 pass condition from the production handoff:

> complete Hermes conversation → CIDM/Jev → approved Hermes procedure/frontier work → validators → Jev → result in same conversation smoke and adversarial traces.

What this branch delivers against each clause:

- **Hermes conversation.** `hermes chat --model cidm-jev` reaches CIDM via the installed `providers.cidm` entry.
- **CIDM/Jev.** Every turn runs `validate_broker_request` under the chosen gate policy (recovery by default), producing the plan Jev would have followed.
- **Approved work.** Strong requests are gated: pending record, approval URL emitted into the chat, operator decides via the Operator Console. Decisions are one-shot and atomic.
- **Validators / Jev / result in same conversation.** The thread journal binds the Hermes conversation to a CIDM record; the final content lands back in the Hermes chat on the same request.
- **Adversarial traces.** Nine tests pass.

**What this branch does NOT yet close:**

- **Frontier worker execution.** The broker still runs `--validate-only`. Promotion to live execution is gated by P0-03 (one capped non-production live run with full audit). The OpenAI endpoint will flip from "plan summary" to "worker result" when P0-03 clears.
- **In-process broker call.** Status chunks today describe the validate path; a future slice must move the broker in-process so live-run callbacks can fire during execution.

## 5. Open items picked up in the PR summary

- Timestamp collision in installer backups (1-second granularity). Low risk, operator-driven. See `HERMES-DISPATCH-ADAPTER.md` §9.
- Linux/macOS default target in the installer is Windows-oriented. `--target` lets CI/tests override.
- Classifier false negatives on semantically-destructive requests that avoid the keyword list. The `cidm_strong: true` opt-in exists for callers that know their action is strong.

## 6. Pass/hold decision for this slice

- `scope`: closes P0-04 at the broker-V1 scope; does not open P0-03.
- `decision`: **PASS pending final independent QA on branch head**, after which the branch opens as a PR against `main`.
- `release judgement`: safe to merge once PR is reviewed; this is a broker-V1 feature, not a live-execution release.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*

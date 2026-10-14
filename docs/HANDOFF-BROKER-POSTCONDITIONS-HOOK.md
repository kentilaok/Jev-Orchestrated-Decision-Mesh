# Handoff — Broker postconditions wrapper (15 October 2026)

**Branch:** `feature/broker-postconditions-hook`, based on `main` at `c74322e`.
**Parent gate:** parked P0-02 follow-up — "promote postconditions to in-broker hook".
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

A thin `run_with_postconditions(broker, spec, …)` wrapper in `scripts/postconditions_broker.py` so callers get the postcondition gate without invoking the adapter manually.

- Signature: `run_with_postconditions(broker, spec, *, postconditions, workspace, declared_files=None, resume=None)`.
- Behaviour: calls `broker.run(spec, resume=…)`, then feeds the result to `apply_postconditions`.
- `broker` is duck-typed (any object with `.run(spec, resume=None) -> dict`); `NativeTransitionBroker` fits as-is, tests use lightweight stubs.
- If the broker exposes a `last_candidate` attribute (optional convention), the wrapper forwards that candidate so postconditions see the richer broker-shape candidate (`text`, `data.unresolved`); otherwise a synthetic shell is built from `result["answer"]`.
- All existing semantics preserved: status demotion only when the broker returned `complete`; prior failures preserved.

This closes the P0-02 §4 open item without editing `NativeTransitionBroker` itself (keeps the complex invariant-heavy class untouched; the composition sits in the adapter module).

## 2. Code changes

| File | Change |
|---|---|
| `scripts/postconditions_broker.py` | +18 lines. New `run_with_postconditions` function above `apply_postconditions`. |
| `tests/test_broker_postconditions_hook.py` | New, 115 lines. Seven tests via a `_StubBroker`: spec passed through, empty-checks noop, passing checks → release, failing check demotes `complete`, prior failure preserved, `resume` kwarg forwarded, `last_candidate` convention honoured end-to-end with `postconditions_coding.no_concealed_unresolved`. |

## 3. Verification

| Check | Result |
|---|---|
| Wrapper tests | 7/7 pass |
| Full offline suite | 493/493 pass, 1 opt-in Docker skip |
| Regressions on 486-test post-PR#10 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items (unchanged)

1. Operator Console UI for `content_policy` / `trusted_servers` / `require_action_approval` / strong-permit approval.
2. Approval provenance — Jev-associated immutable evidence.
3. Fast Path admission with `calibration=null`.
4. (New) Have `NativeTransitionBroker` set `self.last_candidate` after each `self._codex` call so real runs transparently feed richer candidates to the gate. Mechanical; parked.

## 5. Decision

- `scope`: follow-up PR; closes the P0-02 §4 "callers need manual adapter call" item.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*

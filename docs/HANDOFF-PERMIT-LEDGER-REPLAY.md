# Handoff — PermitAuthority ledger replay (15 October 2026)

**Branch:** `feature/permit-ledger-replay`, based on `main` at `e26000f`.
**Parent gate:** P0-06 slice 1 — "restart and resume real paused runs; ensure old permits cannot be reused" from the production handoff.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

`PermitAuthority.__init__` now replays its hash-chain ledger before the authority accepts any new calls, so a crashed-and-resumed broker refuses to re-issue or reuse old permit IDs.

- **Issued permits** replay into `self._permits` with the same `capability`, `scope_hash`, `basis_hash`, `issued_at`, `expires_at` the original record held. `scope` itself is intentionally not persisted in the ledger (it stays as `scope_keys` + `scope_hash`), so the replayed grant does not reconstruct the exact scope dict — `consume()` still verifies the caller's scope by hash.
- **Consumed permits** replay into `self._used`, so a second `consume()` after restart raises `permit_already_used` instead of the previous `unknown_permit` false-safe (same end result on this path, but now the diagnosis names the real failure).
- **Expired permits** stay expired — the original `expires_at` wins; a resumed run that would have been timed out before the crash is still refused.
- **Tampered or truncated ledgers** raise `PermitError` at construction. Hash-chain and content-digest checks live in `HashChainLedger.read()`; JSON/IO failures from a half-written final line are now wrapped as `PermitError("ledger_unreadable")` so operators see one failure vocabulary.

The resume path in `NativeTransitionBroker.run` already tolerated unknown-permit outcomes (it reads call receipts, not raw grants); this slice tightens the authority's invariant without changing the broker.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/capability_permits.py` | +40 lines. `PermitAuthority.__init__` wraps `HashChainLedger` construction in a `PermitError` translator; new `_replay_ledger` reads events and rebuilds `_permits`/`_used`. |
| `tests/test_permit_ledger_replay.py` | New, 135 lines. Seven tests: fresh authority on empty path is empty; issued permits rehydrate; consumed permit refuses second `consume` after restart (`permit_already_used`); receipts leave the used-set stable; expired-at-replay refuses; tampered body raises; truncated final line raises. |

## 3. Verification

| Check | Result |
|---|---|
| Replay tests | 7/7 pass |
| Full offline suite | 541/541 pass, 1 opt-in Docker skip |
| Regressions on 534-test post-PR#17 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items (P0-06 next slices)

1. Env scrubbing + spend-cap state field for live runs.
2. `scripts/harden_jev_permissions.py` — ships NTFS/POSIX ACL defaults for `~/.jev` and `runs/`.
3. Retention / backup playbook + restore drill.
4. OTLP ordinal-span caveat telemetry assertion.

## 5. Decision

- `scope`: P0-06 slice 1.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*

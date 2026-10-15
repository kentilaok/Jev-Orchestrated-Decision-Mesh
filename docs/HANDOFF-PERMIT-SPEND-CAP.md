# Handoff — Cumulative spend-cap state on the permit ledger (15 October 2026)

**Branch:** `feature/permit-spend-cap`, based on `main` at `7025633`.
**Parent gate:** P0-06 slice 2b — "Verify … spend alerts before granting persistent access" from the production handoff. Pairs with slice 1 (ledger replay) and slice 2a (env-scrub knob).
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

`PermitAuthority` now persists an API-equivalent cost on every receipt and refuses new permits once a cumulative cap is reached. The state survives restart because it is replayed from the same hash-chain ledger that already carries issue/consume events.

- **`receipt(permit_id, outcome)`** reads `outcome["cost_usd"]`. `None`/missing is accepted (unknown cost). A number must be finite and non-negative, otherwise `PermitError("invalid_receipt_cost")`. The persisted `permit_receipt` event now carries a `cost_usd` field (number or null).
- **`PermitAuthority(max_cumulative_usd=…)`** accepts an optional positive finite cap. `None` disables the check (pre-slice behaviour). Non-numeric, zero, negative, infinite, or NaN values raise `PermitError("invalid_max_cumulative_usd")` at construction.
- **`issue(...)`** refuses with `PermitError("cumulative_cap_exceeded")` once `cumulative_cost_usd >= max_cumulative_usd`. The semantic is "stop after the one that busted", not "pre-flight budget check": the permit that pushed cumulative over the cap still issues, consumes, and receipts; the next `issue()` is where enforcement bites. For V1 this is acceptable because workers are already bounded by `RunConfig.max_output_tokens`, so overshoot per permit is bounded.
- **`_replay_ledger`** sums `cost_usd` from every receipt event. A legacy receipt line without the field contributes zero.
- **Public read:** `authority.cumulative_cost_usd` (read-only property) exposes the current total for diagnostics.

Threading:

- **`_BoundedProvider.run()`** (frontier runs) extracts `api_equivalent_cost_usd` from the adapter's `usage` dict via a new `_cost_from_usage` helper and puts it on both the success outcome and the failure outcome. The helper refuses non-numbers, booleans, infinities, NaN, and negatives (returns `None`). Codex adapters never emit `api_equivalent_cost_usd` today, so Codex contributes `None` — pricing Codex from `RunConfig` ceilings is deliberately deferred.
- **`RunConfig.max_cumulative_usd: float | None = None`** carries the cap through the broker's `--config` JSON. The frozen-dataclass validator in `config.py` accepts `None` or a positive finite number; everything else raises `invalid_max_cumulative_usd`.
- **`native_transition_broker.py`** passes `max_cumulative_usd=config.max_cumulative_usd` into `PermitAuthority` at construction.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/capability_permits.py` | +34 lines. `max_cumulative_usd` constructor kwarg with validation; `_cumulative_cost_usd` state + public property; replay sums cost from receipts; `issue()` cap check; `receipt()` validates cost + persists `cost_usd` field + updates cumulative. |
| `scripts/frontier_providers.py` | +18 lines. New `_cost_from_usage(usage) -> float | None` helper; success and failure outcomes both carry `cost_usd` so cost reaches the ledger even on a failed/cancelled run. |
| `scripts/config.py` | +3 lines. New `max_cumulative_usd: float | None = None` field + `__post_init__` validation. |
| `scripts/native_transition_broker.py` | +1 line. Threaded through to `PermitAuthority(..., max_cumulative_usd=config.max_cumulative_usd)`. |
| `tests/test_permit_spend_cap.py` | New, 26 tests across six classes: receipt cost persistence (incl. negative/non-number rejects), cumulative-state accounting, replay (incl. legacy no-field receipts), cap enforcement (strict `>=` boundary; cap=None disables; restart carries state), `_BoundedProvider.run()` surfacing cost to the receipt (success, failure, missing-usage, negative-usage), `RunConfig.max_cumulative_usd` field validation, and `audit_permit_ledger` backward compat. |
| `docs/HANDOFF-PERMIT-SPEND-CAP.md` | This handoff. |

## 3. Verification

| Check | Result |
|---|---|
| Slice tests | 26/26 pass |
| Full offline suite | 586/586 pass, 1 opt-in Docker skip |
| Regressions on 560-test post-PR#19 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Design calls honoured

- **Cost lives on the receipt**, not a separate ledger event. Simpler, one hash-chained line per outcome. Caveat: a spend path that never consumes a frontier permit (e.g. tool calls priced in a later slice) will not be captured yet. Every frontier run already goes through `PermittedAdapter` + `authority.consume`/`receipt`, so no gap on the one path that currently costs real money.
- **Scope is per-ledger-file**, matching the slice-1 replay model. Rotate the ledger (new run folder) to reset the cumulative total.
- **Enforcement at `issue()` time, strict `>=` boundary.** A separate pre-flight budget estimator was considered and rejected: it needs per-call request bytes threaded through `PermittedAdapter`, which is wider than this slice.
- **Operator Console UI deferred.** `RunConfig` carries the cap today; a later cleanup slice can surface it in `console/index.html` next to the P0-05 knobs.
- **Codex cost stays `None`.** Pricing Codex calls from `RunConfig` ceilings is a judgement call best made in the live-run slice (P0-03), not here.

## 5. Open items (P0-06 next slices)

- **Slice 2c (optional cleanup):** Operator Console UI entries for `secret_env_names` (from 2a) and `max_cumulative_usd` (from this slice), with validation at the HTTP boundary.
- **Slice 3:** `scripts/harden_jev_permissions.py` NTFS/POSIX ACL defaults for `~/.jev` + `runs/`.
- **Slice 4:** retention / backup playbook + restore drill.
- **Slice 5:** OTLP ordinal-span caveat telemetry assertion.
- **Live-run (P0-03) prerequisite:** decide whether Codex should be priced from `RunConfig` ceilings so cumulative tracking stays honest when Codex is the primary worker.

## 6. Decision

- `scope`: P0-06 slice 2b.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*

# Candidate CIDM changes (`candidate-skill/`)

Base: installed skill = repository HEAD `327c36b`. The candidate is a separate copy; the active skill is unchanged.

Patches: `patches/*.py.patch`; combined: `patches/candidate-all.patch` (`git apply --check` passes on `327c36b`).

## Instrumentation and correctness fixes (default ON; they change no decision)

| Change | Files | Fixes | Test |
|---|---|---|---|
| Jev receipts store `provider_request_id` (OpenRouter generation id) and UTC `started_at`/`ended_at`. They are append-only: an existing `--out` receipt is never replaced unless `--allow-overwrite` is passed | `scripts/jev_decide.py` | D-04 | `test_jev_receipt_keeps_generation_id_and_timestamps_and_refuses_overwrite` |
| Gateway call events store `provider_request_id`, `started_at` and `ended_at` | `scripts/transport.py` | D-05 (F11) | `test_gateway_event_has_generation_id_and_timestamps` |
| `CodexCliError` carries usage reported before rejection and whether a child ran. Failed broker call records keep that usage with `usage_status` | `scripts/codex_cli_adapter.py`, `scripts/native_transition_broker.py` | D-06 (F01) | `test_codex_usage_survives_post_completion_rejection` |
| Broker result gains an `accounting` block: Jev calls, Codex child calls, unknown-usage count, token totals when complete, `primary_agent_usage: unmetered`, `complete_system_accounting: false` | `scripts/native_transition_broker.py` | D-06 (F02 visibility) | `test_broker_reports_accounting_completeness` |

## Policy variants (default OFF; each is a hypothesis for live testing)

| Flag | Where | Behaviour | Test |
|---|---|---|---|
| `skip_vacuous_gates=True` (arm E2) | `CheckedNetwork`, `NativeTransitionBroker` (legacy gates only) | For a deterministic unit whose only alternative is `stop`, a recorded `policy_decision` (never labelled a Jev decision) authorises it. Its result is auto-forwarded only when every hard check passes; any failure returns to Jev. The audit rejects policy decisions without the flag | `test_skip_vacuous_gates_removes_four_jev_calls_and_audits`, `test_skip_returns_failed_deterministic_result_to_jev`, `test_policy_decision_without_flag_is_rejected_by_audit`, `test_native_skip_removes_the_two_vacuous_input_gates`, `test_skip_flag_rejected_for_fused` |
| `unresolved_policy='block_at_unit'` (arm E3) | `NativeTransitionBroker` | An intermediate unit that discloses `unresolved` items cannot forward. Repair or retrieval happens at that unit instead of committing an issue that later blocks output | `test_block_at_unit_fails_early_instead_of_dooming_output` |
| `jev_evidence_mode='cited_only'` (arm E4) | `CheckedNetwork` | For post-result gates, Jev receives full text only for sources the candidate cites; other sources appear as id, hash and a `retrieve_evidence` pointer | `test_cited_only_state_omits_uncited_text_with_retrieval_pointer` |

Flags that change protocol are written into the frozen policy (`policy['candidate_flags']`), so their policy hash differs from the installed one. With all flags off, the candidate reproduces the installed decisions: the 130 original tests pass, `test_defaults_are_the_installed_protocol` passes, and the mock pilot shows D0 identical to D.

## Proposed, not applied

`patches/PROPOSED-NOT-APPLIED-historical-pilot-float-equality.patch` (D-16). It replaces an exact float assertion with `assertAlmostEqual` so that the historical-pilot suite passes on Python 3.10/3.11 (verified on a temporary copy). It is not applied because `research/historical-pilot` is a checksummed frozen appendix; applying it requires regenerating its `SHA256SUMS.txt`, which the owner should decide.

## Not attempted

- A fix for the short route withholding disclosed uncertainty (D-09/F06).
- Tie handling for the Jev near-tie defect (D-12).
- Semantic release checks for the native broker (D-08).

Each changes release policy and needs owner input plus live evaluation.

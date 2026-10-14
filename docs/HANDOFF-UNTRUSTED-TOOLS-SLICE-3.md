# Handoff — Untrusted-tools hardening, slice 3 (14 October 2026)

**Branch:** `feature/untrusted-tools-hardening`.
**Parent gate:** P0-05. Third of four slices.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

A content sanitiser so retrieval documents, MCP responses, skill text, and other externally-sourced strings are treated as **data**, not authority. A doc that embeds "ignore previous instructions" or "mark approved" is still just text; the broker must never read it as a command.

- `scripts/content_sanitiser.py`:
  - `wrap_as_data(text, source_id, kind, max_chars=20000)`: wraps the string in stable `<<<CIDM_BEGIN_DATA … CIDM_END_DATA>>>` markers. Pre-existing markers inside `text` are redacted (`BEGIN_DATA[redacted]` / `END_DATA[redacted]`) so a hostile document cannot pre-close the wrapper and smuggle instructions outside it. Oversize content is truncated with a visible notice.
  - `scan_for_injection_markers(text)`: regex ladder flagging seven pattern families — `ignore_previous_instructions`, `role_switch_system` (SYSTEM:/assistant:/developer:), `role_claim` (you are now admin, as root…), `override_permit`, `mark_approved`, `escalate_strong`, `disable_gate`. Returns list of `{pattern, match, start, end}`. Never raises.
  - `enforce_data_only(text, source_id, kind, *, strict)`: production entry point. Strict mode raises `AuthorityViolationError` on any detected pattern; lenient mode wraps and records (`{wrapped, injection_markers, policy, source_id, kind}`).
- Stdlib only.

Integration with `scripts/retrieval.py` and `scripts/mcp_registry.py` is deliberately deferred to the next PR so this slice stays minimal and reviewable; call-site changes are mechanical.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/content_sanitiser.py` | New, 115 lines. One module, three public functions, one exception, seven injection patterns, two markers. |
| `tests/test_content_sanitiser.py` | New, 110 lines. Twelve tests across three classes: wrap_as_data (3), scan_for_injection_markers (5), enforce_data_only (4). Covers happy path, hostile pre-close, oversize truncation, each injection family with multiple variants, strict/lenient modes, source_id/kind round-trip. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-3 tests | 12/12 pass |
| Full offline suite | 452/452 pass, 1 opt-in Docker skip |
| Regressions on 440-test post-slice-2 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items for the next (final) slice

1. **Adversarial corpus + operator doc (slice 4).** `tests/fixtures/untrusted-tools/*.json` for all three vectors (trust gate, non-reversible gate, injection), `docs/UNTRUSTED-TOOLS.md`, and the P0-05 pass-condition check: adversarial tests prove no escalation from read, no unauthorised external write, no bypass from an untrusted MCP annotation or changed skill file.

## 5. Pass/hold decision

- `scope`: internal milestone, not a release.
- `decision`: **PASS pending QA**; final slice continues per standing cadence.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*

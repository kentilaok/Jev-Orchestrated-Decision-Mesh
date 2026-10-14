# Handoff — Operator Console security HTML (15 October 2026)

**Branch:** `feature/console-security-html`, based on `main` at `b199c91` (via `feature/wire-console-broker-config`).
**Parent gate:** closes the HTML-binding carry-over so an operator can see and edit the P0-05 knobs + decide pending approvals from the browser.
**Evidence level:** offline tests + static HTML markers. No model calls.

## 1. What this slice delivers

A new **Security** section in the Operator Console that reads from and writes to the existing `/api/*` endpoints shipped in PR #12.

- **Nav:** new `data-view="security"` button; `titles` and `loaders` maps extended.
- **View body** (`<section id="view-security">`):
  - `#contentPolicy` `<select>` with `off` / `audit` / `wrap`.
  - `#requireActionApproval` checkbox.
  - `#trustedMcpServers` `<textarea>` (comma or newline separated).
  - `#saveSecurity` button writes all three via existing `POST /api/config`.
  - `#pendingApprovals` region lists records from `GET /api/approvals` with inline Approve/Reject buttons that POST to `/api/approvals/<token>`.
  - `#decidedApprovals` region shows the audit trail (operator + status) read-only.
- **New JS function `loadSecurity()`** registered in `loaders` so clicking the nav loads live data; Approve/Reject calls `prompt()` for the operator id, posts, then re-fetches.

The Approvals API already enforces loopback host + the Console-CSRF header; the HTML uses the existing `post()` helper that attaches both.

## 2. Code changes

| File | Change |
|---|---|
| `console/index.html` | +45 lines of HTML/JS. One new nav button, one new view section, one new `loadSecurity()` function registered in `loaders`, one `#saveSecurity` click handler. |
| `tests/test_console_security_html.py` | New, 40 lines. Six static-content assertions: nav button, section, three field ids, approvals region ids, `/api/approvals` fetch and `/api/approvals/` POST URLs present. |

## 3. Verification

| Check | Result |
|---|---|
| HTML marker tests | 6/6 pass |
| Full offline suite | 534/534 pass, 1 opt-in Docker skip |
| Regressions on 528-test post-PR#16 baseline | 0 |
| Live model calls | None |

Browser smoke not run from the suite (no headless browser installed), but the fetch targets match the existing security tests in `test_operator_console_security.py` + `test_console_security_knobs.py` which already exercise the backend behavior.

## 4. Open items

1. **Approval provenance** — Jev-signed evidence on strong permits (depth work).
2. **Fast Path admission with `calibration=null`**.
3. **P0-06 UI / credentials / recovery hardening** — new P0 gate, 3–4 slices.
4. **P0-01 CI billing banner**.

## 5. Decision

- `scope`: closes the HTML-binding carry-over flagged in PR #12 and later handoffs.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*

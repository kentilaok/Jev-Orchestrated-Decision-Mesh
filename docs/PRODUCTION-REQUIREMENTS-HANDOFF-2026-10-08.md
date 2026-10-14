# CIDM Arsenal V1 — Production Requirements and Release Handoff

**Date:** 8 October 2026  
**Author / thesis attribution:** Ken Caber (Kenneth Vic A. Caber)  
**Source branch:** `integration/arsenal-v1` — integration commit `db714f516854d6ee310bcffc931a9cd8a30dc0ea` before this handoff  
**Pull request:** [#3](https://github.com/kentilaok/Jev-Orchestrated-Decision-Mesh/pull/3)  
**Release status:** **HOLD — preproduction / experimental V1**. No production merge or production-acceptance claim until the gates below are satisfied.

This document supersedes informal assertions of "fully operational" V1. The integration built a substantial body of code and passed tests on the builder's workstation, but the recorded evidence does not yet demonstrate a secure, correct, economical **live** Jev + frontier + Hermes/tool execution workflow.

Refer also to [the original build handoff](HANDOFF-2026-10-08.md), [V1 component guide](ARSENAL-V1-BUILD.md), [Operator Console](OPERATOR-CONSOLE.md), [Claude Code adapter](CLAUDE-CODE.md) and [complete thesis](COMPLETE-THESIS.md).

## 1. Release status and evidence inventory

| Check | Evidence as at handoff | Release judgement |
|---|---|---|
| Python tests | Local builder reports 318 methods passed; 1 optional test skipped. Source contains 318 test methods. | **Local report only; independently rerun and archive logs** |
| Docker sandbox | Builder reports local `node:22-alpine` smoke test passed. | Reproduce in isolated test workspace |
| Research verifiers | Builder reports five verifier scripts and 40 historical-pilot tests passed. | Reproduce; no inference-quality claim follows |
| Old frozen inference audit | Historical audit suite 48/50; two tests intentionally expect old D-05/D-06 defects that have since been fixed. | Keep as historical evidence; do not call 50/50 passed |
| GitHub CI | [Workflow 37739388238](https://github.com/kentilaok/Jev-Orchestrated-Decision-Mesh/actions/runs/37739388238) failed on Python 3.10, 3.11, 3.12. The GitHub jobs API shows zero recorded steps for each. | **BLOCKER.** Inspect job annotations / repository Actions settings, rerun to green |
| Current live broker | No evidence of a live Jev + Codex or Claude run on the integrated branch. | **BLOCKER** |
| Hermes governed dispatch | Skills externally registered; management integration only. No permit-bound Hermes-execution adapter. | **BLOCKER to intended single-interface experience** |
| End-to-end model usage, cost, quality | No matched real-project accounting or controlled direct-agent comparison for integrated V1. | **Not proven** |
| Current `main` | Only the earlier reference code and published thesis. | Do not claim integration is on `main` until PR #3 passes release gates and is merged |

**Distinguish evidence levels:** implementation in source; offline/mock testing; local smoke testing; live provider integration; full user-journey acceptance; measured efficiency. One does not establish the next.

## 2. What actually exists

- **CIDM control:** native broker, five-unit Jev decisions, separate/fused/recovery gate modes, checked commits, typed receipts, native-call and permit audits.
- **Frontier clients:** `frontier_providers.py` and provider-specific Claude Code/Codex adapters, run/cancel/usage interface, Codex catalogue query, provider route preflight. Claude model presets remain unverified until a live route test.
- **Arsenal:** SQLite/FTS5 skill index, pinned skills, owner hash admission, experimental policy-controlled Fast Path executor, independent-review calibration ledger, experience distiller and semantic ranking.
- **Evidence/tools:** MCP catalogue and tool calls, local hybrid retrieval and optional Qdrant/hosted reranking, Docker sandbox, browser permit wrappers.
- **Durability/observability:** hash-bound recovery checkpoints, resumes in new run folders, hash-linked permit/calibration ledgers, JSON/OTLP telemetry.
- **Local UI:** Operator Console bound to `127.0.0.1:8765`, provider checks, route previews, explicit live-spend confirmation, run/recovery listings. Hermes dashboard skill toggles use Hermes' separate local dashboard API.

**Not integrated end-to-end:** Hermes as a permit-bound execution worker under Jev; unrestricted autonomous programming/project work; production service hosting; hosted Qdrant/Phoenix/E2B/Daytona provisioning; live benchmark-based safety or savings. The interactive Claude/Codex primary agent remains outside the controlled broker's permit boundary.

## 3. Required P0 release gates (all must pass)

### P0-01 — CI and reproducible artifacts

- Repair GitHub Actions runner/job provisioning or configuration. The last run failed **before reported steps**; do not misreport this as a Python assertion failure, and do not assume it is harmless.
- Get a **green** `3.10 / 3.11 / 3.12` test matrix, broker `--validate-only` checks, and all five pinned research verifiers.
- Re-run and archive the full local Windows Python suite, interpreter version, source commit SHA, elapsed time, exceptions, one optional skip and Docker smoke result. Keep authentic command output.
- Lock versions of optional FastEmbed/Playwright packages and the tested Claude/Codex/Hermes CLI versions. Pin third-party GitHub Actions by trusted immutable revisions before unattended use where possible.
- Produce one release manifest: commit SHA, system versions, test log checksums, required environment variables by **name only**, known open findings, rollback SHA and approving operator.

**Pass condition:** current PR head and intended release SHA match all verified logs; CI has no unresolved required checks.

### P0-02 — Task-specific correctness and evidence boundaries

The native broker's general `_validate_candidate` checks shape, hashes, parent links, and presence/absence of unresolved fields; it does **not** establish the truth of claims. Historical audit finding **D-08** remains relevant.

- Define task-specific deterministic postconditions for each production task class (for coding: build/test results, files changed, lints and independent acceptance criteria).
- Withhold release when citations are irrelevant, unresolved issues are concealed, or an intermediate unresolved result should block the current unit rather than waste downstream calls (D-09).
- Treat a model checker as additional evidence, never a substitute for deterministic acceptance tests.
- Test malicious prompts, contradictory sources, outdated skill versions, wrong project scope, invalid provider receipts and rollback after partial failure.

**Pass condition:** a known-wrong yet perfectly schema-compliant candidate **fails** the production-specific release checks.

### P0-03 — Live provider execution and accounting

Execute one capped **non-production** end-to-end test on each provider intended for launch, not on real customer systems:

1. Confirm account billing mode, live model ID, effort support and frozen route catalogue. For Claude, presets are not account attestation; verify actual `claude -p` model IDs before routing.
2. Verify one real Jev pre-dispatch decision, one appropriate Claude or Codex child with tools disabled/read-only, one return-to-Jev arbitration, and the final release audit.
3. Save provider request/response IDs when available, journal/permit hashes, source binding, model-reported usage, actual billing channel, rejection evidence and exit status.
4. Assert zero unauthorized calls, single-use permits, no missing required Jev decision, and no unvalidated artifact released.
5. Test provider unavailable, wrong model, schema-invalid response, low-budget stop and cancelled request; **no silent fallback**.
6. Account for all model work including any interactive primary host if that route is offered. Usage not reported is `unknown`, never zero.

**Pass condition:** signed-off live run and negative runs are auditable, repeatable and bounded by approved spending caps.

### P0-04 — Governed Hermes integration (for Hermes-first V1)

- Add a real **Hermes dispatch adapter**: Jev-approved exact task/scope/operation → single-use permit → bounded Hermes runtime/skill action → returned artifact + evidence/usage → validator → Jev acceptance.
- Hermes's chat UI, external skill registration and dashboard skill toggles **do not** satisfy this gate.
- Audit skills for prompt injection, command/network access, private data exposure and unpinned dependencies. Keep Matt Pocock skill authorship/license intact.
- Prove that an unapproved Hermes tool action cannot bypass Jev by using an ordinary Hermes conversation or a direct dashboard call.
- Register project-scoped skills separately from the global Arsenal admission policy; a Hermes-enabled skill is not a Fast Path-authorized skill.

**Pass condition:** complete **Hermes conversation → CIDM/Jev → approved Hermes procedure/frontier work → validators → Jev → result in same conversation** smoke and adversarial traces.

*If Hermes-first is explicitly deferred, label the release `CIDM broker V1`, not `integrated Hermes CIDM V1`.*

### P0-05 — Permissions and untrusted tools

- Treat third-party MCP `readOnlyHint` and tool-name heuristics as untrusted claims. Require an owner-verified tool/access map for consequential deployments, particularly where a declared read operation can run code or cause side effects.
- Require Jev-associated immutable evidence for **strong** action permits; a dictionary naming a Jev decision is not independent cryptographic proof of authorization. Revalidate identity and replay protection at the actual dispatcher boundary.
- Bind browser permissions to reviewed target elements/actions and destination origin. A label/selector keyword is **not** enough to classify a payment, delete, external submission or sensitive write.
- Keep Fast Path **disabled** for initial live pilot. The policy loader currently permits `calibration: null`; before any production Fast Path enablement, require a reviewed real-run calibration report (or an explicitly documented owner exception with narrower permitted operations), validated code paths, and independently verified postconditions.
- Reject nonreversible or non-allowlisted external actions until an operator explicitly approves them.
- Treat all retrieved documents, skill text, CLI outputs and MCP responses as **data**, never as authority to change these constraints.

**Pass condition:** adversarial tests prove no escalation from read, no unauthorized external write, no bypass from an untrusted MCP annotation or changed skill file.

### P0-06 — Local UI, credentials, audit logs and recovery

- Keep Operator Console **loopback-only**, off public interfaces. Current Host/Origin/custom-header guards are defense in depth, not authentication for a shared Windows workstation or remote service.
- Use dedicated OS account/file permissions for `~/.jev`, `runs/`, saved prompts, checkpoint JSON and logs. Do not put secrets in the repo, task JSON, screenshots, PRs or cloud telemetry.
- Verify secret references, process environment scrubbing, rotation procedure, provider account identity and spend alerts before granting persistent access.
- Restart and resume real paused runs; ensure old permits cannot be reused, stale input/skill snapshots are rejected and retries do not duplicate external effects.
- Establish retention periods and an access-controlled backup for permit, calibration, checkpoint and run evidence. Restore from backup in a scratch environment.
- OTLP exporter may report **ordinal** event timing rather than measured latency; do not use ordinal spans for p95 response-time claims.

**Pass condition:** a third party can replay release audits and recover from a paused state without exposing credentials or accidentally performing a consequential write.

### P0-07 — Full V1 readiness and performance acceptance

- Frozen project-task suite with at least three classes: simple deterministic, genuine multi-stage/recovery, and unknown/misleading source.
- Compare CIDM vs a competent direct Claude/Codex agent and, where appropriate, deterministic no-Jev rules.
- Score **verified output quality first**, then total usage and API charges, wall-clock time, model calls per role, retries, rejected candidates, failures and operator actions.
- Use independently reviewed results, report provider-specific and unknown usage honestly, and retain negative findings.
- Set a preregistered minimum sample size, risk thresholds and defined stop/go criteria. Historical toy arithmetic fixtures and mock audit runs do not establish current production improvement.

**Pass condition:** a signed, dated acceptance report records whether quality is non-inferior, operational safety holds, and whether any efficiency gain exists. Savings are not a V1 release claim until measured.

## 4. Windows workstation bootstrap — D:\\Hermes Jev CIDM

The working directory may already contain a clone and local edits. **Never discard local state automatically.** In PowerShell:

```powershell
Set-Location 'D:\Hermes Jev CIDM'
git status --short
git branch --show-current
git fetch origin --prune
git branch --list integration/arsenal-v1
```

If `integration/arsenal-v1` already exists locally:

```powershell
git switch integration/arsenal-v1
git pull --ff-only origin integration/arsenal-v1
```

Otherwise:

```powershell
git switch --track origin/integration/arsenal-v1
```

If the directory is not a Git clone, clone the project into an **empty** folder first; never use `git reset --hard` or `git clean -fdx` on a working installation without reviewed backups. This handoff is currently **on the integration branch, not `main`**. Do not replace the branch name with main until PR #3 actually merges.

Create a Python 3.11 environment (stdlib core; this is for reproducibility):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m compileall -q scripts tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/native_transition_broker.py --validate-only --gate-policy recovery --host claude --task examples/native-project.request.json
```

Inspect the test result; do not proceed to live spending if the suite fails. A separately maintained log of this command's stdout/stderr and its exit code is the acceptance evidence, not a self-reported success sentence.

Open the local Operator Console (no JavaScript compilation):

```powershell
.\.venv\Scripts\python.exe scripts/operator_console.py
```

Open `http://127.0.0.1:8765` **from the same trusted machine**. Use **Preview** and **Validate** first. Do not click Live Run until a capped, nonproduction test is explicitly approved.

Provider diagnostic commands (no Jev model calls):

```powershell
.\.venv\Scripts\python.exe scripts/frontier_providers.py status --provider claude
.\.venv\Scripts\python.exe scripts/frontier_providers.py status --provider codex
.\.venv\Scripts\python.exe scripts/frontier_providers.py models --provider codex
```

Hermes integration checks, when Hermes is installed and configured:

```powershell
.\.venv\Scripts\python.exe scripts/install_hermes_skill.py --dry-run
hermes dashboard --no-open
```

The installer without `--dry-run` can update Hermes's `config.yaml` and creates a backup. It should run only after confirming you want the external skill wrapper. It **does not** enable governed Hermes dispatch.

**Optional modules only as needed:** `fastembed==0.8.0` for CPU semantic retrieval; `playwright==1.62.0` plus Chromium for browser tools; Docker and local `node:22-alpine` for the opt-in sandbox test. There is no V1 requirement to run a local large language model or train a model on an RTX 3050.

## 5. Configuration, secrets and operational storage

| Requirement | Present state / owner task |
|---|---|
| `OPENROUTER_API_KEY` | Required for live Jev calls; keep in private OS environment or secret manager, not source files |
| Claude Code sign-in | Required if `--host claude`; verify actual served route/effort and whether an `ANTHROPIC_API_KEY` changes billing |
| Codex sign-in | Required if `--host codex`; refresh/check account model catalogue, no identity assumptions from stale cache |
| Hermes | Installed on build workstation per handoff, typically `%LOCALAPPDATA%\hermes`; inspect config/skill paths on the actual machine |
| `~/.jev/arsenal/arsenal.db` | Local SQLite; 68 indexed skills reported; **zero owner-admitted**; preserve its contents when updating Git |
| `~/.jev/arsenal/calibration.jsonl` | Requires independently adjudicated **live** run records for threshold decisions; protect and back up |
| `~/.jev/hermes-skills/` | External managed wrappers/approved skills; separate from core repo and global trust |
| `runs/` | Per-run journals/results/checkpoints; ignored by Git; protect, retain and back up for audit |
| MCP configs | Discover and classify, then explicitly verify access levels before starting real servers |
| Qdrant Cloud | Optional managed vector index; provision per namespace and access group if scaling needs it |
| Phoenix/OpenTelemetry | Optional monitoring; configure receiver, privacy filtering, storage and retention |
| Hosted reranker / remote sandbox | Optional; requires actual account, policy, endpoints and cost limits |

No passwords, tokens, OAuth cookies or raw private transcripts should be placed in this public repository or in a handoff.

## 6. Exact operational smoke sequence

**Offline (no paid model calls):**

1. Record Git branch + commit and Python/CLI versions.
2. Run `compileall`, the 318-method suite, verifier scripts and validate-only broker on a clean task.
3. Open Console, check Provider/Arsenal/MCP/Runs views, verify no model calls occurred.
4. Index a small fictional test skill and confirm that **not admitted** means Fast Path denied.
5. Check malformed input, tampered ledger, revoked permit, stale checkpoint and wrong-project-scope rejection.
6. Run optional network-disabled Docker smoke on a disposable checkout if Docker is installed.

**Live (requires separate owner approval of costs):**

1. Choose a fictional bounded task; save expected postconditions and ceiling on Jev/worker/checker calls and cost.
2. Confirm credentials, selected host model, route catalogue, and that existing test run data will not be overwritten.
3. Execute recovery mode with a **fresh** output folder, a permitted read-only worker, and explicit spend approval.
4. Inspect `result.json`, `journal.jsonl`, `permits.jsonl`, checkpoints and provider events; audit their hashes and usage.
5. Repeat negative cases in the test environment; do **not** switch to real data or enable mutation as part of initial validation.

**Only after P0:** consider a tagged V1 release, merged `main`, release notes, rollback drill and changes in owner-admitted skill/permission policy.

## 7. Historical inference audit: retain as research, exclude from runtime claims

The path `.cidm/studies/20260928T013651Z-cidm-inference-audit/` is a **September 28 historical research and patch-provenance snapshot**, **not** a dependency of the operational CIDM scripts.

At the integration commit it contains **232 tracked files (~5.2 MB)**, primarily archived mock runs and candidate code copies. It:
- checks prior public fixture receipts, records known defects D-01–D-20 and some reproducibility provenance;
- exposes the limitations of the former interactive-host measurements;
- contains mock benchmark results and historical pilot data **which do not measure complete V1 real-project worker or primary-host usage**;
- preserves the reasoning behind D-04/D-05/D-06 code hardening.

**Keep its `AUDIT.md`, `RESULTS.md`, `RESEARCH.md`, provenance and relevant manifests in Git history** (even if later removed from the current working tree). It has scientific/debugging value but should not be loaded into the live skill registry, retrieval namespace, or current analytics dashboard as operational outcome records.

For a lean runtime checkout, **no tool needs this study folder**; do not delete tracked files casually from an active Git worktree. If the repository needs slimming, make a separate, reviewed archival commit that keeps a short research index with links to the pinned historical commit and removes bulky mock/candidate duplicates from the current branch, preserving access in Git history. Do not modify the frozen study in place and then claim its original checksums still represent the original experiment.

Any new **true** usage study must collect host + Jev + worker + checker logs on matched **live** tasks, with call IDs, usage, prices, time and independent correctness checks; missing measurements remain `unknown`.

## 8. Known open issues from the inference audit

D-01/D-02/D-03/D-07 concern host-metering and Jev's authority for interactive agents; D-08/D-09 concern quality release and unresolved items; D-11/D-12/D-13 concern fused-option semantics and unstable Jev route choices. These require explicit resolution or tightly documented risk acceptance, with fresh regression evidence. D-04/D-05/D-06 instrumentation fixes are reported integrated; reproduce their behavior on current code.

The original audit's historical test failures should not be counted as new integration regressions. Conversely, changing old tests to green without preservation would invalidate study provenance.

## 9. Owner approval and merge decision template

Record an explicit dated acceptance decision after evidence is collected:

- `release_commit`: **actual immutable commit SHA**
- `release_scope`: `CIDM broker V1` **or** `CIDM + Hermes-integrated V1`
- `test_matrix`: links to green jobs and archived Windows logs
- `live_acceptance`: links to scrubbed real-provider run receipts and negative tests
- `security_review`: owner-approved MCP/browser/Fast Path policy and risk assessment
- `operational_review`: secret rotation, rollback, backup restore, telemetry, runbooks
- `performance_review`: explicit measured claim or "unmeasured"
- `reviewer`: approver identity
- `decision`: GO / HOLD, with outstanding blockers

**Current decision: HOLD.** No justified production merge of PR #3 exists yet. The handoff itself can be merged later with the code after gates clear.

### Rollback approach

Tag an approved release. Keep the last known-good commit and its database/backups. For a bad merge, prefer an auditable Git revert PR (not a destructive force-push of `main`), then restart only after verifying active-run and permit state. Git rollback alone does **not** roll back SQLite databases, issued permits, external API actions, secrets or queued workloads.

---

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber); third-party models, skills and packages retain their respective owners, authorship and licences.*

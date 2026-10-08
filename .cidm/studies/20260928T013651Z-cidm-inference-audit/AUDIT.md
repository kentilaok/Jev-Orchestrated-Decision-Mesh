# CIDM inference audit: architecture, evidence and defects

**Study:** `20260928T013651Z-cidm-inference-audit` · started 2026-09-28T01:36:51Z (container clock, UTC)
**Subject:** Caber Interstitial Decision Mesh (CIDM), attributed in this project to Kenneth Vic A. Caber (older files: "Kenneth A. Caber"). This audit investigates the design; it asserts no scientific priority or patentability.

## 0. Bottom line

- **Evidence counts are accurate.**
  - Every numeric claim in the published evidence reproduces exactly from the raw receipts: 59 claims, 0 mismatches.
  - Every price row reproduces every recorded charge exactly (122/122).
  -  [withheld: private project evidence]
- **The complete system is not metered.** What is missing is the primary Codex host, the workers and the checkers.  [withheld: private project evidence]
- **Jev's decisions are advisory in the route actually used.** The broker that enforces them in code [withheld: private project evidence].
- **No valid savings claim is possible yet.** No run anywhere measures CIDM against a competent direct model or a no-Jev cascade on matched tasks with complete accounting. The one matched fixture shows the five-unit graph costing 1.81–3.72× a single Sol-high call for the same correct answer.

## 1. Scope, environment and evidence inventory

| Item | Finding |
|---|---|
| Execution environment | Linux cloud container (Python 3.10–3.13 available; 3.11 default). The operator's Windows `SKILL_ROOT` and `EVIDENCE_ROOT` [withheld: private project evidence] are **not reachable** from here. |
| Repository | `kentilaok/Jev-Orchestrated-Decision-Mesh`, HEAD `327c36b` (2026-09-24 00:38 +08:00), clean before this study. File hashes: `provenance/repo-file-sha256.txt`. |
| Installed skill |  [withheld: private project evidence] |
| Project evidence (`.cidm`) |  [withheld: private project evidence] |
| Codex host telemetry | None anywhere in the evidence. No Codex CLI or App Server is installed in this container, so local Codex schemas could not be inspected. |
| Network | Egress to provider/doc hosts denied by environment policy; see RESEARCH.md. **No live model calls were made by this study.** |
| Budget | No approved study budget was found, so live spend defaulted to **$0**. |

Baseline tests (unchanged code): 130/130 pass on Python 3.10, 3.11, 3.12 and 3.13. The historical-pilot appendix passes 40/40 on Python 3.12/3.13 but **fails 1 test on 3.10/3.11**. The failing test uses exact float equality, and Python 3.12 changed `sum()` to compensated summation (D-16). See `provenance/python-version-matrix.txt`.

## 2. What exists versus what runs

| Component | Code | Enforces Jev's choice? | Used in recorded work |
|---|---|---|---|
| `SKILL.md` instructions to the Codex primary agent | SKILL.md:14–58 | **No.** "a skill-guided procedure, not automatic control over the primary agent" (SKILL.md:22) |  [withheld: private project evidence] |
| `scripts/jev_decide.py` one-shot Jev CLI | jev_decide.py:224–276 | No; it returns a choice to whoever called it |  [withheld: private project evidence] |
| `scripts/native_transition_broker.py` (Codex CLI children) | :110–469 | **Yes, for the children it launches** (single-use permits, atomic_mesh.py:133–153) |  [withheld: private project evidence] |
| `scripts/network_run.py` / `adaptive_run.py` (OpenRouter) | checked_network.py, transport.py | Yes, for its own API calls | Public GPT-6 fixture runs only (research/live-gpt6-*) |
| `scripts/fused_checked_network.py` | :18–403 | Yes | Offline tests only [withheld: private project evidence] |

## 3. Reconstructed call paths

### 3.1 Interactive route (the one actually used)

1. **Input and classification by the host LLM.** The host classifies "each new user input together with the carried project context" (SKILL.md:14). This is "a host assertion, not a Jev decision" (SKILL.md:24).
2. **Evidence preflight by the host** before the first Jev decision (SKILL.md:16): the host reads connectors and sources, then writes "a concise source-linked evidence packet". This is host reading and summarisation before Jev sees anything.
3. **The host writes the Jev request by hand.** It chooses `state` (objective, facts, constraints, remaining budget) and the **option menu**.  [withheld: private project evidence]
4. **Jev call.** `jev_decide.py` validates the request (:78–112), calls OpenRouter's decision endpoint (:192–207) and writes a receipt (:210–221) that **omits the provider generation id** (:256–261) and **silently replaces an existing receipt file** (`os.replace`, :218).
5. **The host executes the chosen option.** "Deterministic" means the host does the work itself. A worker route means the host asks a Codex subagent with the requested model/effort; nothing verifies the served identity.
6. **Validation.** The host judges the result, writes the next Jev request, and after the final gate composes the answer shown to the user.

**Short path:** host classification → one requested Luna-low subagent → host validation → answer. There is no Jev call and no saved request or response. [withheld: private project evidence]

### 3.2 Broker route (implemented, controls only its children)

`validate_spec` (native_transition_broker.py:29–84) binds a host classification to the input hash, but "Classification truth remains a host assertion". On the broad route, the flow is:

1. `CheckedNetwork` or `FusedCheckedNetwork` (:422–431) asks `_judge` (:142–172) at every gate.
2. `_codex` (:174–216) runs `codex exec --json --ephemeral -s read-only -m <model> -c model_reasoning_effort=<effort>` (codex_cli_adapter.py:276–280).
3. `_validate_candidate` (:299–336) runs the hard checks.
4. On completion, `audit_network`/`audit_fused_network` plus `audit_native_calls` run before release (:434–448).

The primary agent that prepared the spec and reads the result is outside this control boundary (SKILL.md:20).

### 3.3 Answers to the call-path questions

| Question | Answer (evidence) |
|---|---|
| Is Jev's decision enforced by executable dispatch code? | **Only inside the broker and the OpenRouter runners**, through single-use permits bound to the chosen option (atomic_mesh.py:133–153; F14 shows a mutated route catalogue halts the run). In the interactive route, **no**: the host writes the menu, calls Jev, and chooses whether to comply. [withheld: private project evidence] |
| What can the host do without mediation? | Before the first gate: classify, inspect sources, summarise evidence, write every state capsule and option menu (§3.1). Between gates: all "deterministic" work, reading, coding, testing, deploying [withheld: private project evidence]. After gates: rewrite the accepted answer.  [withheld: private project evidence] |
| Who performs work labelled "deterministic"? | SKILL.md:52 defines it correctly: fixed code on frozen inputs.  [withheld: private project evidence] In the public fixtures, "deterministic" units are genuinely fixed Python (network_run.py:41–48). |
| Does a route select a real provider/model/effort? | **OpenRouter runners:** the model and provider are pinned, fallbacks are disallowed, and the returned model and provider are validated (transport.py:128–143, 162–165). **Effort** is sent (`reasoning.effort`, transport.py:268) but no saved provider response contains an effort field, so `confirmed_effort` is unavailable for every worker and checker call. **Codex route:** "requested_only" identity unless the stream reports a model (codex_cli_adapter.py:344–349; F03).  [withheld: private project evidence] |
| Does the host duplicate or rewrite work? Does it pre-solve? |  [withheld: private project evidence] Pre-solving is built into the policy: the evidence preflight (SKILL.md:16) and host classification (SKILL.md:24) happen before any Jev decision. |
| Are before/after gates separate decisions, and could fusion lose information? | They are separate calls in the legacy protocol (checked_network.py:153, 191). The fused protocol merges "accept this result" with "authorise next route" into one categorical menu (fused_checked_network.py:210–261). **It is not information-preserving:** a passing candidate loses the `repair` and `escalate` options (:237, F08). The menu grows to 11 options, so an argmax can select a minority action while 88% of the mass favours "accept" (F09). Fusion does not merge a future-dependent decision into an earlier call, because the next route is chosen after the result. |

### 3.4 Observable transitions and bundles (definitions used for gate coverage)

- **Semantic transition:** a point where a new artifact would be accepted into project state, a model route would be dispatched, or an external or irreversible action would start.
- **Deterministic bundle:** a sequence of fixed-code operations on frozen inputs with no model choosing, interpreting, writing or judging, whose outputs are checkable by fixed assertions. Under this definition, "run the given test suite" is a bundle; "inspect the guards and write a handoff" is not.
- **Observed gate coverage:** Jev decisions per semantic transition. More gates are not better. A gate whose only non-terminal option is fixed code (checked_network.py:145–153 for `input` and `hidden2`) is **vacuous**. In the two public conditional runs these were 4 of 10 Jev calls and 26.6% of Jev tokens (`reconciliation/jev-decision-analysis.json`).

### 3.5 Context transfer

- The legacy controller sends **all source text** to Jev at every gate (checked_network.py:64); nothing is compressed.
- Hash-only references do not transfer meaning.  [withheld: private project evidence] The native broker asks workers to echo `required_source_hashes` and `required_parent_hashes` (:362, :406). Its hard checks then compare the echo (:333–334), so an answer with no content passes (F04).

## 4. Historical ledgers

### 4.1 Public evidence (repository `research/`)

`harness/reconcile_ledgers.py` rebuilt 123 events from raw request/response bytes (`reconciliation/events.reconstructed.jsonl`):

- **Integrity.** All five `SHA256SUMS.txt` inventories verify, with no uncovered files. Every GPT-6 request hash and every historical request hash, generation id and usage matches its raw file.
- **Claims.** 59 README/doc claims (calls, tokens, cost, latency, per-role splits) all match. One is partial by disclosure: attempt A's $0.000093534 excludes a failed checker whose usage was never returned.
- **Dedupe.** `combined-ledger.jsonl` duplicates the split ledgers 60/60; they are resolved by generation id. Four groups of **byte-identical requests are distinct billed calls** with different generation ids. Deduping by prompt hash would have deleted real charges.
- **Pricing.** Snapshot rates reproduce 122/122 charges. The historical Azure route billed GPT-5.6 Sol at $5/$30 per M, 2.5–3× the same model's OpenAI endpoint listing. Price by the served endpoint, not the model.
- **Cache premium (new finding).** The historical pilot billed 51,411 cache-write tokens at 1.25× input and read none. Its harness normalisation dropped `cache_write_tokens` (kept only in `usage_raw`). Removing the unrecouped premium from both arms changes the reported CIDM cost saving from **9.6% to 2.9%**, so about 70% of the reported difference came from Arm A's longer prompts attracting provider cache writes. This is a derived sensitivity, not a causal effect.
- **Provenance (new finding).** Rebuilding the GPT-6 conditional runs' Jev requests byte-for-byte (10/10; 9/10 for the pre-hardening run) requires the **saved** configuration, not `RunConfig` from any commit. That configuration lacks `max_jev_calls`, `max_jev_tokens`, `max_worker_calls` and `max_checker_calls`, which exist at every commit from `9a56346`. The runs were made with uncommitted code, and the role caps documented in VALIDATION.md were **not in force** during them (F15).
- **Jev behaviour.**
  - Byte-identical `authorize_unit` requests for the Interpret unit returned luna_low 0.55 in one run and sol_low 0.50 in the other.
  - That flip, not a prompt change, sent the second run to a worker about 16× more expensive for that unit, although Luna-low had passed the same checks.
  - `confidence = (k·p_max − 1)/(k − 1)` fits all 63 public Choice answers (max error 0.0175).
  - Every route decision in the three five-unit runs had p(choice) ≤ 0.59.

 [withheld: private project evidence]

## 5. Defect register

Severity reflects impact on the study question: can CIDM's efficiency be measured and trusted?

| ID | Sev | Defect | Evidence | Status |
|---|---|---|---|---|
| D-01 | High | Primary-agent (host) model work is unmetered; "deterministic" routes conceal it | SKILL.md:52 rule unenforced [withheld: private project evidence] | Open. Needs Codex host telemetry capture or routing that work through metered workers |
| D-02 | High | Jev decisions are advisory in the interactive route; the host writes state and menus and chooses compliance | SKILL.md:22; §3.1 [withheld: private project evidence] | Open (design). Use the broker, or treat interactive runs as observational only |
| D-03 | High | Worker and checker usage and served identity unrecorded for host subagents |  [withheld: private project evidence] SKILL.md:20 | Open |
| D-04 | Med | `jev_decide.py` drops the provider generation id, records no timestamps, and overwrites existing receipts | jev_decide.py:218, 256–261 | **Fixed in candidate** (default on) |
| D-05 | Med | Gateway events lack generation id and timestamps; no wall-clock record in any GPT-6 run | transport.py:186–196; F11 | **Fixed in candidate** |
| D-06 | Med | Codex adapter discards reported usage when a completed child's artifact is rejected; missing usage is accepted as an ok call | codex_cli_adapter.py:336–343; native_transition_broker.py:208; F01, F02 | **Fixed in candidate** (usage kept plus `usage_status`); F02 surfaced in the `accounting` block |
| D-07 | Med | Remaining budget in the Jev state is typed by the host and drifts from receipts | SKILL.md:57 [withheld: private project evidence] | Open for the interactive route (the broker derives it: native_transition_broker.py:122–140) |
| D-08 | Med | Native broker hard checks are structural echoes; an answer with no content is released | :299–336; F04 | Open (docs admit "structural"; the release gate treats them as sufficient) |
| D-09 | Med | Honest `unresolved` disclosure in an intermediate unit commits, then makes the output unreleasable: 12 more calls wasted in the mock trace (F05). The short route withholds disclosed uncertainty but releases concealment (F06) | :330–336 | F05: candidate flag `unresolved_policy=block_at_unit` (E3); F06 open |
| D-10 | Low-Med | Vacuous gates for deterministic units | checked_network.py:145–153; F07; 26.6% of Jev tokens in public fixtures | Candidate flag `skip_vacuous_gates` (E2) |
| D-11 | Med | Fused protocol changes option semantics (no repair or escalate for passing candidates) and flattens a joint decision into up to 11 options | fused_checked_network.py:210–261; F08, F09 | Open; confounds fused-vs-legacy comparisons |
| D-12 | Med | Jev near-tie defect (`choice` 0.01 below argmax) fails the run after billing | jev_decide.py:169; F10 [withheld: private project evidence] | Open |
| D-13 | Med | Route choice is near coin-flip (p(choice) 0.50–0.59) and not reproducible on byte-identical input; two runs of the same fixture differed 2.06× in cost, and their first divergence was a route flip on an identical request | reconciliation/jev-decision-analysis.json | Open (evidence against relying on zero-shot routing) |
| D-14 | Low | Published live runs used uncommitted code without the documented role caps | F15 | Open (disclosure) |
| D-15 | Low | Historical pilot normalisation dropped cache-write tokens; the premium explains ~70% of the reported cost gap | §4.1 | Open (disclosure) |
| D-16 | Low | Historical-pilot test fails on Python 3.10/3.11 despite "3.10+" | provenance/python-version-matrix.txt | Patch proposed, **not applied** (frozen checksummed appendix) |
| D-17 | Low | Broker reserves source ids `request`, `context` and `outstanding`; tasks using them are rejected | :44–59 (found by fixture CDR-D1) | Open |
| D-18 | Low | Requested effort is never confirmed by any provider response; Codex identity is requested-only | F03; model-registry.json | Provider limitation; record as `unavailable` |
| D-19 | Info | Short-path runs leave no request or response record |  [withheld: private project evidence] | Open |
| D-20 | Info | Jev `confidence` is a rescaling of p_max, not a success probability | F16 | Documentation only; no code uses it for gating |

**Controls that worked as designed (positive controls):**
- Single-use, state-bound permits, and halting on a mutated route catalogue (F14).
- Rejection of injected, unlisted routes (F12).
- Fail-closed transport on HTTP-200 error bodies, missing usage, model or provider mismatch, and price-ceiling breach (existing `tests/test_transport.py`).
- Identity pinning with fallbacks disallowed, and checksum-verified evidence bundles.

Manipulation *within* the offered menu (e.g. `stop`) is not detectable by the controller (F13).

## 6. Unknowns (not resolved by this study)

- Primary-agent, worker and checker tokens, cost, served identity and latency for every project run. These cannot be recovered from local records; they need Codex session telemetry, if the installed Codex version retains it.
- Whether any overwritten `jev_decide.py` receipt hid a billed call. This needs the OpenRouter activity or generation export for the study window.
- Full-text verification of R1–R12 (egress blocked).
- Codex CLI/App Server event schemas for the installed version (no Codex installation here).
- Any live quality, cost or latency comparison of CIDM arms. Not run: zero approved budget, no credentials, egress blocked.

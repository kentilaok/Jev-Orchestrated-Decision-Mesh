# Handoff — Retriever per-chunk content wrapping (14 October 2026)

**Branch:** `feature/retriever-chunk-wrapping`, based on `main` at `2f42966`.
**Parent gate:** closes the retrieval half of the P0-05 "shape only" caveat.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

`RetrievalEvidenceRetriever.__call__` now honours its `content_policy` kwarg per chunk:

- `off` (default): behaviour unchanged.
- `audit`: scans each chosen chunk for injection patterns and records per-chunk entries on `receipt['injection_markers']`. Text is not altered.
- `wrap`: scans + wraps each chunk's text in `<<<CIDM_BEGIN_DATA source=retrieval:<chunk_id> kind=retrieval_chunk … CIDM_END_DATA>>>` so downstream consumers see every chunk as inert data.
- `content_hashes` on the receipt are computed from the **pre-wrap** text so replay/dedup is unaffected by the sanitiser.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/retrieval.py` | +14 lines in `__call__`. Pre-wrap-hash first, scan per chunk, optionally rewrite `source["text"]`. Lazy-imports `content_sanitiser` so the dependency is not required unless opted in. |
| `docs/UNTRUSTED-TOOLS.md` | Updated §5(1) to mark the retriever half closed. |
| `tests/test_retriever_chunk_wrapping.py` | New, 115 lines. Five tests: default off leaves text raw and no markers field; audit records per-chunk markers without altering text; wrap wraps each chunk's text with the correct source/kind metadata; `content_hashes` stay identical between `off` and `wrap` for the same input; wrap records markers for audit alongside the wrapped text. |

## 3. Verification

| Check | Result |
|---|---|
| Chunk-wrapping tests | 5/5 pass |
| Full offline suite | 486/486 pass, 1 opt-in Docker skip |
| Regressions on 481-test post-PR#9 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items

1. **Operator Console UI** for `content_policy`, `trusted_servers`, `require_action_approval`, and the strong-permit approval flow.
2. **Approval provenance** — Jev-associated immutable evidence on strong permits (`UNTRUSTED-TOOLS.md` §5(4)).
3. **Fast Path admission with `calibration=null`** — still open per `UNTRUSTED-TOOLS.md` §5(5).

## 5. Decision

- `scope`: follow-up PR; closes the retrieval half of the P0-05 "shape only" caveat.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*

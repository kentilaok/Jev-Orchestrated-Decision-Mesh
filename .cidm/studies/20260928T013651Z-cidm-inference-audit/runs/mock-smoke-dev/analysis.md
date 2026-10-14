# Analysis of `mock-smoke-dev`

**Evidence status:** MOCK: harness validation only

Attempts 70; events 670; schema-invalid events 0.

| Arm | Accepted | Critical (95% UB) | Cost/attempt | Cost/accepted | Jev | Worker | Host | Strong | Median wall ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A A_direct_sol_medium | 7/7 | 0 (0.35) | 0.00511 | 0.00511 | 0 | 7 | 0 | 0 | 1 |
| B B_cascade_luna_low_to_sol_medium | 5/7 | 0 (0.35) | 0.00013 | 0.00018 | 0 | 7 | 0 | 0 | 1 |
| C C_router_only_jev | 5/7 | 0 (0.35) | 0.00047 | 0.00066 | 7 | 7 | 0 | 0 | 1 |
| D D_installed_cidm_legacy | 4/7 | 0 (0.35) | 0.01051 | 0.01840 | 66 | 25 | 8 | 0 | 71 |
| D0 D0_candidate_code_all_flags_off | 4/7 | 0 (0.35) | 0.01051 | 0.01840 | 66 | 25 | 8 | 0 | 69 |
| E1 E1_fused_gates | 4/7 | 0 (0.35) | 0.01156 | 0.02022 | 36 | 25 | 8 | 0 | 63 |
| E2 E2_skip_vacuous_gates | 4/7 | 1 (0.52) | 0.01223 | 0.02141 | 54 | 25 | 8 | 0 | 71 |
| E3 E3_block_unresolved_at_unit | 4/7 | 1 (0.52) | 0.01064 | 0.01862 | 66 | 25 | 8 | 0 | 67 |
| E4 E4_cited_only_jev_state | 4/7 | 1 (0.52) | 0.01049 | 0.01836 | 66 | 25 | 8 | 0 | 71 |
| E5 E5_combined_E2_E3_E4 | 4/7 | 1 (0.52) | 0.01115 | 0.01951 | 54 | 25 | 8 | 0 | 65 |

| Hypothesis | Comparison | Tasks | Accept diff [95% CI] | Saving/accepted [95% CI] | Holm p |
|---|---|---:|---|---|---:|
| H1 | D vs A | 7 | -0.429 [-0.857, -0.143] | -2.601 [-8.034, -0.879] |  |
| H2 | D vs B | 7 | -0.143 [-0.571, +0.286] | -103.741 [-295.706, -38.181] | 1.0 |
| H3 | C vs B | 7 | +0.000 [+0.000, +0.000] | -2.759 [-8.313, -0.165] | 1.0 |
| H4 | D0 vs D | 7 | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | 1.0 |
| H5 | E1 vs D | 7 | +0.000 [+0.000, +0.000] | -0.099 [-0.383, +0.120] | 1.0 |
| H6 | E2 vs D | 7 | +0.000 [+0.000, +0.000] | -0.163 [-0.507, +0.061] | 1.0 |
| H7 | E3 vs D | 7 | +0.000 [+0.000, +0.000] | -0.012 [-0.296, +0.274] | 1.0 |
| H8 | E4 vs D | 7 | +0.000 [+0.000, +0.000] | +0.002 [-0.232, +0.202] | 1.0 |
| H9 | E5 vs D | 7 | +0.000 [+0.000, +0.000] | -0.060 [-0.391, +0.188] | 1.0 |

Primary decision (H1): **no_advantage_or_inconclusive** — exploratory: the preregistered power requirement (~314 tasks) is not met.

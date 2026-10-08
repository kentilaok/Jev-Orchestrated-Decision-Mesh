# Analysis of `mock-pilot-heldout`

**Evidence status:** MOCK: harness validation only

Attempts 360; events 3417; schema-invalid events 0.

| Arm | Accepted | Critical (95% UB) | Cost/attempt | Cost/accepted | Jev | Worker | Host | Strong | Median wall ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A A_direct_sol_medium | 32/36 | 1 (0.13) | 0.00704 | 0.00791 | 0 | 37 | 0 | 0 | 1 |
| B B_cascade_luna_low_to_sol_medium | 22/36 | 3 (0.20) | 0.00035 | 0.00058 | 0 | 37 | 0 | 0 | 1 |
| C C_router_only_jev | 24/36 | 4 (0.24) | 0.00169 | 0.00254 | 36 | 37 | 0 | 0 | 2 |
| D D_installed_cidm_legacy | 21/36 | 7 (0.33) | 0.01530 | 0.02623 | 330 | 126 | 48 | 0 | 66 |
| D0 D0_candidate_code_all_flags_off | 21/36 | 7 (0.33) | 0.01530 | 0.02623 | 330 | 126 | 48 | 0 | 68 |
| E1 E1_fused_gates | 22/36 | 4 (0.24) | 0.01377 | 0.02253 | 180 | 126 | 48 | 0 | 69 |
| E2 E2_skip_vacuous_gates | 17/36 | 6 (0.30) | 0.01479 | 0.03131 | 270 | 126 | 48 | 0 | 68 |
| E3 E3_block_unresolved_at_unit | 20/36 | 3 (0.20) | 0.01483 | 0.02669 | 330 | 126 | 48 | 0 | 66 |
| E4 E4_cited_only_jev_state | 19/36 | 7 (0.33) | 0.01490 | 0.02824 | 330 | 126 | 48 | 0 | 67 |
| E5 E5_combined_E2_E3_E4 | 21/36 | 3 (0.20) | 0.01488 | 0.02551 | 270 | 126 | 48 | 0 | 67 |

| Hypothesis | Comparison | Tasks | Accept diff [95% CI] | Saving/accepted [95% CI] | Holm p |
|---|---|---:|---|---|---:|
| H1 | D vs A | 12 | -0.306 [-0.556, -0.056] | -2.314 [-4.002, -1.411] |  |
| H2 | D vs B | 12 | -0.028 [-0.333, +0.250] | -44.448 [-109.069, -20.914] | 1.0 |
| H3 | C vs B | 12 | +0.056 [-0.083, +0.194] | -3.401 [-8.028, -0.972] | 1.0 |
| H4 | D0 vs D | 12 | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | 1.0 |
| H5 | E1 vs D | 12 | +0.028 [-0.083, +0.139] | +0.141 [-0.024, +0.312] | 0.3712 |
| H6 | E2 vs D | 12 | -0.111 [-0.250, +0.028] | -0.194 [-0.693, +0.110] | 1.0 |
| H7 | E3 vs D | 12 | -0.028 [-0.250, +0.194] | -0.017 [-0.527, +0.355] | 1.0 |
| H8 | E4 vs D | 12 | -0.056 [-0.222, +0.083] | -0.077 [-0.393, +0.160] | 1.0 |
| H9 | E5 vs D | 12 | +0.000 [-0.222, +0.222] | +0.027 [-0.453, +0.348] | 1.0 |

Primary decision (H1): **harmful** — exploratory: the preregistered power requirement (~314 tasks) is not met.

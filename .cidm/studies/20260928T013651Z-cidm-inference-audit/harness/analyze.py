"""Paired analysis of a benchmark run (standard library only).

    python -B analyze.py --run <study>/runs/<run> [--baseline A] [--primary D]

Writes analysis.json and analysis.md next to results.csv. Every number is labelled
with the run's record_kind (mock results are harness validation, not evidence).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cidm_accounting as acc  # noqa: E402


def binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def upper_bound(failures, n, alpha=0.05):
    """Exact one-sided (1-alpha) Clopper-Pearson upper bound."""
    if n == 0:
        return None
    if failures >= n:
        return 1.0
    lo, hi = failures / n, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if binom_cdf(failures, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def holm(pvalues):
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted, running = [None] * len(pvalues), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvalues) - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def per_task(rows, arm):
    """Task-level means over repetitions (repetitions are not independent tasks)."""
    grouped = defaultdict(list)
    for r in rows:
        if r["arm_id"] == arm:
            grouped[r["task_id"]].append(r)
    out = {}
    for task, rs in grouped.items():
        costs = [float(r["charge_usd"]) for r in rs if r["charge_usd"] not in ("", "None")]
        out[task] = {"accept": sum(r["accepted"] == "True" for r in rs) / len(rs),
                     "cost": sum(costs) / len(costs) if len(costs) == len(rs) else None,
                     "cost_total": sum(costs) if len(costs) == len(rs) else None,
                     "accepted_n": sum(r["accepted"] == "True" for r in rs), "n": len(rs),
                     "critical": sum(bool(r["critical_failures"]) for r in rs),
                     "wall": statistics.median(float(r["wall_ms"]) for r in rs if r["wall_ms"] not in ("", "None"))}
    return out


def paired(rows, candidate, baseline, replicates, seed):
    a, b = per_task(rows, candidate), per_task(rows, baseline)
    tasks = sorted(set(a) & set(b))
    if not tasks:
        return None
    rng = random.Random(seed)

    def stats(sample):
        d_acc = sum(a[t]["accept"] - b[t]["accept"] for t in sample) / len(sample)
        ca = [a[t]["cost_total"] for t in sample]
        cb = [b[t]["cost_total"] for t in sample]
        acc_a = sum(a[t]["accepted_n"] for t in sample)
        acc_b = sum(b[t]["accepted_n"] for t in sample)
        if None in ca or None in cb or acc_a == 0 or acc_b == 0:
            return d_acc, None
        return d_acc, acc.savings(sum(ca) / acc_a, sum(cb) / acc_b)
    point = stats(tasks)
    boots = [stats([rng.choice(tasks) for _ in tasks]) for _ in range(replicates)]
    d = [x[0] for x in boots]
    s = [x[1] for x in boots if x[1] is not None]
    p_acc_le_0 = sum(x <= 0 for x in d) / len(d)
    p_sav_le_0 = sum(x <= 0 for x in s) / len(s) if s else None
    return {"tasks": len(tasks), "accept_diff": point[0], "accept_diff_ci95": [quantile(d, 0.025), quantile(d, 0.975)],
            "saving_cost_per_accepted": point[1],
            "saving_ci95": [quantile(s, 0.025), quantile(s, 0.975)] if s else None,
            "bootstrap_p_saving_le_0": p_sav_le_0, "bootstrap_p_accept_diff_le_0": p_acc_le_0,
            "undefined_saving_resamples": len(boots) - len(s)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="A")
    parser.add_argument("--primary", default="D")
    parser.add_argument("--replicates", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=1729)
    args = parser.parse_args(argv)
    experiment = json.loads((HERE.parent / "EXPERIMENT.json").read_text(encoding="utf-8"))
    arm_ids = {k: v["arm_id"] for k, v in experiment["arms"].items()}
    rows = list(csv.DictReader((args.run / "results.csv").open(encoding="utf-8")))
    events = [json.loads(l) for l in (args.run / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = sorted({r["record_kind"] for r in rows})
    schema_issues = sum(bool(acc.validate_event(e)) for e in events)
    arms = {}
    for key, arm in arm_ids.items():
        rs = [r for r in rows if r["arm_id"] == arm]
        if not rs:
            continue
        costs = [float(r["charge_usd"]) for r in rs if r["charge_usd"] not in ("", "None")]
        total = sum(costs) if len(costs) == len(rs) else None
        accepted = sum(r["accepted"] == "True" for r in rs)
        crit = sum(bool(r["critical_failures"]) for r in rs)
        walls = [float(r["wall_ms"]) for r in rs if r["wall_ms"] not in ("", "None")]
        shares = {}
        for actor in ("host", "jev", "worker", "checker", "compressor"):
            vals = [r[actor + "_charge"] for r in rs]
            known = [float(v) for v in vals if v not in ("", "None")]
            shares[actor] = (sum(known) / total if total else None) if len(known) == len(vals) else None
        by_family = defaultdict(lambda: [0, 0])
        for r in rs:
            by_family[r["family"]][0] += r["accepted"] == "True"
            by_family[r["family"]][1] += 1
        arms[key] = {"arm_id": arm, "attempts": len(rs), "accepted": accepted, "accepted_rate": accepted / len(rs),
                     "accepted_by_family": {f: f"{a}/{n}" for f, (a, n) in sorted(by_family.items())},
                     "critical_failures": crit, "critical_upper_bound_95": upper_bound(crit, len(rs)),
                     "total_charge_usd": total, "cost_per_attempt": total / len(rs) if total is not None else None,
                     "cost_per_accepted": acc.cost_per_accepted(total, accepted),
                     "charge_share_by_actor": shares,
                     "jev_calls": sum(int(r["jev_calls"]) for r in rs), "worker_calls": sum(int(r["worker_calls"]) for r in rs),
                     "host_calls": sum(int(r["host_calls"]) for r in rs), "checker_calls": sum(int(r["checker_calls"]) for r in rs),
                     "strong_model_calls": sum(int(r["strong_model_calls"]) for r in rs),
                     "unknown_charge_calls": sum(int(r["unknown_charge_calls"]) for r in rs),
                     "wall_ms_median": statistics.median(walls) if walls else None, "wall_ms_p90": quantile(walls, 0.9)}
    comparisons, pvals, names = {}, [], []
    base = arm_ids[args.baseline]
    for hyp in [experiment["hypotheses"]["primary"]] + experiment["hypotheses"]["secondary"]:
        cand_key, base_key = [x.strip() for x in hyp["comparison"].split(" vs ")[:2]]
        base_key = base_key.split()[0]
        if cand_key not in arms or base_key not in arms:
            continue
        result = paired(rows, arm_ids[cand_key], arm_ids[base_key], args.replicates, args.seed)
        if result is None:
            continue
        comparisons[hyp["id"]] = {"comparison": f"{cand_key} vs {base_key}", **result}
        if hyp["id"] != "H1" and result["bootstrap_p_saving_le_0"] is not None:
            pvals.append(result["bootstrap_p_saving_le_0"])
            names.append(hyp["id"])
    for name, adj in zip(names, holm(pvals)):
        comparisons[name]["holm_adjusted_p_saving_le_0"] = adj
    margin = experiment["acceptance"]["quality_noninferiority_margin_pct_points"] / 100
    minimum = experiment["acceptance"]["minimum_useful_saving_pct"] / 100
    h1 = comparisons.get("H1")
    decision = None
    if h1:
        noninferior = h1["accept_diff_ci95"][0] is not None and h1["accept_diff_ci95"][0] >= -margin
        saving_ok = bool(h1["saving_ci95"]) and h1["saving_ci95"][0] is not None and h1["saving_ci95"][0] > 0 \
            and h1["saving_cost_per_accepted"] is not None and h1["saving_cost_per_accepted"] >= minimum
        excess_critical = arms[args.primary]["critical_failures"] > arms[args.baseline]["critical_failures"]
        decision = {"noninferior_at_margin": noninferior, "useful_saving_supported": saving_ok,
                    "excess_critical_failures": excess_critical,
                    "verdict": ("advantage" if noninferior and saving_ok and not excess_critical else
                                "harmful" if excess_critical else "no_advantage_or_inconclusive"),
                    "caveat": "exploratory: the preregistered power requirement (~314 tasks) is not met"}
    report = {"record_kinds": kinds, "evidence_status": "MOCK: harness validation only" if kinds == ["mock"] else kinds,
              "attempts": len(rows), "events": len(events), "schema_invalid_events": schema_issues,
              "arms": arms, "comparisons": comparisons, "primary_decision": decision}
    (args.run / "analysis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [f"# Analysis of `{args.run.name}`", "", f"**Evidence status:** {report['evidence_status']}", "",
             f"Attempts {len(rows)}; events {len(events)}; schema-invalid events {schema_issues}.", "",
             "| Arm | Accepted | Critical (95% UB) | Cost/attempt | Cost/accepted | Jev | Worker | Host | Strong | Median wall ms |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, a in arms.items():
        fmt = lambda v, d=5: "n/a" if v is None else f"{v:.{d}f}"
        lines.append(f"| {key} {a['arm_id']} | {a['accepted']}/{a['attempts']} | {a['critical_failures']} "
                     f"({fmt(a['critical_upper_bound_95'], 2)}) | {fmt(a['cost_per_attempt'])} | {fmt(a['cost_per_accepted'])} | "
                     f"{a['jev_calls']} | {a['worker_calls']} | {a['host_calls']} | {a['strong_model_calls']} | {fmt(a['wall_ms_median'], 0)} |")
    lines += ["", "| Hypothesis | Comparison | Tasks | Accept diff [95% CI] | Saving/accepted [95% CI] | Holm p |", "|---|---|---:|---|---|---:|"]
    for hid, c in comparisons.items():
        ci = lambda v: "n/a" if not v or v[0] is None else f"[{v[0]:+.3f}, {v[1]:+.3f}]"
        sav = "n/a" if c["saving_cost_per_accepted"] is None else f"{c['saving_cost_per_accepted']:+.3f}"
        lines.append(f"| {hid} | {c['comparison']} | {c['tasks']} | {c['accept_diff']:+.3f} {ci(c['accept_diff_ci95'])} | "
                     f"{sav} {ci(c['saving_ci95'])} | {c.get('holm_adjusted_p_saving_le_0', '')} |")
    if decision:
        lines += ["", f"Primary decision (H1): **{decision['verdict']}** — {decision['caveat']}."]
    (args.run / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

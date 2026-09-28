"""Replay saved five-unit traces through the repository's own controllers (no network).

Purpose: diagnose, not measure. The recorded Jev choices and worker artifacts are
replayed through (a) the unchanged legacy CheckedNetwork, to verify the replay
reproduces the recorded Jev request bytes; (b) FusedCheckedNetwork; (c) a legacy
variant that skips gates whose only non-terminal option is deterministic code.
Jev token counts for (b) and (c) are ESTIMATES from a bytes->tokens fit on the
recorded requests. They assume Jev would choose the same routes, which a replay
cannot establish; see RESULTS.md.

Usage: python -B replay_gate_variants.py --repo <repo-root> --out <dir>
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

BUNDLES = {"conditional_first": "research/live-gpt6-optional-fixture",
           "conditional_hardened": "research/live-gpt6-optional-final"}
JEV_INPUT_USD_PER_M = 0.042   # recorded charges: 998 tokens -> $0.000041916
JEV_OUTPUT_USD_PER_M = 0.0


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fit_through_origin(xs, ys):
    return sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)


def fit_linear(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scripts-rev", default=None,
                        help="git revision whose scripts/ to replay against (default: working tree)")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    import subprocess, tarfile, io, tempfile as _tf
    scripts_dir = repo / "scripts"
    if args.scripts_rev:
        holder = _tf.mkdtemp(prefix="cidm-replay-")
        blob = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", args.scripts_rev, "scripts"],
                              check=True, capture_output=True).stdout
        tarfile.open(fileobj=io.BytesIO(blob)).extractall(holder)
        scripts_dir = Path(holder) / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import jev_decide  # noqa: E402
    import transport  # noqa: E402
    from atomic_mesh import fingerprint, packed  # noqa: E402
    from checked_network import CheckedNetwork  # noqa: E402
    from config import RunConfig  # noqa: E402
    try:
        from fused_checked_network import FusedCheckedNetwork  # noqa: E402
    except ImportError:
        FusedCheckedNetwork = None
    from network_run import DemoPipeline, fake_check  # noqa: E402
    import tempfile

    class CaptureGateway(transport.Gateway):
        """Builds real Jev payloads via Gateway.network_judge; never sends them."""

        def __init__(self, folder, config, chooser):
            super().__init__(folder, config)
            self.chooser, self.captured, self._phase, self._options = chooser, [], None, None

        def network_judge(self, phase, options, state):
            self._phase, self._options = phase, options
            return super().network_judge(phase, options, state)

        def call(self, role, payload, *, followup_required=False):
            assert role == "jev"
            body = jev_decide.validate_request(payload, "openrouter")
            choice = self.chooser(self._phase, self._options, payload["state"])
            k = len(self._options)
            probabilities = {o: (1.0 if o == choice else 0.0) for o in self._options}
            self.captured.append({"phase": self._phase, "bytes": len(body), "options": k,
                                  "choice": choice, "request_hash": fingerprint(payload)})
            response = {"model": "typesafe/jev-1.13-20260917",
                        "answers": {"next": {"type": "choice", "choice": choice,
                                             "probabilities": probabilities, "confidence": 1.0}}}
            return response, {"id": "replay-" + str(len(self.captured)), "usage": None}

    # ---- calibration data: every recorded Jev request/usage in the GPT-6 bundles
    xs, ys, ks, outs = [], [], [], []
    for rel in ("research/live-gpt6-fixture/checked", *BUNDLES.values(),
                "research/live-gpt6-fast-exit/initial", "research/live-gpt6-fast-exit/compact"):
        for event_path in sorted((repo / rel).glob("call-*.event.json")):
            event = load(event_path)
            if event["role"] != "jev":
                continue
            request = load(str(event_path).replace(".event.json", ".request.json"))
            body = jev_decide.validate_request(request, "openrouter")
            xs.append(len(body)); ys.append(event["usage"]["input_tokens"])
            ks.append(len(request["questions"]["next"]["criteria"])); outs.append(event["usage"]["output_tokens"])
    tokens_per_byte = fit_through_origin(xs, ys)
    residuals = [y - tokens_per_byte * x for x, y in zip(xs, ys)]
    out_a, out_b = fit_linear(ks, outs)
    calibration = {"n_requests": len(xs), "input_tokens_per_request_byte": round(tokens_per_byte, 6),
                   "max_abs_residual_tokens": round(max(abs(r) for r in residuals), 1),
                   "max_rel_residual": round(max(abs(r) / y for r, y in zip(residuals, ys)), 4),
                   "output_tokens_model": {"intercept": round(out_a, 3), "per_option": round(out_b, 3)},
                   "output_max_abs_residual": round(max(abs(o - (out_a + out_b * k)) for o, k in zip(outs, ks)), 1)}

    def estimate(captured):
        inp = sum(tokens_per_byte * c["bytes"] for c in captured)
        out = sum(out_a + out_b * c["options"] for c in captured)
        return {"jev_calls": len(captured), "est_input_tokens": round(inp), "est_output_tokens": round(out),
                "est_tokens": round(inp + out), "est_cost_usd": round(inp * JEV_INPUT_USD_PER_M / 1e6
                                                                    + out * JEV_OUTPUT_USD_PER_M / 1e6, 9)}

    report = {"scripts_revision": args.scripts_rev or "working_tree", "calibration": calibration, "bundles": {}}
    for bundle, rel in BUNDLES.items():
        folder = repo / rel
        result = load(folder / "result.json")
        config = RunConfig.from_dict(result["configuration"])
        recorded = []
        for event_path in sorted(folder.glob("call-*.event.json"), key=lambda p: int(p.name.split("-")[1].split(".")[0])):
            event = load(event_path)
            request = load(str(event_path).replace(".event.json", ".request.json"))
            response = load(str(event_path).replace(".event.json", ".response.json"))
            recorded.append({"role": event["role"], "request": request, "response": response, "event": event})
        jev_choices = [r["response"]["answers"]["next"]["choice"] for r in recorded if r["role"] == "jev"]
        artifacts = [json.loads(r["response"]["choices"][0]["message"]["content"])
                     for r in recorded if r["role"] == "worker"]
        task = load(repo / "examples/production-records.json")

        def producer_factory(pipeline):
            queue = list(copy.deepcopy(artifacts))

            def produce(unit, parents, feedback, worker_route=None):
                if unit.id in ("input", "hidden2"):
                    return pipeline.produce(unit, parents, feedback, worker_route)
                return queue.pop(0)
            return produce

        # (a) legacy replay: must reproduce the recorded request hashes
        pipeline = DemoPipeline(task)
        legacy_queue = list(jev_choices)
        with tempfile.TemporaryDirectory() as tmp:
            gw = CaptureGateway(tmp, config, lambda phase, options, state: legacy_queue.pop(0))
            net = CheckedNetwork(task["goal"], {"records": {"title": "Original records", "text": packed(task)}},
                                 gw.network_judge, producer_factory(pipeline), fake_check, pipeline.validate,
                                 policy=copy.deepcopy(result["configuration"]), checker_identity={"model": config.checker_model, "effort": config.checker_effort},
                                 worker_routes=config.worker_routes(), simulation=False)
            legacy = net.run()
            legacy_captured = gw.captured
        recorded_hashes = [r["event"]["request_hash"] for r in recorded if r["role"] == "jev"]
        replay_hashes = [c["request_hash"] for c in legacy_captured]
        fidelity = {"recorded_jev_requests": len(recorded_hashes), "replayed": len(replay_hashes),
                    "byte_identical_requests": sum(a == b for a, b in zip(recorded_hashes, replay_hashes)),
                    "status": legacy["status"]}
        recorded_jev = [r["event"]["usage"] for r in recorded if r["role"] == "jev"]
        measured = {"jev_calls": len(recorded_jev),
                    "tokens": sum(u["input_tokens"] + u["output_tokens"] for u in recorded_jev),
                    "cost_usd": round(sum(u["cost"] for u in recorded_jev), 12)}

        # route per generative unit, as chosen by the recorded legacy authorize_unit gates
        routes = [c["choice"] for c in legacy_captured if c["phase"] == "authorize_unit"]
        unit_routes = dict(zip(("input", "hidden1", "hidden2", "hidden3", "output"), routes))

        # (b) fused replay: same routes, one decision per completed unit
        order = ("input", "hidden1", "hidden2", "hidden3", "output")

        def fused_choice(phase, options, state):
            unit = state["unit"]["id"]
            if phase == "authorize_first_unit":
                return "compute"
            index = order.index(unit)
            if index + 1 == len(order):
                return "forward_finish"
            return "forward_" + unit_routes[order[index + 1]]
        pipeline = DemoPipeline(task)
        fused_captured, fused = [], {"status": "not_available_at_this_revision"}
        if FusedCheckedNetwork is not None:
            with tempfile.TemporaryDirectory() as tmp:
                gw = CaptureGateway(tmp, config, fused_choice)
                net = FusedCheckedNetwork(task["goal"], {"records": {"title": "Original records", "text": packed(task)}},
                                          gw.network_judge, producer_factory(pipeline), fake_check, pipeline.validate,
                                          policy=copy.deepcopy(result["configuration"]),
                                          checker_identity={"model": config.checker_model, "effort": config.checker_effort},
                                          worker_routes=config.worker_routes(), simulation=False,
                                          deterministic_units=("input", "hidden2"))
                fused = net.run()
                fused_captured = gw.captured

        # (c) event-driven legacy: skip gates whose only non-terminal option is 'compute',
        # and the post-result gate of a deterministic unit whose hard checks all pass.
        skipped = []

        def skip_filter(captured):
            kept = []
            for c, unit in zip(captured, _units_for(captured)):
                if unit in ("input", "hidden2") and c["phase"] in ("authorize_unit", "after_worker"):
                    skipped.append({"unit": unit, "phase": c["phase"],
                                    "policy_reason": "deterministic_unit_fixed_code_frozen_inputs_checks_passed"})
                    continue
                kept.append(c)
            return kept

        def _units_for(captured):
            units, index = [], 0
            for c in captured:
                units.append(order[index] if index < 5 else None)
                if c["phase"] == "after_worker" and c["choice"] == "forward":
                    index += 1
            return units
        event_driven = skip_filter(legacy_captured)

        report["bundles"][bundle] = {
            "replay_fidelity": fidelity,
            "measured_legacy_jev": measured,
            "estimated_legacy_jev_from_replay_bytes": estimate(legacy_captured),
            "estimated_fused_jev": {**estimate(fused_captured), "status": fused["status"],
                                    "phases": [c["phase"] for c in fused_captured],
                                    "options_per_decision": [c["options"] for c in fused_captured]},
            "estimated_event_driven_jev": {**estimate(event_driven), "skipped_gates": skipped},
            "unit_routes_replayed": unit_routes,
            "caveat": "Estimates assume identical Jev choices and worker outputs; they are not measurements.",
        }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / ("replay-gate-variants." + (args.scripts_rev or "working-tree") + ".json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

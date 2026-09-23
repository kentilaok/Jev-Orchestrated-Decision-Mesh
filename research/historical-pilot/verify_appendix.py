"""Offline integrity and accounting verification for the historical CIDM pilot."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def digest_json(value: object) -> str:
    content = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_hashes() -> None:
    frozen = json.loads((ROOT / "frozen-manifest.json").read_text(encoding="utf-8"))
    dataset = json.loads((ROOT / "dataset_manifest.json").read_text(encoding="utf-8"))
    for manifest in (frozen["source_hashes"], dataset["sha256"]):
        for name, expected in manifest.items():
            actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            require(actual == expected, f"Hash mismatch: {name}")
    for line in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        require(actual == expected, f"Appendix checksum mismatch: {name}")


def check_split_records() -> tuple[list[dict], list[dict]]:
    for stem in ("ledger", "runs"):
        combined = (ROOT / f"combined-{stem}.jsonl").read_bytes()
        split = (ROOT / "runs-development" / f"{stem}.jsonl").read_bytes()
        split += (ROOT / "runs-evaluation" / f"{stem}.jsonl").read_bytes()
        require(combined == split, f"Combined {stem} differs from phase records")
    return (read_jsonl(ROOT / "runs-evaluation/ledger.jsonl"),
            read_jsonl(ROOT / "runs-evaluation/runs.jsonl"))


def check_raw_evaluation(ledger: list[dict], runs: list[dict]) -> None:
    require(len(ledger) == 52, "Expected 52 evaluation calls")
    require(len(runs) == 24, "Expected 24 paired task runs")
    require(len({e["event_id"] for e in ledger}) == 52, "Duplicate event ID")
    event_ids = {e["event_id"] for e in ledger}
    referenced = [event_id for run in runs for event_id in run["event_ids"]]
    require(len(referenced) == len(event_ids) and set(referenced) == event_ids,
            "Task runs do not link every evaluation call exactly once")

    raw_dir = ROOT / "runs-evaluation"
    requests = {p.stem.split(".")[0] for p in raw_dir.glob("*.request.json")}
    responses = {p.stem.split(".")[0] for p in raw_dir.glob("*.response.json")}
    require(requests == event_ids and responses == event_ids, "Raw call inventory mismatch")

    for event in ledger:
        event_id = event["event_id"]
        request = json.loads((raw_dir / f"{event_id}.request.json").read_text(encoding="utf-8"))
        response = json.loads((raw_dir / f"{event_id}.response.json").read_text(encoding="utf-8"))
        require(digest_json(request) == event["request_sha256"], f"Request hash mismatch: {event_id}")
        require(response.get("model") == event["model_returned"], f"Model mismatch: {event_id}")
        require(response.get("provider") == event["provider_returned"], f"Provider mismatch: {event_id}")
        raw_usage = response["usage"]
        role = event["role"]
        extracted = {
            "input_tokens": raw_usage.get("prompt_tokens") if role == "worker" else raw_usage.get("input_tokens"),
            "output_tokens": raw_usage.get("completion_tokens") if role == "worker" else raw_usage.get("output_tokens"),
            "total_tokens": raw_usage.get("total_tokens"),
            "cost": raw_usage.get("cost"),
        }
        for key, expected in extracted.items():
            require(event["usage"][key] == expected, f"Usage mismatch: {event_id}/{key}")

    by_arm_role = Counter((e["arm"], e["role"]) for e in ledger)
    require(by_arm_role == {("A", "worker"): 12, ("B", "worker"): 14, ("B", "jev"): 26},
            "Call inventory differs from report")
    for arm, expected_tokens, expected_cost in (("A", 34942, 0.25523625),
                                                ("B", 131388, 0.230692994)):
        events = [e for e in ledger if e["arm"] == arm]
        tokens = sum(e["usage"]["total_tokens"] if e["usage"]["total_tokens"] is not None
                     else e["usage"]["input_tokens"] + e["usage"]["output_tokens"] for e in events)
        cost = sum(e["usage"]["cost"] for e in events)
        require(tokens == expected_tokens, f"Token total mismatch: arm {arm}")
        require(abs(cost - expected_cost) < 1e-10, f"Cost total mismatch: arm {arm}")


def check_analysis() -> None:
    with tempfile.TemporaryDirectory(prefix="cidm-pilot-check-") as output:
        command = [sys.executable, "-B", str(ROOT / "analyze_measured.py"),
                   "--tasks", str(ROOT / "tasks.json"), "--gold", str(ROOT / "gold.json"),
                   "--ledger", str(ROOT / "combined-ledger.jsonl"),
                   "--runs", str(ROOT / "combined-runs.jsonl"),
                   "--output-dir", output, "--seed", "1729", "--bootstrap-replicates", "10000"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
        require(result.returncode == 0, f"Analyzer failed: {result.stderr[-400:]}")
        for name in ("results.json", "summary.md", "task_results.csv"):
            require((Path(output) / name).read_bytes() == (ROOT / "analysis" / name).read_bytes(),
                    f"Reproduced analysis differs: {name}")


def main() -> None:
    check_hashes()
    ledger, runs = check_split_records()
    check_raw_evaluation(ledger, runs)
    check_analysis()
    print("PASS: frozen hashes, appendix checksums, 52 raw calls, paired records, and byte-identical analysis")


if __name__ == "__main__":
    main()

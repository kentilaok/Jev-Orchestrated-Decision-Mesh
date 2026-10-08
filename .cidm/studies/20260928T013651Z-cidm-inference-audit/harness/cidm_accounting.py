"""Append-only accounting primitives for the CIDM inference audit.

Standard library only. Every numeric field carries a provenance label and every
missing value carries a reason. Provider-reported and reconstructed charges for
the same request are kept in separate fields and never summed together.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math

PROVENANCE = ("provider_reported", "directly_observed", "derived", "estimated", "unavailable")

# Field order is the canonical column order for results.csv exports.
EVENT_FIELDS = (
    "run_id", "task_id", "task_family", "arm_id", "repetition_id", "policy_version",
    "event_id", "parent_event_id", "provider_request_id", "record_kind", "source_record",
    "actor", "purpose", "status", "billing_status",
    "requested_model", "returned_model", "returned_provider", "requested_effort", "confirmed_effort",
    "input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens",
    "reasoning_tokens", "provider_total_tokens",
    "provider_reported_cost", "reconstructed_cost", "currency", "pricing_source_date",
    "started_at", "ended_at", "api_duration_ms",
    "retry_of", "fallback_status",
    "source_hash", "prompt_hash", "result_hash",
    "gate_phase", "gate_action", "gate_options", "authorised_next_operation",
    "acceptance_test_result",
)
COUNTER_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens",
                  "reasoning_tokens", "provider_total_tokens")
ACTORS = ("host", "jev", "worker", "checker", "compressor", "retriever", "tool", "evaluator", "harness")
RECORD_KINDS = ("live_evaluation", "live_development_attempt", "replay", "mock", "simulation", "estimate")
STATUSES = ("ok", "failed", "cancelled", "timeout", "rejected_after_completion", "unknown")
BILLING = ("billed", "unbilled", "unknown")


class AccountingError(ValueError):
    pass


def packed(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(value) -> str:
    """Same canonicalisation as scripts/atomic_mesh.py:fingerprint."""
    return sha256_bytes(packed(value).encode())


def _counter(value):
    return type(value) is int and value >= 0


def _money(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def new_event(**values):
    """Create an event with every field present; absent fields are null with a reason."""
    unknown = set(values) - set(EVENT_FIELDS) - {"missing", "provenance", "usage_raw", "notes"}
    if unknown:
        raise AccountingError("unknown_event_fields:" + ",".join(sorted(unknown)))
    event = {name: None for name in EVENT_FIELDS}
    event["missing"] = {}
    event["provenance"] = {}
    event["usage_raw"] = None
    event["notes"] = []
    for key, value in values.items():
        event[key] = copy.deepcopy(value)
    for name in EVENT_FIELDS:
        if event[name] is None and name not in event["missing"]:
            event["missing"][name] = "not_supplied"
    return event


def set_field(event, name, value, provenance, reason=None):
    if name not in EVENT_FIELDS:
        raise AccountingError("unknown_field:" + name)
    if provenance not in PROVENANCE:
        raise AccountingError("unknown_provenance:" + str(provenance))
    if value is None:
        if not reason:
            raise AccountingError("null_requires_reason:" + name)
        event[name] = None
        event["missing"][name] = reason
        event["provenance"][name] = "unavailable"
        return event
    event[name] = value
    event["missing"].pop(name, None)
    event["provenance"][name] = provenance
    return event


def validate_event(event):
    """Return a list of issues; an empty list means the event satisfies the schema."""
    issues = []
    for name in EVENT_FIELDS:
        if name not in event:
            issues.append("missing_field:" + name)
        elif event[name] is None and name not in event.get("missing", {}):
            issues.append("null_without_reason:" + name)
    for name, label in event.get("provenance", {}).items():
        if label not in PROVENANCE:
            issues.append("bad_provenance:" + name)
    if event.get("actor") is not None and event["actor"] not in ACTORS:
        issues.append("bad_actor")
    if event.get("record_kind") is not None and event["record_kind"] not in RECORD_KINDS:
        issues.append("bad_record_kind")
    if event.get("status") is not None and event["status"] not in STATUSES:
        issues.append("bad_status")
    if event.get("billing_status") is not None and event["billing_status"] not in BILLING:
        issues.append("bad_billing_status")
    for name in COUNTER_FIELDS:
        value = event.get(name)
        if value is not None and not _counter(value):
            issues.append("bad_counter:" + name)
    for name in ("provider_reported_cost", "reconstructed_cost", "api_duration_ms"):
        value = event.get(name)
        if value is not None and not _money(value):
            issues.append("bad_number:" + name)
    issues.extend(subset_issues(event))
    return issues


def subset_issues(usage):
    """Cached/cache-write are subsets of input; reasoning is a subset of output."""
    issues = []
    inp, out = usage.get("input_tokens"), usage.get("output_tokens")
    cached, write, reasoning = (usage.get("cached_input_tokens"), usage.get("cache_write_tokens"),
                                usage.get("reasoning_tokens"))
    if _counter(inp):
        if _counter(cached) and cached > inp:
            issues.append("cached_exceeds_input")
        if _counter(write) and write > inp:
            issues.append("cache_write_exceeds_input")
        if _counter(cached) and _counter(write) and cached + write > inp:
            issues.append("cache_read_plus_write_exceeds_input")
    if _counter(out) and _counter(reasoning) and reasoning > out:
        issues.append("reasoning_exceeds_output")
    total = usage.get("provider_total_tokens")
    if _counter(total) and _counter(inp) and _counter(out) and total != inp + out:
        issues.append("provider_total_not_input_plus_output")
    return issues


def io_total(event):
    """Input plus output once; subsets are never added. None when unknown."""
    inp, out = event.get("input_tokens"), event.get("output_tokens")
    if _counter(inp) and _counter(out):
        return inp + out
    return None


# ---------------------------------------------------------------- usage schemas

def normalize_openrouter_chat_usage(raw):
    """OpenRouter chat.completions usage -> canonical counters (all provider_reported)."""
    if not isinstance(raw, dict):
        return None, ["usage_missing_or_not_object"]
    issues = []
    details_in = raw.get("prompt_tokens_details") if isinstance(raw.get("prompt_tokens_details"), dict) else {}
    details_out = (raw.get("completion_tokens_details")
                   if isinstance(raw.get("completion_tokens_details"), dict) else {})
    usage = {
        "input_tokens": raw.get("prompt_tokens"),
        "output_tokens": raw.get("completion_tokens"),
        "provider_total_tokens": raw.get("total_tokens"),
        "cached_input_tokens": details_in.get("cached_tokens"),
        "cache_write_tokens": details_in.get("cache_write_tokens"),
        "reasoning_tokens": details_out.get("reasoning_tokens"),
        "provider_reported_cost": raw.get("cost"),
    }
    for key in COUNTER_FIELDS:
        if usage[key] is not None and not _counter(usage[key]):
            issues.append("invalid_counter:" + key)
            usage[key] = None
    if usage["provider_reported_cost"] is not None and not _money(usage["provider_reported_cost"]):
        issues.append("invalid_cost")
        usage["provider_reported_cost"] = None
    issues.extend(subset_issues(usage))
    return usage, issues


def normalize_typesafe_usage(raw):
    """TypeSafe/OpenRouter decision usage: input_tokens, output_tokens, cost; no total."""
    if not isinstance(raw, dict):
        return None, ["usage_missing_or_not_object"]
    usage = {"input_tokens": raw.get("input_tokens"), "output_tokens": raw.get("output_tokens"),
             "provider_total_tokens": raw.get("total_tokens"), "cached_input_tokens": None,
             "cache_write_tokens": None, "reasoning_tokens": None,
             "provider_reported_cost": raw.get("cost")}
    issues = []
    for key in COUNTER_FIELDS:
        if usage[key] is not None and not _counter(usage[key]):
            issues.append("invalid_counter:" + key)
            usage[key] = None
    if usage["provider_reported_cost"] is not None and not _money(usage["provider_reported_cost"]):
        issues.append("invalid_cost")
        usage["provider_reported_cost"] = None
    issues.extend(subset_issues(usage))
    return usage, issues


def normalize_codex_turn_usage(raw):
    """codex exec --json turn.completed.usage (per ephemeral turn; not dollar-priced)."""
    if not isinstance(raw, dict):
        return None, ["usage_missing_or_not_object"]
    usage = {"input_tokens": raw.get("input_tokens"), "output_tokens": raw.get("output_tokens"),
             "provider_total_tokens": None, "cached_input_tokens": raw.get("cached_input_tokens"),
             "cache_write_tokens": raw.get("cache_write_input_tokens"),
             "reasoning_tokens": raw.get("reasoning_output_tokens"), "provider_reported_cost": None}
    issues = []
    for key in COUNTER_FIELDS:
        if usage[key] is not None and not _counter(usage[key]):
            issues.append("invalid_counter:" + key)
            usage[key] = None
    issues.extend(subset_issues(usage))
    return usage, issues


# ---------------------------------------------------------------- cumulative telemetry

def cumulative_to_deltas(samples, fields=("input_tokens", "cached_input_tokens", "output_tokens",
                                          "reasoning_tokens")):
    """Convert cumulative per-thread counters into per-sample deltas.

    samples: ordered dicts with 'total' (cumulative counters) and optional 'last'
    (provider-reported per-response delta). A decrease in any cumulative field is
    treated as a reset (for example compaction or a new thread); the delta for that
    sample then comes from 'last' when supplied, otherwise it is unknown. When both
    a difference and 'last' exist they must agree, otherwise the sample is flagged.
    Returns (deltas, issues). Never sums cumulative values directly.
    """
    deltas, issues, previous = [], [], None
    for index, sample in enumerate(samples):
        total = sample.get("total") or {}
        last = sample.get("last")
        delta = {"index": index, "reset": False, "source": None}
        if previous is None:
            if last is not None:
                delta.update({k: last.get(k) for k in fields}, source="last_first_sample")
            else:
                # The first cumulative sample equals its own delta only if the thread started here.
                started = sample.get("thread_started_here") is True
                delta.update({k: (total.get(k) if started else None) for k in fields},
                             source="first_total_new_thread" if started else "unknown_prior_state")
                if not started:
                    issues.append({"index": index, "issue": "first_sample_without_baseline"})
        else:
            differences = {k: (total.get(k) - previous.get(k)
                               if _counter(total.get(k)) and _counter(previous.get(k)) else None)
                           for k in fields}
            reset = any(v is not None and v < 0 for v in differences.values())
            delta["reset"] = reset
            if reset:
                issues.append({"index": index, "issue": "cumulative_counter_decreased_reset"})
                if last is not None:
                    delta.update({k: last.get(k) for k in fields}, source="last_after_reset")
                else:
                    delta.update({k: None for k in fields}, source="unknown_after_reset")
            else:
                delta.update(differences, source="difference")
                if last is not None:
                    mismatch = [k for k in fields if differences[k] is not None
                                and last.get(k) is not None and differences[k] != last[k]]
                    if mismatch:
                        issues.append({"index": index, "issue": "difference_disagrees_with_last",
                                       "fields": mismatch})
                        delta["source"] = "difference_conflicts_with_last"
        deltas.append(delta)
        previous = total
    return deltas, issues


def exclude_rollups(events):
    """Drop parent aggregate records whose children are present, to avoid double counting.

    An event with 'aggregates' listing child event_ids is a rollup. If every child
    is present the rollup is excluded; if some are missing the rollup is kept and
    the children are excluded, and the case is flagged so no total mixes both.
    """
    by_id = {e["event_id"]: e for e in events if e.get("event_id")}
    keep, issues, dropped = [], [], set()
    for event in events:
        children = event.get("aggregates")
        if not children:
            continue
        present = [c for c in children if c in by_id]
        if len(present) == len(children):
            dropped.add(event["event_id"])
        else:
            dropped.update(present)
            issues.append({"event_id": event["event_id"], "issue": "partial_children_rollup_kept",
                           "missing_children": sorted(set(children) - set(present))})
    for event in events:
        if event.get("event_id") not in dropped:
            keep.append(event)
    return keep, issues


# ---------------------------------------------------------------- dedupe

def dedupe(events):
    """Separate repeated representations of one request from repeated billed requests.

    Identity is the provider request/generation id. Records sharing it are one
    request (the later copies are representation duplicates); identical prompt
    hashes with different ids are distinct billed calls. Records without an id
    cannot be deduplicated safely and are returned for manual review, not merged.
    """
    seen, unique, duplicates, unidentified = {}, [], [], []
    same_prompt = {}
    for event in events:
        rid = event.get("provider_request_id")
        if not rid:
            unidentified.append(event)
            unique.append(event)
            continue
        if rid in seen:
            first = seen[rid]
            conflict = [k for k in ("input_tokens", "output_tokens", "provider_reported_cost")
                        if first.get(k) != event.get(k)]
            duplicates.append({"provider_request_id": rid, "kept": first.get("source_record"),
                               "duplicate": event.get("source_record"), "conflicting_fields": conflict})
            continue
        seen[rid] = event
        unique.append(event)
        if event.get("prompt_hash"):
            same_prompt.setdefault(event["prompt_hash"], set()).add(rid)
    repeated_prompts = {h: sorted(ids) for h, ids in same_prompt.items() if len(ids) > 1}
    return unique, {"representation_duplicates": duplicates,
                    "unidentified_records": [e.get("source_record") for e in unidentified],
                    "identical_prompt_distinct_billed_requests": repeated_prompts}


# ---------------------------------------------------------------- cost

def reconstruct_cost(event, price):
    """Estimate a charge from disjoint token categories and a dated price row.

    price: {input, output, cache_read, cache_write} in currency per million tokens;
    missing rates make the estimate partial (None) when the matching category is
    non-zero or unknown. Returns (value or None, basis string).
    """
    inp, out = event.get("input_tokens"), event.get("output_tokens")
    if not (_counter(inp) and _counter(out)):
        return None, "unknown_input_or_output"
    cached = event.get("cached_input_tokens")
    write = event.get("cache_write_tokens")
    basis = []
    if cached is None:
        cached, _ = 0, basis.append("cached_unknown_assumed_uncached")
    if write is None:
        write, _ = 0, basis.append("cache_write_unknown_assumed_zero")
    uncached = inp - cached - write
    if uncached < 0:
        return None, "inconsistent_cache_subsets"
    total = 0.0
    for tokens, rate_name in ((uncached, "input"), (cached, "cache_read"), (write, "cache_write"),
                              (out, "output")):
        rate = price.get(rate_name)
        if tokens == 0:
            continue
        if rate is None:
            return None, "missing_rate:" + rate_name
        total += tokens * rate / 1_000_000
    return total, ";".join(basis) or "complete"


def charge_for_totals(event):
    """Pick exactly one charge per request: provider-reported if present, else estimate."""
    if _money(event.get("provider_reported_cost")):
        return event["provider_reported_cost"], "provider_reported"
    if _money(event.get("reconstructed_cost")):
        return event["reconstructed_cost"], "estimated"
    return None, "unavailable"


def summarize(events, group_by=("actor",)):
    """Totals per group. Any unknown member makes that group's total unknown."""
    groups = {}
    for event in events:
        key = tuple(event.get(k) for k in group_by)
        groups.setdefault(key, []).append(event)
    out = {}
    for key, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        tokens = [io_total(e) for e in members]
        charges = [charge_for_totals(e) for e in members]
        durations = [e.get("api_duration_ms") for e in members]
        out["|".join(str(k) for k in key)] = {
            "calls": len(members),
            "billed_calls": sum(e.get("billing_status") == "billed" for e in members),
            "failed_calls": sum(e.get("status") not in ("ok", None) for e in members),
            "input_plus_output_tokens": sum(tokens) if all(t is not None for t in tokens) else None,
            "unknown_token_calls": sum(t is None for t in tokens),
            "charge": sum(c for c, _ in charges) if all(c is not None for c, _ in charges) else None,
            "charge_basis": sorted({b for _, b in charges}),
            "unknown_charge_calls": sum(c is None for c, _ in charges),
            "sum_api_duration_ms": (sum(durations) if all(_money(d) for d in durations) else None),
        }
    return out


def cost_per_accepted(total_cost, accepted):
    if total_cost is None or not _counter(accepted) or accepted == 0:
        return None
    return total_cost / accepted


def savings(candidate_cost, baseline_cost):
    """1 - candidate/baseline; negative means the candidate cost more."""
    if not (_money(candidate_cost) and _money(baseline_cost)) or baseline_cost == 0:
        return None
    return 1 - candidate_cost / baseline_cost


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(packed(record) + "\n")

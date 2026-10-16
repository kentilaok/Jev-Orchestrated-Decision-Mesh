"""Re-audit a saved live broker run folder against P0-03 (slice 3a).

Reads `result.json`, `journal.jsonl` and `permits.jsonl` from a broker `--out`
folder and recomputes, without trusting the run's own audit fields:

- permit ledger integrity, single-use permits, one receipt per consumption;
- one consumed permit per frontier child call (zero unauthorized calls);
- for a released answer: complete status, Jev order audit, native call audit;
- Jev spend within `max_usd`, no permit issued after the cumulative cap was hit;
- usage not reported stays unknown (None), never summed as zero.

It also collects the evidence P0-03 asks to keep (hashes, served identities,
session IDs). Exit 0 when no issue is found, 1 otherwise. Offline only.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from audit_network import audit as audit_order
from capability_permits import HashChainLedger, audit_permit_ledger
from config import RunConfig
from native_transition_broker import NativeTransitionBroker


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _known_tokens(usage) -> bool:
    return (type(usage) is dict and type(usage.get('input_tokens')) is int
            and type(usage.get('output_tokens')) is int)


def _known_cost(usage) -> bool:
    return type(usage) is dict and type(usage.get('cost')) in (int, float)


def audit_run(folder: Path, config: RunConfig) -> dict:
    folder = Path(folder)
    issues = []
    result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
    calls = result.get('calls') or []
    frontier = [c for c in calls if c.get('role') in ('worker', 'checker')]

    # Permits: every frontier call consumed exactly one permit.
    permit_events = []
    if (folder / 'permits.jsonl').is_file():
        try:
            permit_events = HashChainLedger(folder / 'permits.jsonl').read()
        except Exception as error:
            issues.append('permit_ledger_unreadable:' + str(error))
        permit_audit = audit_permit_ledger(permit_events, result.get('events') or [])
        issues += ['permit:' + issue for issue in permit_audit['issues']]
    elif frontier:
        issues.append('frontier_calls_without_permit_ledger')
    # A call refused at permit issue (e.g. cap reached) is recorded as failed with
    # no consumption, so only successful calls must each have consumed a permit.
    consumed = sum(e.get('kind') == 'permit_consumed' for e in permit_events)
    succeeded = sum(c.get('status') == 'ok' for c in frontier)
    if consumed < succeeded:
        issues.append(f'frontier_call_without_permit:{consumed}_consumed_{succeeded}_ok_calls')
    if consumed > len(frontier):
        issues.append(f'permit_without_frontier_call:{consumed}_consumed_{len(frontier)}_calls')
    consumed_ids = {e.get('permit_id') for e in permit_events if e.get('kind') == 'permit_consumed'}
    for call in frontier:
        if call.get('status') == 'ok' and call.get('permit_id') not in consumed_ids:
            issues.append('ok_call_permit_not_consumed:' + str(call.get('permit_id')))

    # Cumulative cap: nothing issued once the receipted cost reached the cap.
    if config.max_cumulative_usd is not None:
        spent = 0.0
        for event in permit_events:
            if event.get('kind') == 'permit_issued' and spent >= config.max_cumulative_usd:
                issues.append('permit_issued_past_cumulative_cap')
            if event.get('kind') == 'permit_receipt' and type(event.get('cost_usd')) in (int, float):
                spent += event['cost_usd']

    # Release: only an audited, complete run may carry an answer.
    if result.get('answer') is not None:
        if result.get('status') != 'complete':
            issues.append('answer_released_without_complete_status')
        order = audit_order(result)
        issues += ['order:' + issue for issue in order['issues']]
        if not order['valid'] and not order['issues']:
            issues.append('order:invalid')
        native = NativeTransitionBroker.audit_native_calls(
            SimpleNamespace(calls=calls, config=config), result)
        issues += ['native:' + issue for issue in native['issues']]
        if not native['valid'] and not native['issues']:
            issues.append('native:invalid')

    # Jev spend: provider events are the billing record.
    jev_events = result.get('jev_provider_events') or []
    jev_cost = result.get('jev_api_cost_usd')
    if any(not _known_cost(e.get('usage')) for e in jev_events):
        if jev_cost is not None:
            issues.append('jev_cost_reported_despite_unknown_usage')
    else:
        recomputed = sum(e['usage']['cost'] for e in jev_events)
        if jev_cost is None or abs(jev_cost - recomputed) > 1e-12:
            issues.append('jev_cost_mismatch')
        if recomputed > config.max_usd:
            issues.append('jev_spend_over_max_usd')

    # Unknown usage stays unknown.
    accounting = result.get('accounting') or {}
    unknown = sum(not _known_tokens(c.get('usage')) for c in frontier)
    if accounting.get('frontier_calls_usage_unknown') != unknown:
        issues.append('unknown_usage_count_mismatch')
    if unknown and (accounting.get('frontier_input_tokens') is not None
                    or accounting.get('frontier_output_tokens') is not None):
        issues.append('unknown_usage_summed_as_known')

    evidence = {
        'status': result.get('status'),
        'task_hash': result.get('task_hash'),
        'source_hashes': result.get('source_hashes'),
        'policy_hash': config.policy_hash,
        'result_sha256': _sha256(folder / 'result.json'),
        'journal_sha256': _sha256(folder / 'journal.jsonl'),
        'permits_sha256': _sha256(folder / 'permits.jsonl'),
        'jev_calls': len(jev_events),
        'jev_api_cost_usd': jev_cost,
        'frontier_calls': [{'role': c.get('role'), 'status': c.get('status'),
                            'requested_model': c.get('requested_model'),
                            'actual_model': c.get('actual_model'),
                            'identity_verification': c.get('identity_verification'),
                            'session_id': c.get('session_id'),
                            'usage_known': _known_tokens(c.get('usage'))} for c in frontier],
        'permits_consumed': consumed,
        'route_coverage': (result.get('route_coverage') or {}).get('status'),
    }
    return {'ok': not issues, 'issues': issues, 'evidence': evidence}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run_dir', type=Path, help='broker --out folder')
    parser.add_argument('--config', type=Path, help='RunConfig JSON the run used')
    parser.add_argument('--host', choices=('claude', 'codex'), default='claude')
    args = parser.parse_args(argv)
    settings = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
    family = 'claude' if args.host == 'claude' else 'gpt6'
    report = audit_run(args.run_dir, RunConfig.from_dict({**settings, 'worker_family': family}))
    print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

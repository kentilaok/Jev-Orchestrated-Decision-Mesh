"""Re-audit a saved live broker run folder against P0-03 (slice 3a).

Reads `result.json`, `journal.jsonl` and `permits.jsonl` from a broker `--out`
folder and recomputes, without trusting the run's own audit fields:

- the auditor's RunConfig matches the run's `config_policy_hash`;
- `journal.jsonl` matches the result's events (a tail of them for a resumed run);
- permit ledger integrity, single-use `frontier.run` permits, one per successful
  frontier call, each bound by `permit_id` (calls carried from a checkpoint cite
  the source run's ledger and are reported, not bound here);
- route-specific release audits: order + native audits for broad routes, the
  single pinned worker and hard checks for the short route;
- Jev spend within `max_usd`, no permit issued after the cumulative cap was hit,
  and a cap that cannot be verified (frontier receipt without cost) is flagged;
- usage not reported stays unknown (None), never summed as zero.

Trust model: this catches broker bugs and accidental corruption. It does not
prove the folder was not rewritten: the ledger chain and recorded hashes mean
something only once committed with the evidence bundle (slice 3c).
Exit 0 when no issue is found, 1 otherwise. Offline only.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from capability_permits import HashChainLedger, audit_permit_ledger
from config import RunConfig
from native_transition_broker import NativeTransitionBroker

SHORT_ROUTE = 'short_self_contained'
FUSED_PROTOCOL = 'cidm-fused-review-v1'


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _known_tokens(usage) -> bool:
    return (type(usage) is dict and type(usage.get('input_tokens')) is int
            and type(usage.get('output_tokens')) is int)


def _is_cost(value) -> bool:
    return type(value) in (int, float) and value >= 0


def _read_jsonl(path: Path) -> list:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _audit_permits(folder, result, frontier, config, issues) -> int:
    permit_events = []
    if (folder / 'permits.jsonl').is_file():
        try:
            permit_events = HashChainLedger(folder / 'permits.jsonl').read()
        except Exception as error:
            issues.append('permit_ledger_unreadable:' + str(error))
        permit_audit = audit_permit_ledger(permit_events, result.get('events') or [])
        issues += ['permit:' + issue for issue in permit_audit['issues']]
    elif any(not c.get('carried_from_checkpoint') for c in frontier):
        issues.append('frontier_calls_without_permit_ledger')

    # Only frontier.run permits back frontier calls; retrieval/MCP permits share the ledger.
    frontier_ids = {e.get('permit_id') for e in permit_events
                    if e.get('kind') == 'permit_issued' and e.get('capability') == 'frontier.run'}
    consumed = [e.get('permit_id') for e in permit_events
                if e.get('kind') == 'permit_consumed' and e.get('permit_id') in frontier_ids]
    own = [c for c in frontier if not c.get('carried_from_checkpoint')]
    ok_ids = [c.get('permit_id') for c in own if c.get('status') == 'ok']
    # A call refused at permit issue is recorded as failed with no consumption,
    # so only successful calls must each have consumed a distinct permit.
    if len(consumed) < len(ok_ids):
        issues.append(f'frontier_call_without_permit:{len(consumed)}_consumed_{len(ok_ids)}_ok_calls')
    if len(consumed) > len(own):
        issues.append(f'permit_without_frontier_call:{len(consumed)}_consumed_{len(own)}_calls')
    if len(set(ok_ids)) != len(ok_ids):
        issues.append('permit_id_reused_across_calls')
    for permit_id in ok_ids:
        if permit_id not in consumed:
            issues.append('ok_call_permit_not_consumed:' + str(permit_id))

    # Cumulative cap: nothing issued once the receipted cost reached the cap.
    if config.max_cumulative_usd is not None:
        spent = 0.0
        for event in permit_events:
            if event.get('kind') == 'permit_issued' and spent >= config.max_cumulative_usd:
                issues.append('permit_issued_past_cumulative_cap')
            if event.get('kind') == 'permit_receipt' and event.get('permit_id') in frontier_ids:
                if _is_cost(event.get('cost_usd')):
                    spent += event['cost_usd']
                else:
                    issues.append('cumulative_cap_unverifiable:receipt_without_cost')
    return len(consumed)


def _audit_journal(folder, result, resumed, issues):
    events = result.get('events')
    if not events:
        return
    journal = [e for e in _read_jsonl(folder / 'journal.jsonl')
               if not str(e.get('kind', '')).startswith('arsenal_shadow')]
    if resumed:
        if not journal or events[len(events) - len(journal):] != journal:
            issues.append('journal_not_tail_of_result_events')
    elif journal != events:
        issues.append('journal_differs_from_result_events')


def _audit_release(result, calls, frontier, config, issues):
    released = result.get('answer') is not None
    if released and result.get('status') != 'complete':
        issues.append('answer_released_without_complete_status')
    if result.get('route') == SHORT_ROUTE:
        if released:
            short = config.short_route()
            if (len(calls) != 1 or len(frontier) != 1 or frontier[0].get('role') != 'worker'
                    or frontier[0].get('status') != 'ok'
                    or frontier[0].get('requested_model') != short['model'].split('/', 1)[-1]
                    or frontier[0].get('requested_effort') != short['effort']):
                issues.append('short_route_call_mismatch')
            checks = result.get('hard_checks')
            if not isinstance(checks, dict) or not checks or not all(checks.values()):
                issues.append('short_route_hard_checks_not_passed')
        return
    if not result.get('events'):
        return
    if result.get('protocol_version') == FUSED_PROTOCOL:
        from audit_fused_network import audit as audit_order
    else:
        from audit_network import audit as audit_order
    if released or result.get('status') == 'complete':
        issues += ['order:' + issue for issue in audit_order(result)['issues']]
        native = NativeTransitionBroker.audit_native_calls(
            SimpleNamespace(calls=calls, config=config), result)
        issues += ['native:' + issue for issue in native['issues']]
    else:
        # Unreleased runs: order is still checked, but a partial result may lack
        # fields the order audit needs, and that is not itself a violation.
        try:
            issues += ['order:' + issue for issue in audit_order(result)['issues']]
        except (KeyError, TypeError):
            pass


def _audit_spend(result, frontier, config, issues):
    jev_events = result.get('jev_provider_events') or []
    jev_cost = result.get('jev_api_cost_usd')
    costs = [(e.get('usage') or {}).get('cost') if isinstance(e.get('usage'), dict) else None
             for e in jev_events]
    known = sum(c for c in costs if _is_cost(c))
    if known > config.max_usd:
        issues.append('jev_spend_over_max_usd')
    if any(not _is_cost(c) for c in costs):
        if jev_cost is not None:
            issues.append('jev_cost_reported_despite_unknown_usage')
    elif jev_events or jev_cost is not None:
        if jev_cost is None or abs(jev_cost - known) > 1e-12:
            issues.append('jev_cost_mismatch')

    if not result.get('calls'):
        return
    accounting = result.get('accounting') or {}
    unknown = sum(not _known_tokens(c.get('usage')) for c in frontier)
    if accounting.get('frontier_calls_usage_unknown') != unknown:
        issues.append('unknown_usage_count_mismatch')
    if unknown:
        if (accounting.get('frontier_input_tokens') is not None
                or accounting.get('frontier_output_tokens') is not None):
            issues.append('unknown_usage_summed_as_known')
    elif frontier:
        if (accounting.get('frontier_input_tokens') != sum(c['usage']['input_tokens'] for c in frontier)
                or accounting.get('frontier_output_tokens') != sum(c['usage']['output_tokens'] for c in frontier)):
            issues.append('frontier_token_totals_mismatch')


def audit_run(folder: Path, config: RunConfig) -> dict:
    folder = Path(folder)
    issues = []
    if (folder / 'result.json').is_file():
        result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
    else:
        issues.append('result_missing')
        result = {}
    run_hash = result.get('config_policy_hash')
    if result and run_hash is None:
        issues.append('config_policy_hash_missing')
    elif run_hash is not None and run_hash != config.policy_hash:
        issues.append('config_mismatch')

    calls = result.get('calls') or []
    frontier = [c for c in calls if c.get('role') in ('worker', 'checker')]
    resumed = any(c.get('carried_from_checkpoint') for c in calls)

    consumed = _audit_permits(folder, result, frontier, config, issues)
    if result:
        _audit_journal(folder, result, resumed, issues)
        _audit_release(result, calls, frontier, config, issues)
        _audit_spend(result, frontier, config, issues)

    evidence = {
        'status': result.get('status'),
        'route': result.get('route'),
        'task_hash': result.get('task_hash'),
        'source_hashes': result.get('source_hashes'),
        'policy_hash': config.policy_hash,
        'run_config_policy_hash': run_hash,
        'result_sha256': _sha256(folder / 'result.json'),
        'journal_sha256': _sha256(folder / 'journal.jsonl'),
        'permits_sha256': _sha256(folder / 'permits.jsonl'),
        'jev_calls': len(result.get('jev_provider_events') or []),
        'jev_api_cost_usd': result.get('jev_api_cost_usd'),
        'resumed_calls_carried': sum(bool(c.get('carried_from_checkpoint')) for c in calls),
        'frontier_calls': [{'role': c.get('role'), 'status': c.get('status'),
                            'requested_model': c.get('requested_model'),
                            'actual_model': c.get('actual_model'),
                            'identity_verification': c.get('identity_verification'),
                            'session_id': c.get('session_id'),
                            'permit_id': c.get('permit_id'),
                            'carried_from_checkpoint': bool(c.get('carried_from_checkpoint')),
                            'error_type': c.get('error_type'),
                            'usage_status': c.get('usage_status'),
                            'usage_known': _known_tokens(c.get('usage'))} for c in frontier],
        'permits_consumed': consumed,
        'route_coverage': (result.get('route_coverage') or {}).get('status'),
    }
    return {'ok': not issues, 'issues': issues, 'evidence': evidence}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('run_dir', type=Path, help='broker --out folder')
    parser.add_argument('--config', type=Path, help='RunConfig JSON the run used')
    parser.add_argument('--max-cumulative-usd', type=float, default=None,
                        help='the --max-cumulative-usd the run was launched with; overrides --config')
    parser.add_argument('--host', choices=('claude', 'codex'), default='claude')
    args = parser.parse_args(argv)
    settings = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
    if args.max_cumulative_usd is not None:
        settings['max_cumulative_usd'] = args.max_cumulative_usd
    family = 'claude' if args.host == 'claude' else 'gpt6'
    report = audit_run(args.run_dir, RunConfig.from_dict({**settings, 'worker_family': family}))
    print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

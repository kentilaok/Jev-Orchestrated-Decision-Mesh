"""Structural audit for saved CIDM fused-v1 traces; does not prove semantic truth.

This checks the event sequence and hashes within an exported run. It cannot
attest to a provider's actual inference, hidden model thinking, or a hostile
host that fabricates an internally consistent trace.
"""
import argparse
import json
from pathlib import Path

from atomic_mesh import fingerprint
from checked_network import UNITS


def _audit(result, issues):
    if result.get('protocol_version') != 'cidm-fused-review-v1':
        issues.append('wrong_protocol')
    events = result.get('events', [])
    if not isinstance(events, list):
        issues.append('invalid_events')
        return
    seen = {}
    gates = {}
    gate_dispatches = set()
    issued = {}
    used_deferred = set()
    pending_producer = None
    pending_checker = None
    unreviewed_worker = None
    unreviewed_checker = None
    worker_gate_issued = False
    checker_gate_issued = False
    current_review = None
    policy_action = None
    committed = []
    first_gate_seen = False
    last_release_gate = None
    initial_dispatches = 0
    post_worker_count = 0
    post_checker_count = 0
    entry_goal = None
    entry_evidence = None

    def gate_option(e, worker=None):
        gate = gates.get(e.get('gate_id'))
        if gate is None:
            issues.append('missing_jev_gate')
            return None, None
        option = gate['options'].get(gate['decision']['choice'])
        if option is None:
            issues.append('invalid_gate_choice')
            return gate, None
        if worker is not None and option.get('worker_id') != worker:
            issues.append('wrong_gate_worker')
        return gate, option

    for offset, event in enumerate(events, 1):
        eid = event.get('id')
        kind = event.get('kind')
        if eid != 'e'+str(offset) or eid in seen:
            issues.append('nonsequential_or_duplicate_event')
        if kind == 'jev_decision':
            phase = event.get('phase')
            choice = event.get('decision', {}).get('choice')
            state = event.get('state', {})
            if choice not in event.get('options', {}):
                issues.append('invalid_gate_choice')
            if state.get('policy_version') != result.get('policy_version'):
                issues.append('jev_state_policy_changed')
            if entry_goal is None:
                entry_goal, entry_evidence = state.get('goal'), state.get('evidence')
            elif state.get('goal') != entry_goal or state.get('evidence') != entry_evidence:
                issues.append('jev_state_goal_or_evidence_changed')
            if phase == 'authorize_first_unit':
                if first_gate_seen or committed or pending_producer:
                    issues.append('repeated_or_late_initial_gate')
                first_gate_seen = True
            elif phase == 'after_worker_fused':
                if unreviewed_worker is None:
                    issues.append('worker_gate_without_return')
                else:
                    if worker_gate_issued:
                        issues.append('duplicate_jev_gate_for_worker_return')
                    worker_gate_issued = True
                    state = event.get('state', {})
                    candidate_view = state.get('candidate', {})
                    candidate_hash = (candidate_view.get('raw_return_hash')
                                      if isinstance(candidate_view, dict) and candidate_view.get('invalid_response')
                                      else fingerprint(candidate_view))
                    if candidate_hash != unreviewed_worker['hash']:
                        issues.append('worker_gate_candidate_changed')
                    if state.get('unit', {}).get('id') != unreviewed_worker['unit_id']:
                        issues.append('worker_gate_wrong_unit')
                    if state.get('attempt') != unreviewed_worker['action']['attempt']:
                        issues.append('worker_gate_wrong_attempt')
                    checks = state.get('hard_checks')
                    if not isinstance(checks, dict) or not checks or not all(type(x) is bool for x in checks.values()):
                        issues.append('missing_or_invalid_hard_checks')
            elif phase == 'after_sol_high_fused':
                if unreviewed_checker is None or current_review is None:
                    issues.append('checker_gate_without_return')
                else:
                    if checker_gate_issued:
                        issues.append('duplicate_jev_gate_for_checker_return')
                    checker_gate_issued = True
                    state = event.get('state', {})
                    check_view = state.get('sol_high_result', {})
                    check_hash = (check_view.get('raw_return_hash')
                                  if isinstance(check_view, dict) and check_view.get('verdict') == 'invalid_response'
                                  else fingerprint(check_view))
                    if check_hash != unreviewed_checker['hash']:
                        issues.append('checker_gate_result_changed')
                    if state.get('unit', {}).get('id') != current_review['unit_id']:
                        issues.append('checker_gate_wrong_unit')
                    if state.get('hard_checks') != current_review['checks']:
                        issues.append('checker_gate_hard_checks_changed')
            else:
                issues.append('unknown_jev_phase')
            gates[eid] = event

        elif kind == 'dispatch':
            gate, option = gate_option(event, event.get('worker_id'))
            if option is not None and option.get('action') != event.get('action'):
                issues.append('changed_dispatch_action')
            if event.get('action_hash') != fingerprint(event.get('action')):
                issues.append('changed_dispatch_hash')
            if event.get('gate_id') in gate_dispatches:
                issues.append('reused_jev_gate')
            gate_dispatches.add(event.get('gate_id'))
            worker = event.get('worker_id')
            action = event.get('action', {})
            if action.get('policy_version') != result.get('policy_version'):
                issues.append('dispatch_policy_changed')
            if worker == 'producer':
                initial_dispatches += 1
                if gate is None or gate.get('phase') != 'authorize_first_unit' or initial_dispatches != 1:
                    issues.append('unapproved_initial_dispatch')
                if action.get('unit_id') != UNITS[0].id or action.get('attempt') != 0:
                    issues.append('wrong_initial_unit')
                if pending_producer is not None:
                    issues.append('overlapping_producer_dispatch')
                pending_producer = action
            elif worker == 'checker':
                if gate is None or gate.get('phase') not in ('after_worker_fused', 'after_sol_high_fused'):
                    issues.append('checker_without_post_result_jev')
                if (current_review is None or action.get('candidate_hash') != current_review['candidate_hash']
                        or action.get('checks_hash') != fingerprint(current_review['checks'])):
                    issues.append('checker_candidate_or_checks_changed')
                if pending_checker is not None:
                    issues.append('overlapping_checker_dispatch')
                pending_checker = action
            elif worker == 'policy':
                if gate is None or gate.get('phase') not in ('after_worker_fused', 'after_sol_high_fused'):
                    issues.append('policy_without_post_result_jev')
                if current_review is None or current_review['gate_id'] != event.get('gate_id'):
                    issues.append('policy_without_matching_review')
                elif (action.get('candidate_hash') != current_review['candidate_hash']
                      or action.get('checks_hash') != fingerprint(current_review['checks'])
                      or action.get('check_hash') != (current_review['receipt']['check_hash']
                                                        if current_review['receipt'] else None)):
                    issues.append('policy_candidate_checks_or_checker_changed')
                if action.get('operation') == 'fused_forward':
                    if current_review is None or not all(current_review['checks'].values()):
                        issues.append('failed_hard_checks_forwarded')
                    if current_review is not None and current_review['receipt'] is not None:
                        receipt = current_review['receipt']
                        if not receipt.get('contract_valid') or receipt['result'].get('verdict') != 'pass':
                            issues.append('failed_checker_forwarded')
                elif action.get('operation') != 'fused_retry':
                    issues.append('unknown_policy_action')
                policy_action = {'gate_id': event.get('gate_id'), 'action': action,
                                 'candidate_hash': current_review['candidate_hash'] if current_review else None,
                                 'committed': False, 'deferred_issued': False}
            else:
                issues.append('unknown_dispatch_worker')

        elif kind == 'deferred_issued':
            gate, option = gate_option(event, 'policy')
            action = event.get('action')
            if gate is None or option is None or option['action'].get('next_action') != action:
                issues.append('unapproved_deferred_action')
            if event.get('action_hash') != fingerprint(action):
                issues.append('deferred_issue_hash_changed')
            if policy_action is None or policy_action['gate_id'] != event.get('gate_id'):
                issues.append('deferred_issue_without_policy_dispatch')
            elif policy_action['deferred_issued']:
                issues.append('duplicate_deferred_issue')
            else:
                if policy_action['action']['operation'] == 'fused_forward' and not policy_action['committed']:
                    issues.append('deferred_issue_before_commit')
                if policy_action['action']['operation'] == 'fused_retry' and policy_action['committed']:
                    issues.append('retry_after_commit')
                policy_action['deferred_issued'] = True
            if (current_review is None or event.get('candidate_hash') != current_review['candidate_hash']
                    or event.get('checks_hash') != fingerprint(current_review['checks'])):
                issues.append('deferred_issue_result_changed')
            if event.get('gate_id') in issued:
                issues.append('duplicate_deferred_gate')
            issued[event.get('gate_id')] = event

        elif kind == 'deferred_dispatch':
            gate_id = event.get('gate_id')
            issue = issued.get(gate_id)
            action = event.get('action', {})
            if action.get('policy_version') != result.get('policy_version'):
                issues.append('deferred_policy_changed')
            if issue is None or gate_id in used_deferred:
                issues.append('missing_or_reused_deferred_permit')
            else:
                if offset != int(issue['id'][1:]) + 1:
                    issues.append('deferred_event_cursor_changed')
                if issue.get('action') != action or issue.get('action_hash') != event.get('action_hash'):
                    issues.append('deferred_dispatch_changed')
                if (issue.get('candidate_hash') != event.get('candidate_hash')
                        or issue.get('checks_hash') != event.get('checks_hash')):
                    issues.append('deferred_dispatch_binding_changed')
            if event.get('action_hash') != fingerprint(action):
                issues.append('deferred_dispatch_hash_changed')
            used_deferred.add(gate_id)
            expected_index = len(committed)
            if expected_index >= 5 or action.get('unit_id') != UNITS[expected_index].id:
                issues.append('wrong_deferred_unit_order')
            parents = ([{'id': committed[-1]['id'], 'hash': committed[-1]['artifact_hash']}]
                       if committed else [])
            if action.get('parents') != parents:
                issues.append('deferred_parent_changed')
            if action.get('attempt') not in (0, 1):
                issues.append('invalid_deferred_attempt')
            if pending_producer is not None:
                issues.append('overlapping_producer_dispatch')
            pending_producer = action

        elif kind == 'provisional_return':
            worker = event.get('worker_id')
            if worker == 'producer':
                if pending_producer is None or event.get('unit_id') != pending_producer.get('unit_id'):
                    issues.append('producer_return_without_dispatch')
                else:
                    if unreviewed_worker is not None:
                        issues.append('worker_return_without_jev')
                    unreviewed_worker = {'unit_id': event['unit_id'],
                                         'hash': fingerprint(event.get('value')),
                                         'action': pending_producer,
                                         'value': event.get('value')}
                    worker_gate_issued = False
                pending_producer = None
            elif worker == 'checker':
                if pending_checker is None or event.get('unit_id') != pending_checker.get('unit_id'):
                    issues.append('checker_return_without_dispatch')
                else:
                    unreviewed_checker = {'hash': fingerprint(event.get('value')),
                                          'action': pending_checker,
                                          'value': event.get('value')}
                    checker_gate_issued = False
                pending_checker = None

        elif kind == 'post_worker_decision':
            gate = gates.get(event.get('gate_id'))
            if gate is None or gate.get('phase') != 'after_worker_fused' or unreviewed_worker is None:
                issues.append('worker_result_without_post_jev')
            else:
                if (event.get('choice') != gate['decision']['choice']
                    or event.get('unit_id') != unreviewed_worker['unit_id']
                    or event.get('candidate_hash') != unreviewed_worker['hash']
                    or event.get('hard_checks') != gate['state'].get('hard_checks')):
                    issues.append('worker_decision_binding_changed')
                current_review = {'gate_id': event['gate_id'],
                                  'unit_id': unreviewed_worker['unit_id'],
                                  'candidate_hash': unreviewed_worker['hash'],
                                  'checks': event['hard_checks'],
                                  'receipt': None, 'candidate': unreviewed_worker['value']}
                unreviewed_worker = None
                worker_gate_issued = False
                post_worker_count += 1

        elif kind == 'post_checker_decision':
            gate = gates.get(event.get('gate_id'))
            receipt = event.get('receipt', {})
            if (gate is None or gate.get('phase') != 'after_sol_high_fused' or unreviewed_checker is None
                    or current_review is None):
                issues.append('checker_result_without_post_jev')
            else:
                view = gate['state'].get('sol_high_result')
                if (event.get('choice') != gate['decision']['choice']
                    or event.get('unit_id') != current_review['unit_id']
                    or receipt.get('candidate_hash') != current_review['candidate_hash']
                    or receipt.get('check_hash') != fingerprint(view)
                    or receipt.get('result') != view):
                    issues.append('checker_decision_binding_changed')
                if receipt.get('contract_valid') and view != unreviewed_checker['value']:
                    issues.append('checker_raw_result_changed')
                current_review = {**current_review, 'gate_id': event['gate_id'], 'receipt': receipt}
                unreviewed_checker = None
                checker_gate_issued = False
                post_checker_count += 1

        elif kind == 'checked_commit':
            packet = event.get('packet', {})
            gate, option = gate_option(event, 'policy')
            if (policy_action is None or policy_action['gate_id'] != event.get('gate_id')
                    or policy_action['action'].get('operation') != 'fused_forward'):
                issues.append('commit_without_fused_forward')
            else:
                if policy_action['committed']:
                    issues.append('duplicate_commit_for_gate')
                policy_action['committed'] = True
            if (current_review is None or packet.get('artifact_hash') != current_review['candidate_hash']
                    or packet.get('artifact') != current_review['candidate']
                    or packet.get('checker') != current_review['receipt']):
                issues.append('commit_candidate_or_checker_changed')
            if packet.get('artifact_hash') != fingerprint(packet.get('artifact')):
                issues.append('commit_artifact_hash_changed')
            if not set(packet.get('artifact', {}).get('source_ids', [])) <= {
                    source['id'] for source in (entry_evidence or [])}:
                issues.append('commit_source_outside_evidence')
            if gate is None or gate.get('phase') != packet.get('decision_phase'):
                issues.append('commit_phase_changed')
            if packet.get('policy_version') != result.get('policy_version'):
                issues.append('commit_policy_changed')
            if packet.get('id') != event.get('unit_id') or packet.get('decision_id') != event.get('gate_id'):
                issues.append('commit_identity_changed')
            expected_index = len(committed)
            if expected_index >= 5 or packet.get('id') != UNITS[expected_index].id:
                issues.append('wrong_commit_order')
            expected_parent = ([{'id': committed[-1]['id'], 'hash': committed[-1]['artifact_hash']}]
                               if committed else [])
            if packet.get('parent_artifacts') != expected_parent:
                issues.append('commit_parent_changed')
            if option is None or option['action'].get('candidate_hash') != packet.get('artifact_hash'):
                issues.append('commit_not_selected_by_jev')
            committed.append(packet)
            if option is not None and option['action'].get('next_action') is None:
                last_release_gate = event.get('gate_id')

        seen[eid] = event

    if unreviewed_worker is not None:
        issues.append('worker_return_without_jev')
    if unreviewed_checker is not None:
        issues.append('checker_return_without_jev')
    if pending_producer is not None or pending_checker is not None:
        issues.append('dispatch_without_return')
    if committed != result.get('committed', []):
        issues.append('committed_packets_changed')
    if result.get('checks', []) != [e['receipt'] for e in events if e.get('kind') == 'post_checker_decision']:
        issues.append('checker_receipts_changed')
    if result.get('status') == 'complete':
        if len(issued) != len(used_deferred):
            issues.append('unused_deferred_permit_on_complete_run')
        if len(committed) != 5 or last_release_gate is None or committed[-1]['id'] != 'output':
            issues.append('incomplete_chain_claimed_complete')
        if not committed or result.get('answer') != committed[-1]['artifact']['text']:
            issues.append('final_answer_changed')
        if last_release_gate != committed[-1]['decision_id']:
            issues.append('final_release_not_jev_selected')
    elif result.get('answer') is not None:
        issues.append('unreleased_answer_present')
    if not first_gate_seen:
        issues.append('missing_initial_jev_gate')
    return {'committed_units': [p['id'] for p in committed],
            'jev_decisions': len(gates), 'post_worker_decisions': post_worker_count,
            'post_checker_decisions': post_checker_count,
            'deferred_issued': len(issued), 'deferred_dispatched': len(used_deferred)}


def audit(result):
    issues = []
    stats = None
    try:
        stats = _audit(result, issues)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        issues.append('malformed_trace_'+type(error).__name__)
    return {'valid': not issues, 'status': result.get('status'),
            'issues': list(dict.fromkeys(issues)), **(stats or {})}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Audit one saved fused-v1 CIDM result')
    parser.add_argument('result', type=Path)
    args = parser.parse_args()
    report = audit(json.loads(args.result.read_text(encoding='utf-8')))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['valid'] else 2)

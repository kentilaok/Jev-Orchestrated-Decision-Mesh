"""Offline/reference CIDM controller with one Jev decision per completed unit.

The post-result choice both accepts/rejects the current candidate and authorizes
the exact next dispatch. A deferred, single-use permit binds that dispatch to
the Jev option, candidate, hard checks, sources, policy, and resulting state.
This class does not replace the historical v3 protocol or its audit format.
The injected judge/producer/checker callbacks enforce any live Jev, worker,
token, and dollar caps. A live adapter must reserve a post-result Jev slot
before each producer or checker call; this pure controller has no billing view.
"""
import copy
import uuid

from atomic_mesh import MeshError, fingerprint, packed, require
from checked_network import CheckedNetwork, blind


class FusedCheckedNetwork(CheckedNetwork):
    protocol_version = 'cidm-fused-review-v1'

    def __init__(self, *args, **kwargs):
        # A generic project may not silently label model-written design/code
        # as deterministic. Only the caller can name exact code-only units.
        kwargs.setdefault('deterministic_units', ())
        super().__init__(*args, **kwargs)
        self.policy['review_policy'] = self.protocol_version
        self.policy_version = self.frozen_policy = fingerprint(self.policy)
        self._pending = {}
        self._used_deferred = set()
        self._deferred_gate_ids = set()
        self._running = False
        self._latest_candidate = None
        self._latest_checks = None
        self._latest_binding = None
        self._checker_identity_hash = fingerprint(self.checker_identity)

    def integrity(self):
        super().integrity()
        require(fingerprint(self.checker_identity) == self._checker_identity_hash,
                'checker_identity_changed_during_run')

    def _action_for(self, index, attempt, route, feedback=None, parents_override=None):
        unit = self.units[index]
        parents = (copy.deepcopy(parents_override) if parents_override is not None else
                   [{'id': p['id'], 'hash': p['artifact_hash']} for p in self.committed[-1:]])
        return {'operation': 'compute_unit', 'unit_id': unit.id, 'attempt': attempt,
                'parents': parents, 'worker_route': copy.deepcopy(route),
                'feedback_hash': fingerprint(feedback) if feedback is not None else None,
                'policy_version': self.policy_version}

    def _route_options(self, index, attempt, prefix, feedback=None, min_rank=0, parents_override=None):
        unit = self.units[index]
        if unit.id in self.deterministic_units:
            routes = [('compute', None)]
        else:
            routes = [(route['id'], route) for route in self.worker_routes[min_rank:]]
        return {prefix + name: self._action_for(index, attempt, route, feedback, parents_override)
                for name, route in routes}

    def _binding(self, unit, attempt, candidate, checks, receipt=None):
        self._latest_candidate = candidate
        self._latest_checks = checks
        self._latest_binding = {
            'unit_id': unit.id, 'attempt': attempt,
            'candidate_hash': fingerprint(candidate), 'checks_hash': fingerprint(checks),
            'receipt_hash': fingerprint(receipt) if receipt is not None else None,
            'checker_result_hash': receipt['check_hash'] if receipt is not None else None,
            'checks_log_hash': fingerprint(self.checks),
            'worker_route_hash': fingerprint(self.active_route),
        }

    def _guard_binding(self):
        require(self._latest_binding is not None, 'missing_result_binding')
        require(fingerprint(self._latest_candidate) == self._latest_binding['candidate_hash'],
                'candidate_changed_after_jev')
        require(fingerprint(self._latest_checks) == self._latest_binding['checks_hash'],
                'hard_checks_changed_after_jev')
        require(fingerprint(self.checks) == self._latest_binding['checks_log_hash'],
                'checker_log_changed_after_jev')
        require(fingerprint(self.active_route) == self._latest_binding['worker_route_hash'],
                'worker_route_changed_after_jev')

    def _issue_deferred(self, gate_id, approved, next_action, feedback):
        require(self._running, 'deferred_issue_after_terminal_state')
        self.integrity()
        self._guard_binding()
        event = next((e for e in self.mesh.events if e['id'] == gate_id), None)
        require(event is not None and event['kind'] == 'jev_decision'
                and gate_id in self.mesh._issued_gates, 'unconsumed_fused_gate')
        chosen = event['options'][event['decision']['choice']]
        require(chosen.get('worker_id') == 'policy' and chosen.get('action') == approved,
                'deferred_gate_action_mismatch')
        require(approved.get('candidate_hash') == self._latest_binding['candidate_hash']
                and approved.get('checks_hash') == self._latest_binding['checks_hash']
                and approved.get('check_hash') == self._latest_binding['checker_result_hash'],
                'deferred_result_not_approved')
        require(approved.get('next_action') == next_action and next_action is not None,
                'deferred_action_not_approved')
        require(gate_id not in self._deferred_gate_ids, 'deferred_gate_already_issued')
        require(next_action['feedback_hash'] == (fingerprint(feedback) if feedback is not None else None),
                'deferred_feedback_mismatch')
        token = uuid.uuid4().hex
        self._pending[token] = {
            'gate_id': gate_id, 'gate_hash': fingerprint(event),
            'decision_action_hash': fingerprint(approved),
            'action': copy.deepcopy(next_action), 'action_hash': fingerprint(next_action),
            'feedback': copy.deepcopy(feedback),
            'mesh_hash': self.mesh.state_hash(),
            'committed_hash': fingerprint(self.committed),
            'policy_hash': fingerprint(self.policy),
            'binding': copy.deepcopy(self._latest_binding),
            'binding_hash': fingerprint(self._latest_binding),
        }
        self._deferred_gate_ids.add(gate_id)
        self.mesh.record('deferred_issued', gate_id=gate_id, action=next_action,
                         action_hash=fingerprint(next_action),
                         candidate_hash=self._latest_binding['candidate_hash'],
                         checks_hash=self._latest_binding['checks_hash'])
        self._pending[token]['event_cursor'] = len(self.mesh.events)
        return token

    def dispatch_deferred(self, token, action):
        """Consume one Jev-approved next dispatch; exposed for controller tests."""
        require(self._running, 'deferred_dispatch_after_terminal_state')
        require(token in self._pending and token not in self._used_deferred,
                'missing_or_used_deferred_permit')
        permit = self._pending[token]
        self.integrity()
        self._guard_binding()
        require(fingerprint(self.policy) == permit['policy_hash'], 'deferred_policy_changed')
        require(self.mesh.state_hash() == permit['mesh_hash'], 'stale_deferred_state')
        require(fingerprint(self.committed) == permit['committed_hash'],
                'deferred_predecessor_changed')
        require(fingerprint(self._latest_binding) == permit['binding_hash']
                and self._latest_binding == permit['binding'], 'stale_result_binding')
        require(len(self.mesh.events) == permit['event_cursor'], 'deferred_event_cursor_changed')
        require(fingerprint(permit['action']) == permit['action_hash']
                and action == permit['action'] and fingerprint(action) == permit['action_hash'],
                'deferred_action_changed')
        event = next((e for e in self.mesh.events if e['id'] == permit['gate_id']), None)
        require(event is not None and fingerprint(event) == permit['gate_hash']
                and fingerprint(event['options'][event['decision']['choice']]['action'])
                == permit['decision_action_hash'], 'deferred_gate_changed')
        require(event['options'][event['decision']['choice']]['action']['next_action'] == action,
                'deferred_gate_payload_changed')
        approved = event['options'][event['decision']['choice']]['action']
        require(approved['candidate_hash'] == permit['binding']['candidate_hash']
                and approved['checks_hash'] == permit['binding']['checks_hash']
                and approved['check_hash'] == permit['binding']['checker_result_hash'],
                'deferred_result_binding_changed')
        index = next((i for i, u in enumerate(self.units) if u.id == action['unit_id']), None)
        require(index is not None and len(self.committed) == index
                and [p['id'] for p in self.committed] == [u.id for u in self.units[:index]],
                'deferred_unit_order_changed')
        require(action['attempt'] in (0, 1), 'deferred_attempt_out_of_range')
        route = action['worker_route']
        require((route is None and action['unit_id'] in self.deterministic_units)
                or (route in self.worker_routes and action['unit_id'] not in self.deterministic_units),
                'deferred_route_not_permitted')
        require(action == self._action_for(index, action['attempt'], route, permit['feedback']),
                'deferred_context_changed')
        self._used_deferred.add(token)
        del self._pending[token]
        self.active_route = copy.deepcopy(route)
        self.mesh.record('deferred_dispatch', gate_id=permit['gate_id'], action=action,
                         action_hash=fingerprint(action),
                         candidate_hash=permit['binding']['candidate_hash'],
                         checks_hash=permit['binding']['checks_hash'])
        result = self.producer(self.units[index], copy.deepcopy(self.committed),
                               copy.deepcopy(permit['feedback']), copy.deepcopy(route))
        self.mesh.record('provisional_return', worker_id='producer', unit_id=action['unit_id'], value=result)
        self.integrity()
        return index, action['attempt'], permit['feedback'], result

    def _commit(self, unit, index, candidate, checks, receipt, gate_id, phase):
        self.integrity()
        self._guard_binding()
        require(all(checks.values()) and fingerprint(checks) == self._latest_binding['checks_hash'],
                'failed_or_changed_checks_cannot_forward')
        candidate_hash = self._latest_binding['candidate_hash']
        require(fingerprint(candidate) == candidate_hash, 'candidate_changed_before_commit')
        if receipt is not None:
            require(receipt['contract_valid'] and receipt['candidate_hash'] == candidate_hash
                    and receipt['result']['verdict'] == 'pass'
                    and fingerprint(receipt['result']) == receipt['check_hash']
                    and fingerprint(receipt) == self._latest_binding['receipt_hash'],
                    'failed_or_changed_checker_cannot_forward')
        parents = [{'id': p['id'], 'hash': p['artifact_hash']} for p in self.committed[-1:]]
        packet = {'id': unit.id, 'artifact': copy.deepcopy(candidate), 'artifact_hash': candidate_hash,
                  'parent_artifacts': parents, 'worker_route': copy.deepcopy(self.active_route),
                  'checker': copy.deepcopy(receipt), 'decision_id': gate_id,
                  'decision_phase': phase, 'policy_version': self.policy_version}
        self.committed.append(packet)
        self.mesh.accepted.append({'id': unit.id, 'operation': 'validated_unit',
                                   'summary': candidate['text'], 'source_ids': candidate['source_ids'],
                                   'data': copy.deepcopy(candidate['data']),
                                   'artifact_hash': candidate_hash, 'reviewed_by_sol': receipt is not None})
        self.mesh.version += 1
        self.mesh.record('checked_commit', unit_id=unit.id, packet=packet, gate_id=gate_id)
        return packet

    def _feedback(self, checks, receipt):
        if receipt is not None:
            return copy.deepcopy(receipt['result'])
        return {'verdict': 'repair_required',
                'failed_criteria': [k for k, passed in checks.items() if not passed],
                'reason': 'Jev requested a fresh candidate after this result.',
                'missing_evidence': []}

    def _options(self, index, attempt, candidate, checks, receipt=None, check_attempt=0):
        unit = self.units[index]
        candidate_hash, checks_hash = fingerprint(candidate), fingerprint(checks)
        check_hash = receipt['check_hash'] if receipt is not None else None
        options = {'stop': {'description': 'Stop unresolved without accepting this result.'},
                   'retrieve_evidence': {'description': 'Stop for missing original evidence.'}}
        if all(checks.values()) and (receipt is None or
                                     receipt['contract_valid'] and receipt['result']['verdict'] == 'pass'):
            if index + 1 < len(self.units):
                successor_parents = [{'id': unit.id, 'hash': candidate_hash}]
                for name, next_action in self._route_options(
                        index + 1, 0, 'forward_', parents_override=successor_parents).items():
                    options[name] = {'worker_id': 'policy',
                                     'action': {'operation': 'fused_forward', 'unit_id': unit.id,
                                                'candidate_hash': candidate_hash, 'checks_hash': checks_hash,
                                                'check_hash': check_hash, 'next_action': next_action,
                                                'policy_version': self.policy_version},
                                     'description': 'Accept this checked result and authorize '+name[8:]+' for the next unit.'}
            else:
                options['forward_finish'] = {'worker_id': 'policy',
                                             'action': {'operation': 'fused_forward', 'unit_id': unit.id,
                                                        'candidate_hash': candidate_hash, 'checks_hash': checks_hash,
                                                        'check_hash': check_hash, 'next_action': None,
                                                        'policy_version': self.policy_version},
                                             'description': 'Release this checked output as the final answer.'}
        defect = not all(checks.values()) or (receipt is not None and
                 (not receipt['contract_valid'] or receipt['result']['verdict'] != 'pass'))
        if attempt == 0 and defect:
            feedback = self._feedback(checks, receipt)
            min_rank = (self.worker_routes.index(self.active_route) if self.active_route is not None else 0)
            for name, next_action in self._route_options(index, 1, 'retry_', feedback, min_rank).items():
                options[name] = {'worker_id': 'policy',
                                 'action': {'operation': 'fused_retry', 'unit_id': unit.id,
                                            'candidate_hash': candidate_hash, 'checks_hash': checks_hash,
                                            'check_hash': check_hash, 'next_action': next_action,
                                            'policy_version': self.policy_version},
                                 'description': 'Reject this candidate and retry with '+name[6:]+'.'}
        if receipt is None and all(checks.values()) and len(self.checks) < self.policy.get('max_checker_calls', 10):
            check_action = {'operation': 'sol_high_check', 'unit_id': unit.id,
                            'attempt': attempt, 'check_attempt': 0,
                            'candidate_hash': candidate_hash, 'checks_hash': checks_hash,
                            'policy_version': self.policy_version}
            options['check_sol_high'] = {'worker_id': 'checker', 'action': check_action,
                                         'description': 'Request separate Sol-high review of this exact candidate.'}
        if receipt is not None and check_attempt == 0 and len(self.checks) < self.policy.get('max_checker_calls', 10):
            next_check = {'operation': 'sol_high_check', 'unit_id': unit.id,
                          'attempt': attempt, 'check_attempt': 1,
                          'candidate_hash': candidate_hash, 'checks_hash': checks_hash,
                          'policy_version': self.policy_version}
            options['verify_again'] = {'worker_id': 'checker', 'action': next_check,
                                       'description': 'Request one more Sol-high review of the same candidate.'}
        return options

    def _apply_decision(self, phase, unit, index, attempt, candidate, checks, receipt, options, choice, gate):
        if choice in ('stop', 'retrieve_evidence'):
            return 'stopped_by_jev' if choice == 'stop' else 'needs_evidence'
        selected = options[choice]
        if choice in ('check_sol_high', 'verify_again'):
            return ('check', selected['action'], gate)
        approved = selected['action']
        require(approved['candidate_hash'] == fingerprint(candidate)
                and approved['checks_hash'] == fingerprint(checks)
                and approved['check_hash'] == (receipt['check_hash'] if receipt else None)
                and approved['policy_version'] == self.policy_version, 'fused_choice_binding_mismatch')
        if approved['operation'] == 'fused_forward':
            self.invoke('policy', approved, gate,
                        lambda: self._commit(unit, index, candidate, checks, receipt, gate, phase))
            if approved['next_action'] is None:
                require(index == len(self.units) - 1, 'early_final_release')
                self.final = self.committed[-1]['artifact']['text']
                return 'complete'
            token = self._issue_deferred(gate, approved, approved['next_action'], None)
            return ('dispatch', token, approved['next_action'])
        require(approved['operation'] == 'fused_retry' and attempt == 0,
                'invalid_fused_retry')
        feedback = self._feedback(checks, receipt)
        self.invoke('policy', approved, gate, lambda: None)
        token = self._issue_deferred(gate, approved, approved['next_action'], feedback)
        return ('dispatch', token, approved['next_action'])

    def _review_input(self, unit, candidate, checks):
        return {'goal': self.mesh.goal, 'unit': {'id': unit.id, 'objective': unit.objective},
                'original_evidence': copy.deepcopy(self.mesh.sources),
                'parents': [{'id': p['id'], 'artifact': blind(p['artifact'])}
                            for p in self.committed[-1:]],
                'candidate': blind(candidate), 'hard_checks': copy.deepcopy(checks)}

    def _check_and_decide(self, unit, index, attempt, candidate, checks, action, gate):
        review_input = self._review_input(unit, candidate, checks)
        for check_attempt in range(action['check_attempt'], 2):
            raw = self.invoke('checker', action, gate,
                              lambda: self.checker(copy.deepcopy(review_input)))
            valid = True
            try:
                self.validate_check(raw)
                check = raw
            except MeshError as error:
                valid = False
                check = {'verdict': 'invalid_response', 'contract_error': str(error),
                         'raw_return_hash': fingerprint(raw),
                         'raw_return_preview': packed(raw)[:600],
                         'raw_return_location': 'checker provisional_return journal event'}
            receipt = {'unit_id': unit.id, 'candidate_hash': fingerprint(candidate),
                       'check_hash': fingerprint(check),
                       'checker_model': self.checker_identity['model'],
                       'checker_effort': self.checker_identity['effort'],
                       'contract_valid': valid, 'result': check}
            self.checks.append(copy.deepcopy(receipt))
            self._binding(unit, attempt, candidate, checks, receipt)
            options = self._options(index, attempt, candidate, checks, receipt, check_attempt)
            state = self.state(unit, candidate, checks, check)
            state['attempt'] = attempt
            require(len(packed(state).encode()) <= 16000, 'unit_context_too_large')
            choice, decision_id = self.mesh.gate('after_sol_high_fused', options, state)
            self.mesh.record('post_checker_decision', unit_id=unit.id, choice=choice,
                             gate_id=decision_id, receipt=receipt)
            outcome = self._apply_decision('after_sol_high_fused', unit, index, attempt,
                                           candidate, checks, receipt, options, choice, decision_id)
            if isinstance(outcome, tuple) and outcome[0] == 'check':
                _, action, gate = outcome
                continue
            return outcome
        return 'verification_limit'

    def _after_candidate(self, index, attempt, feedback, candidate):
        unit = self.units[index]
        self.integrity()
        candidate_view = candidate
        try:
            self.validate_artifact(candidate)
            checks = self.validator(unit, copy.deepcopy(candidate), copy.deepcopy(self.committed))
            checks['artifact_schema_valid'] = True
        except MeshError as error:
            checks = {'artifact_schema_valid': False}
            candidate_view = {'invalid_response': True, 'contract_error': str(error),
                              'raw_return_hash': fingerprint(candidate),
                              'raw_return_preview': packed(candidate)[:600],
                              'raw_return_location': 'producer provisional_return journal event'}
        require(isinstance(checks, dict) and checks and all(type(x) is bool for x in checks.values()),
                'invalid_hard_checks')
        self._binding(unit, attempt, candidate, checks)
        options = self._options(index, attempt, candidate, checks)
        state = self.state(unit, candidate_view, checks)
        state['attempt'] = attempt
        state['repair_feedback'] = feedback
        require(len(packed(state).encode()) <= 16000, 'unit_context_too_large')
        choice, gate = self.mesh.gate('after_worker_fused', options, state)
        self.mesh.record('post_worker_decision', unit_id=unit.id, choice=choice,
                         gate_id=gate, candidate_hash=fingerprint(candidate), hard_checks=checks)
        outcome = self._apply_decision('after_worker_fused', unit, index, attempt,
                                       candidate, checks, None, options, choice, gate)
        if isinstance(outcome, tuple) and outcome[0] == 'check':
            return self._check_and_decide(unit, index, attempt, candidate, checks,
                                          outcome[1], outcome[2])
        return outcome

    def run(self):
        status = 'failed'
        try:
            require(not self.mesh.events and not self.committed, 'fused_network_already_started')
            self._running = True
            options = {'stop': {'description': 'Stop without running the network.'},
                       'retrieve_evidence': {'description': 'Stop for missing original evidence before dispatch.'}}
            for name, action in self._route_options(0, 0, '').items():
                options[name] = {'worker_id': 'producer', 'action': action,
                                 'description': 'Authorize the first unit with '+name+'.'}
            choice, gate = self.mesh.gate('authorize_first_unit', options, self.state(self.units[0]))
            if choice in ('stop', 'retrieve_evidence'):
                status = 'stopped_by_jev' if choice == 'stop' else 'needs_evidence'
            else:
                action = options[choice]['action']
                self.active_route = copy.deepcopy(action['worker_route'])
                candidate = self.invoke('producer', action, gate,
                                        lambda: self.producer(self.units[0], [], None,
                                                              copy.deepcopy(self.active_route)))
                index, attempt, feedback = 0, 0, None
                while True:
                    outcome = self._after_candidate(index, attempt, feedback, candidate)
                    if isinstance(outcome, str):
                        status = outcome
                        break
                    require(outcome[0] == 'dispatch', 'invalid_fused_transition')
                    _, token, next_action = outcome
                    index, attempt, feedback, candidate = self.dispatch_deferred(token, next_action)
        except Exception as error:
            status = 'failed'
            self.mesh.record('halt', error=str(error) if isinstance(error, MeshError)
                             else type(error).__name__+': '+str(error))
        finally:
            self._running = False
            self._pending.clear()
        return {'status': status, 'answer': self.final, 'protocol_version': self.protocol_version,
                'policy_version': self.policy_version, 'simulation': self.mesh.simulation,
                'committed': self.committed, 'checks': self.checks, 'events': self.mesh.events}

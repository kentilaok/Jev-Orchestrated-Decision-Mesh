"""Controlled Codex CLI workers with Jev decisions between observable stages.

This standalone broker owns the calls it launches. It cannot intercept an
interactive Codex agent, a worker's private reasoning, or arbitrary host tools.
"""
import argparse
import copy
import json
import math
from pathlib import Path

from adaptive_run import CLASSIFICATION_FLAGS, PROJECT_OPTIONS, input_snapshot_hash
from atomic_mesh import MeshError, fingerprint, packed, require
from checked_network import CheckedNetwork, Unit, blind
from config import RunConfig
from fused_checked_network import FusedCheckedNetwork
from recovery_protocol import (
    RecoverySupervisor, build_recovery_network, checkpoint_bundle, restore_supervisor,
)
from transport import CHECK_SCHEMA, Gateway


PROJECT_UNITS = (
    Unit('input', 'Input', 'Preserve the current request, carried context, and original source identities.'),
    Unit('hidden1', 'Interpret', 'Identify requirements, dependencies, constraints, and missing evidence.'),
    Unit('hidden2', 'Compute', 'Perform the bounded substantive work using accepted context and original evidence.'),
    Unit('hidden3', 'Reconcile', 'Check the proposed work against requirements, predecessors, and source evidence.'),
    Unit('output', 'Output', 'Deliver a concise supported result and state material unresolved issues.'),
)


def validate_spec(spec):
    """Validate one fresh request. Classification truth remains a host assertion."""
    require(type(spec) is dict and set(spec) == {
        'goal', 'context', 'sources', 'active_project', 'unresolved_stages', 'classification'
    }, 'native_spec_schema')
    goal, context = spec['goal'], spec['context']
    require(type(goal) is str and 0 < len(goal) <= 1200, 'native_goal_limit')
    require(type(context) is str and len(context) <= 1200, 'native_context_limit')
    require(type(spec['active_project']) is bool, 'native_active_project_flag')
    unresolved = spec['unresolved_stages']
    require(type(unresolved) is list and len(unresolved) <= 8
            and all(type(value) is str and 0 < len(value) <= 120 for value in unresolved),
            'native_unresolved_stages')
    original = spec['sources']
    require(type(original) is dict and len(original) <= 6, 'native_source_limit')
    sources = {'request': {'title': 'Current request', 'text': goal}}
    if context:
        sources['context'] = {'title': 'Accepted carried context', 'text': context}
    if unresolved:
        sources['outstanding'] = {'title': 'Outstanding project stages',
                                  'text': '\n'.join(unresolved)}
    for sid, source in original.items():
        require(type(sid) is str and sid not in sources
                and sid not in ('request', 'context', 'outstanding')
                and 1 <= len(sid) <= 64 and sid.replace('_', '').replace('-', '').isalnum(),
                'native_source_id')
        require(type(source) is dict and set(source) == {'title', 'text'}
                and type(source['title']) is str and 0 < len(source['title']) <= 120
                and type(source['text']) is str and 0 < len(source['text']) <= 1200,
                'native_source_schema')
        sources[sid] = copy.deepcopy(source)
    task = {key: copy.deepcopy(spec[key]) for key in
            ('goal', 'sources', 'active_project', 'unresolved_stages')}
    snapshot = input_snapshot_hash(task, context)
    classification = spec['classification']
    if classification is None:
        scope = 'broad_or_uncertain'
        record = {'source': 'conservative_default', 'snapshot_hash': snapshot,
                  'flags': None, 'rationale': None, 'scope': scope}
    else:
        require(type(classification) is dict
                and set(classification) == {'snapshot_hash', 'rationale', *CLASSIFICATION_FLAGS},
                'native_classification_schema')
        require(classification['snapshot_hash'] == snapshot, 'stale_native_classification')
        flags = {name: classification[name] for name in CLASSIFICATION_FLAGS}
        require(all(type(value) is bool for value in flags.values()), 'native_classification_flags')
        rationale = classification['rationale']
        require(type(rationale) is str and 10 <= len(rationale) <= 500,
                'native_classification_rationale')
        scope = ('broad_or_uncertain' if any(flags.values()) or spec['active_project'] or unresolved
                 else 'short_self_contained')
        record = {'source': 'explicit_host', 'snapshot_hash': snapshot, 'flags': flags,
                  'rationale': rationale, 'scope': scope,
                  'active_project_guard': spec['active_project'] or bool(unresolved)}
    return {'goal': goal, 'context': context, 'sources': sources,
            'classification': record, 'snapshot_hash': snapshot}


def artifact_schema(source_ids):
    source_ids = list(source_ids)
    data = {'type': 'object', 'properties': {
        'summary': {'type': 'string'},
        'claims': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 12},
        'unresolved': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 8},
        'parent_hashes': {'type': 'array', 'items': {'type': 'string'}},
        'source_hashes': {'type': 'object',
                          'properties': {sid: {'type': 'string'} for sid in source_ids},
                          'required': source_ids, 'additionalProperties': False},
    }, 'required': ['summary', 'claims', 'unresolved', 'parent_hashes', 'source_hashes'],
        'additionalProperties': False}
    return {'type': 'object', 'properties': {
        'text': {'type': 'string'}, 'data': data,
        'source_ids': {'type': 'array', 'items': {'type': 'string', 'enum': list(source_ids)},
                       'minItems': 1},
        'five_scores': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1, 'maximum': 5},
                        'minItems': 5, 'maxItems': 5},
        'self_probability': {'type': ['number', 'null']},
    }, 'required': ['text', 'data', 'source_ids', 'five_scores', 'self_probability'],
        'additionalProperties': False}


class NativeTransitionBroker:
    def __init__(self, adapter, judge, config, folder, *, simulation=False,
                 gate_policy='legacy', arsenal_observer=None, permit_authority=None,
                 evidence_retriever=None):
        require(isinstance(config, RunConfig), 'validated_run_config_required')
        require(gate_policy in ('legacy', 'fused', 'recovery'), 'invalid_native_gate_policy')
        self.adapter, self.judge, self.config = adapter, judge, config
        self.folder, self.simulation = Path(folder), simulation
        self.gate_policy = gate_policy
        require(arsenal_observer is None or callable(arsenal_observer),
                'invalid_arsenal_observer')
        self.arsenal_observer = arsenal_observer
        # Optional Arsenal Phase B capability permits; the adapter must expose
        # prepare(basis) so every frontier call names its exact authorization.
        self.permit_authority = permit_authority
        # Trusted read-only retrieval (MCP plan or local index) for the recovery
        # policy; it turns retrieve_evidence into new hashed sources plus a fresh
        # Jev gate instead of a halt.
        require(evidence_retriever is None or (callable(evidence_retriever) and gate_policy == 'recovery'),
                'evidence_retriever_requires_recovery_policy')
        self.evidence_retriever = evidence_retriever
        self._last_dispatch = None
        self._short_basis = None
        self.calls = []
        self.worker_count = 0
        self.checker_count = 0

    def jev_budget(self):
        """Derive remaining Jev capacity from accepted call receipts, never prompt text."""
        receipts = [call for call in self.calls if call['role'] == 'jev']
        spent_tokens = 0
        spent_usd = 0.0
        for call in receipts:
            usage = call.get('usage')
            require(type(usage) is dict
                    and type(usage.get('input_tokens')) is int and usage['input_tokens'] >= 0
                    and type(usage.get('output_tokens')) is int and usage['output_tokens'] >= 0
                    and type(usage.get('cost')) in (int, float)
                    and math.isfinite(usage['cost']) and usage['cost'] >= 0,
                    'jev_usage_unknown_budget')
            spent_tokens += usage['input_tokens'] + usage['output_tokens']
            spent_usd += usage['cost']
        return {'jev_calls_remaining': self.config.max_jev_calls - len(receipts),
                'jev_tokens_remaining': self.config.max_jev_tokens - spent_tokens,
                'jev_api_usd_remaining': self.config.max_usd - spent_usd,
                'basis': 'reported_input_plus_output_and_cost_receipts'}

    def _judge(self, phase, options, state):
        budget = self.jev_budget()
        require(budget['jev_calls_remaining'] > 0
                and budget['jev_tokens_remaining'] > 0
                and budget['jev_api_usd_remaining'] > 0,
                'jev_budget_exhausted')
        bounded_state = copy.deepcopy(state)
        bounded_state['remaining_budget'] = budget
        try:
            decision = self.judge(phase, options, bounded_state)
            require(type(decision) is dict and decision.get('choice') in options,
                    'invalid_jev_choice')
            require(self.simulation or (decision.get('live') is True
                                        and 'jev-' in decision.get('model', '')),
                    'real_jev_required')
            usage = decision.get('usage')
            require(type(usage) is dict
                    and type(usage.get('input_tokens')) is int and usage['input_tokens'] >= 0
                    and type(usage.get('output_tokens')) is int and usage['output_tokens'] >= 0
                    and type(usage.get('cost')) in (int, float)
                    and math.isfinite(usage['cost']) and usage['cost'] >= 0,
                    'jev_usage_unknown_budget')
        except Exception as error:
            self.calls.append({'role': 'jev', 'phase': phase, 'status': 'failed',
                               'usage': None, 'error_type': type(error).__name__})
            raise MeshError('jev_call_failed') from None
        self.calls.append({'role': 'jev', 'phase': phase, 'choice': decision['choice'],
                           'usage': decision.get('usage'),
                           'identity': decision.get('model'),
                           'identity_verification': 'provider_reported', 'status': 'ok'})
        return decision

    def _codex(self, role, model, effort, prompt, schema):
        # A completed worker/checker always needs capacity for its return to Jev.
        if role == 'checker' or (role == 'worker' and self.calls and
                                 any(call['role'] == 'jev' for call in self.calls)):
            budget = self.jev_budget()
            require(budget['jev_calls_remaining'] > 0
                    and budget['jev_tokens_remaining'] > 0
                    and budget['jev_api_usd_remaining'] > 0,
                    'post_codex_jev_capacity_exhausted')
        if role == 'worker':
            require(self.worker_count < self.config.max_worker_calls,
                    'native_worker_call_budget_exhausted')
            self.worker_count += 1
        else:
            require(self.checker_count < self.config.max_checker_calls,
                    'native_checker_call_budget_exhausted')
            self.checker_count += 1
        requested = model.split('/', 1)[-1]   # 'openai/gpt-6-luna' -> 'gpt-6-luna'; 'anthropic/claude-opus-5' -> 'claude-opus-5'
        response = None
        try:
            if callable(getattr(self.adapter, 'prepare', None)):
                self.adapter.prepare(self._permit_basis(role))
            response = self.adapter.run(requested, effort, prompt, schema, self.worker_workspace)
            require(type(response) is dict and type(response.get('artifact')) is dict,
                    'native_codex_contract_failure')
            require(response.get('requested_model') == requested
                    and response.get('requested_effort') == effort,
                    'native_codex_route_mismatch')
            require(response.get('actual_model') in (None, requested)
                    and response.get('actual_effort') in (None, effort),
                    'native_codex_reported_identity_mismatch')
            artifact_hash = fingerprint(response['artifact'])
        except Exception as error:
            self.calls.append({'role': role, 'requested_model': requested,
                               'requested_effort': effort, 'status': 'failed',
                               'error_type': type(error).__name__,
                               'usage': response.get('usage') if type(response) is dict else None})
            raise MeshError('native_codex_call_failed') from None
        self.calls.append({'role': role, 'requested_model': requested,
                           'requested_effort': effort, 'actual_model': response.get('actual_model'),
                           'actual_effort': response.get('actual_effort'),
                           'identity_verification': response.get('identity_verification'),
                           'usage': response.get('usage'), 'status': 'ok',
                           'artifact_hash': artifact_hash})
        return response['artifact']

    def _permit_basis(self, role):
        """Name the exact authorization for the next frontier call."""
        if self._short_basis is not None:
            return copy.deepcopy(self._short_basis)
        event = self._last_dispatch
        require(event is not None, 'frontier_call_without_dispatch_event')
        expected = 'checker' if role == 'checker' else 'producer'
        require(event.get('worker_id', 'producer') == expected, 'frontier_call_dispatch_role_mismatch')
        return {'kind': 'cidm_mesh_dispatch', 'event_id': event['id'],
                'gate_id': event['gate_id'], 'action_hash': event['action_hash']}

    def _source_hashes(self, sources, selected):
        return {sid: fingerprint(sources[sid]) for sid in selected}

    def audit_native_calls(self, network_result):
        """Reconcile accepted CLI calls with the five-unit journal before release."""
        issues = []
        events = network_result.get('events', [])
        calls = self.calls
        fused = network_result.get('protocol_version') == 'cidm-fused-review-v1'
        recovery = network_result.get('protocol_version') == 'cidm-recovery-first-v1'
        entry_phase = ('authorize_first_unit' if fused else
                       'authorize_unit' if recovery else 'project_route')
        if not calls or calls[0].get('role') != 'jev' or calls[0].get('phase') != entry_phase:
            issues.append('missing_entry_jev')
        if any(call.get('status') != 'ok' for call in calls):
            issues.append('failed_call_in_complete_run')
        for index, call in enumerate(calls):
            if call.get('role') not in ('worker', 'checker'):
                continue
            required_phase = (('after_worker_fused' if call['role'] == 'worker'
                               else 'after_sol_high_fused') if fused else
                              ('after_worker' if call['role'] == 'worker' else 'after_sol_high'))
            following = calls[index + 1] if index + 1 < len(calls) else None
            if not following or following.get('role') != 'jev' or following.get('phase') != required_phase:
                issues.append('native_return_without_jev_' + call['role'])
        decision_events = [event for event in events if event['kind'] == 'jev_decision']
        jev_calls = [call for call in calls if call['role'] == 'jev']
        network_jev_calls = jev_calls if (fused or recovery) else jev_calls[1:]
        for call, event in zip(network_jev_calls, decision_events):
            if (call.get('phase') != event.get('phase')
                    or call.get('choice') != event.get('decision', {}).get('choice')):
                issues.append('jev_call_event_binding_mismatch')
        if not (fused or recovery) and jev_calls and (jev_calls[0].get('choice') !=
                                                     network_result.get('entry_decision', {}).get('choice')):
            issues.append('entry_jev_choice_mismatch')
        decisions = len(decision_events)
        requested_workers = sum(
            (event['kind'] == 'dispatch' and event.get('worker_id') == 'producer'
             or fused and event['kind'] == 'deferred_dispatch')
            and event.get('action', {}).get('worker_route') is not None
            for event in events)
        requested_checkers = sum(event['kind'] == 'dispatch'
                                 and event.get('worker_id') == 'checker' for event in events)
        dispatches = []
        for event in events:
            kind = event['kind']
            action = event.get('action', {})
            if ((kind == 'dispatch' and event.get('worker_id') == 'producer')
                    or fused and kind == 'deferred_dispatch'):
                route = action.get('worker_route')
                if route is not None:
                    dispatches.append(('worker', action.get('unit_id'),
                                       route.get('model', '').split('/', 1)[-1],
                                       route.get('effort')))
            elif kind == 'dispatch' and event.get('worker_id') == 'checker':
                dispatches.append(('checker', action.get('unit_id'),
                                   self.config.checker_model.split('/', 1)[-1],
                                   self.config.checker_effort))
        returns = [event for event in events if event['kind'] == 'provisional_return'
                   and (event.get('worker_id') == 'checker'
                        or event.get('worker_id') == 'producer'
                        and event.get('unit_id') != 'input')]
        codex_calls = [call for call in calls if call['role'] in ('worker', 'checker')]
        if len(dispatches) != len(codex_calls) or len(returns) != len(codex_calls):
            issues.append('native_call_event_count_mismatch')
        for call, dispatch, returned in zip(codex_calls, dispatches, returns):
            role, unit_id, model, effort = dispatch
            if (call['role'] != role or call.get('requested_model') != model
                    or call.get('requested_effort') != effort
                    or returned.get('worker_id') != ('producer' if role == 'worker' else 'checker')
                    or returned.get('unit_id') != unit_id
                    or call.get('artifact_hash') != fingerprint(returned.get('value'))):
                issues.append('native_call_event_binding_mismatch')
        if sum(call['role'] == 'jev' for call in calls) != decisions + (0 if (fused or recovery) else 1):
            issues.append('jev_call_event_mismatch')
        if sum(call['role'] == 'worker' for call in calls) != requested_workers:
            issues.append('worker_call_event_mismatch')
        if sum(call['role'] == 'checker' for call in calls) != requested_checkers:
            issues.append('checker_call_event_mismatch')
        return {'valid': not issues, 'issues': issues,
                'jev_calls': sum(call['role'] == 'jev' for call in calls),
                'worker_calls': requested_workers, 'checker_calls': requested_checkers}

    def _validate_candidate(self, candidate, sources, parents, *, output=False):
        if type(candidate) is not dict:
            return {'native_shape': False}
        data = candidate.get('data')
        ids = candidate.get('source_ids')
        scores = candidate.get('five_scores')
        probability = candidate.get('self_probability')
        expected_parents = [p['artifact_hash'] for p in parents[-1:]]
        shape = (set(candidate) == {'text', 'data', 'source_ids', 'five_scores', 'self_probability'}
                 and type(data) is dict and set(data) ==
                 {'summary', 'claims', 'unresolved', 'parent_hashes', 'source_hashes'}
                 and type(ids) is list and bool(ids)
                 and all(type(sid) is str and sid in sources for sid in ids)
                 and len(ids) == len(set(ids))
                 and type(scores) is list and len(scores) == 5
                 and all(type(score) is int and 1 <= score <= 5 for score in scores)
                 and (probability is None or type(probability) in (int, float)
                      and math.isfinite(probability) and 0 <= probability <= 1)
                 and type(data.get('summary')) is str and 0 < len(data['summary']) <= 1200
                 and type(data.get('claims')) is list and len(data['claims']) <= 12
                 and all(type(item) is str and len(item) <= 500 for item in data['claims'])
                 and type(data.get('unresolved')) is list and len(data['unresolved']) <= 8
                 and all(type(item) is str and len(item) <= 300 for item in data['unresolved'])
                 and type(candidate.get('text')) is str and 0 < len(candidate['text']) <= 1200)
        if shape:
            try:
                shape = len(packed(data)) <= 4000
            except (TypeError, ValueError):
                shape = False
        if not shape:
            return {'native_shape': False}
        prior_unresolved = (any(packet['artifact']['data'].get('unresolved', [])
                                for packet in parents) if output else False)
        return {'native_shape': True,
                'source_hashes_match': data['source_hashes'] == self._source_hashes(sources, sources),
                'parent_hashes_match': data['parent_hashes'] == expected_parents,
                'prior_units_resolved': not prior_unresolved if output else True,
                'output_has_no_unresolved': not data['unresolved'] if output else True}

    def run(self, spec, resume=None):
        """Run one request; `resume` continues a persisted recovery checkpoint.

        resume = {'bundle': <checkpoint.json>, 'additional_sources': {...} | None,
                  'reset_active_unit_rounds': bool, 'operator': str | None}
        """
        normalized = validate_spec(spec)
        require(not self.folder.exists(), 'output_directory_must_be_new')
        if resume is not None:
            require(self.gate_policy == 'recovery', 'resume_requires_recovery_policy')
            host = (resume.get('bundle') or {}).get('host') or {}
            require(host.get('task_hash') == normalized['snapshot_hash'], 'resume_task_mismatch')
            require(host.get('config_policy_hash') == self.config.policy_hash, 'resume_config_mismatch')
            carried = copy.deepcopy(host.get('calls') or [])
            require(all(type(call) is dict and call.get('status') == 'ok' for call in carried),
                    'resume_carried_calls_invalid')
            for call in carried:
                call['carried_from_checkpoint'] = True
            self.calls = carried
            self.worker_count = sum(call['role'] == 'worker' for call in carried)
            self.checker_count = sum(call['role'] == 'checker' for call in carried)
        self.folder.mkdir(parents=True)
        self.worker_workspace = self.folder / 'codex-workspace'
        self.worker_workspace.mkdir()
        sources = normalized['sources']
        goal = normalized['goal']
        context = normalized['context']
        route = normalized['classification']['scope']
        result = {'status': 'failed', 'route': route, 'gate_policy': self.gate_policy,
                  'answer': None,
                  'task_hash': normalized['snapshot_hash'],
                  'classification': normalized['classification'],
                  'source_hashes': self._source_hashes(sources, sources),
                  'calls': [], 'codex_cost_usd': None, 'training_performed': False,
                  'simulation': self.simulation}
        def journal(event):
            if event.get('kind') in ('dispatch', 'deferred_dispatch'):
                self._last_dispatch = copy.deepcopy(event)
            with (self.folder / 'journal.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(packed(event) + '\n')
        if self.arsenal_observer is not None:
            try:
                observation = self.arsenal_observer({
                    'goal': goal,
                    'context_hash': fingerprint(context),
                    'source_ids': list(sources),
                    'classification': copy.deepcopy(normalized['classification']),
                    'task_hash': normalized['snapshot_hash'],
                })
                require(type(observation) is dict, 'invalid_arsenal_observation')
                result['arsenal_shadow'] = copy.deepcopy(observation)
                journal({'kind': 'arsenal_shadow', 'observation': observation})
            except Exception as error:
                result['arsenal_shadow'] = {
                    'mode': 'shadow',
                    'status': 'observer_error',
                    'error_type': type(error).__name__,
                    'authority': 'none_shadow_observation_only',
                }
                journal({'kind': 'arsenal_shadow_error',
                         'error_type': type(error).__name__})
        try:
            if route == 'short_self_contained':
                prompt = packed({'objective': 'Answer this one bounded request using only supplied evidence.',
                                 'goal': goal, 'context': context, 'sources': sources,
                                 'required_source_hashes': self._source_hashes(sources, sources),
                                 'required_parent_hashes': [],
                                 'format': 'Return the requested structured artifact. State unresolved issues.'})
                short = self.config.short_route()
                self._short_basis = {'kind': 'host_short_classification',
                                     'snapshot_hash': normalized['snapshot_hash'],
                                     'classification_source': normalized['classification']['source']}
                candidate = self._codex('worker', short['model'], short['effort'], prompt,
                                        artifact_schema(sources))
                checks = self._validate_candidate(candidate, sources, [], output=True)
                result.update({'hard_checks': checks, 'candidate_hash': fingerprint(candidate),
                               'status': 'complete' if all(checks.values()) else 'quality_failed',
                               'answer': candidate['text'] if all(checks.values()) else None})
                if (len(self.calls) != 1 or self.calls[0].get('role') != 'worker'
                        or self.calls[0].get('requested_model') != short['model'].split('/', 1)[-1]
                        or self.calls[0].get('requested_effort') != short['effort']):
                    result['status'], result['answer'] = 'audit_failed', None
                journal({'kind': 'short_result', 'candidate_hash': fingerprint(candidate),
                         'hard_checks': checks, 'released': result['status'] == 'complete'})
            else:
                entry_allowed = True
                if self.gate_policy == 'legacy':
                    options = copy.deepcopy(PROJECT_OPTIONS)
                    decision = self._judge('project_route', options,
                                           {'goal': goal, 'context_hash': fingerprint(context),
                                            'source_hashes': result['source_hashes'],
                                            'classification': normalized['classification'],
                                            'required_topology': [unit.id for unit in PROJECT_UNITS]})
                    result['entry_decision'] = decision
                    entry_allowed = decision['choice'] == 'five_unit'
                if not entry_allowed:
                    result['status'] = ('needs_evidence' if decision['choice'] == 'retrieve_evidence'
                                        else 'stopped_by_jev')
                else:
                    holder = {}
                    def live_sources():
                        return holder['network'].mesh.sources if 'network' in holder else sources
                    def produce(unit, parents, feedback, worker_route):
                        sources = live_sources()
                        expected = [p['artifact_hash'] for p in parents[-1:]]
                        if unit.id == 'input':
                            return {'text': 'Input and evidence identities preserved.',
                                    'data': {'summary': goal[:1000], 'claims': [], 'unresolved': [],
                                             'parent_hashes': [],
                                             'source_hashes': self._source_hashes(sources, sources)},
                                    'source_ids': list(sources), 'five_scores': [5] * 5,
                                    'self_probability': None}
                        require(worker_route is not None, 'native_worker_route_required')
                        prompt = packed({'unit': {'id': unit.id, 'objective': unit.objective},
                                         'goal': goal, 'context': context, 'sources': sources,
                                         'accepted_parent': [blind(p['artifact']) for p in parents[-1:]],
                                         'required_parent_hashes': expected,
                                         'required_source_hashes': self._source_hashes(sources, sources),
                                         'repair_feedback': feedback,
                                         'format': 'Return only the structured artifact. Cite source IDs, '
                                                   'preserve predecessor hashes, and disclose unresolved issues.'})
                        return self._codex('worker', worker_route['model'], worker_route['effort'],
                                           prompt, artifact_schema(sources))
                    def validate(unit, candidate, parents):
                        return self._validate_candidate(candidate, live_sources(), parents,
                                                        output=unit.id == 'output')
                    def check(state):
                        prompt = packed({'role': 'separate Sol-high checker',
                                         'review': state,
                                         'format': 'Return only the specified checker verdict. '
                                                   'Judge the local unit, not entire project completion.'})
                        return self._codex('checker', self.config.checker_model,
                                           self.config.checker_effort, prompt, CHECK_SCHEMA)
                    if self.gate_policy == 'fused':
                        network = FusedCheckedNetwork(
                            goal, sources, self._judge, produce, check, validate,
                            policy=self.config.to_dict(),
                            checker_identity={'model': self.config.checker_model,
                                              'effort': self.config.checker_effort},
                            worker_routes=self.config.worker_routes(),
                            simulation=self.simulation, journal=journal,
                            units=PROJECT_UNITS, deterministic_units={'input'})
                        holder['network'] = network
                        network_result = network.run()
                    elif self.gate_policy == 'recovery':
                        if resume is not None:
                            supervisor = restore_supervisor(
                                resume['bundle'], self._judge, produce, check, validate,
                                units=PROJECT_UNITS, journal=journal,
                                evidence_retriever=self.evidence_retriever,
                                max_recovery_rounds=self.config.max_recovery_rounds,
                                additional_sources=resume.get('additional_sources'),
                                reset_active_unit_rounds=resume.get('reset_active_unit_rounds', False),
                                operator=resume.get('operator'))
                            network = supervisor.network
                            result['resumed_from'] = resume['bundle']['bundle_hash']
                        else:
                            network = build_recovery_network(
                                goal, sources, self._judge, produce, check, validate,
                                policy=self.config.to_dict(),
                                checker_identity={'model': self.config.checker_model,
                                                  'effort': self.config.checker_effort},
                                worker_routes=self.config.worker_routes(),
                                simulation=self.simulation, journal=journal,
                                units=PROJECT_UNITS, deterministic_units={'input'})
                            supervisor = RecoverySupervisor(
                                network, evidence_retriever=self.evidence_retriever,
                                max_recovery_rounds=self.config.max_recovery_rounds)
                        holder['network'] = network
                        network_result = supervisor.run()
                        if network_result['status'] == 'paused_recoverable':
                            bundle = checkpoint_bundle(supervisor, host={
                                'task_hash': normalized['snapshot_hash'], 'gate_policy': 'recovery',
                                'config_policy_hash': self.config.policy_hash,
                                'calls': copy.deepcopy(self.calls)})
                            path = self.folder / 'checkpoint.json'
                            path.write_text(json.dumps(bundle, indent=2, allow_nan=False), encoding='utf-8')
                            result['checkpoint_bundle'] = {'path': str(path),
                                                           'bundle_hash': bundle['bundle_hash']}
                        if self.evidence_retriever is not None:
                            result['evidence_receipts'] = copy.deepcopy(
                                getattr(self.evidence_retriever, 'receipts', None))
                    else:
                        network = CheckedNetwork(
                            goal, sources, self._judge, produce, check, validate,
                            policy=self.config.to_dict(),
                            checker_identity={'model': self.config.checker_model,
                                              'effort': self.config.checker_effort},
                            worker_routes=self.config.worker_routes(),
                            simulation=self.simulation, journal=journal,
                            units=PROJECT_UNITS, deterministic_units={'input'})
                        holder['network'] = network
                        network_result = network.run()
                    result.update(network_result)
                    result['source_hashes'] = self._source_hashes(holder['network'].mesh.sources,
                                                                  holder['network'].mesh.sources)
                    result['route'] = route
                    if result['status'] == 'complete':
                        try:
                            if self.gate_policy == 'fused':
                                from audit_fused_network import audit
                            else:
                                from audit_network import audit
                            audit_result = audit(result)
                            native_audit = self.audit_native_calls(result)
                            result['audit'] = audit_result
                            result['native_audit'] = native_audit
                            if not audit_result['valid'] or not native_audit['valid']:
                                result['status'], result['answer'] = 'audit_failed', None
                            if self.permit_authority is not None:
                                from capability_permits import audit_permit_ledger
                                result['permit_audit'] = audit_permit_ledger(
                                    self.permit_authority.events(), result.get('events', []))
                                if not result['permit_audit']['valid']:
                                    result['status'], result['answer'] = 'audit_failed', None
                        except Exception as error:
                            result['status'], result['answer'] = 'audit_failed', None
                            result['audit_error_type'] = type(error).__name__
        except MeshError as error:
            result['status'] = str(error)
            result['answer'] = None
        except Exception as error:
            result['status'] = 'native_runtime_failure'
            result['answer'] = None
            result['error_type'] = type(error).__name__
        finally:
            if self.permit_authority is not None and 'permit_audit' not in result:
                from capability_permits import audit_permit_ledger
                result['permit_audit'] = audit_permit_ledger(
                    self.permit_authority.events(),
                    result.get('events') if route != 'short_self_contained' else None)
            if result['status'] != 'complete':
                result['answer'] = None
            result['calls'] = copy.deepcopy(self.calls)
            result['primary_agent_tokens'] = None
            result['jev_api_cost_usd'] = (sum(call['usage']['cost'] for call in self.calls
                                              if call['role'] == 'jev' and type(call.get('usage')) is dict
                                              and type(call['usage'].get('cost')) in (int, float))
                                          if all(type(call.get('usage')) is dict
                                                 and type(call['usage'].get('cost')) in (int, float)
                                                 for call in self.calls if call['role'] == 'jev') else None)
            (self.folder / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False),
                                                     encoding='utf-8')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', type=Path, required=True,
                        help='JSON goal, accepted context, sources, and fresh classification')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--host', choices=('codex', 'claude'), default='codex',
                        help='Worker host: Codex CLI (GPT-6 routes) or Claude Code CLI (Sonnet/Opus routes)')
    parser.add_argument('--gate-policy', choices=('legacy', 'fused', 'recovery'), default='legacy',
                        help='Choose legacy, fused, or recovery-first Jev gate policy for broad requests')
    parser.add_argument('--arsenal-shadow', action='store_true',
                        help='Record local Arsenal routing evidence without changing execution')
    parser.add_argument('--arsenal-db', type=Path,
                        default=Path('~/.jev/arsenal/arsenal.db').expanduser())
    parser.add_argument('--arsenal-project-scope')
    parser.add_argument('--arsenal-bug-key')
    parser.add_argument('--arsenal-operation')
    parser.add_argument('--arsenal-semantic-model')
    parser.add_argument('--arsenal-reranker-model')
    parser.add_argument('--arsenal-shadow-ledger', type=Path,
                        default=Path('~/.jev/arsenal/native-shadow.jsonl').expanduser())
    parser.add_argument('--arsenal-calibration-ledger', type=Path,
                        help='Opt-in append-only shadow calibration; no routing changes')
    parser.add_argument('--evidence-plan', type=Path,
                        help='Recovery policy only: bounded read-only MCP calls for retrieve_evidence')
    parser.add_argument('--mcp-db', type=Path, default=Path('~/.jev/arsenal/mcp.db').expanduser())
    parser.add_argument('--retrieval-index', type=Path,
                        help='Recovery policy only: local hybrid index used for retrieve_evidence')
    parser.add_argument('--retrieval-namespace', default='default')
    parser.add_argument('--resume', type=Path,
                        help='Recovery policy only: continue from a checkpoint.json written by a paused run')
    parser.add_argument('--resume-sources', type=Path,
                        help='JSON object of new sources {id: {title, text}} that satisfy the pause')
    parser.add_argument('--reset-recovery-rounds', action='store_true',
                        help='Grant the paused unit a fresh replan budget (operator action)')
    parser.add_argument('--operator', help='Operator id recorded for resume actions')
    parser.add_argument('--skip-route-preflight', action='store_true',
                        help='Do not compare the frozen route catalogue with the account catalogue')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--live', action='store_true',
                      help='Explicitly permit Codex plan calls and separately billed Jev API calls')
    mode.add_argument('--validate-only', action='store_true',
                      help='Validate the bounded input and report its route without model calls')
    args = parser.parse_args()
    require(not args.arsenal_calibration_ledger or args.arsenal_shadow,
            'calibration_requires_shadow_observer')
    spec = json.loads(args.task.read_text(encoding='utf-8-sig'))
    normalized = validate_spec(spec)
    arsenal_observer = None
    if args.arsenal_shadow:
        from arsenal_shadow import append_ledger, run_shadow
        def arsenal_observer(state):
            observation = run_shadow(
                args.arsenal_db,
                state['goal'],
                project_scope=args.arsenal_project_scope,
                bug_key=args.arsenal_bug_key,
                operation=args.arsenal_operation,
                semantic_model=args.arsenal_semantic_model,
                reranker_model=args.arsenal_reranker_model,
            )
            append_ledger(args.arsenal_shadow_ledger, observation)
            return observation
    if args.validate_only:
        output = {'route': normalized['classification']['scope'],
                  'gate_policy': args.gate_policy, 'host': args.host,
                  'snapshot_hash': normalized['snapshot_hash'],
                  'source_ids': list(normalized['sources']),
                  'model_calls': 0}
        if arsenal_observer is not None:
            try:
                output['arsenal_shadow'] = arsenal_observer({
                    'goal': normalized['goal'],
                    'context_hash': fingerprint(normalized['context']),
                    'source_ids': list(normalized['sources']),
                    'classification': copy.deepcopy(normalized['classification']),
                    'task_hash': normalized['snapshot_hash'],
                })
            except Exception as error:
                output['arsenal_shadow'] = {
                    'mode': 'shadow', 'status': 'observer_error',
                    'error_type': type(error).__name__,
                    'authority': 'none_shadow_observation_only',
                }
        print(packed(output))
        return 0
    require(args.out is not None, 'output_directory_required_for_live_run')
    settings = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
    family = 'claude' if args.host == 'claude' else 'gpt6'
    require(settings.get('worker_family', family) == family, 'host_and_worker_family_mismatch')
    config = RunConfig.from_dict({**settings, 'worker_family': family})
    require(not args.out.exists(), 'output_directory_must_be_new')
    gateway = None
    def judge(phase, options, state):
        nonlocal gateway
        if gateway is None:
            gateway = Gateway(args.out, config)
        return gateway.network_judge(phase, options, state)
    from capability_permits import PermitAuthority
    from frontier_providers import PermittedAdapter, build_provider, route_coverage
    authority = PermitAuthority(args.out / 'permits.jsonl')
    options = ({} if args.host == 'claude'
               else {'astra_explicitly_authorized': config.astra_explicitly_authorized})
    provider = build_provider(args.host, authority, **options)
    coverage = None
    if not args.skip_route_preflight:
        # Fail closed before any paid call when the account cannot serve the
        # frozen route catalogue; never substitute a different model.
        coverage = route_coverage(provider, list(config.worker_routes()),
                                  checker=(config.checker_model, config.checker_effort))
        if coverage['status'] in ('partial', 'unavailable'):
            args.out.mkdir(parents=True)
            result = {'status': 'route_preflight_failed', 'route': normalized['classification']['scope'],
                      'gate_policy': args.gate_policy, 'host': args.host, 'answer': None,
                      'task_hash': normalized['snapshot_hash'], 'route_coverage': coverage,
                      'calls': [], 'simulation': False, 'training_performed': False}
            (args.out / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False),
                                                  encoding='utf-8')
            print(packed({'status': result['status'], 'route': result['route'], 'answer': None,
                          'calls': 0, 'missing_routes': len(coverage['missing'])}))
            return 2
    require(not (args.evidence_plan and args.retrieval_index), 'choose_one_evidence_retriever')
    retriever = None
    if args.evidence_plan:
        require(args.gate_policy == 'recovery', 'evidence_plan_requires_recovery_policy')
        from mcp_registry import McpCatalog, McpEvidenceRetriever, discover_servers
        plan = json.loads(args.evidence_plan.read_text(encoding='utf-8-sig'))
        require(type(plan) is dict and set(plan) <= {'steps', 'max_calls'}, 'evidence_plan_schema')
        servers = {spec['name']: spec for spec in discover_servers()}
        retriever = McpEvidenceRetriever(McpCatalog(args.mcp_db), servers, authority, plan['steps'],
                                         max_calls=plan.get('max_calls', 4),
                                         evidence_dir=args.out / 'evidence')
    elif args.retrieval_index:
        require(args.gate_policy == 'recovery', 'retrieval_requires_recovery_policy')
        from retrieval import LocalHybridIndex, RetrievalEvidenceRetriever
        retriever = RetrievalEvidenceRetriever(LocalHybridIndex(args.retrieval_index), authority,
                                               namespace=args.retrieval_namespace)
    broker = NativeTransitionBroker(
        PermittedAdapter(provider, authority), judge, config, args.out, gate_policy=args.gate_policy,
        arsenal_observer=arsenal_observer, permit_authority=authority, evidence_retriever=retriever)
    resume = None
    if args.resume:
        require(args.gate_policy == 'recovery', 'resume_requires_recovery_policy')
        resume = {'bundle': json.loads(args.resume.read_text(encoding='utf-8')),
                  'additional_sources': (json.loads(args.resume_sources.read_text(encoding='utf-8-sig'))
                                         if args.resume_sources else None),
                  'reset_active_unit_rounds': args.reset_recovery_rounds, 'operator': args.operator}
    result = broker.run(spec, resume=resume)
    result['host'] = args.host
    result['route_coverage'] = coverage if coverage is not None else {'status': 'skipped'}
    provider_events = copy.deepcopy(gateway.calls) if gateway is not None else []
    result['jev_provider_events'] = provider_events
    result['jev_api_cost_usd'] = (
        sum(event['usage']['cost'] for event in provider_events)
        if all(type(event.get('usage')) is dict
               and type(event['usage'].get('cost')) in (int, float)
               for event in provider_events) else None)
    if args.arsenal_calibration_ledger:
        # The calibration ledger observes completed executions only; it is
        # intentionally not consulted by Jev, the adapter, or validators.
        try:
            from arsenal_calibration import (
                append_event, hash_id, prediction_event, read_events, runtime_event,
            )
            run_id = 'native-' + hash_id(
                str(args.out.resolve()) + ':' + result['task_hash']
            )[:24]
            observation = result.get('arsenal_shadow')
            prediction = prediction_event(run_id, result['task_hash'], observation)
            actual = runtime_event(run_id, result)
            previous = read_events(args.arsenal_calibration_ledger)
            if any(item['run_id'] == run_id for item in previous):
                raise ValueError('duplicate_or_partial_calibration_run')
            append_event(args.arsenal_calibration_ledger, prediction)
            append_event(args.arsenal_calibration_ledger, actual)
            result['arsenal_calibration'] = {
                'status': 'recorded', 'run_id': run_id, 'authority': 'none',
            }
        except Exception as error:
            result['arsenal_calibration'] = {
                'status': 'record_failed',
                'error_type': type(error).__name__,
                'authority': 'none',
            }
    (args.out / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False),
                                          encoding='utf-8')
    print(packed({'status': result['status'], 'route': result['route'],
                  'answer': result['answer'], 'calls': len(result['calls'])}))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())

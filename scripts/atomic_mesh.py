"""CIDM v0.2: Jev-controlled observable microsteps, not private model thoughts.

Pure controller. The worker API gets no tools; only this broker executes actions.
Callbacks supplied by the host are trusted integration code, not a sandbox.
"""
import ast
import copy
import hashlib
import json
import math
import operator
import uuid
from fractions import Fraction


class MeshError(Exception):
    pass


def require(ok, code):
    if not ok:
        raise MeshError(code)


def packed(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def calculate(expression):
    """Small exact-operation allowlist; no eval, names, calls, powers, or attributes."""
    require(isinstance(expression, str) and 0 < len(expression) <= 120, 'invalid_expression')
    try:
        tree = ast.parse(expression, mode='eval')
    except SyntaxError:
        raise MeshError('invalid_expression') from None
    require(len(list(ast.walk(tree))) <= 30, 'expression_too_complex')
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            try:
                value = Fraction(ast.get_source_segment(expression,node).replace('_',''))
            except (ValueError,ZeroDivisionError):
                raise MeshError('invalid_numeric_literal') from None
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in operations:
            try:
                value = operations[type(node.op)](visit(node.left), visit(node.right))
            except (ZeroDivisionError, OverflowError):
                raise MeshError('invalid_arithmetic') from None
        else:
            raise MeshError('operation_not_allowed')
        require(math.isfinite(value) and abs(value) <= 1e12, 'arithmetic_out_of_range')
        return value
    return visit(tree.body)


class AtomicMesh:
    def __init__(self, goal, sources, workers, judge, *, constraints=(), max_steps=8,
                 max_state_bytes=6500, simulation=False, journal=None):
        require(isinstance(goal, str) and 0 < len(goal) <= 1500, 'invalid_goal')
        require(workers and 1 <= max_steps <= 30, 'invalid_configuration')
        self.goal, self.constraints = goal, list(constraints)
        self.sources = copy.deepcopy(sources)
        for sid, source in self.sources.items():
            require(isinstance(sid, str) and isinstance(source, dict), 'invalid_source')
            require(isinstance(source.get('text'), str) and 0 < len(source['text']) <= 1200, 'source_requires_chunking')
        self.source_hashes = {sid: fingerprint(s) for sid, s in self.sources.items()}
        self.workers, self.judge = workers, judge
        require('stop' not in workers, 'reserved_worker_id')
        self.max_steps, self.max_state_bytes = max_steps, max_state_bytes
        self.simulation, self.journal = simulation, journal
        self.version, self.events, self.accepted = 0, [], []
        self._permits = {}
        self._used = set()
        self._issued_gates = set()
        self.final = None
        self.last_issue = None
        self.pending_verification = None
        self.invalidated = set()
        self.stalled = {}

    def record(self, kind, **data):
        event = {'id': 'e'+str(len(self.events)+1), 'kind': kind, 'version': self.version,
                 'simulation': self.simulation, **copy.deepcopy(data)}
        self.events.append(event)
        if self.journal:
            self.journal(copy.deepcopy(event))
        return event['id']

    def state_hash(self):
        require(set(self.sources)==set(self.source_hashes), 'source_set_changed')
        require(all(fingerprint(s)==self.source_hashes[sid] for sid,s in self.sources.items()), 'source_changed')
        return fingerprint({'goal': self.goal, 'constraints': self.constraints,
                            'sources': self.source_hashes, 'accepted': self.accepted, 'version': self.version,
                            'last_issue':self.last_issue,'pending_verification':self.pending_verification,
                            'invalidated':sorted(self.invalidated),'stalled':self.stalled})

    def context(self, source_ids=(), result=None):
        # Local accepted observations plus actual selected evidence. No hidden text truncation.
        source_ids = list(dict.fromkeys(source_ids))
        require(all(sid in self.sources for sid in source_ids), 'unknown_source')
        active=[r for r in self.accepted if r['id'] not in self.invalidated]
        state = {'goal': self.goal, 'constraints': self.constraints, 'version': self.version,
                 'source_manifest': [{'id': sid, 'title': s.get('title', sid)} for sid,s in self.sources.items()],
                 'recent_accepted': active[-3:],
                 'older_accepted_ids': [r['id'] for r in active[:-3]],
                 'evidence': [{'id': sid, 'hash': self.source_hashes[sid], 'text': self.sources[sid]['text']} for sid in source_ids],
                 'last_issue': self.last_issue, 'pending_verification':self.pending_verification,
                 'invalidated_result_ids':sorted(self.invalidated),
                 'completion':{'accepted_draft_ids':[r['id'] for r in active if r.get('mode')=='draft_answer'],
                               'released':self.final is not None,'required':'Accept a draft_answer, then explicitly finish to deliver it.'}}
        if result is not None:
            state['candidate_result'] = result
        require(len(packed(state).encode()) <= self.max_state_bytes, 'focused_context_limit_exceeded')
        return copy.deepcopy(state)

    def gate(self, phase, options, state):
        require(len(options) >= 2 and len(options)==len(set(options)), 'invalid_gate_options')
        before = self.state_hash()
        decision = self.judge(phase, copy.deepcopy(options), copy.deepcopy(state))
        require(isinstance(decision, dict) and decision.get('choice') in options, 'invalid_jev_choice')
        require(self.simulation or (decision.get('live') is True and 'jev-' in decision.get('model', '')), 'real_jev_required')
        require(before==self.state_hash(), 'state_changed_during_gate')
        eid = self.record('jev_decision', phase=phase, options=options, state_hash=before,
                          state=state, decision=decision)
        return decision['choice'], eid

    def permit(self, worker_id, action, gate_id):
        require(gate_id in {e['id'] for e in self.events if e['kind']=='jev_decision'}, 'missing_gate')
        event = next(e for e in self.events if e['id']==gate_id)
        require(gate_id not in self._issued_gates and event['state_hash']==self.state_hash(), 'gate_already_used_or_stale')
        chosen = event['decision']['choice']
        # Bind the exact payload shown to Jev; a receipt cannot approve new arguments.
        approved = event['options'][chosen]
        require(approved.get('worker_id')==worker_id and approved.get('action')==action, 'gate_payload_mismatch')
        token = uuid.uuid4().hex
        self._permits[token] = {'worker_id': worker_id, 'action_hash': fingerprint(action),
                                'state_hash': self.state_hash(), 'gate_id': gate_id}
        self._issued_gates.add(gate_id)
        return token

    def consume(self, worker_id, action, token):
        require(token in self._permits and token not in self._used, 'missing_or_used_permit')
        grant = self._permits[token]
        require(grant['worker_id']==worker_id and grant['action_hash']==fingerprint(action), 'permit_scope_mismatch')
        require(grant['state_hash']==self.state_hash(), 'stale_permit')
        self._used.add(token)
        return grant['gate_id']

    def validate_options(self, options):
        require(isinstance(options, list) and 1 <= len(options) <= 3, 'invalid_proposal_count')
        seen = set()
        for option in options:
            require(isinstance(option, dict) and set(option)=={'id','operation','objective','source_ids','arguments'}, 'invalid_proposal_schema')
            require(isinstance(option['id'], str) and 0 < len(option['id']) <= 32 and option['id'] not in seen, 'invalid_option_id')
            seen.add(option['id'])
            require(option['id'] not in ('stop','request_new_options'), 'reserved_option_id')
            require(isinstance(option['objective'], str) and 0 < len(option['objective']) <= 240, 'objective_must_be_bounded')
            op, args, refs = option['operation'], option['arguments'], option['source_ids']
            require(op in ('read_source','recall','calculate','reason','finish'), 'operation_not_allowed')
            require(isinstance(refs, list) and len(refs)<=3 and all(s in self.sources for s in refs), 'invalid_source_refs')
            require(isinstance(args, dict), 'invalid_arguments')
            if self.pending_verification:
                require(op in ('read_source','recall','calculate') or (op=='reason' and args.get('mode')=='verify'), 'verification_required_before_continuing')
            if op=='read_source':
                require(set(args)=={'source_id'} and args['source_id'] in refs and len(refs)==1, 'invalid_read')
            elif op=='recall':
                require(set(args)=={'result_id'} and any(r['id']==args['result_id'] and r['id'] not in self.invalidated for r in self.accepted), 'invalid_recall')
            elif op=='calculate':
                require(set(args)=={'expression'} and refs, 'invalid_calculation')
                calculate(args['expression'])
            elif op=='reason':
                require(set(args)=={'mode','question'} and args['mode'] in ('hypothesis','compare','derive','verify','summarize','draft_answer'), 'invalid_reasoning_unit')
                require(isinstance(args['question'], str) and 0 < len(args['question']) <= 300, 'question_must_be_bounded')
            elif op=='finish':
                require(set(args)=={'result_id'} and any(r['id']==args['result_id'] and r['id'] not in self.invalidated and r['operation']=='reason' and r.get('mode')=='draft_answer' for r in self.accepted), 'finish_requires_accepted_draft')
        return options

    def validate_packet(self, packet, refs, mode=None):
        fields={'summary','source_ids','five_scores','self_probability','uncertainties'}
        if mode=='verify': fields.add('verification')
        require(isinstance(packet, dict) and set(packet)==fields, 'invalid_worker_packet')
        if mode=='verify': require(packet['verification'] in ('supported','defect','uncertain'),'invalid_verification_finding')
        require(isinstance(packet['summary'], str) and 0 < len(packet['summary']) <= 800, 'result_too_large')
        require(isinstance(packet['source_ids'], list) and all(s in refs for s in packet['source_ids']), 'unprovided_source_ref')
        require(isinstance(packet['five_scores'], list) and len(packet['five_scores'])==5 and all(type(s) is int and 1<=s<=5 for s in packet['five_scores']), 'invalid_five_scores')
        p = packet['self_probability']
        require(p is None or (type(p) in (int,float) and math.isfinite(p) and 0<=p<=1), 'invalid_self_probability')
        require(isinstance(packet['uncertainties'], list) and len(packet['uncertainties'])<=3 and all(isinstance(s,str) and len(s)<=160 for s in packet['uncertainties']), 'invalid_uncertainties')
        return packet

    def dispatch(self, worker_id, action, token):
        gate_id = self.consume(worker_id, action, token)
        self.record('dispatch', worker_id=worker_id, action=action, gate_id=gate_id, action_hash=fingerprint(action))
        op = action['operation']
        if op=='propose':
            return self.workers[worker_id].propose(self.context())
        args, refs = action['arguments'], action['source_ids']
        if op=='read_source':
            sid=args['source_id']
            return {'summary': self.sources[sid]['text'], 'source_ids': [sid], 'checks': {'exact_source_copy': True}}
        if op=='recall':
            recalled=copy.deepcopy(next(r for r in self.accepted if r['id']==args['result_id']))
            return {'summary': recalled['summary'], 'source_ids': recalled['source_ids'], 'checks': {'exact_recall': True}}
        if op=='calculate':
            return {'summary': args['expression']+' = '+str(calculate(args['expression'])), 'source_ids': refs,
                    'checks': {'arithmetic_verified': True, 'operand_semantics_verified': False}}
        if op=='reason':
            raw=self.workers[worker_id].execute(copy.deepcopy(action), self.context(refs))
            self.record('worker_result', worker_id=worker_id, raw=raw)
            try:
                return self.validate_packet(raw, refs, args['mode'])
            except MeshError as e:
                e.artifact_preview=packed(raw)[:800]
                raise
        if op=='finish':
            candidate=next(r for r in self.accepted if r['id']==args['result_id'])
            return {'summary': candidate['summary'], 'source_ids': candidate['source_ids'], 'checks': {'accepted_draft_selected': True}}
        raise MeshError('operation_not_allowed')

    def run(self):
        status='step_limit'
        try:
            for step in range(self.max_steps):
                routes={wid:{'worker_id':wid,'action':{'operation':'propose'},'description':w.description} for wid,w in self.workers.items()}
                if not self.pending_verification:
                    for draft in self.accepted:
                        if draft.get('mode')=='draft_answer' and draft['id'] not in self.invalidated:
                            action={'id':'finish_'+draft['id'],'operation':'finish','objective':'Release this accepted draft after final review.',
                                    'source_ids':draft['source_ids'],'arguments':{'result_id':draft['id']}}
                            routes['finish_'+draft['id']]={'worker_id':draft['worker_id'],'action':action,'description':'Select an accepted draft for final release review.'}
                routes['stop']={'description':'Stop unresolved without delivering any answer, only if useful progress cannot continue. Successful verification still needs a draft and explicit finish.'}
                route, eid = self.gate('before_proposal', routes, self.context())
                if route=='stop': status='stopped_by_jev'; break
                selected=routes[route]
                route=selected['worker_id']
                if selected['action']['operation']=='finish':
                    action=selected['action']
                else:
                    proposal_action={'operation':'propose'}
                    raw=self.dispatch(route,proposal_action,self.permit(route,proposal_action,eid))
                    self.record('worker_proposals', worker_id=route, proposals=raw)
                    try:
                        options=self.validate_options(raw)
                    except MeshError as e:
                        self.last_issue={'error':str(e),'invalid_proposal_preview':packed(raw)[:800]}
                        self.record('proposal_rejected', reason=str(e))
                        continue
                    choices={o['id']:{'worker_id':route,'action':o} for o in options}
                    choices['request_new_options']={'description':'Proposals are inadequate; request different bounded options next round.'}
                    choices['stop']={'description':'Stop without executing any proposal.'}
                    refs=list(dict.fromkeys(s for o in options for s in o['source_ids']))
                    choice,eid=self.gate('before_action',choices,self.context(refs))
                    if choice=='stop': status='stopped_by_jev'; break
                    if choice=='request_new_options':
                        self.last_issue='Jev requested different next-step options.'
                        continue
                    action=choices[choice]['action']
                try:
                    result=self.dispatch(route,action,self.permit(route,action,eid))
                    valid=True
                except MeshError as e:
                    result={'summary':'Execution failed: '+str(e),'source_ids':action['source_ids'],'checks':{'hard_failure':True}}
                    if hasattr(e,'artifact_preview'):
                        result['invalid_artifact_preview']=e.artifact_preview
                    valid=False
                self.record('uncommitted_result', worker_id=route, action=action, result=result)
                state=self.context(action['source_ids'],result)
                state['public_contract_valid']=valid
                state['authorized_action']=copy.deepcopy(action)
                review={'commit':{'description':'Use this bounded result; required checks pass and the provided evidence supports its meaning.'},
                        'verify':{'description':'Meaning or evidence is uncertain; request a focused verification or original source.'},
                        'reject':{'description':'A concrete defect or failed hard check prevents using the result.'},
                        'stop':{'description':'Stop without committing this result.'}}
                verdict,review_id=self.gate('after_action',review,state)
                if verdict=='stop': status='stopped_by_jev'; break
                if verdict=='commit' and valid:
                    accepted={'id':'r'+str(len(self.accepted)+1),'operation':action['operation'],
                              'mode':action['arguments'].get('mode'),'worker_id':route,**copy.deepcopy(result)}
                    self.accepted.append(accepted)
                    self.version+=1
                    self.last_issue=None
                    self.stalled={}
                    self.record('commit', result=accepted, gate_id=review_id)
                    if action['operation']=='reason' and action['arguments'].get('mode')=='verify' and self.pending_verification:
                        if result['verification'] in ('supported','defect'):
                            if result['verification']=='defect':
                                original=self.pending_verification['action']
                                if original['operation']=='finish': self.invalidated.add(original['arguments']['result_id'])
                                self.last_issue={'confirmed_defect':result['summary']}
                            self.pending_verification=None
                    if action['operation']=='finish':
                        self.final=result['summary']; status='complete'; break
                else:
                    self.last_issue={'decision':verdict,'action':action['objective'],'result':result}
                    if verdict=='verify': self.pending_verification={'action':action,'candidate':result}
                    self.record('not_committed', decision=verdict, gate_id=review_id, hard_failure=not valid)
                    key=fingerprint({'operation':action['operation'],'arguments':action['arguments'],'source_ids':action['source_ids']})
                    self.stalled[key]=self.stalled.get(key,0)+1
                    if self.stalled[key]>=2:
                        status='no_progress'; break
            else:
                status='step_limit'
        except Exception as e:
            status='failed'
            self.record('halt', error=e.code if hasattr(e,'code') else type(e).__name__+': '+str(e))
        return {'version':'0.2','status':status,'simulation':self.simulation,'answer':self.final,
                'accepted':copy.deepcopy(self.accepted),'events':copy.deepcopy(self.events)}

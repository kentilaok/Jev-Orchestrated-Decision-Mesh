"""Five CIDM units with Jev after every output and optional Sol-high review."""
import copy
from dataclasses import dataclass
from atomic_mesh import AtomicMesh, MeshError, require, fingerprint, packed
from config import RunConfig


@dataclass(frozen=True)
class Unit:
    id: str
    name: str
    objective: str


UNITS = (
    Unit('input','Input','Normalize the original data without changing source values or scope.'),
    Unit('hidden1','Interpret','Identify the included records and the calculation requested by the user.'),
    Unit('hidden2','Compute','Calculate the result using the checked interpretation and exact arithmetic.'),
    Unit('hidden3','Reconcile','Check whether the calculation, interpretation, and original evidence agree.'),
    Unit('output','Output','Produce the final answer supported by the checked predecessors and sources.'),
)


def blind(value):
    excluded={'five_scores','self_probability','router_advice','jev_decision','confidence'}
    if isinstance(value,dict): return {k:blind(v) for k,v in value.items() if k not in excluded}
    if isinstance(value,list): return [blind(v) for v in value]
    return copy.deepcopy(value)


class PlaceholderWorker:
    description='Registered gate computation; execution is owned by the checked network broker.'


class CheckedNetwork:
    def __init__(self, goal, sources, judge, producer, checker, validator, *,
                 policy=None, checker_identity=None, worker_routes=None, simulation=False, journal=None, units=UNITS):
        require(len(units)==5 and [u.id for u in units]==[u.id for u in UNITS], 'expected_five_sequential_units')
        self.units=units; self.producer=producer; self.checker=checker; self.validator=validator
        self.policy=copy.deepcopy(policy or {"version":"training-free-v1"})
        self.policy['review_policy']='jev_conditional_sol_high_v3'
        astra_allowed=self.policy.get('astra_explicitly_authorized') is True
        expected_routes=RunConfig(astra_explicitly_authorized=astra_allowed).worker_routes()
        self.worker_routes=copy.deepcopy(worker_routes if worker_routes is not None else expected_routes)
        require(self.worker_routes==expected_routes, 'worker_route_catalog_mismatch')
        self.policy['worker_routes']=self.worker_routes
        self.policy_version=fingerprint(self.policy)
        self.frozen_policy=self.policy_version
        self.checker_identity=copy.deepcopy(checker_identity or {"model":"openai/gpt-6-sol","effort":"high"})
        self.mesh=AtomicMesh(goal,sources,{'producer':PlaceholderWorker(),'checker':PlaceholderWorker(),'policy':PlaceholderWorker()},
                             judge,simulation=simulation,max_state_bytes=16000,journal=journal)
        self.committed=[]; self.checks=[]; self.final=None
        self.active_route=None

    def integrity(self):
        require(self.policy_version==self.frozen_policy and fingerprint(self.policy)==self.frozen_policy,'policy_changed_during_run')
        require(all(fingerprint(p['artifact'])==p['artifact_hash'] for p in self.committed),'committed_artifact_changed')

    def state(self, unit, candidate=None, checks=None, checker_result=None):
        self.integrity()
        state=self.mesh.context(list(self.mesh.sources))
        state['unit']={'id':unit.id,'name':unit.name,'objective':unit.objective}
        state['parents']=[{'id':p['id'],'artifact_hash':p['artifact_hash']} for p in self.committed[-1:]]
        state['completion']={'completed_units':[p['id'] for p in self.committed],
                             'required_order':[u.id for u in self.units],'active_unit':unit.id,'released':self.final is not None}
        state['policy_version']=self.policy_version
        if self.active_route is not None: state['selected_worker']=copy.deepcopy(self.active_route)
        if candidate is not None: state['candidate']=candidate
        if checks is not None: state['hard_checks']=checks
        if checker_result is not None: state['sol_high_result']=checker_result
        require(len(packed(state).encode())<=16000,'unit_context_too_large')
        return state

    def invoke(self, worker_id, action, gate_id, fn):
        self.integrity()
        permit=self.mesh.permit(worker_id,action,gate_id)
        authorizer=self.mesh.consume(worker_id,action,permit)
        self.mesh.record('dispatch',worker_id=worker_id,action=action,action_hash=fingerprint(action),gate_id=authorizer)
        value=fn()
        self.mesh.record('provisional_return',worker_id=worker_id,unit_id=action['unit_id'],value=value)
        return value

    def validate_artifact(self, candidate):
        require(isinstance(candidate,dict) and set(candidate)=={'text','data','source_ids','five_scores','self_probability'},'artifact_schema')
        require(isinstance(candidate['text'],str) and len(candidate['text'])<=1200,'artifact_text_limit')
        require(isinstance(candidate['data'],dict) and len(packed(candidate['data']))<=4000,'artifact_data_limit')
        require(isinstance(candidate['source_ids'],list) and all(s in self.mesh.sources for s in candidate['source_ids']),'artifact_sources')
        require(not self.mesh.sources or bool(candidate['source_ids']),'artifact_source_required')
        require(isinstance(candidate['five_scores'],list) and len(candidate['five_scores'])==5 and all(type(x)is int and 1<=x<=5 for x in candidate['five_scores']),'artifact_scores')
        p=candidate['self_probability']
        require(p is None or (type(p)in(int,float) and 0<=p<=1),'artifact_probability')

    @staticmethod
    def validate_check(check):
        require(isinstance(check,dict) and set(check)=={'verdict','failed_criteria','reason','missing_evidence'},'checker_schema')
        require(check['verdict'] in ('pass','repair_required','insufficient_evidence','reject'),'checker_verdict')
        require(isinstance(check['reason'],str) and len(check['reason'])<=800,'checker_reason')
        for key in ('failed_criteria','missing_evidence'):
            require(isinstance(check[key],list) and len(check[key])<=6 and all(isinstance(x,str) and len(x)<=200 for x in check[key]),'checker_list')
        require(check['verdict']!='pass' or not check['failed_criteria'] and not check['missing_evidence'],'inconsistent_checker_pass')

    def forward_action(self, unit, index, candidate_hash, receipt):
        return {'operation':'forward','unit_id':unit.id,'candidate_hash':candidate_hash,
                'check_hash':receipt['check_hash'] if receipt else None,
                'successor':self.units[index+1].id if index+1<len(self.units) else 'user',
                'policy_version':self.policy_version}

    def commit_candidate(self, unit, index, candidate, candidate_hash, parents, checks, receipt, decision_id, phase):
        require(all(checks.values()),'failed_candidate_cannot_forward')
        require(fingerprint(candidate)==candidate_hash,'candidate_changed_before_commit')
        if receipt is not None:
            require(receipt['contract_valid'] and receipt['candidate_hash']==candidate_hash
                    and receipt['result']['verdict']=='pass'
                    and fingerprint(receipt['result'])==receipt['check_hash'],'failed_or_changed_checker_cannot_forward')
        action=self.forward_action(unit,index,candidate_hash,receipt)
        def commit():
            packet={'id':unit.id,'artifact':copy.deepcopy(candidate),'artifact_hash':candidate_hash,
                    'parent_artifacts':copy.deepcopy(parents),'worker_route':copy.deepcopy(self.active_route),
                    'checker':copy.deepcopy(receipt),'decision_id':decision_id,'decision_phase':phase,
                    'policy_version':self.policy_version}
            self.committed.append(packet)
            self.mesh.accepted.append({'id':unit.id,'operation':'validated_unit','summary':candidate['text'],
                                       'source_ids':candidate['source_ids'],'data':copy.deepcopy(candidate['data']),
                                       'artifact_hash':candidate_hash,'reviewed_by_sol':receipt is not None})
            self.mesh.version+=1
            self.mesh.record('checked_commit',unit_id=unit.id,packet=packet,gate_id=decision_id)
            return packet
        self.invoke('policy',action,decision_id,commit)

    def run_unit(self, unit, index):
        require(type(index) is int and 0<=index<len(self.units) and unit==self.units[index],'unit_index_mismatch')
        require(len(self.committed)==index and [p['id'] for p in self.committed]==[u.id for u in self.units[:index]],
                'unit_predecessor_missing')
        feedback=None
        min_route_rank=0
        for attempt in range(2):
            self.active_route=None
            parents=[{'id':p['id'],'hash':p['artifact_hash']} for p in self.committed[-1:]]
            base_action={'operation':'compute_unit','unit_id':unit.id,'attempt':attempt,'parents':parents,
                         'policy_version':self.policy_version}
            state=self.state(unit); state['repair_feedback']=feedback
            options={'stop':{'description':'Stop without computing or forwarding.'}}
            if unit.id in ('input','hidden2'):
                options['compute']={'worker_id':'producer','action':{**base_action,'worker_route':None},
                                    'description':'Use deterministic code for this unit; no generative worker call.'}
            else:
                for route in self.worker_routes[min_route_rank:]:
                    options[route['id']]={'worker_id':'producer','action':{**base_action,'worker_route':route},
                                          'description':'Run only this unit with '+route['model']+' at '+route['effort']+' effort.'}
            choice,gate=self.mesh.gate('authorize_unit',options,state)
            if choice=='stop': return 'stopped_by_jev'
            action=options[choice]['action']
            self.active_route=copy.deepcopy(action['worker_route'])
            candidate=self.invoke('producer',action,gate,lambda:self.producer(unit,copy.deepcopy(self.committed),
                                                                              feedback,copy.deepcopy(self.active_route)))
            candidate_view=candidate
            try:
                self.validate_artifact(candidate)
                checks=self.validator(unit,copy.deepcopy(candidate),copy.deepcopy(self.committed))
                checks['artifact_schema_valid']=True
            except MeshError as error:
                checks={'artifact_schema_valid':False}
                candidate_view={'invalid_response':True,'contract_error':str(error),
                                'raw_return_hash':fingerprint(candidate),
                                'raw_return_preview':packed(candidate)[:600],
                                'raw_return_location':'producer provisional_return journal event'}
            require(isinstance(checks,dict) and checks and all(type(x)is bool for x in checks.values()),
                    'invalid_hard_checks')
            candidate_hash=fingerprint(candidate)
            post_state=self.state(unit,candidate_view,checks)
            post_state['repair_feedback']=feedback
            options={'repair':{'description':'Retry a concrete defect using a new candidate and fresh Jev route.'},
                     'retrieve_evidence':{'description':'Stop for original evidence that is missing.'},
                     'stop':{'description':'Stop without accepting this candidate.'}}
            if all(checks.values()):
                forward_action=self.forward_action(unit,index,candidate_hash,None)
                options['forward']={'worker_id':'policy','action':forward_action,
                                    'description':'Accept this candidate after passed executable checks; no Sol-high review was requested.'}
                if len(self.checks)<self.policy.get('max_checker_calls',10):
                    check_action={'operation':'sol_high_check','unit_id':unit.id,'attempt':attempt,
                                  'check_attempt':0,'candidate_hash':candidate_hash,'policy_version':self.policy_version}
                    options['check_sol_high']={'worker_id':'checker','action':check_action,
                                               'description':'Request a separate Sol-high review because this candidate needs more scrutiny.'}
            if self.active_route is not None:
                route_rank=self.worker_routes.index(self.active_route)
                if route_rank+1<len(self.worker_routes):
                    options['escalate']={'description':'Retry this unit using a higher resource worker route; no current candidate is accepted.'}
            choice,gate=self.mesh.gate('after_worker',options,post_state)
            self.mesh.record('post_worker_decision',unit_id=unit.id,choice=choice,gate_id=gate,
                             candidate_hash=candidate_hash,hard_checks=checks)
            if choice=='forward':
                self.commit_candidate(unit,index,candidate,candidate_hash,parents,checks,None,gate,'after_worker')
                return 'forwarded'
            if choice=='repair':
                feedback={'verdict':'repair_required','failed_criteria':[k for k,v in checks.items() if not v],
                          'reason':'Jev requested a new candidate after this worker output.','missing_evidence':[]}
                continue
            if choice=='escalate':
                min_route_rank=route_rank+1
                feedback={'verdict':'repair_required','failed_criteria':[k for k,v in checks.items() if not v],
                          'reason':'Jev requested a higher resource worker route.','missing_evidence':[]}
                continue
            if choice=='retrieve_evidence': return 'needs_evidence'
            if choice=='stop': return 'stopped_by_jev'
            review_input={'goal':self.mesh.goal,'unit':{'id':unit.id,'objective':unit.objective},
                          'original_evidence':copy.deepcopy(self.mesh.sources),
                          'parents':[{'id':p['id'],'artifact':blind(p['artifact'])} for p in self.committed[-1:]],
                          'candidate':blind(candidate),'hard_checks':checks}
            check_action=options['check_sol_high']['action']
            check_gate=gate
            for check_attempt in range(2):
                check=self.invoke('checker',check_action,check_gate,lambda:self.checker(copy.deepcopy(review_input)))
                check_valid=True
                try: self.validate_check(check)
                except MeshError as error:
                    check_valid=False
                    check={'verdict':'invalid_response','contract_error':str(error),
                           'raw_return_hash':fingerprint(check),'raw_return_preview':packed(check)[:600],
                           'raw_return_location':'checker provisional_return journal event'}
                receipt={'unit_id':unit.id,'candidate_hash':candidate_hash,'check_hash':fingerprint(check),
                         'checker_model':self.checker_identity['model'],'checker_effort':self.checker_identity['effort'],
                         'contract_valid':check_valid,'result':check}
                self.checks.append(copy.deepcopy(receipt))
                options={'repair':{'description':'Make a new candidate and request a fresh Jev route.'},
                         'retrieve_evidence':{'description':'Stop for additional original evidence.'},
                         'stop':{'description':'Stop without accepting this candidate.'}}
                if check_valid and all(checks.values()) and check['verdict']=='pass':
                    options['forward']={'worker_id':'policy',
                                        'action':self.forward_action(unit,index,candidate_hash,receipt),
                                        'description':'Accept only the exact candidate that passed hard checks and this Sol-high review.'}
                if check_attempt==0 and len(self.checks)<self.policy.get('max_checker_calls',10):
                    next_check={'operation':'sol_high_check','unit_id':unit.id,'attempt':attempt,
                                'check_attempt':1,'candidate_hash':candidate_hash,'policy_version':self.policy_version}
                    options['verify_again']={'worker_id':'checker','action':next_check,
                                              'description':'Request one more separate Sol-high review of the same candidate.'}
                if self.active_route is not None and route_rank+1<len(self.worker_routes):
                    options['escalate']={'description':'Retry with a higher resource worker route after this review.'}
                choice,decision_id=self.mesh.gate('after_sol_high',options,self.state(unit,candidate,checks,check))
                self.mesh.record('post_checker_decision',unit_id=unit.id,choice=choice,gate_id=decision_id,receipt=receipt)
                if choice=='forward':
                    self.commit_candidate(unit,index,candidate,candidate_hash,parents,checks,receipt,
                                          decision_id,'after_sol_high')
                    return 'forwarded'
                if choice=='verify_again':
                    check_gate=decision_id
                    check_action=options['verify_again']['action']
                    continue
                if choice=='repair': feedback=check; break
                if choice=='escalate':
                    min_route_rank=route_rank+1
                    feedback=check
                    break
                return 'needs_evidence' if choice=='retrieve_evidence' else 'stopped_by_jev'
            else:
                return 'verification_limit'
        return 'repair_limit'

    def run(self):
        status='complete'
        try:
            for index,unit in enumerate(self.units):
                outcome=self.run_unit(unit,index)
                if outcome!='forwarded': status=outcome; break
            if status=='complete': self.final=self.committed[-1]['artifact']['text']
        except Exception as error:
            status='failed'
            self.mesh.record('halt',error=error.code if hasattr(error,'code') else type(error).__name__+': '+str(error))
        return {'status':status,'answer':self.final,'protocol_version':'cidm-conditional-review-v3',
                'policy_version':self.policy_version,
                'simulation':self.mesh.simulation,'committed':self.committed,'checks':self.checks,'events':self.mesh.events}

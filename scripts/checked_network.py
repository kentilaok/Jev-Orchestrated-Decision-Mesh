"""Five checked CIDM units. Every Sol-high return requires a Jev option decision."""
import copy
from dataclasses import dataclass
from atomic_mesh import AtomicMesh, MeshError, require, fingerprint, packed


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
                 policy=None, checker_identity=None, simulation=False, journal=None, units=UNITS):
        require(len(units)==5 and [u.id for u in units]==[u.id for u in UNITS], 'expected_five_sequential_units')
        self.units=units; self.producer=producer; self.checker=checker; self.validator=validator
        self.policy=copy.deepcopy(policy or {"version":"training-free-v1"})
        self.policy_version=fingerprint(self.policy)
        self.frozen_policy=self.policy_version
        self.checker_identity=copy.deepcopy(checker_identity or {"model":"openai/gpt-5.6-sol","effort":"high"})
        self.mesh=AtomicMesh(goal,sources,{'producer':PlaceholderWorker(),'checker':PlaceholderWorker(),'policy':PlaceholderWorker()},
                             judge,simulation=simulation,max_state_bytes=16000,journal=journal)
        self.committed=[]; self.checks=[]; self.final=None

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

    def run_unit(self, unit, index):
        require(type(index) is int and 0<=index<len(self.units) and unit==self.units[index],'unit_index_mismatch')
        require(len(self.committed)==index and [p['id'] for p in self.committed]==[u.id for u in self.units[:index]],'unit_predecessor_missing')
        feedback=None
        for attempt in range(2):
            parents=[{'id':p['id'],'hash':p['artifact_hash']} for p in self.committed[-1:]]
            action={'operation':'compute_unit','unit_id':unit.id,'attempt':attempt,'parents':parents,'policy_version':self.policy_version}
            state=self.state(unit); state['repair_feedback']=feedback
            options={'compute':{'worker_id':'producer','action':action,'description':'Execute only the current unit objective.'},'stop':{'description':'Stop without computing or forwarding.'}}
            choice,gate=self.mesh.gate('authorize_unit',options,state)
            if choice!='compute': return 'stopped_by_jev'
            candidate=self.invoke('producer',action,gate,lambda:self.producer(unit,copy.deepcopy(self.committed),feedback))
            try:
                self.validate_artifact(candidate)
                checks=self.validator(unit,candidate,copy.deepcopy(self.committed))
                checks['artifact_schema_valid']=True
            except MeshError:
                checks={'artifact_schema_valid':False}
            require(isinstance(checks,dict) and checks and all(type(x)is bool for x in checks.values()),'invalid_hard_checks')
            candidate_hash=fingerprint(candidate)
            for check_attempt in range(2):
                check_action={'operation':'sol_high_check','unit_id':unit.id,'attempt':attempt,'check_attempt':check_attempt,
                              'candidate_hash':candidate_hash,'policy_version':self.policy_version}
                options={'check':{'worker_id':'checker','action':check_action,'description':'Run a separate Sol-high check on this exact candidate.'},
                         'stop':{'description':'Stop; an unchecked candidate cannot advance.'}}
                choice,gate=self.mesh.gate('authorize_checker',options,self.state(unit,candidate,checks))
                if choice!='check': return 'stopped_before_checker'
                review_input={'goal':self.mesh.goal,'unit':{'id':unit.id,'objective':unit.objective},
                              'original_evidence':copy.deepcopy(self.mesh.sources),
                              'parents':[{'id':p['id'],'artifact':blind(p['artifact'])} for p in self.committed[-1:]],
                              'candidate':blind(candidate),'hard_checks':checks}
                check=self.invoke('checker',check_action,gate,lambda:self.checker(copy.deepcopy(review_input)))
                check_valid=True
                try: self.validate_check(check)
                except MeshError as error:
                    check_valid=False
                    # The full return is already preserved in the provisional_return
                    # journal event. Keep the decision envelope bounded so malformed
                    # model output cannot crowd out the required Jev handoff.
                    check={'verdict':'invalid_response','contract_error':str(error),
                           'raw_return_hash':fingerprint(check),'raw_return_preview':packed(check)[:600],
                           'raw_return_location':'checker provisional_return journal event'}
                receipt={'unit_id':unit.id,'candidate_hash':candidate_hash,'check_hash':fingerprint(check),
                         'checker_model':self.checker_identity['model'],'checker_effort':self.checker_identity['effort'],'contract_valid':check_valid,'result':check}
                self.checks.append(copy.deepcopy(receipt))
                forward_action={'operation':'forward','unit_id':unit.id,'candidate_hash':candidate_hash,'check_hash':receipt['check_hash'],
                                'successor':self.units[index+1].id if index+1<len(self.units) else 'user','policy_version':self.policy_version}
                options={
                    'forward':{'worker_id':'policy','action':forward_action,'description':'Forward only if all hard checks pass and this Sol-high check passed; otherwise this option is ineligible.'},
                    'repair':{'description':'Ask the producer to repair a concrete defect, then require a new Sol-high check.'},
                    'retrieve_evidence':{'description':'Stop for additional original evidence; do not guess or advance.'},
                    'verify_again':{'description':'Request one more isolated Sol-high check of the same candidate.'},
                    'stop':{'description':'Stop without forwarding the candidate.'}}
                choice,decision_id=self.mesh.gate('after_sol_high',options,self.state(unit,candidate,checks,check))
                self.mesh.record('post_checker_decision',unit_id=unit.id,choice=choice,gate_id=decision_id,receipt=receipt)
                if choice=='forward':
                    require(check_valid and all(checks.values()) and check['verdict']=='pass','failed_candidate_cannot_forward')
                    require(fingerprint(candidate)==candidate_hash and fingerprint(check)==receipt['check_hash'],'candidate_or_checker_changed')
                    def commit():
                        packet={'id':unit.id,'artifact':copy.deepcopy(candidate),'artifact_hash':candidate_hash,'parent_artifacts':parents,
                                'checker':copy.deepcopy(receipt),'decision_id':decision_id,'policy_version':self.policy_version}
                        self.committed.append(packet)
                        self.mesh.accepted.append({'id':unit.id,'operation':'checked_unit','summary':candidate['text'],'source_ids':candidate['source_ids'],
                                                   'data':copy.deepcopy(candidate['data']),'artifact_hash':candidate_hash})
                        self.mesh.version+=1
                        self.mesh.record('checked_commit',unit_id=unit.id,packet=packet,gate_id=decision_id)
                        return packet
                    self.invoke('policy',forward_action,decision_id,commit)
                    return 'forwarded'
                if choice=='verify_again': continue
                if choice=='repair': feedback=check; break
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
        return {'status':status,'answer':self.final,'policy_version':self.policy_version,
                'simulation':self.mesh.simulation,'committed':self.committed,'checks':self.checks,'events':self.mesh.events}

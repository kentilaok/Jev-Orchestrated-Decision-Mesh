import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from atomic_mesh import MeshError, packed
from checked_network import CheckedNetwork, UNITS
from config import RunConfig
from network_run import DEMO, DemoPipeline, fake_judge, fake_check
from audit_network import audit


def build(judge=fake_judge,checker=fake_check,producer=None,validator=None):
    demo=DemoPipeline(DEMO)
    return CheckedNetwork(DEMO['goal'],{'records':{'text':packed(DEMO)}},judge,
        producer or demo.produce,checker,validator or demo.validate,policy={'version':'fixture'},simulation=True)


class ControllerTests(unittest.TestCase):
    def test_five_units_can_commit_after_jev_without_sol_checker(self):
        result=build().run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual([p['id'] for p in result['committed']],[u.id for u in UNITS])
        self.assertTrue(audit(result)['valid'])
        self.assertEqual(len(result['checks']),0)
        events={e['id']:e for e in result['events']}
        for p in result['committed']:
            self.assertIsNone(p['checker'])
            self.assertEqual(events[p['decision_id']]['phase'],'after_worker')
            self.assertEqual(events[p['decision_id']]['decision']['choice'],'forward')
        self.assertEqual(audit(result)['post_worker_jev_decisions'],5)

    def test_jev_can_request_one_optional_sol_high_review(self):
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_worker' and state['unit']['id']=='hidden1': result['choice']='check_sol_high'
            return result
        result=build(judge).run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(result['checks']),1)
        self.assertTrue(audit(result)['valid'])
        checked=[p for p in result['committed'] if p['checker'] is not None]
        self.assertEqual([p['id'] for p in checked],['hidden1'])
        events={e['id']:e for e in result['events']}
        self.assertEqual(events[checked[0]['decision_id']]['phase'],'after_sol_high')

    def test_jev_stop_after_requested_checker_pass_prevents_forward(self):
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_worker': result['choice']='check_sol_high'
            if phase=='after_sol_high': result['choice']='stop'
            return result
        result=build(judge).run()
        self.assertEqual(result['status'],'stopped_by_jev')
        self.assertEqual(result['checks'][0]['result']['verdict'],'pass')
        self.assertEqual(result['committed'],[])

    def test_checker_failure_cannot_be_overridden(self):
        def reject(state): return {'verdict':'reject','failed_criteria':['fixture'],'reason':'Fixture rejection.','missing_evidence':[]}
        visible=[]
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_worker': result['choice']='check_sol_high'
            if phase=='after_sol_high': visible.append(set(options)); result['choice']='stop'
            return result
        result=build(judge,checker=reject).run()
        self.assertEqual(result['status'],'stopped_by_jev')
        self.assertNotIn('forward',visible[0])
        self.assertEqual(result['committed'],[])

    def test_hard_failure_cannot_be_overridden(self):
        visible=[]
        def judge(phase,options,state):
            if phase=='after_worker': visible.append(set(options))
            return fake_judge(phase,options,state)
        result=build(judge,validator=lambda *a:{'hard':False}).run()
        self.assertEqual(result['status'],'repair_limit')
        self.assertTrue(all('forward' not in options and 'check_sol_high' not in options for options in visible))
        self.assertEqual(result['committed'],[])

    def test_bad_checker_structure_still_reaches_jev(self):
        phases=[]
        def judge(phase,options,state):
            phases.append(phase)
            result=fake_judge(phase,options,state)
            if phase=='after_worker': result['choice']='check_sol_high'
            if phase=='after_sol_high': result['choice']='stop'
            return result
        result=build(judge,lambda state:{'verdict':'pass'}).run()
        self.assertIn('after_sol_high',phases)
        self.assertEqual(result['committed'],[])

    def test_missing_predecessors_block_output_unit(self):
        with self.assertRaises(MeshError): build().run_unit(UNITS[-1],4)

    def test_oversized_invalid_checker_report_reaches_jev_with_bounded_envelope(self):
        captured=[]
        raw={'verdict':'pass','reason':'X'*18000,'failed_criteria':[],'missing_evidence':[]}
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_worker': result['choice']='check_sol_high'
            if phase=='after_sol_high':
                captured.append(state['sol_high_result'])
                result['choice']='stop'
            return result
        result=build(judge,lambda state:raw).run()
        self.assertEqual(len(captured),1)
        self.assertEqual(captured[0]['verdict'],'invalid_response')
        self.assertLess(len(packed(captured[0])),1000)
        self.assertEqual(result['committed'],[])
        returns=[e for e in result['events'] if e['kind']=='provisional_return' and e['worker_id']=='checker']
        self.assertEqual(returns[0]['value'],raw)

    def test_oversized_invalid_worker_result_reaches_jev_with_bounded_envelope(self):
        captured=[]
        demo=DemoPipeline(DEMO)
        def producer(unit,parents,feedback,route):
            candidate=demo.produce(unit,parents,feedback,route)
            if unit.id=='input': candidate['text']='X'*18000
            return candidate
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_worker':
                captured.append(state['candidate'])
                result['choice']='stop'
            return result
        result=build(judge,producer=producer).run()
        self.assertEqual(result['status'],'stopped_by_jev')
        self.assertEqual(len(captured),1)
        self.assertTrue(captured[0]['invalid_response'])
        self.assertLess(len(packed(captured[0])),1000)
        self.assertEqual(result['committed'],[])

    def test_policy_mutation_blocks_progress(self):
        network=build(); network.policy['version']='changed'
        self.assertEqual(network.run()['committed'],[])

    def test_checker_receives_evidence_without_prior_opinions(self):
        captured=[]
        def checker(state): captured.append(state); return fake_check(state)
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_worker': result['choice']='check_sol_high'
            return result
        self.assertEqual(build(judge,checker=checker).run()['status'],'complete')
        self.assertEqual(len(captured),5)
        for state in captured:
            payload=packed(state)
            for key in ('five_scores','self_probability','decision_id','router_advice'):
                self.assertNotIn(key,payload)
            self.assertIn('original_evidence',state)

    def test_jev_selects_luna_or_sol_effort_for_each_generative_unit(self):
        demo=DemoPipeline(DEMO); selected=[]
        def producer(unit,parents,feedback,route):
            selected.append((unit.id,route))
            return demo.produce(unit,parents,feedback,route)
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='authorize_unit' and 'sol_xhigh' in options:
                result['choice']='sol_xhigh' if state['unit']['id']=='hidden1' else 'luna_low'
            return result
        result=build(judge,producer=producer).run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual([route['id'] for _,route in selected if route],
                         ['sol_xhigh','luna_low','luna_low'])
        self.assertEqual([p['worker_route']['id'] for p in result['committed'] if p['worker_route']],
                         ['sol_xhigh','luna_low','luna_low'])
        self.assertTrue(audit(result)['valid'])

    def test_astra_is_absent_without_explicit_authorization(self):
        captured=[]
        def judge(phase,options,state):
            if phase=='authorize_unit': captured.append(set(options))
            return fake_judge(phase,options,state)
        self.assertEqual(build(judge).run()['status'],'complete')
        self.assertTrue(all('astra_low' not in options for options in captured))

    def test_zero_checker_budget_omits_review_option(self):
        config=RunConfig(max_checker_calls=0)
        demo=DemoPipeline(DEMO); visible=[]
        def judge(phase,options,state):
            if phase=='after_worker': visible.append(set(options))
            return fake_judge(phase,options,state)
        network=CheckedNetwork(DEMO['goal'],{'records':{'text':packed(DEMO)}},judge,demo.produce,fake_check,
                               demo.validate,policy=config.to_dict(),worker_routes=config.worker_routes(),simulation=True)
        result=network.run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(visible),5)
        self.assertTrue(all('check_sol_high' not in options for options in visible))

    def test_astra_low_requires_explicit_authorization(self):
        config=RunConfig(astra_explicitly_authorized=True)
        demo=DemoPipeline(DEMO); captured=[]
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='authorize_unit' and 'astra_low' in options:
                result['choice']='astra_low'; captured.append(options['astra_low']['action']['worker_route'])
            return result
        network=CheckedNetwork(DEMO['goal'],{'records':{'text':packed(DEMO)}},judge,demo.produce,fake_check,
                               demo.validate,policy=config.to_dict(),worker_routes=config.worker_routes(),simulation=True)
        self.assertEqual(network.run()['status'],'complete')
        self.assertEqual(len(captured),3)
        self.assertTrue(all(r=={'id':'astra_low','model':'openai/gpt-6-astra','effort':'low'} for r in captured))

    def test_repair_creates_new_candidate_and_check(self):
        demo=DemoPipeline(DEMO); attempts={}
        def producer(unit,parents,feedback,route):
            candidate=demo.produce(unit,parents,feedback,route)
            attempts[unit.id]=attempts.get(unit.id,0)+1
            if unit.id=='hidden1' and attempts[unit.id]==2: candidate['text']+=' Revised after review.'
            return candidate
        review_attempts={}
        def checker(state):
            uid=state['unit']['id']; review_attempts[uid]=review_attempts.get(uid,0)+1
            if uid=='hidden1' and review_attempts[uid]==1:
                return {'verdict':'repair_required','failed_criteria':['semantic_review'],
                        'reason':'Revise the interpretation.','missing_evidence':[]}
            return fake_check(state)
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_worker' and state['unit']['id']=='hidden1': result['choice']='check_sol_high'
            if phase=='after_sol_high' and state['sol_high_result']['verdict']!='pass': result['choice']='repair'
            return result
        result=build(judge,checker=checker,producer=producer).run()
        self.assertEqual(result['status'],'complete')
        checks=[c for c in result['checks'] if c['unit_id']=='hidden1']
        self.assertEqual(len(checks),2)
        self.assertNotEqual(checks[0]['candidate_hash'],checks[1]['candidate_hash'])

    def test_failed_precheck_can_repair_before_spending_checker_call(self):
        demo=DemoPipeline(DEMO); attempts={}
        def producer(unit,parents,feedback,route):
            candidate=demo.produce(unit,parents,feedback,route)
            attempts[unit.id]=attempts.get(unit.id,0)+1
            if unit.id=='hidden1' and attempts[unit.id]==1: candidate['data']['scale']=2000
            return candidate
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            return result
        result=build(judge,producer=producer).run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(attempts['hidden1'],2)
        self.assertEqual(len(result['checks']),0)
        self.assertTrue(audit(result)['valid'])

    def test_escalation_requires_new_jev_route_and_recomputes_candidate(self):
        demo=DemoPipeline(DEMO); attempts={}
        def producer(unit,parents,feedback,route):
            attempts[unit.id]=attempts.get(unit.id,0)+1
            return demo.produce(unit,parents,feedback,route)
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_worker' and state['unit']['id']=='hidden1' and attempts.get('hidden1')==1:
                result['choice']='escalate'
            return result
        result=build(judge,producer=producer).run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(attempts['hidden1'],2)
        self.assertEqual(next(p for p in result['committed'] if p['id']=='hidden1')['worker_route']['id'],'luna_medium')
        self.assertTrue(audit(result)['valid'])

    def test_optional_second_check_has_jev_decision_after_each_return(self):
        seen=[]
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_worker' and state['unit']['id']=='input': result['choice']='check_sol_high'
            if phase=='after_sol_high':
                seen.append(state['unit']['id'])
                if len(seen)==1: result['choice']='verify_again'
            return result
        result=build(judge).run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(seen,['input','input'])
        self.assertEqual(len(result['checks']),2)
        self.assertTrue(audit(result)['valid'])

    def test_numeric_unit_format_and_magnitude(self):
        pipeline=DemoPipeline(DEMO)
        candidate={'source_ids':['records'],'text':'50 defects per 1,000 production items; trial excluded. [records]',
                   'data':{'answer':50,'unit':'defects per 1,000 production items'}}
        self.assertTrue(all(pipeline.validate(UNITS[-1],candidate,[]).values()))
        candidate['data']['unit']='defects per 10000 items'
        self.assertFalse(all(pipeline.validate(UNITS[-1],candidate,[]).values()))

    def test_direct_output_cannot_forward_false_or_unsourced_text(self):
        demo=DemoPipeline(DEMO)
        for bad in ('500 defects per 1,000 production items; trial excluded. [records]',
                    '50 defects per 1,000 production items; trial excluded.',
                    '50 defects per 1,000 production items. [records]'):
            candidate=demo.produce(UNITS[-1],[],None)
            candidate['text']=bad
            checks=demo.validate(UNITS[-1],candidate,[])
            self.assertFalse(all(checks.values()),bad)

    def test_audit_detects_changed_final_answer(self):
        result=build().run(); result['answer']='Changed after checks'
        self.assertFalse(audit(result)['valid'])

    def test_audit_detects_mutated_committed_packet_even_if_answer_is_changed_with_it(self):
        result=build().run()
        result['committed'][-1]['artifact']['text']='Tampered answer'
        result['answer']='Tampered answer'
        self.assertFalse(audit(result)['valid'])

    def test_audit_detects_missing_worker_jev_decision(self):
        result=build().run()
        result['events']=[e for e in result['events'] if not
                          (e['kind']=='post_worker_decision' and e['unit_id']=='hidden1')]
        self.assertFalse(audit(result)['valid'])

    def test_offline_cli_works_without_credentials_or_optional_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'run'
            env=dict(os.environ); env.pop('OPENROUTER_API_KEY',None)
            completed=subprocess.run([sys.executable,'-S','-B',str(ROOT/'scripts/network_run.py'),'--offline','--out',str(out)],env=env,text=True,capture_output=True)
            self.assertEqual(completed.returncode,0,completed.stderr)
            result=json.loads((out/'result.json').read_text())
            self.assertFalse(result['training_performed'])
            self.assertEqual(result['calls'],[])
            self.assertEqual(len(result['committed']),5)
            self.assertEqual(len(result['checks']),0)


if __name__=='__main__': unittest.main()

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
    def test_all_five_gates_have_check_then_jev_decision(self):
        result=build().run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual([p['id'] for p in result['committed']],[u.id for u in UNITS])
        self.assertTrue(audit(result)['valid'])
        self.assertEqual(len(result['checks']),5)
        events={e['id']:e for e in result['events']}
        for p in result['committed']:
            self.assertEqual(p['checker']['result']['verdict'],'pass')
            self.assertEqual(events[p['decision_id']]['phase'],'after_sol_high')
            self.assertEqual(events[p['decision_id']]['decision']['choice'],'forward')

    def test_jev_stop_after_checker_pass_prevents_forward(self):
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_sol_high': result['choice']='stop'
            return result
        result=build(judge).run()
        self.assertEqual(result['checks'][0]['result']['verdict'],'pass')
        self.assertEqual(result['committed'],[])

    def test_checker_failure_cannot_be_overridden(self):
        def reject(state): return {'verdict':'reject','failed_criteria':['fixture'],'reason':'Fixture rejection.','missing_evidence':[]}
        result=build(checker=reject).run()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['committed'],[])

    def test_hard_failure_cannot_be_overridden(self):
        def pass_check(state): return {'verdict':'pass','failed_criteria':[],'reason':'Fixture.','missing_evidence':[]}
        result=build(checker=pass_check,validator=lambda *a:{'hard':False}).run()
        self.assertEqual(result['committed'],[])

    def test_bad_checker_structure_still_reaches_jev(self):
        phases=[]
        def judge(phase,options,state): phases.append(phase); return fake_judge(phase,options,state)
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

    def test_policy_mutation_blocks_progress(self):
        network=build(); network.policy['version']='changed'
        self.assertEqual(network.run()['committed'],[])

    def test_checker_receives_evidence_without_prior_opinions(self):
        captured=[]
        def checker(state): captured.append(state); return fake_check(state)
        self.assertEqual(build(checker=checker).run()['status'],'complete')
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
            if unit.id=='hidden1' and attempts[unit.id]==1: candidate['data']['scale']=2000
            return candidate
        def judge(phase,options,state):
            result=fake_judge(phase,options,state)
            if phase=='after_sol_high' and state['sol_high_result']['verdict']!='pass': result['choice']='repair'
            return result
        result=build(judge,producer=producer).run()
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
            if phase=='authorize_checker' and 'repair' in options: result['choice']='repair'
            return result
        result=build(judge,producer=producer).run()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(attempts['hidden1'],2)
        self.assertEqual(len([r for r in result['checks'] if r['unit_id']=='hidden1']),1)
        self.assertEqual(len(result['checks']),5)
        self.assertTrue(audit(result)['valid'])

    def test_numeric_unit_format_and_magnitude(self):
        pipeline=DemoPipeline(DEMO)
        candidate={'source_ids':['records'],'data':{'answer':50,'unit':'defects per 1,000 production items'}}
        self.assertTrue(all(pipeline.validate(UNITS[-1],candidate,[]).values()))
        candidate['data']['unit']='defects per 10000 items'
        self.assertFalse(all(pipeline.validate(UNITS[-1],candidate,[]).values()))

    def test_audit_detects_changed_final_answer(self):
        result=build().run(); result['answer']='Changed after checks'
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


if __name__=='__main__': unittest.main()

"""Context-bound route boundaries; provider calls are mocked."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from adaptive_run import PROJECT_OPTIONS,input_snapshot_hash,run_adaptive
from atomic_mesh import MeshError
from config import RunConfig
from network_run import DEMO,DemoPipeline
from compare_baseline import simulated_candidate
from audit_network import audit
from transport import Gateway


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder=Path(temporary.name)
        env=patch.dict(os.environ,{'OPENROUTER_API_KEY':'sk-test-adaptive-do-not-log'})
        env.start();self.addCleanup(env.stop)

    def short_classification(self,task=DEMO,context_summary=''):
        return {'snapshot_hash':input_snapshot_hash(task,context_summary),
                'multiple_steps':False,'broad_project':False,
                'ambiguous':False,'depends_on_context':False}

    def test_missing_classification_defaults_to_five_unit(self):
        result=run_adaptive(DEMO,RunConfig(),self.folder/'broad',live=False)
        self.assertEqual((result['status'],result['selected_route']),('complete','five_unit'))
        self.assertTrue(result['simulation'])
        self.assertEqual(result['calls'],[])
        self.assertEqual(result['metrics']['jev_passes'],0)
        self.assertFalse(result['metrics']['early_exit_selected'])
        self.assertEqual(result['input_classification']['source'],'conservative_default')
        self.assertEqual(len(result['committed']),5)
        self.assertIn('50.0 defects',result['answer'])

    def test_offline_five_unit_branch_still_uses_post_worker_jev(self):
        classification=self.short_classification()
        classification['ambiguous']=True
        result=run_adaptive(DEMO,RunConfig(),self.folder/'five',live=False,
                            classification=classification)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(result['committed']),5)
        self.assertEqual(result['metrics']['early_exit_selected'],False)
        self.assertEqual(result['input_classification']['scope'],'broad_or_uncertain')
        self.assertEqual(audit(result)['post_worker_jev_decisions'],5)

    def test_short_prompt_text_does_not_classify_itself_as_short(self):
        terse=copy.deepcopy(DEMO)
        terse['goal']='Rate?'
        result=run_adaptive(terse,RunConfig(),self.folder/'terse',live=False)
        self.assertEqual(result['selected_route'],'five_unit')
        self.assertEqual(result['input_classification']['scope'],'broad_or_uncertain')

    def test_live_short_path_has_one_luna_low_worker_and_no_jev_or_checker(self):
        artifact=simulated_candidate(DEMO,DemoPipeline(DEMO))
        worker={'model':'openai/gpt-6-luna','provider':'Azure',
                'usage':{'prompt_tokens':150,'completion_tokens':100,'total_tokens':250,'cost':0.0001},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(artifact)}}]}
        with patch.object(Gateway,'_request',return_value=worker) as request:
            result=run_adaptive(DEMO,RunConfig(),self.folder/'live',live=True,
                                classification=self.short_classification())
        self.assertEqual(request.call_count,1)
        self.assertEqual(request.call_args.args[0],'worker')
        self.assertEqual(result['status'],'complete')
        self.assertEqual([c['role'] for c in result['calls']],['worker'])
        self.assertEqual(result['calls'][0]['requested_model'],'openai/gpt-6-luna')
        self.assertEqual(result['calls'][0]['reasoning_effort'],'low')
        self.assertFalse(result['calls'][0]['followup_jev_required'])
        self.assertEqual(result['metrics']['jev_passes'],0)
        self.assertTrue(result['metrics']['early_exit_selected'])

    def test_direct_luna_result_must_pass_hard_checks_to_finish(self):
        artifact=simulated_candidate(DEMO,DemoPipeline(DEMO))
        artifact['answer']=99.0
        worker={'model':'openai/gpt-6-luna','provider':'Azure',
                'usage':{'prompt_tokens':150,'completion_tokens':100,'total_tokens':250,'cost':0.0001},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(artifact)}}]}
        with patch.object(Gateway,'_request',return_value=worker) as request:
            result=run_adaptive(DEMO,RunConfig(),self.folder/'invalid-worker',live=True,
                                classification=self.short_classification())
        self.assertEqual(request.call_count,1)
        self.assertEqual(result['status'],'quality_failed')
        self.assertIsNone(result['answer'])
        self.assertFalse(result['quality_checks']['answer_matches_exact_reference'])

    def test_broad_jev_can_only_choose_five_unit_retrieve_or_stop(self):
        probabilities={name:(1.0 if name=='stop' else 0.0) for name in PROJECT_OPTIONS}
        jev={'model':'typesafe/jev-1.13-20260917','provider':'TypeSafe',
             'usage':{'input_tokens':100,'output_tokens':10,'total_tokens':110,'cost':0.00001},
             'answers':{'next':{'type':'choice','choice':'stop',
                                'probabilities':probabilities,'confidence':1.0}}}
        with patch.object(Gateway,'_request',return_value=jev) as request:
            result=run_adaptive(DEMO,RunConfig(),self.folder/'broad-live',live=True)
        self.assertEqual(result['status'],'stopped_by_jev')
        self.assertEqual([c['role'] for c in result['calls']],['jev'])
        payload=request.call_args.args[1]
        self.assertEqual(set(payload['questions']['next']['criteria']),set(PROJECT_OPTIONS))
        self.assertNotIn('direct_luna_low',payload['questions']['next']['criteria'])

    def test_stale_or_invalid_host_classification_fails_before_provider_or_output(self):
        stale=self.short_classification()
        newer=copy.deepcopy(DEMO);newer['scale']=100
        with self.assertRaisesRegex(MeshError,'stale_input_classification'):
            run_adaptive(newer,RunConfig(),self.folder/'stale',live=True,
                         classification=stale)
        self.assertFalse((self.folder/'stale').exists())
        with self.assertRaisesRegex(MeshError,'stale_input_classification'):
            run_adaptive(DEMO,RunConfig(),self.folder/'stale-context',live=False,
                         context_summary='new follow-up',classification=stale)
        invalid=self.short_classification()
        invalid['multiple_steps']='false'
        with self.assertRaisesRegex(MeshError,'invalid_input_classification'):
            run_adaptive(DEMO,RunConfig(),self.folder/'invalid',live=False,
                         classification=invalid)

    def test_subsequent_input_uses_fresh_classification_and_defaults_to_five(self):
        first=run_adaptive(DEMO,RunConfig(),self.folder/'first',live=False,
                           classification=self.short_classification())
        newer=copy.deepcopy(DEMO);newer['scale']=100
        second=run_adaptive(newer,RunConfig(),self.folder/'second',live=False,
                            context_summary='follow-up project input')
        self.assertEqual(first['selected_route'],'direct_luna_low')
        self.assertEqual(second['selected_route'],'five_unit')
        self.assertNotEqual(first['input_classification']['snapshot_hash'],
                            second['input_classification']['snapshot_hash'])
        self.assertEqual(second['input_classification']['source'],'conservative_default')

    def test_zero_jev_call_cap_stops_before_the_project_route_request(self):
        with patch.object(Gateway,'_request') as request:
            result=run_adaptive(DEMO,RunConfig(max_jev_calls=0),self.folder/'blocked',live=True)
        request.assert_not_called()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['error_code'],'role_call_budget_exhausted')
        self.assertEqual(result['calls'],[])


if __name__=='__main__': unittest.main()

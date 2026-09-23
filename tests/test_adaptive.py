"""Fast-gate route boundaries; provider calls are mocked."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from adaptive_run import FAST_OPTIONS,run_adaptive
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

    def test_offline_deterministic_exits_after_one_simulated_gate(self):
        result=run_adaptive(DEMO,RunConfig(),self.folder/'direct',live=False)
        self.assertEqual((result['status'],result['selected_route']),('complete','deterministic'))
        self.assertTrue(result['simulation'])
        self.assertEqual(result['calls'],[])
        self.assertEqual(result['metrics']['jev_passes'],0)
        self.assertTrue(result['metrics']['early_exit_selected'])
        self.assertIn('50.0 defects',result['answer'])

    def test_offline_five_unit_branch_still_uses_post_worker_jev(self):
        result=run_adaptive(DEMO,RunConfig(),self.folder/'five',live=False,offline_route='five_unit')
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(result['committed']),5)
        self.assertEqual(result['metrics']['early_exit_selected'],False)
        self.assertEqual(audit(result)['post_worker_jev_decisions'],5)

    def test_live_luna_direct_path_has_one_jev_then_one_worker_and_no_followup(self):
        probs={name:(1.0 if name=='direct_luna_low' else 0.0) for name in FAST_OPTIONS}
        jev={'model':'typesafe/jev-1.13-20260917','provider':'TypeSafe',
             'usage':{'input_tokens':100,'output_tokens':10,'total_tokens':110,'cost':0.00001},
             'answers':{'next':{'type':'choice','choice':'direct_luna_low',
                                'probabilities':probs,'confidence':1.0}}}
        artifact=simulated_candidate(DEMO,DemoPipeline(DEMO))
        worker={'model':'openai/gpt-6-luna','provider':'Azure',
                'usage':{'prompt_tokens':150,'completion_tokens':100,'total_tokens':250,'cost':0.0001},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps(artifact)}}]}
        with patch.object(Gateway,'_request',side_effect=[jev,worker]) as request:
            result=run_adaptive(DEMO,RunConfig(),self.folder/'live',live=True)
        self.assertEqual(request.call_count,2)
        self.assertEqual(result['status'],'complete')
        self.assertEqual([c['role'] for c in result['calls']],['jev','worker'])
        self.assertEqual(result['calls'][1]['requested_model'],'openai/gpt-6-luna')
        self.assertFalse(result['calls'][1]['followup_jev_required'])
        self.assertEqual(result['metrics']['orchestration_ratio'],110/250)
        self.assertEqual(result['metrics']['jev_passes'],1)
        self.assertTrue(result['metrics']['early_exit_selected'])

    def test_zero_jev_call_cap_stops_before_the_fast_gate_request(self):
        with patch.object(Gateway,'_request') as request:
            result=run_adaptive(DEMO,RunConfig(max_jev_calls=0),self.folder/'blocked',live=True)
        request.assert_not_called()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['error_code'],'role_call_budget_exhausted')
        self.assertEqual(result['calls'],[])


if __name__=='__main__': unittest.main()

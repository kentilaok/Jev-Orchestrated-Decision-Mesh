import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from metrics import summarize_calls


class MetricsTests(unittest.TestCase):
    def test_ratio_and_baseline_comparison_use_all_role_calls(self):
        calls=[{'role':'jev','usage':{'total_tokens':120,'cost':0.00001}},
               {'role':'worker','usage':{'total_tokens':40,'cost':0.001}},
               {'role':'checker','usage':{'total_tokens':20,'cost':0.0005}}]
        baseline={'status':'complete','quality_checks':{'answer':True},'reported_cost':0.001}
        result=summarize_calls(calls,baseline=baseline,quality_pass=True,
                               early_exit_selected=False,escalations=1)
        self.assertEqual(result['total_tokens'],180)
        self.assertAlmostEqual(result['total_cost_usd'],0.00151)
        self.assertEqual(result['orchestration_ratio'],3)
        self.assertAlmostEqual(result['roles']['jev']['blended_usd_per_million_tokens'],0.00001/120*1_000_000)
        self.assertAlmostEqual(result['comparison']['cost_multiplier'],1.51)
        self.assertEqual(result['comparison']['quality_gain_binary'],0)
        self.assertIsNone(result['comparison']['cost_per_quality_gain_usd'])
        self.assertEqual(result['escalations'],1)

    def test_unknown_charge_or_tokens_never_become_zero(self):
        result=summarize_calls([{'role':'jev','usage':{'total_tokens':None,'cost':None}},
                                {'role':'worker','usage':{'total_tokens':10,'cost':0.0001}}])
        self.assertIsNone(result['total_tokens'])
        self.assertIsNone(result['total_cost_usd'])
        self.assertIsNone(result['orchestration_ratio'])
        self.assertEqual(result['roles']['jev']['unknown_token_calls'],1)
        self.assertEqual(result['roles']['jev']['unknown_cost_calls'],1)


if __name__=='__main__': unittest.main()

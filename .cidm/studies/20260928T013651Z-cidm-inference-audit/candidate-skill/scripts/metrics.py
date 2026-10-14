"""Complete call accounting; missing provider counters stay unknown."""
import math


def _nonnegative(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0


def summarize_calls(calls, *, baseline=None, quality_pass=None, early_exit_selected=None, escalations=0):
    roles={}
    for role in ('jev','worker','checker'):
        entries=[event for event in calls if event.get('role')==role]
        totals=[(event.get('usage') or {}).get('total_tokens') for event in entries]
        charges=[(event.get('usage') or {}).get('cost') for event in entries]
        roles[role]={
            'calls':len(entries),
            'tokens':sum(totals) if all(_nonnegative(v) for v in totals) else None,
            'cost_usd':sum(charges) if all(_nonnegative(v) for v in charges) else None,
            'unknown_token_calls':sum(not _nonnegative(v) for v in totals),
            'unknown_cost_calls':sum(not _nonnegative(v) for v in charges),
        }
        tokens=roles[role]['tokens'];cost=roles[role]['cost_usd']
        roles[role]['blended_usd_per_million_tokens']=(cost/tokens*1_000_000
                                                        if tokens is not None and cost is not None
                                                        and tokens>0 else None)
    total_tokens=(sum(role['tokens'] for role in roles.values())
                  if all(role['tokens'] is not None for role in roles.values()) else None)
    total_cost=(sum(role['cost_usd'] for role in roles.values())
                if all(role['cost_usd'] is not None for role in roles.values()) else None)
    worker_tokens=roles['worker']['tokens']
    jev_tokens=roles['jev']['tokens']
    ratio=(jev_tokens/worker_tokens if jev_tokens is not None and worker_tokens is not None
           and worker_tokens>0 else None)
    comparison=None
    if baseline is not None:
        baseline_cost=baseline.get('reported_cost')
        baseline_checks=baseline.get('quality_checks')
        baseline_pass=(baseline.get('status')=='complete' and isinstance(baseline_checks,dict)
                       and bool(baseline_checks) and all(baseline_checks.values()))
        quality_gain=(int(quality_pass)-int(baseline_pass) if type(quality_pass) is bool else None)
        cost_multiplier=(total_cost/baseline_cost if _nonnegative(total_cost)
                         and _nonnegative(baseline_cost) and baseline_cost>0 else None)
        comparison={'baseline_cost_usd':baseline_cost if _nonnegative(baseline_cost) else None,
                    'cost_multiplier':cost_multiplier,'quality_baseline':baseline_pass,
                    'quality_cidm':quality_pass,'quality_gain_binary':quality_gain,
                    'cost_per_quality_gain_usd':((total_cost-baseline_cost)/quality_gain
                                                  if cost_multiplier is not None and quality_gain is not None
                                                  and quality_gain>0 else None)}
    return {
        'roles':roles,'total_calls':len(calls),'total_tokens':total_tokens,
        'total_cost_usd':total_cost,'orchestration_ratio':ratio,
        'worker_calls':roles['worker']['calls'],'jev_passes':roles['jev']['calls'],
        'checker_calls':roles['checker']['calls'],'escalations':escalations,
        'avoidable_escalations':None,'avoidable_worker_calls':None,
        'early_exit_selected':early_exit_selected,'early_exit_possible':None,
        'comparison':comparison,
        'accounting_note':'Cached input and reasoning output are subsets of input/output totals; unknown counters are not zero.',
    }

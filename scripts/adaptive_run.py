"""CIDM fast gate for bounded project subtasks; simple standalone questions skip this skill."""
import argparse
import copy
import json
from pathlib import Path

from atomic_mesh import MeshError, fingerprint, require
from compare_baseline import (BASELINE_INSTRUCTIONS, BASELINE_SCHEMA,
                              simulated_candidate, validate_baseline)
from config import RunConfig
from metrics import summarize_calls
from network_run import DEMO, DemoPipeline, execute_network
from transport import Gateway


FAST_OPTIONS={
    'deterministic':{'description':'Exact code and source checks; no worker.'},
    'direct_luna_low':{'description':'One Luna-low worker and hard checks; no follow-up.'},
    'direct_sol_high':{'description':'One Sol-high worker and hard checks; no follow-up.'},
    'five_unit':{'description':'Five Jev-governed units; optional Sol-high review.'},
    'retrieve_evidence':{'description':'Need missing original evidence.'},
    'stop':{'description':'No safe route.'},
}


def fast_state(task,config):
    return {'goal':task['goal'],'source_id':'records','source_hash':fingerprint(task),
            'rows':len(task['records']),'kinds':sorted({row['kind'] for row in task['records']}),
            'include':task['include_kind'],'scale':task['scale'],
            'exact_checks':True,'budget_usd':config.max_usd}


def run_adaptive(task,config,folder,*,live,baseline=None,offline_route='deterministic'):
    require(isinstance(config,RunConfig),'validated_run_config_required')
    pipeline=DemoPipeline(task)
    folder=Path(folder)
    require(not folder.exists(),'output_directory_must_be_new')
    folder.mkdir(parents=True,exist_ok=False)
    gateway=Gateway(folder,config) if live else None
    result={'status':'failed','mode':'adaptive_fast_gate','simulation':not live,
            'task_hash':fingerprint(task),'configuration':config.to_dict(),
            'fast_gate':None,'selected_route':None,'answer':None,
            'quality_checks':None,'calls':[],'reported_cost':None if not live else 0.0,
            'training_performed':False}
    try:
        if live:
            decision=gateway.network_judge('fast_exit',FAST_OPTIONS,fast_state(task,config))
            selected=decision['choice']
        else:
            require(offline_route in FAST_OPTIONS,'invalid_offline_route')
            selected=offline_route
            decision={'choice':selected,'model':'offline_simulation','live':False}
        result['fast_gate']=decision
        result['selected_route']=selected
        if selected=='five_unit':
            network_result=execute_network(task,config,folder,gateway,simulation=not live)
            result.update(network_result)
            result['mode']='adaptive_fast_gate'
            result['fast_gate']=decision
            result['selected_route']=selected
            result['task_hash']=fingerprint(task)
        elif selected in ('deterministic','direct_luna_low','direct_sol_high'):
            if selected=='deterministic' or not live:
                candidate=simulated_candidate(task,pipeline)
            else:
                route_id='luna_low' if selected=='direct_luna_low' else 'sol_high'
                route=next(r for r in config.worker_routes() if r['id']==route_id)
                schema=copy.deepcopy(BASELINE_SCHEMA)
                unit=f"defects per {task['scale']} production items"
                schema['properties']['unit']['enum']=[unit]
                candidate=gateway.ask('worker',BASELINE_INSTRUCTIONS+' The unit field must be exactly: '+unit+'.',
                                      {'source_id':'records','task':task},schema,worker_route=route)
            checks=validate_baseline(task,pipeline,candidate)
            result['quality_checks']=checks
            result['status']='complete' if all(checks.values()) else 'quality_failed'
            result['answer']=candidate['text'] if result['status']=='complete' else None
            result['candidate']=candidate
        else:
            result['status']='needs_evidence' if selected=='retrieve_evidence' else 'stopped_by_jev'
    except MeshError as error:
        result['status']='failed'
        result['error_code']=str(error) if str(error) in {
            'provider_call_failed','call_or_cost_budget_exhausted','role_call_budget_exhausted',
            'jev_token_budget_exhausted','invalid_jev_choice','focused_context_limit_exceeded'} else 'adaptive_contract_failure'
    if gateway:
        result['calls']=gateway.calls
        result['reported_cost']=gateway.spent
    result['metrics']=summarize_calls(result['calls'],baseline=baseline if live else None,
                                     quality_pass=result['status']=='complete',
                                     early_exit_selected=result['selected_route'] in ('deterministic','direct_luna_low','direct_sol_high'),
                                     escalations=sum(e['kind'] in ('post_worker_decision','post_checker_decision')
                                                     and e.get('choice')=='escalate' for e in result.get('events',[])))
    (folder/'result.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--offline',action='store_true');mode.add_argument('--live',action='store_true')
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--task',type=Path)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--baseline-result',type=Path)
    parser.add_argument('--offline-route',choices=tuple(FAST_OPTIONS),default='deterministic')
    args=parser.parse_args()
    require(args.offline or args.offline_route=='deterministic','offline_route_requires_offline_mode')
    config=RunConfig.from_dict(json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {})
    task=json.loads(args.task.read_text(encoding='utf-8-sig')) if args.task else DEMO
    baseline=json.loads(args.baseline_result.read_text(encoding='utf-8-sig')) if args.baseline_result else None
    require(baseline is None or baseline.get('task_hash')==fingerprint(task),'baseline_task_mismatch')
    result=run_adaptive(task,config,args.out,live=args.live,baseline=baseline,offline_route=args.offline_route)
    print(json.dumps({'status':result['status'],'route':result['selected_route'],
                      'answer':result['answer'],'metrics':result['metrics']},allow_nan=False))
    return 0 if result['status']=='complete' else 2


if __name__=='__main__': raise SystemExit(main())

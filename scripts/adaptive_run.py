"""Context-bound routing for the production-record CIDM fixture.

The host classifies the current input and carried context. This runner does not
infer general project complexity from prose. Unknown scope defaults to the full
five-unit graph; an explicitly short, independent input uses one Luna-low call.
"""
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


PROJECT_OPTIONS={
    'five_unit':{'description':'Five Jev-governed units; optional Sol-high review.'},
    'retrieve_evidence':{'description':'Need missing original evidence.'},
    'stop':{'description':'No safe route.'},
}
CLASSIFICATION_FLAGS=('multiple_steps','broad_project','ambiguous','depends_on_context')


def input_snapshot_hash(task,context_summary=''):
    """Bind a host classification to one input and its carried context."""
    require(type(context_summary) is str and len(context_summary)<=2000,'invalid_context_summary')
    return fingerprint({'task':task,'context_summary':context_summary})


def classify_input(task,context_summary='',classification=None):
    """Validate host signals. An absent or positive signal takes the broad route."""
    snapshot=input_snapshot_hash(task,context_summary)
    if classification is None:
        return {'source':'conservative_default','snapshot_hash':snapshot,
                'flags':None,'scope':'broad_or_uncertain'}
    require(type(classification) is dict
            and set(classification)=={'snapshot_hash',*CLASSIFICATION_FLAGS},
            'invalid_input_classification')
    require(classification['snapshot_hash']==snapshot,'stale_input_classification')
    require(all(type(classification[name]) is bool for name in CLASSIFICATION_FLAGS),
            'invalid_input_classification')
    flags={name:classification[name] for name in CLASSIFICATION_FLAGS}
    return {'source':'explicit_host','snapshot_hash':snapshot,'flags':flags,
            'scope':'broad_or_uncertain' if any(flags.values()) else 'short_self_contained'}


def project_state(task,config,routing,context_summary):
    return {'goal':task['goal'],'source_id':'records','source_hash':fingerprint(task),
            'rows':len(task['records']),'kinds':sorted({row['kind'] for row in task['records']}),
            'include':task['include_kind'],'scale':task['scale'],
            'exact_checks':True,'budget_usd':config.max_usd,
            'input_classification':routing,'context_summary':context_summary}


def run_adaptive(task,config,folder,*,live,baseline=None,context_summary='',
                 classification=None,offline_route='five_unit'):
    """Route one fixture input. Reclassify on every invocation, including follow-ups."""
    require(isinstance(config,RunConfig),'validated_run_config_required')
    pipeline=DemoPipeline(task)
    routing=classify_input(task,context_summary,classification)
    require(offline_route in PROJECT_OPTIONS,'invalid_offline_route')
    folder=Path(folder)
    require(not folder.exists(),'output_directory_must_be_new')
    folder.mkdir(parents=True,exist_ok=False)
    gateway=Gateway(folder,config) if live else None
    result={'status':'failed','mode':'context_classified_route','simulation':not live,
            'task_hash':fingerprint(task),'context_hash':fingerprint(context_summary),
            'input_classification':routing,'configuration':config.to_dict(),
            'route_gate':None,'selected_route':None,'answer':None,
            'quality_checks':None,'calls':[],'reported_cost':None if not live else 0.0,
            'training_performed':False}
    try:
        if routing['scope']=='short_self_contained':
            result['selected_route']='direct_luna_low'
            if not live:
                candidate=simulated_candidate(task,pipeline)
            else:
                route=next(r for r in config.worker_routes() if r['id']=='luna_low')
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
            if live:
                decision=gateway.network_judge('project_route',PROJECT_OPTIONS,
                                               project_state(task,config,routing,context_summary))
                selected=decision['choice']
            else:
                selected=offline_route
                decision={'choice':selected,'model':'offline_simulation','live':False}
            result['route_gate']=decision
            result['selected_route']=selected
            if selected=='five_unit':
                network_result=execute_network(task,config,folder,gateway,simulation=not live)
                result.update(network_result)
                result['mode']='context_classified_route'
                result['route_gate']=decision
                result['selected_route']=selected
                result['task_hash']=fingerprint(task)
                result['context_hash']=fingerprint(context_summary)
                result['input_classification']=routing
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
                                     early_exit_selected=result['selected_route']=='direct_luna_low',
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
    parser.add_argument('--context-summary',default='')
    parser.add_argument('--classification',type=Path,
                        help='JSON host signals bound to input_snapshot_hash(task, context_summary)')
    parser.add_argument('--offline-route',choices=tuple(PROJECT_OPTIONS),default='five_unit')
    args=parser.parse_args()
    require(args.offline or args.offline_route=='five_unit','offline_route_requires_offline_mode')
    config=RunConfig.from_dict(json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {})
    task=json.loads(args.task.read_text(encoding='utf-8-sig')) if args.task else DEMO
    classification=(json.loads(args.classification.read_text(encoding='utf-8-sig'))
                    if args.classification else None)
    baseline=json.loads(args.baseline_result.read_text(encoding='utf-8-sig')) if args.baseline_result else None
    require(baseline is None or baseline.get('task_hash')==fingerprint(task),'baseline_task_mismatch')
    result=run_adaptive(task,config,args.out,live=args.live,baseline=baseline,
                        context_summary=args.context_summary,classification=classification,
                        offline_route=args.offline_route)
    print(json.dumps({'status':result['status'],'route':result['selected_route'],
                      'answer':result['answer'],'metrics':result['metrics']},allow_nan=False))
    return 0 if result['status']=='complete' else 2


if __name__=='__main__': raise SystemExit(main())

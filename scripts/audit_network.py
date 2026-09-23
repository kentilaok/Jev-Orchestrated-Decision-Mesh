"""Check recorded gate/checker/Jev order and integrity; not semantic correctness."""
import argparse
import json
from pathlib import Path
from atomic_mesh import fingerprint
from checked_network import UNITS


def audit(result, folder=None):
    issues=[]; seen={}; used=set(); post_checks=0; commits=0
    for event in result.get('events',[]):
        if event['id'] in seen: issues.append('duplicate_event')
        if event['kind']=='dispatch':
            gate=seen.get(event.get('gate_id'))
            if not gate or gate['kind']!='jev_decision': issues.append('missing_authorization')
            else:
                option=gate['options'].get(gate['decision']['choice'],{})
                if option.get('worker_id')!=event['worker_id'] or option.get('action')!=event['action']: issues.append('changed_dispatch')
                if fingerprint(event['action'])!=event['action_hash']: issues.append('changed_action_hash')
                if gate['id'] in used: issues.append('reused_gate')
                used.add(gate['id'])
        if event['kind']=='post_checker_decision':
            post_checks+=1; gate=seen.get(event.get('gate_id'))
            if not gate or gate.get('phase')!='after_sol_high': issues.append('checker_without_jev_option')
        if event['kind']=='checked_commit':
            commits+=1; packet=event['packet']; gate=seen.get(event['gate_id'])
            if not gate or gate.get('phase')!='after_sol_high' or gate['decision']['choice']!='forward': issues.append('automatic_or_unapproved_forward')
            if packet['checker']['result']['verdict']!='pass' or not packet['checker']['contract_valid']: issues.append('failed_check_forwarded')
            if fingerprint(packet['artifact'])!=packet['artifact_hash'] or packet['checker']['candidate_hash']!=packet['artifact_hash']: issues.append('candidate_changed')
            if fingerprint(packet['checker']['result'])!=packet['checker']['check_hash']: issues.append('checker_changed')
            if gate and not all(gate['state']['hard_checks'].values()): issues.append('hard_failure_forwarded')
        seen[event['id']]=event
    ids=[p['id'] for p in result.get('committed',[])]
    if ids!=[u.id for u in UNITS[:len(ids)]]: issues.append('wrong_unit_order')
    if result['status']=='complete' and len(ids)!=5: issues.append('incomplete_chain_claimed_complete')
    if result['status']=='complete' and result['answer']!=result['committed'][-1]['artifact']['text']: issues.append('final_changed')
    checker_calls=[]
    if folder is not None and not result.get('simulation',True):
        calls=result.get('calls',[])
        for i,call in enumerate(calls):
            if call['role']!='checker' or call['status']!='ok': continue
            if i+1>=len(calls) or calls[i+1]['role']!='jev' or calls[i+1]['status']!='ok':
                issues.append('live_checker_return_not_followed_by_jev')
            request=json.loads((folder/(call['id']+'.request.json')).read_text())
            if request.get('reasoning',{}).get('effort')!='high': issues.append('checker_not_high')
            state=json.loads(request['messages'][1]['content'])
            checker_calls.append({'call_id':call['id'],'unit_id':state['unit']['id'],'effort':request['reasoning']['effort']})
        for uid in ids:
            if not any(c['unit_id']==uid for c in checker_calls): issues.append('missing_live_checker_'+uid)
    return {'valid':not issues,'status':result['status'],'committed_units':ids,'checked_commits':commits,
            'post_checker_jev_decisions':post_checks,'live_high_checker_calls':checker_calls,'issues':issues}


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('result',type=Path); a=p.parse_args()
    report=audit(json.loads(a.result.read_text()),a.result.parent)
    print(json.dumps(report,indent=2)); raise SystemExit(0 if report['valid'] else 2)

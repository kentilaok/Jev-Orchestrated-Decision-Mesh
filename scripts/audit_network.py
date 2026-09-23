"""Audit CIDM worker/Jev order and optional checker returns; not semantic truth."""
import argparse
import json
from pathlib import Path
from atomic_mesh import fingerprint
from checked_network import UNITS


def audit(result, folder=None):
    issues=[]; seen={}; used=set(); post_checks=0; post_workers=0; commits=0
    conditional=result.get('protocol_version')=='cidm-conditional-review-v3'
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
        if event['kind']=='post_worker_decision':
            post_workers+=1; gate=seen.get(event.get('gate_id'))
            if not gate or gate.get('phase')!='after_worker': issues.append('worker_without_jev_option')
        if event['kind']=='checked_commit':
            commits+=1; packet=event['packet']; gate=seen.get(event['gate_id'])
            phase=gate.get('phase') if gate else None
            if not gate or phase not in (('after_worker','after_sol_high') if conditional else ('after_sol_high',)) or gate['decision']['choice']!='forward':
                issues.append('automatic_or_unapproved_forward')
            checker=packet.get('checker')
            if checker is None:
                if not conditional or phase!='after_worker': issues.append('unreviewed_forward_without_worker_decision')
            else:
                if phase!='after_sol_high' or checker['result']['verdict']!='pass' or not checker['contract_valid']:
                    issues.append('failed_check_forwarded')
                if checker['candidate_hash']!=packet['artifact_hash'] or fingerprint(checker['result'])!=checker['check_hash']:
                    issues.append('checker_changed')
            if fingerprint(packet['artifact'])!=packet['artifact_hash']: issues.append('candidate_changed')
            if gate and not all(gate['state']['hard_checks'].values()): issues.append('hard_failure_forwarded')
            if conditional and not any(e['kind']=='post_worker_decision' and e['unit_id']==packet['id']
                                       and e['candidate_hash']==packet['artifact_hash'] for e in result.get('events',[])[:len(seen)]):
                issues.append('missing_worker_jev_decision')
        seen[event['id']]=event
    ids=[p['id'] for p in result.get('committed',[])]
    if ids!=[u.id for u in UNITS[:len(ids)]]: issues.append('wrong_unit_order')
    committed_events=[e['packet'] for e in result.get('events',[]) if e['kind']=='checked_commit']
    if len(committed_events)!=len(result.get('committed',[])): issues.append('commit_event_count_mismatch')
    for index,packet in enumerate(result.get('committed',[])):
        if fingerprint(packet['artifact'])!=packet['artifact_hash']: issues.append('committed_artifact_changed')
        if packet.get('policy_version')!=result.get('policy_version'): issues.append('committed_policy_changed')
        if index<len(committed_events) and fingerprint(packet)!=fingerprint(committed_events[index]):
            issues.append('committed_packet_changed')
        expected_parent=([{'id':result['committed'][index-1]['id'],
                           'hash':result['committed'][index-1]['artifact_hash']}] if index else [])
        if packet.get('parent_artifacts')!=expected_parent: issues.append('committed_parent_changed')
    if result['status']=='complete' and len(ids)!=5: issues.append('incomplete_chain_claimed_complete')
    if result['status']=='complete' and result['answer']!=result['committed'][-1]['artifact']['text']: issues.append('final_changed')
    if conditional and result['status']=='complete' and post_workers<len(ids): issues.append('missing_worker_jev_decision')
    checker_calls=[]
    if folder is not None and not result.get('simulation',True):
        calls=result.get('calls',[])
        for i,call in enumerate(calls):
            if conditional and call['role']=='worker' and call['status']=='ok':
                if not call.get('followup_jev_required') or i+1>=len(calls) or calls[i+1]['role']!='jev' or calls[i+1]['status']!='ok':
                    issues.append('live_worker_return_not_followed_by_jev')
            if call['role']!='checker' or call['status']!='ok': continue
            if i+1>=len(calls) or calls[i+1]['role']!='jev' or calls[i+1]['status']!='ok':
                issues.append('live_checker_return_not_followed_by_jev')
            request=json.loads((folder/(call['id']+'.request.json')).read_text())
            if request.get('reasoning',{}).get('effort')!='high': issues.append('checker_not_high')
            state=json.loads(request['messages'][1]['content'])
            checker_calls.append({'call_id':call['id'],'unit_id':state['unit']['id'],'effort':request['reasoning']['effort']})
        if not conditional:
            for uid in ids:
                if not any(c['unit_id']==uid for c in checker_calls): issues.append('missing_live_checker_'+uid)
    return {'valid':not issues,'status':result['status'],'committed_units':ids,'checked_commits':commits,
            'post_worker_jev_decisions':post_workers,'post_checker_jev_decisions':post_checks,
            'live_high_checker_calls':checker_calls,'issues':issues}


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('result',type=Path); a=p.parse_args()
    report=audit(json.loads(a.result.read_text()),a.result.parent)
    print(json.dumps(report,indent=2)); raise SystemExit(0 if report['valid'] else 2)

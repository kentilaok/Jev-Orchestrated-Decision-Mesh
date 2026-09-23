"""Metered CIDM selection/review pilot. No gold labels or host LLM in execution."""
import argparse
import hashlib
import http.client
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error
import uuid

ROOT = Path(__file__).resolve().parent
SOL = 'openai/gpt-5.6-sol'
JEV = 'typesafe/jev-1.13'
EFFORT = 'medium'
MAX_OUTPUT = 4000
GLOBAL_USD = 3.0
ARM_USD = .40
ARM_TOKENS = 100000
SEED = 1729
BASE_SYSTEM = ('Answer the requested fields using only the supplied source documents. '
    'Respect scope, exceptions, dependencies, units, and conflicting or missing evidence. '
    'Return null for an answer that cannot be established; do not guess. '
    'Cite supporting document IDs for each field. Follow the exact requested answer encoding. '
    'Use partial status if any requested value is unavailable or unresolved; otherwise complete. '
    'Before finalizing, check your answers against the evidence. Return only the requested JSON object.')
CIDM_EXTRA = (' Also return a cidm object with five integer self_scores rated 1 to 5 '
    '(correctness,evidence_support,completeness,constraint_compliance,usefulness), '
    'self_estimated_success_probability (uncalibrated number 0 to 1 or null), '
    'missing_evidence array, and next_action chosen from finish, retrieve, revise. '
    'Keep missing_evidence to at most three short entries. Keep the packet concise. '
    'These self-assessments are not proof and must not replace checking sources.')
LEVELS = ['Material failure','Major gaps','Partially adequate','Adequate with minor uncertainty','Fully adequate']

spec = importlib.util.spec_from_file_location('jev_helper', ROOT/'jev_decide.py')
jev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jev)

def canonical(value): return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'))
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def write_json(path,value): path.write_text(json.dumps(value,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
def append(path,value):
    with path.open('a',encoding='utf-8') as f: f.write(canonical(value)+'\n')

def load_tasks():
    data=json.loads((ROOT/'tasks.json').read_text(encoding='utf-8'))
    return data if isinstance(data,list) else data['tasks']

def result_schema(task, arm):
    fields=task['answer_fields']
    props={
        'answers':{'type':'object','properties':{f:{'type':['string','number','null']} for f in fields},'required':fields,'additionalProperties':False},
        'evidence':{'type':'object','properties':{f:{'type':'array','items':{'type':'string'}} for f in fields},'required':fields,'additionalProperties':False},
        'status':{'type':'string','enum':['complete','partial']}}
    if arm=='B':
        names=['correctness','evidence_support','completeness','constraint_compliance','usefulness']
        props['cidm']={'type':'object','properties':{
            'self_scores':{'type':'object','properties':{n:{'type':'integer','minimum':1,'maximum':5} for n in names},'required':names,'additionalProperties':False},
            'self_estimated_success_probability':{'type':['number','null'],'minimum':0,'maximum':1},
            'missing_evidence':{'type':'array','items':{'type':'string'}},
            'next_action':{'type':'string','enum':['finish','retrieve','revise']}},
            'required':['self_scores','self_estimated_success_probability','missing_evidence','next_action'],'additionalProperties':False}
    return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}

def check_candidate(value, task, arm='A'):
    # Only public structural checks; no gold values or oracle feedback.
    fields=set(task['answer_fields']); ids={d['id'] for d in task['documents']}
    if not isinstance(value,dict) or value.get('status') not in ('complete','partial'): return False
    if set(value)!=({'answers','evidence','status','cidm'} if arm=='B' else {'answers','evidence','status'}): return False
    a,e=value.get('answers'),value.get('evidence')
    if not isinstance(a,dict) or set(a)!=fields or not isinstance(e,dict) or set(e)!=fields: return False
    for field in fields:
        if type(a[field]) not in (str,int,float,type(None)): return False
        if isinstance(a[field],float) and not math.isfinite(a[field]): return False
        if not isinstance(e[field],list) or not all(isinstance(x,str) and x in ids for x in e[field]): return False
    if arm=='B':
        meta=value.get('cidm')
        names={'correctness','evidence_support','completeness','constraint_compliance','usefulness'}
        if not isinstance(meta,dict) or set(meta)!={'self_scores','self_estimated_success_probability','missing_evidence','next_action'}: return False
        scores=meta.get('self_scores')
        if not isinstance(scores,dict) or set(scores)!=names or not all(type(v) is int and 1<=v<=5 for v in scores.values()): return False
        p=meta['self_estimated_success_probability']
        if p is not None and (type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1): return False
        if not isinstance(meta['missing_evidence'],list) or not all(isinstance(s,str) for s in meta['missing_evidence']): return False
        if meta['next_action'] not in ('finish','retrieve','revise'): return False
    return True

def intake_request(task):
    questions={'operation':{'type':'choice','instructions':'Choose a suitable way to send sources to the fixed Sol worker for this task.',
        'criteria':{'select_context':'Some documents do not contribute; use the independently evaluated relevance results to select sources.',
                    'use_all':'All documents may be needed, or reliable source selection is uncertain.'}}}
    for doc in task['documents']:
        questions['keep_'+doc['id']]={'type':'noul','instructions':
            'Is document '+doc['id']+' potentially necessary for any requested answer, evidence, exception, dependency, contradiction, or missing-information determination? Retain indirect supporting records.'}
    return {'model':JEV,'state':{'original_request':task['query'],'answer_fields':task['answer_fields'],'documents':task['documents']},'questions':questions}

def review_request(task, packet, structure_ok, final_attempt):
    q={}
    criteria={
        'correctness':'Judge whether stated answers correctly follow from the original documents, including arithmetic, exceptions and units.',
        'evidence_support':'Judge whether supplied citations adequately support each answer. Null is appropriate when the requested value is absent or contradictory.',
        'completeness':'Judge whether every field is addressed appropriately; justified null for unavailable information counts as appropriate coverage.',
        'constraint_compliance':'Judge compliance with the query encoding, source scope, and no guessing.',
        'usefulness':'Judge whether the answers are usable for the query, including explicit justified unknowns.'}
    for name,instructions in criteria.items(): q[name]={'type':'score','instructions':instructions,'criteria':LEVELS}
    q['supported']={'type':'noul','instructions':'Are the substantive answers supported by the source documents, with unknown or conflicting values appropriately represented as null?'}
    q['release']={'type':'choice','instructions':'Choose whether the actual candidate is adequate to return. Evaluate it from the state, not from other question outputs. Justified unknowns may be accepted.',
        'criteria':{'accept':'The candidate appropriately answers all fields, including justified unknowns, with supporting citations.',
                    'revise':'The candidate needs correction or omitted source recovery.',
                    'stop_unresolved':'The candidate cannot be accepted within the available evidence and budget.'}}
    return {'model':JEV,'state':{'original_request':task['query'],'answer_fields':task['answer_fields'],
        'documents':task['documents'],'actual_worker_packet':packet,'structure_ok':structure_ok,'final_attempt':final_attempt},'questions':q}

class Halt(Exception): pass

class Harness:
    def __init__(self, out, phase):
        self.out=out; self.phase=phase; self.key=os.environ.get('OPENROUTER_API_KEY','')
        if not self.key: raise Halt('OPENROUTER_API_KEY is unavailable')
        self.out.mkdir(parents=True,exist_ok=True)
        self.events=[]; self.spent=.32304; self.unknown_billing=False
        # Shared setup: .00304 measured Azure compatibility cost plus .16 reserved
        # for each of two pre-inference route rejections with unknown counters.
        for path in ROOT.glob('runs-*/ledger.jsonl'):
            for line in path.read_text(encoding='utf-8').splitlines():
                event=json.loads(line); cost=event.get('usage',{}).get('cost')
                if cost is None: self.unknown_billing=True
                else: self.spent+=cost
        self.opener=urllib.request.build_opener(jev.NoRedirect())

    def call(self, task, arm, role, stage, payload, parent=None):
        body=canonical(payload).encode()
        if role=='jev': jev.validate_request(payload,'openrouter')
        if len(body)>55000: raise Halt('Request exceeds local byte bound')
        matching=[e for e in self.events if e['task_id']==task['id'] and e['arm']==arm]
        tokens=sum(e['usage']['input_tokens']+e['usage']['output_tokens'] for e in matching)
        costs=sum(e['usage']['cost'] for e in matching)
        # Conservative reservation uses ASCII bytes as an upper bound, not measured tokens.
        reserve=(len(body)*.000006+MAX_OUTPUT*.000036) if role=='worker' else len(body)*.00000005
        review_reserve_bytes=28000 if role=='worker' and arm=='B' else 0
        reserve+=review_reserve_bytes*.00000005
        reserved_tokens=len(body)+(MAX_OUTPUT if role=='worker' else 2500)+review_reserve_bytes+(2500 if review_reserve_bytes else 0)
        if self.unknown_billing or self.spent+reserve>GLOBAL_USD or costs+reserve>ARM_USD or tokens+reserved_tokens>ARM_TOKENS:
            raise Halt('Conservative budget reservation would exceed cap or billing is unknown')
        event_id=uuid.uuid4().hex
        event={'event_id':event_id,'phase':self.phase,'task_id':task['id'],'replicate':0,'arm':arm,'role':role,'stage':stage,
            'status':'failed','model_requested':payload['model'],'model_returned':None,'effort':EFFORT if role=='worker' else None,
            'parent_event_id':parent,'request_sha256':digest(payload),'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'usage':{'input_tokens':None,'output_tokens':None,'total_tokens':None,'reasoning_tokens':None,'cached_input_tokens':None,'cost':None}}
        write_json(self.out/(event_id+'.request.json'),payload)
        url='https://openrouter.ai/api/v1/chat/completions' if role=='worker' else 'https://openrouter.ai/api/alpha/decisions'
        request=urllib.request.Request(url,data=body,headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json','Accept':'application/json'},method='POST')
        started=time.monotonic(); response=None
        try:
            with self.opener.open(request,timeout=60) as r: response=jev.decode_json(r.read(2_000_001))
            if not isinstance(response,dict): raise Halt('Response is not an object')
            u=response.get('usage') or {}
            if not isinstance(u,dict): raise Halt('Usage is not an object')
            event['usage_raw']=u
            event['model_returned']=response.get('model'); event['provider_returned']=response.get('provider')
            event['generation_id']=response.get('id')
            event['usage'].update(input_tokens=u.get('prompt_tokens') if role=='worker' else u.get('input_tokens'),
                output_tokens=u.get('completion_tokens') if role=='worker' else u.get('output_tokens'), total_tokens=u.get('total_tokens'),
                reasoning_tokens=(u.get('completion_tokens_details') or {}).get('reasoning_tokens'),
                cached_input_tokens=(u.get('prompt_tokens_details') or {}).get('cached_tokens'), cost=u.get('cost'))
            if role=='jev':
                event['warnings']=[]; jev.validate_response(response,payload,event['warnings'])
            else:
                actual=response.get('model','')
                if actual not in (SOL,SOL+'-20260709'): raise Halt('Model substitution detected')
                if response.get('provider')!='Azure': raise Halt('Provider substitution detected')
                if not response.get('choices'): raise Halt('Missing worker choices')
            usage=event['usage']
            for field in ('input_tokens','output_tokens'):
                if type(usage[field]) is not int or usage[field]<0: raise Halt('Missing or invalid measured usage')
            if type(usage['cost']) not in (int,float) or not math.isfinite(usage['cost']) or usage['cost']<0: raise Halt('Missing measured cost')
            if usage['total_tokens'] is not None and usage['total_tokens']!=usage['input_tokens']+usage['output_tokens']: raise Halt('Usage totals disagree')
            event['status']='ok'
        except urllib.error.HTTPError as e: event['error']={'code':'http_error','status':e.code}
        except (urllib.error.URLError,TimeoutError,OSError,http.client.HTTPException) as e: event['error']={'code':'network_error'}
        except (Halt,jev.Failure,ValueError,KeyError,TypeError,AttributeError) as e: event['error']={'code':e.code if isinstance(e,jev.Failure) else str(e)}
        finally:
            event['latency_ms']=round((time.monotonic()-started)*1000,3)
            if response is not None:
                # reasoning.exclude=True: no hidden reasoning text is requested or persisted.
                write_json(self.out/(event_id+'.response.json'),response)
            billed=event['usage']['cost']
            if type(billed) not in (int,float) or not math.isfinite(billed) or billed<0:
                event['usage']['cost']=None
                self.unknown_billing=True
            else: self.spent+=billed
            append(self.out/'ledger.jsonl',event); self.events.append(event)
            print(canonical({'task':task['id'],'arm':arm,'role':role,'stage':stage,'status':event['status'],'budget_committed_including_setup_reserve':round(self.spent,6)}),flush=True)
        if event['status']!='ok': raise Halt('API event failed: '+event_id)
        return response,event_id

    def worker(self,task,arm,docs,attempt,previous=None,parent=None):
        user={'query':task['query'],'answer_fields':task['answer_fields'],'documents':docs}
        if attempt: user['revision']={'previous_candidate':previous,'instruction':'Recheck the complete sources. Repair incorrect or incomplete answers and citations. Return a replacement answer.'}
        request={'model':SOL,'messages':[{'role':'system','content':BASE_SYSTEM+(CIDM_EXTRA if arm=='B' else '')},{'role':'user','content':canonical(user)}],
            'reasoning':{'effort':EFFORT,'exclude':True},'max_completion_tokens':MAX_OUTPUT,'seed':SEED,
            'provider':{'only':['azure'],'ignore':['azure/us','azure/eu'],'allow_fallbacks':False,'require_parameters':True},
            'response_format':{'type':'json_schema','json_schema':{'name':'task_answer','strict':True,'schema':result_schema(task,arm)}}}
        response,eid=self.call(task,arm,'worker','answer' if not attempt else 'revision',request,parent)
        choice=response['choices'][0]; content=choice.get('message',{}).get('content')
        if choice.get('finish_reason')!='stop':
            return {'invalid_artifact':True,'finish_reason':choice.get('finish_reason'),'actual_visible_output':content},eid
        try: return jev.decode_json(content),eid
        except (TypeError,jev.Failure):
            return {'invalid_artifact':True,'finish_reason':choice.get('finish_reason'),'actual_visible_output':content,'error':'invalid_json'},eid

    def run_arm(self,task,arm):
        start=time.monotonic(); before=len(self.events); packet=None; released=False; status='failed'; error=None; selected=task['documents']; parent=None
        try:
            if arm=='B':
                response,parent=self.call(task,arm,'jev','intake',intake_request(task))
                if response['answers']['operation']['choice']=='select_context':
                    selected=[d for d in task['documents'] if response['answers']['keep_'+d['id']]['noul']>=.25]
                    if not selected: selected=task['documents']
                append(self.out/'transitions.jsonl',{'task_id':task['id'],'arm':arm,'gate':parent,'action':'delegate',
                    'selected_source_ids':[d['id'] for d in selected],'omitted_source_ids':[d['id'] for d in task['documents'] if d not in selected]})
            for attempt in range(2):
                packet,worker_id=self.worker(task,arm,selected if attempt==0 else task['documents'],attempt,packet,parent)
                valid=check_candidate(packet,task,arm)
                if arm=='A':
                    if valid: released=True; break
                    continue
                response,parent=self.call(task,arm,'jev','review',review_request(task,packet,valid,attempt==1),worker_id)
                answers=response['answers']; action=answers['release']['choice']
                scores_ok=all(answers[n]['score']>=3 for n in ('correctness','evidence_support','completeness','constraint_compliance','usefulness'))
                accepted=valid and action=='accept' and scores_ok and answers['supported']['noul']>=.85
                append(self.out/'transitions.jsonl',{'task_id':task['id'],'arm':arm,'gate':parent,'action':'finish' if accepted else action,'attempt':attempt,'accepted':accepted})
                if accepted: released=True; break
                if action!='revise': break
            status=packet.get('status','failed') if released else 'failed'
        except (Halt,jev.Failure) as e: error=str(e)
        candidate={k:packet[k] for k in ('answers','evidence','status')} if isinstance(packet,dict) and all(k in packet for k in ('answers','evidence','status')) else None
        run={'task_id':task['id'],'stratum':task['stratum'],'replicate':0,'arm':arm,'phase':self.phase,'status':status,
            'candidate':candidate,'released':released,'elapsed_seconds':round(time.monotonic()-start,3),
            'event_ids':[e['event_id'] for e in self.events[before:]],'selected_source_ids':[d['id'] for d in selected],'worker_packet':packet,'error':error}
        append(self.out/'runs.jsonl',run)
        print(canonical({'completed_task':task['id'],'arm':arm,'released':released,'elapsed_seconds':run['elapsed_seconds']}),flush=True)
        return run

def freeze(tasks):
    manifest={'name':'CIDM vs fixed Sol pilot','attribution':'Kenneth A. Caber','version':'pilot-1','created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'sol_model':SOL,'sol_effort':EFFORT,'jev_model':JEV,'provider':'OpenRouter with Azure standard endpoint only (account ZDR compliant)','seed':SEED,
        'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'tasks.json',ROOT/'gold.json',ROOT/'run_benchmark.py',ROOT/'jev_decide.py',ROOT/'grader.py',ROOT/'analyze.py',ROOT/'provider-preflight.json']},
        'prompt_hashes':{'baseline_system':digest(BASE_SYSTEM),'cidm_system':digest(BASE_SYSTEM+CIDM_EXTRA)},
        'evaluation_task_ids':[t['id'] for t in tasks if t.get('phase')=='evaluation'],'replicates':1,
        'arms':{'A':'Sol full source corpus, one answer plus structural repair if needed','B':'Jev intake/relevance -> same Sol -> Jev five-score review; at most one corrective Sol call'},
        'scope':'Bounded selection/review CIDM prototype; not full recursive multi-model application',
        'caps':{'global_usd':GLOBAL_USD,'per_arm_usd':ARM_USD,'per_arm_tokens':ARM_TOKENS,'sol_calls_per_arm':2,'jev_calls_per_B':3,'max_output_per_Sol':MAX_OUTPUT,'network_timeout_seconds':60},
        'policy':{'retain_probability':.25,'accept_support_probability':.85,'minimum_review_score_raw_0_to_4':3,'calibration':'Uncalibrated fixed engineering thresholds; no learned routing claims'},
        'quality':{'primary':'all fields, required evidence and status pass deterministic independent gold grader','noninferiority_margin':.05,'sample_size_rationale':'12-task feasibility pilot, not powered to establish 5pp noninferiority','gold_hidden_from_controller':True},
        'analysis':{'primary':'B versus A total provider-accounted tokens, quality reported separately','bootstrap':'10000 stratified paired task resamples, seed1729','secondary':'cost, latency, worker-only tokens, rejection and raw candidate quality'},
        'execution_order':'alternate A/B first by task index; serial, no cross-arm memory','cache_policy':'no explicit response cache; fresh calls, counterbalanced order; report provider cache counters; common provider cache behavior cannot be disabled',
        'tools':'No external tools or embeddings; original documents supplied as immutable text. Python selects/assembles exact source units and checks public schema.',
        'accounting':'Reasoning subset of output, cached subset of input. All Jev, workers, repairs, failures counted. Unknown is null. Development separate, execution subtotal plus dev lifecycle subtotal.',
        'setup_accounting':{'two_direct_OpenAI_route_rejections':'Account ZDR policy excluded endpoint. No inference response or usage returned; counters unknown, preserved separately.',
            'Azure_compatibility_probe':{'input_tokens':368,'output_tokens':40,'total_tokens':408,'cost_usd':.00304},
            'unknown_setup_budget_reserve_usd':.32,'total_committed_setup_usd':.32304},
        'setup_overhead':'Research, dataset/code creation, review and this host conversation are unmetered one-time preparation, outside measured API execution; no end-to-end development lifecycle savings claim.'}
    path=ROOT/'frozen-manifest.json'
    if path.exists(): raise Halt('Manifest already exists; do not overwrite preregistration')
    write_json(path,manifest); print('Manifest frozen before evaluation',flush=True)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--phase',choices=['development','evaluation'],required=True); ap.add_argument('--freeze',action='store_true'); args=ap.parse_args()
    tasks=load_tasks()
    if args.freeze: freeze(tasks)
    if args.phase=='evaluation':
        manifest=json.loads((ROOT/'frozen-manifest.json').read_text())
        for name,h in manifest['source_hashes'].items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h: raise Halt('Frozen source changed: '+name)
    out=ROOT/('runs-'+args.phase)
    if (out/'runs.jsonl').exists() or (out/'ledger.jsonl').exists(): raise Halt('Run directory already contains events; no duplicate execution')
    harness=Harness(out,args.phase)
    selected=[t for t in tasks if t.get('phase')==args.phase]
    for i,task in enumerate(selected):
        for arm in (('A','B') if i%2==0 else ('B','A')): harness.run_arm(task,arm)
        if harness.unknown_billing: raise Halt('Stop experiment: missing cost after call')

if __name__=='__main__':
    try: main()
    except Halt as e: print(str(e),file=sys.stderr); sys.exit(2)

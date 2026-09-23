"""Bounded five-gate reference pipeline, with Sol-high -> Jev after every gate."""
import argparse
import json
import re
from pathlib import Path
from fractions import Fraction

from transport import Gateway
from config import RunConfig
from atomic_mesh import AtomicMesh, require, packed, fingerprint
from checked_network import CheckedNetwork, UNITS

DEMO={'goal':'Report production defects per 1,000 items, excluding trial records, with source support.',
      'records':[{'segment':'A','kind':'production','items':240,'defects':12},
                 {'segment':'B','kind':'production','items':160,'defects':8},
                 {'segment':'T','kind':'trial','items':100,'defects':30}],
      'include_kind':'production','scale':1000}


def artifact(text,data):
    return {'text':text,'data':data,'source_ids':['records'],'five_scores':[5,5,5,5,5],'self_probability':None}


class DemoPipeline:
    def __init__(self,task,gateway=None):
        self.task=task; self.gateway=gateway
        require(set(task)=={'goal','records','include_kind','scale'},'task_schema')
        require(isinstance(task['records'],list) and 1<=len(task['records'])<=8,'record_limit')
        require(type(task['scale']) is int and 0<task['scale']<=10000,'scale_range')
        ids=set()
        for row in task['records']:
            require(set(row)=={'segment','kind','items','defects'} and isinstance(row['segment'],str) and row['segment'] not in ids,'record_schema')
            require(type(row['items']) is int and type(row['defects']) is int and 0<=row['defects']<=row['items']<=1000000,'record_numbers')
            ids.add(row['segment'])
        self.rows=[r for r in task['records'] if r['kind']==task['include_kind']]
        require(sum(r['items'] for r in self.rows)>0,'empty_denominator')
        self.expected=Fraction(sum(r['defects'] for r in self.rows),sum(r['items'] for r in self.rows))*task['scale']

    def produce(self,unit,parents,feedback):
        if unit.id=='input': return artifact('Original records normalized without changing values.',{'records':self.task['records'],'include_kind':self.task['include_kind'],'scale':self.task['scale']})
        if unit.id=='hidden2':
            plan=parents[-1]['artifact']['data']
            rows=[r for r in self.task['records'] if r['segment'] in plan['segments']]
            numerator=sum(r[plan['numerator']] for r in rows); denominator=sum(r[plan['denominator']] for r in rows)
            value=Fraction(numerator,denominator)*plan['scale']
            return artifact('Computed with exact rational arithmetic; numerator '+str(numerator)+', denominator '+str(denominator)+'.',
                            {'numerator':numerator,'denominator':denominator,'scale':plan['scale'],'result':float(value),'exact_fraction':str(value)})
        if not self.gateway:
            if unit.id=='hidden1': return artifact('Use production records and exclude trial records.',{'segments':[r['segment'] for r in self.rows],'numerator':'defects','denominator':'items','scale':self.task['scale']})
            if unit.id=='hidden3': return artifact('The checked interpretation and exact calculation agree with original records.',{'consistent':True,'unresolved':[],'result':float(self.expected)})
            return artifact(str(float(self.expected))+' defects per '+str(self.task['scale'])+' production items; trial excluded. [records]',{'answer':float(self.expected),'unit':'defects per '+str(self.task['scale'])+' items'})
        schemas={
            'hidden1':'data must have exactly segments (array of included segment IDs), numerator (literal string "defects", NOT the total number), denominator (literal string "items", NOT the total number), scale (integer). Example {"segments":["A","B"],"numerator":"defects","denominator":"items","scale":1000}. This unit chooses fields; the following unit computes totals.',
            'hidden3':'data must have exactly consistent (boolean), unresolved (array of strings), result (numeric checked result).',
            'output':'data must have exactly answer (numeric checked result), unit (string). text must be the final concise answer including source citation [records].'}
        instructions=('Execute only the specified unit. Return exactly JSON text (<=1200 chars), data (object), source_ids (["records"]), '
            'five_scores (five integers1-5 for correctness, evidence, completeness, constraints, usefulness), self_probability (uncalibrated0-1 or null). '
            'Do not expose hidden reasoning; give the bounded result. '+schemas[unit.id])
        data_properties={
            'hidden1':{'segments':{'type':'array','items':{'type':'string'}},'numerator':{'type':'string','enum':['defects']},'denominator':{'type':'string','enum':['items']},'scale':{'type':'integer'}},
            'hidden3':{'consistent':{'type':'boolean'},'unresolved':{'type':'array','items':{'type':'string'}},'result':{'type':'number'}},
            'output':{'answer':{'type':'number'},'unit':{'type':'string','enum':['defects per '+str(self.task['scale'])+' items']}}}[unit.id]
        schema={'type':'object','properties':{'text':{'type':'string'},
            'data':{'type':'object','properties':data_properties,'required':list(data_properties),'additionalProperties':False},
            'source_ids':{'type':'array','items':{'type':'string','enum':['records']}},
            'five_scores':{'type':'array','items':{'type':'integer','minimum':1,'maximum':5},'minItems':5,'maxItems':5},
            'self_probability':{'type':['number','null']}},
            'required':['text','data','source_ids','five_scores','self_probability'],'additionalProperties':False}
        return self.gateway.ask('worker',instructions,{'unit':unit.__dict__,'goal':self.task['goal'],'original_records':self.task,
            'accepted_parents':[p['artifact'] for p in parents[-2:]],'repair_feedback':feedback},schema)

    def validate(self,unit,candidate,parents):
        d=candidate['data']; checks={'source_present':candidate['source_ids']==['records']}
        if unit.id=='input': checks['exact_original_values']=d=={'records':self.task['records'],'include_kind':self.task['include_kind'],'scale':self.task['scale']}
        elif unit.id=='hidden1':
            checks['correct_scope_and_formula']=set(d)=={'segments','numerator','denominator','scale'} and d['segments']==[r['segment'] for r in self.rows] and d['numerator']=='defects' and d['denominator']=='items' and d['scale']==self.task['scale']
        elif unit.id=='hidden2': checks['exact_arithmetic']=d.get('exact_fraction')==str(self.expected) and d.get('result')==float(self.expected)
        elif unit.id=='hidden3': checks['consistent_with_calculation']=set(d)=={'consistent','unresolved','result'} and d['consistent'] is True and d['unresolved']==[] and d['result']==float(self.expected)
        else:
            match=re.fullmatch(r'defects per (\d{1,3}(?:,\d{3})+|\d+) (?:production )?items',str(d.get('unit','')).strip().lower())
            checks['final_answer_matches_calculation']=set(d)=={'answer','unit'} and d['answer']==float(self.expected) and bool(match) and int(match.group(1).replace(',',''))==self.task['scale']
        return checks


def fake_judge(phase,options,state):
    mapping={'authorize_unit':'compute','authorize_checker':'check','after_sol_high':'forward'}
    return {'choice':mapping[phase],'live':False,'model':'simulation'}


def fake_check(state):
    passed=all(state.get('hard_checks',{'synthetic':True}).values())
    return {'verdict':'pass' if passed else 'repair_required','failed_criteria':[] if passed else ['hard_check'],
            'reason':'Offline fixture only.','missing_evidence':[]}


def main():
    p=argparse.ArgumentParser(description="Training-free CIDM checked-gate demonstration")
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--offline',action='store_true'); mode.add_argument('--live',action='store_true')
    p.add_argument('--out',type=Path,required=True); p.add_argument('--task',type=Path)
    p.add_argument('--config',type=Path)
    a=p.parse_args()
    require(not a.out.exists(),'output_directory_must_be_new')
    configuration=RunConfig.from_dict(json.loads(a.config.read_text(encoding='utf-8-sig')) if a.config else {})
    a.out.mkdir(parents=True)
    task=json.loads(a.task.read_text(encoding='utf-8-sig')) if a.task else DEMO
    gateway=Gateway(a.out,configuration) if a.live else None
    pipeline=DemoPipeline(task,gateway)
    sources={'records':{'title':'Original records','text':packed(task)}}
    def journal(event):
        with (a.out/'journal.jsonl').open('a',encoding='utf-8') as stream: stream.write(packed(event)+'\n')
    network=CheckedNetwork(task['goal'],sources,gateway.network_judge if gateway else fake_judge,pipeline.produce,
        gateway.high_check if gateway else fake_check,pipeline.validate,policy=configuration.to_dict(),
        checker_identity={'model':configuration.checker_model,'effort':configuration.checker_effort},
        simulation=a.offline,journal=journal)
    result=network.run(); result['calls']=gateway.calls if gateway else []
    result['reported_cost']=gateway.spent if gateway else 0
    result['configuration']=configuration.to_dict()
    result['training_performed']=False
    result['scope']='Training-free Jev orchestration. Neural-network and Transformer concepts are routing inspirations only.'
    (a.out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(packed({'status':result['status'],'answer':result['answer'],'committed_units':len(result['committed']),
        'checker_returns':len(result['checks']),'reported_cost':result['reported_cost'],'training_performed':False}))
    return 0 if result['status']=='complete' else 2


if __name__=='__main__': raise SystemExit(main())

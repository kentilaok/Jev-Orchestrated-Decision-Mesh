"""Verify saved CIDM Jev fast exits without network or credentials."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def packed(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False)


def verify(name,expected_tokens,expected_cost):
    folder=ROOT/name
    result=read(folder/'result.json')
    assert result['status']=='complete' and result['selected_route']=='deterministic'
    assert result['simulation'] is False and len(result['calls'])==1
    assert result['fast_gate']['choice']=='deterministic'
    assert all(result['quality_checks'].values()) and '[records]' in result['answer']
    assert result['candidate']['answer']==50
    event=result['calls'][0]
    request=read(folder/'call-1.request.json')
    response=read(folder/'call-1.response.json')
    assert event['role']=='jev' and event['status']=='ok'
    assert hashlib.sha256(packed(request).encode()).hexdigest()==event['request_hash']
    assert request['model']==event['requested_model']
    assert response['model']==event['returned_model']
    assert response.get('provider')==event['provider']=='TypeSafe'
    assert event['usage']['total_tokens']==event['usage']['input_tokens']+event['usage']['output_tokens']==expected_tokens
    assert Decimal(str(event['usage']['cost']))==expected_cost
    assert Decimal(str(result['reported_cost']))==expected_cost
    assert result['metrics']['jev_passes']==1 and result['metrics']['worker_calls']==0
    assert result['metrics']['checker_calls']==0 and result['metrics']['early_exit_selected'] is True
    return result


def main():
    lines=(ROOT/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines()
    expected=set()
    for line in lines:
        digest,path=line.split('  ',1)
        expected.add(path)
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
            and p.name not in ('README.md','SHA256SUMS.txt')}
    assert actual==expected
    initial=verify('initial',889,Decimal('0.00003423'))
    compact=verify('compact',716,Decimal('0.000026964'))
    baseline=read(ROOT.parent/'live-gpt6-fixture/single-sol/result.json')
    assert initial['task_hash']==compact['task_hash']==baseline['task_hash']
    assert baseline['status']=='complete' and all(baseline['quality_checks'].values())
    print(json.dumps({'verified':True,'initial_jev_tokens':889,'compact_jev_tokens':716,
                      'compact_cost_usd':'0.000026964','route':'deterministic'}))


if __name__=='__main__': main()

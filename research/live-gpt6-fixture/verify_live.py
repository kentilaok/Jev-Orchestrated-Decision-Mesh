"""Recheck published synthetic GPT-6 call records without network or API keys."""
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def packed(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(",", ":"),allow_nan=False)


def verify_run(folder,expected_calls):
    result=read(folder/"result.json")
    assert result["status"]=="complete" and len(result["calls"])==expected_calls
    total_tokens=0; cost=Decimal(0)
    for i,event in enumerate(result["calls"],1):
        name=f"call-{i}"
        assert event["id"]==name and event["status"]=="ok"
        request=read(folder/(name+".request.json"))
        response=read(folder/(name+".response.json"))
        assert hashlib.sha256(packed(request).encode()).hexdigest()==event["request_hash"]
        assert request["model"]==event["requested_model"]
        assert response["model"]==event["returned_model"]
        assert response.get("provider")==event["provider"]
        usage=event["usage"]
        raw=response["usage"]
        assert usage["cost"]==raw["cost"]
        assert usage["total_tokens"]==usage["input_tokens"]+usage["output_tokens"]
        assert usage["cached_input_tokens"] is None or usage["cached_input_tokens"]<=usage["input_tokens"]
        assert usage["reasoning_tokens"] is None or usage["reasoning_tokens"]<=usage["output_tokens"]
        total_tokens+=usage["total_tokens"]
        cost+=Decimal(str(usage["cost"]))
    assert abs(cost-Decimal(str(result["reported_cost"])))<Decimal("0.00000000001")
    return result,total_tokens,cost


def main():
    manifest=ROOT/"SHA256SUMS.txt"
    expected=set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest,path=line.split("  ",1)
        expected.add(path)
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()
            and p.name not in ("README.md","SHA256SUMS.txt")}
    assert expected==actual
    checked,tokens,cost=verify_run(ROOT/"checked",23)
    roles=Counter(c["role"] for c in checked["calls"])
    assert roles=={"jev":15,"checker":5,"worker":3}
    assert tokens==36663 and cost==Decimal("0.012201078")
    assert len(checked["committed"])==len(checked["checks"])==5
    assert [p["id"] for p in checked["committed"]]==["input","hidden1","hidden2","hidden3","output"]
    assert all(p["checker"]["result"]["verdict"]=="pass" for p in checked["committed"])
    assert all(c["role"]!="checker" or i+1<len(checked["calls"]) and
               checked["calls"][i+1]["role"]=="jev" and checked["calls"][i+1]["status"]=="ok"
               for i,c in enumerate(checked["calls"]))
    assert sum(e["kind"]=="checked_commit" for e in checked["events"])==5
    assert sum(e["kind"]=="post_checker_decision" for e in checked["events"])==5
    assert "50 defects per 1,000" in checked["answer"] and "[records]" in checked["answer"]
    single,one_tokens,one_cost=verify_run(ROOT/"single-sol",1)
    assert one_tokens==431 and one_cost==Decimal("0.001726")
    assert single["model"]=="openai/gpt-6-sol" and single["effort"]=="high"
    assert single["answer"]==50 and all(single["quality_checks"].values())
    assert read(ROOT/"attempts/checked-provider-filtered.json")["status"]=="failed"
    assert read(ROOT/"attempts/checked-jev-stop.json")["status"]=="stopped_before_checker"
    assert read(ROOT/"attempts/baseline-schema-mismatch.json")["status"]=="quality_failed"
    print(json.dumps({"verified":True,"checked_calls":23,"checked_tokens":tokens,
                      "checked_cost_usd":str(cost),"baseline_calls":1,
                      "baseline_tokens":one_tokens,"baseline_cost_usd":str(one_cost)}))


if __name__=="__main__": main()

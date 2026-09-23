"""Verify the saved conditional-review GPT-6 fixture without API access."""
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def packed(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(",",":"),allow_nan=False)


def main():
    paths=set()
    for line in (ROOT/"SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest,relative=line.split("  ",1)
        paths.add(relative)
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()
            and p.name not in ("README.md","SHA256SUMS.txt")}
    assert paths==actual
    result=read(ROOT/"result.json")
    assert result["status"]=="complete" and result["protocol_version"]=="cidm-conditional-review-v3"
    assert len(result["calls"])==13
    roles=Counter(c["role"] for c in result["calls"])
    assert roles=={"jev":10,"worker":3}
    total_tokens=0;cost=Decimal(0)
    for index,event in enumerate(result["calls"]):
        name=f"call-{index+1}"
        assert event["id"]==name and event["status"]=="ok"
        request=read(ROOT/(name+".request.json"))
        response=read(ROOT/(name+".response.json"))
        assert hashlib.sha256(packed(request).encode()).hexdigest()==event["request_hash"]
        assert request["model"]==event["requested_model"]
        assert response["model"]==event["returned_model"]
        assert response.get("provider")==event["provider"]
        usage=event["usage"]
        assert usage["total_tokens"]==usage["input_tokens"]+usage["output_tokens"]
        assert usage["cost"]==response["usage"]["cost"]
        if event["role"]=="worker":
            assert event["followup_jev_required"] is True
            assert index+1<len(result["calls"]) and result["calls"][index+1]["role"]=="jev"
        total_tokens+=usage["total_tokens"]
        cost+=Decimal(str(usage["cost"]))
    assert total_tokens==25510 and cost==Decimal("0.006413654")
    assert abs(cost-Decimal(str(result["reported_cost"])))<Decimal("0.00000000001")
    assert [p["id"] for p in result["committed"]]==["input","hidden1","hidden2","hidden3","output"]
    assert all(p["checker"] is None and p["decision_phase"]=="after_worker" for p in result["committed"])
    assert [p["worker_route"]["id"] for p in result["committed"] if p["worker_route"]]
    assert [p["worker_route"]["id"] for p in result["committed"] if p["worker_route"]]==["sol_low","sol_low","sol_low"]
    assert len(result["checks"])==0
    assert sum(e["kind"]=="post_worker_decision" for e in result["events"])==5
    assert sum(e["kind"]=="post_checker_decision" for e in result["events"])==0
    assert "50 defects per 1,000" in result["answer"] and "[records]" in result["answer"]
    print(json.dumps({"verified":True,"calls":13,"post_worker_jev_decisions":5,
                      "sol_high_checks":0,"tokens":total_tokens,"cost_usd":str(cost)}))


if __name__=="__main__": main()

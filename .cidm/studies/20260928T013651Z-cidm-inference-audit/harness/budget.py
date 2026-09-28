"""Fail-closed study spending guard. Default cap is zero.

Every provider request must reserve its worst-case charge before launch.
Reservations count against the per-request, per-run and study totals while in
flight. A request whose worst case cannot be bounded is refused. When the actual
charge is unknown after a call, the full reservation stays spent.
"""
from __future__ import annotations

import json
import threading
import uuid


class BudgetRefused(RuntimeError):
    pass


def worst_case_usd(price, *, max_input_tokens, max_output_tokens):
    """Upper bound from rates in USD per million tokens. None when unbounded."""
    if price is None or max_input_tokens is None:
        return None
    rate_in = price.get("input")
    rate_out = price.get("output")
    # cache writes can cost more than plain input; take the larger rate for every input token
    rate_in_max = max(r for r in (rate_in, price.get("cache_write")) if r is not None) if rate_in is not None else None
    if rate_in_max is None or rate_out is None:
        return None
    if max_output_tokens is None:
        return None if rate_out > 0 else max_input_tokens * rate_in_max / 1e6
    surcharge = price.get("per_request_usd", 0.0)
    return max_input_tokens * rate_in_max / 1e6 + max_output_tokens * rate_out / 1e6 + surcharge


class StudyBudget:
    def __init__(self, *, total_usd=0.0, per_run_usd=0.0, per_request_usd=0.0,
                 max_concurrency=1, max_retries=0, ledger=None):
        for name, value in (("total_usd", total_usd), ("per_run_usd", per_run_usd),
                            ("per_request_usd", per_request_usd)):
            if type(value) not in (int, float) or value < 0 or value != value:
                raise ValueError("invalid_" + name)
        if type(max_concurrency) is not int or max_concurrency < 1:
            raise ValueError("invalid_max_concurrency")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("invalid_max_retries")
        self.total_usd, self.per_run_usd, self.per_request_usd = float(total_usd), float(per_run_usd), float(per_request_usd)
        self.max_concurrency, self.max_retries = max_concurrency, max_retries
        self.spent_total, self.spent_by_run = 0.0, {}
        self.in_flight = {}
        self.retries_by_request = {}
        self.ledger = ledger
        self._lock = threading.Lock()

    def _log(self, record):
        if self.ledger is not None:
            with open(self.ledger, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")

    def reserve(self, run_id, worst_case, *, logical_request=None, retry=False):
        with self._lock:
            if worst_case is None:
                raise BudgetRefused("unbounded_request_cost")
            if worst_case > self.per_request_usd:
                raise BudgetRefused("per_request_cap")
            if len(self.in_flight) >= self.max_concurrency:
                raise BudgetRefused("concurrency_cap")
            if retry:
                count = self.retries_by_request.get(logical_request, 0)
                if count >= self.max_retries:
                    raise BudgetRefused("retry_cap")
                self.retries_by_request[logical_request] = count + 1
            run_reserved = sum(r["usd"] for r in self.in_flight.values() if r["run_id"] == run_id)
            all_reserved = sum(r["usd"] for r in self.in_flight.values())
            if self.spent_by_run.get(run_id, 0.0) + run_reserved + worst_case > self.per_run_usd:
                raise BudgetRefused("per_run_cap")
            if self.spent_total + all_reserved + worst_case > self.total_usd:
                raise BudgetRefused("study_total_cap")
            token = uuid.uuid4().hex
            self.in_flight[token] = {"run_id": run_id, "usd": worst_case}
            self._log({"event": "reserve", "token": token, "run_id": run_id, "usd": worst_case})
            return token

    def settle(self, token, actual_usd):
        """Record the outcome of a launched request. Unknown actual keeps the reservation."""
        with self._lock:
            reservation = self.in_flight.pop(token)
            known = type(actual_usd) in (int, float) and actual_usd >= 0 and actual_usd == actual_usd
            charged = float(actual_usd) if known else reservation["usd"]
            self.spent_total += charged
            run = reservation["run_id"]
            self.spent_by_run[run] = self.spent_by_run.get(run, 0.0) + charged
            self._log({"event": "settle", "token": token, "run_id": run, "charged": charged,
                       "basis": "provider_reported" if known else "reservation_kept_unknown_actual",
                       "overrun": bool(known and actual_usd > reservation["usd"])})
            return charged

    def release_unsent(self, token):
        """Only for a request that provably never left the process."""
        with self._lock:
            reservation = self.in_flight.pop(token)
            self._log({"event": "release_unsent", "token": token, "run_id": reservation["run_id"]})

    def state(self):
        with self._lock:
            return {"total_cap": self.total_usd, "spent_total": round(self.spent_total, 12),
                    "in_flight": len(self.in_flight), "spent_by_run": dict(self.spent_by_run)}

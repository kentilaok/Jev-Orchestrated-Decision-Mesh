"""Validated, secret-free settings for the built-in OpenRouter adapter.

Concept, architecture, and methodology: Kenneth Vic A. Caber.
Price ceilings are configurable reservation assumptions, not an invoice guarantee.
The defaults are model-family list rates from the official model documentation
as checked on 2026-09-23; cached-input discounts are not assumed at admission.
"""
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
import re


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _number(value, *, positive=False):
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and (value > 0 if positive else value >= 0))
    except OverflowError:
        return False


@dataclass(frozen=True)
class RunConfig:
    worker_model: str = "openai/gpt-6-sol"
    worker_effort: str = "medium"
    checker_model: str = "openai/gpt-6-sol"
    checker_effort: str = "high"
    astra_explicitly_authorized: bool = False
    jev_model: str = "typesafe/jev-1.13"
    provider_route: str = "azure"
    provider_name: str = "Azure"
    jev_provider_name: str = "TypeSafe"
    worker_model_aliases: tuple = ()
    checker_model_aliases: tuple = ()
    jev_model_aliases: tuple = ("typesafe/jev-1.13-20260917",)
    max_usd: float = 1.50
    max_calls: int = 40
    max_output_tokens: int = 2000
    timeout: float = 45
    worker_luna_input_usd_per_million: float = 0.10
    worker_luna_output_usd_per_million: float = 0.50
    # The existing worker price fields are the Sol ceilings. Keep their names
    # so earlier Sol configurations continue to load unchanged.
    worker_input_usd_per_million: float = 2.0
    worker_output_usd_per_million: float = 10.0
    worker_astra_input_usd_per_million: float = 10.0
    worker_astra_output_usd_per_million: float = 50.0
    checker_input_usd_per_million: float = 2.0
    checker_output_usd_per_million: float = 10.0
    jev_input_usd_per_million: float = 0.05
    jev_output_usd_per_million: float = 0.05

    def __post_init__(self):
        _require(type(self.astra_explicitly_authorized) is bool, "astra_authorization_must_be_boolean")
        allowed = {"openai/gpt-6-luna", "openai/gpt-6-sol"}
        if self.astra_explicitly_authorized:
            allowed.add("openai/gpt-6-astra")
        _require(self.worker_model in allowed, "worker_model_not_permitted")
        _require(self.checker_model == "openai/gpt-6-sol", "checker_must_be_gpt_6_sol")
        _require(self.worker_effort in ("low", "medium", "high", "xhigh"), "invalid_worker_effort")
        _require(self.worker_model != "openai/gpt-6-astra" or self.worker_effort == "low", "astra_worker_low_only")
        _require(self.checker_effort == "high", "checker_effort_must_be_high")
        _require(isinstance(self.jev_model, str) and re.fullmatch(r"typesafe/jev-[A-Za-z0-9._-]+", self.jev_model)
                 and self.jev_model != "typesafe/jev-latest", "explicit_jev_version_required")
        for role in ("worker", "checker", "jev"):
            name = role + "_model_aliases"
            aliases = getattr(self, name)
            _require(type(aliases) in (tuple, list) and all(isinstance(a, str) for a in aliases),
                     "invalid_" + name)
            model = getattr(self, role + "_model")
            _require(len(aliases) <= 8 and len(set(aliases)) == len(aliases), "invalid_" + name)
            _require(all(a.startswith((model + "-", model + ".")) and re.fullmatch(r"[A-Za-z0-9/._-]+", a)
                         and len(a) <= 180 for a in aliases), "aliases_must_be_explicit_model_versions")
            object.__setattr__(self, name, tuple(aliases))
        _require(isinstance(self.provider_route, str) and re.fullmatch(r"[a-z0-9][a-z0-9/_-]{0,79}", self.provider_route),
                 "invalid_provider_route")
        for name in ("provider_name", "jev_provider_name"):
            value = getattr(self, name)
            _require(isinstance(value, str) and 0 < len(value.strip()) <= 80
                     and value == value.strip() and not any(ord(c) < 32 for c in value), "invalid_" + name)
        _require(_number(self.max_usd, positive=True), "invalid_max_usd")
        _require(type(self.max_calls) is int and 1 <= self.max_calls <= 1000, "invalid_max_calls")
        _require(type(self.max_output_tokens) is int and 1 <= self.max_output_tokens <= 32768,
                 "invalid_max_output_tokens")
        _require(_number(self.timeout, positive=True) and self.timeout <= 120, "invalid_timeout")
        for role in ("worker", "checker", "jev"):
            for direction in ("input", "output"):
                name = role + "_" + direction + "_usd_per_million"
                _require(_number(getattr(self, name), positive=True), "invalid_" + name)
        for family, minimum_input, minimum_output in (("luna", 0.10, 0.50), ("astra", 10, 50)):
            for direction, minimum in (("input", minimum_input), ("output", minimum_output)):
                name = "worker_" + family + "_" + direction + "_usd_per_million"
                _require(_number(getattr(self, name), positive=True), "invalid_" + name)
                _require(getattr(self, name) >= minimum, "worker_price_reservation_below_allowed_model")
        _require(self.worker_input_usd_per_million >= 2 and self.worker_output_usd_per_million >= 10,
                 "worker_price_reservation_below_allowed_model")
        _require(self.checker_input_usd_per_million >= 2 and self.checker_output_usd_per_million >= 10,
                 "checker_price_reservation_below_allowed_model")

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict, "configuration_must_be_object")
        allowed = {field.name for field in fields(cls)}
        _require(all(type(k) is str for k in value) and set(value) <= allowed, "unknown_configuration_fields")
        return cls(**value)

    def to_dict(self):
        snapshot = asdict(self)
        for role in ("worker", "checker", "jev"):
            snapshot[role + "_model_aliases"] = list(snapshot[role + "_model_aliases"])
        return snapshot

    @property
    def policy_hash(self):
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    def worker_routes(self):
        routes = tuple({"id": family + "_" + effort, "model": "openai/gpt-6-" + family,
                        "effort": effort} for family in ("luna", "sol")
                       for effort in ("low", "medium", "high", "xhigh"))
        return routes + (({"id": "astra_low", "model": "openai/gpt-6-astra", "effort": "low"},)
                         if self.astra_explicitly_authorized else ())

    def worker_route_allowed(self, model, effort):
        return any(route["model"] == model and route["effort"] == effort for route in self.worker_routes())

    def response_models(self, role, requested_model=None):
        _require(role in ("worker", "checker", "jev"), "invalid_role")
        if role == "worker" and requested_model is not None and requested_model != self.worker_model:
            _require(any(route["model"] == requested_model for route in self.worker_routes()),
                     "worker_model_not_permitted")
            return (requested_model,)
        return (getattr(self, role + "_model"),) + getattr(self, role + "_model_aliases")

    def reserve_usd(self, role, request_bytes, model=None):
        """Conservative byte-based reservation; actual reported charges remain authoritative.

        For Jev this output allowance is a reservation, not an API output-token cap.
        A worker uses the actual selected model's ceilings, regardless of the
        configured default worker. No cached-input discount is assumed. These
        ceilings cannot guarantee an upstream service's final invoice.
        """
        _require(role in ("worker", "checker", "jev"), "invalid_role")
        _require(type(request_bytes) is int and request_bytes >= 0, "invalid_request_size")
        if role == "worker":
            selected = self.worker_model if model is None else model
            _require(any(route["model"] == selected for route in self.worker_routes()),
                     "worker_model_not_permitted")
            family = selected.removeprefix("openai/gpt-6-")
            prefix = "worker_" + family + "_" if family != "sol" else "worker_"
        else:
            _require(model is None or model == getattr(self, role + "_model"), "reservation_model_mismatch")
            prefix = role + "_"
        return (request_bytes * getattr(self, prefix + "input_usd_per_million")
                + self.max_output_tokens * getattr(self, prefix + "output_usd_per_million")) / 1_000_000

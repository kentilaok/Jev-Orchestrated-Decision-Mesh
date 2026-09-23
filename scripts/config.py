"""Validated, secret-free settings for the built-in OpenRouter adapter.

Concept, architecture, and methodology: Kenneth Vic A. Caber.
Price ceilings are user-supplied reservation assumptions, not a price catalog.
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
    worker_model: str = "openai/gpt-5.6-sol"
    worker_effort: str = "medium"
    checker_model: str = "openai/gpt-5.6-sol"
    checker_effort: str = "high"
    jev_model: str = "typesafe/jev-1.13"
    provider_route: str = "azure/us"
    provider_name: str = "Azure"
    jev_provider_name: str = "TypeSafe"
    worker_model_aliases: tuple = ()
    checker_model_aliases: tuple = ()
    jev_model_aliases: tuple = ("typesafe/jev-1.13-20260917",)
    max_usd: float = 1.50
    max_calls: int = 40
    max_output_tokens: int = 2000
    timeout: float = 45
    worker_input_usd_per_million: float = 6.0
    worker_output_usd_per_million: float = 36.0
    checker_input_usd_per_million: float = 6.0
    checker_output_usd_per_million: float = 36.0
    jev_input_usd_per_million: float = 0.05
    jev_output_usd_per_million: float = 0.05

    def __post_init__(self):
        for role in ("worker", "checker"):
            model = getattr(self, role + "_model")
            _require(isinstance(model, str) and re.fullmatch(r"openai/[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model),
                     role + "_requires_explicit_openai_model")
        _require(self.worker_effort in ("low", "medium", "high", "xhigh"), "invalid_worker_effort")
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

    def response_models(self, role):
        _require(role in ("worker", "checker", "jev"), "invalid_role")
        return (getattr(self, role + "_model"),) + getattr(self, role + "_model_aliases")

    def reserve_usd(self, role, request_bytes):
        """Conservative byte-based reservation; actual reported charges remain authoritative.

        For Jev this output allowance is a reservation, not an API output-token cap.
        Configured ceilings cannot guarantee an upstream service's final invoice.
        """
        _require(role in ("worker", "checker", "jev"), "invalid_role")
        _require(type(request_bytes) is int and request_bytes >= 0, "invalid_request_size")
        return (request_bytes * getattr(self, role + "_input_usd_per_million")
                + self.max_output_tokens * getattr(self, role + "_output_usd_per_million")) / 1_000_000

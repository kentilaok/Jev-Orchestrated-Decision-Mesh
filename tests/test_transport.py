import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
"""Offline transport/configuration checks. All inference is mocked; no API calls."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from atomic_mesh import MeshError, packed
from config import RunConfig
from transport import CHECK_SCHEMA, Gateway, MAX_REQUEST_BYTES


def chat_response(config=None, role="worker", content=None, cost=0.0001):
    config = config or RunConfig()
    return {
        "model": getattr(config, role + "_model"), "provider": config.provider_name,
        "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16, "cost": cost,
                  "prompt_tokens_details": {"cached_tokens": 4},
                  "completion_tokens_details": {"reasoning_tokens": 2}},
        "choices": [{"finish_reason": "stop", "message": {"content": content if content is not None else '{"value": 1}'}}],
    }


def decision_response():
    return {
        "model": "typesafe/jev-1.13-20260917", "provider": "TypeSafe",
        "usage": {"input_tokens": 10, "output_tokens": 6, "total_tokens": 16, "cost": 0.00001},
        "answers": {"next": {"type": "choice", "choice": "compute", "confidence": 1.0,
                             "probabilities": {"compute": 1.0, "stop": 0.0}}},
    }


def checker_payload(config):
    return {
        "model": config.checker_model,
        "messages": [{"role": "user", "content": "Check this bounded candidate."}],
        "reasoning": {"effort": "high", "exclude": True},
        "max_completion_tokens": config.max_output_tokens,
        "provider": {"only": [config.provider_route], "allow_fallbacks": False, "require_parameters": True},
        "response_format": {"type": "json_schema", "json_schema": {"name": "gate_result", "strict": True, "schema": CHECK_SCHEMA}},
    }


class ConfigTests(unittest.TestCase):
    def test_secret_free_roundtrip_and_frozen_snapshot(self):
        config = RunConfig()
        self.assertEqual(config, RunConfig.from_dict(config.to_dict()))
        self.assertEqual(len(config.policy_hash), 64)
        self.assertEqual(config.policy_hash, RunConfig.from_dict(config.to_dict()).policy_hash)
        self.assertNotEqual(config.policy_hash, RunConfig(worker_effort="low").policy_hash)
        self.assertFalse(any("key" in name or "secret" in name for name in config.to_dict()))
        with self.assertRaises(FrozenInstanceError):
            config.worker_effort = "low"
        aliases = ["openai/gpt-6-sol-20260922"]
        config = RunConfig.from_dict({"worker_model_aliases": aliases})
        aliases.append("changed")
        self.assertEqual(config.worker_model_aliases, ("openai/gpt-6-sol-20260922",))

    def test_worker_catalog_is_luna_and_sol_low_through_xhigh_only(self):
        config=RunConfig()
        self.assertEqual(len(config.worker_routes()),8)
        self.assertEqual({r['model'] for r in config.worker_routes()},
                         {'openai/gpt-6-luna','openai/gpt-6-sol'})
        self.assertEqual({r['effort'] for r in config.worker_routes()},
                         {'low','medium','high','xhigh'})
        self.assertEqual((config.checker_model,config.checker_effort),('openai/gpt-6-sol','high'))
        self.assertFalse(config.astra_explicitly_authorized)

    def test_reject_invalid_config_and_unknown_fields(self):
        cases = [
            {"worker_model": "other/model"}, {"checker_model": "other/model"},
            {"worker_model": "openai/gpt-5.6-sol"},
            {"worker_model": "openai/gpt-5.6-luna"},
            {"worker_model": "openai/gpt-5.6-terra"},
            {"worker_model": "openai/gpt-6-astra"},
            {"checker_model": "openai/gpt-6-luna"},
            {"worker_effort": "max"},
            {"astra_explicitly_authorized": "true"},
            {"astra_explicitly_authorized": True, "worker_model": "openai/gpt-6-astra",
             "worker_effort": "high"},
            {"checker_effort": "medium"}, {"worker_effort": "unsupported"},
            {"max_calls": True}, {"max_calls": 0}, {"max_usd": float("nan")},
            {"max_jev_calls": -1}, {"max_jev_calls": 1001},
            {"max_jev_tokens": 0}, {"max_jev_tokens": True},
            {"max_worker_calls": 1001}, {"max_checker_calls": -1},
            {"max_usd": float("inf")}, {"max_usd": 10 ** 1000},
            {"timeout": 0}, {"max_output_tokens": 0}, {"provider_route": "https://example.invalid"},
            {"api_key": "placeholder"}, {"base_url": "https://example.invalid"},
            {"worker_input_usd_per_million": -1},
            {"worker_luna_input_usd_per_million": 0.09},
            {"worker_luna_output_usd_per_million": 0.49},
            {"worker_astra_input_usd_per_million": 9.99},
            {"worker_astra_output_usd_per_million": 49.99},
            {"jev_model": "typesafe/jev-latest"},
            {"worker_model_aliases": ["openai/unrelated-model"]},
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                RunConfig.from_dict(value)

    def test_every_role_reserves_input_and_output(self):
        config = RunConfig()
        for role in ("worker", "checker", "jev"):
            self.assertGreater(config.reserve_usd(role, 100), config.reserve_usd(role, 0))
            self.assertGreater(config.reserve_usd(role, 0), 0)

    def test_worker_reservation_uses_selected_family_and_full_input(self):
        config = RunConfig(max_output_tokens=2000)
        request_bytes = 1000
        luna = config.reserve_usd("worker", request_bytes, "openai/gpt-6-luna")
        sol = config.reserve_usd("worker", request_bytes, "openai/gpt-6-sol")
        self.assertAlmostEqual(luna, (1000 * 0.10 + 2000 * 0.50) / 1_000_000)
        self.assertAlmostEqual(sol, (1000 * 2 + 2000 * 10) / 1_000_000)
        self.assertLess(luna, sol)
        # The admission estimate has no cache information, so all request
        # bytes receive the selected model's full input ceiling.
        self.assertAlmostEqual(config.reserve_usd("worker", 2000, "openai/gpt-6-luna") - luna,
                               1000 * 0.10 / 1_000_000)
        with self.assertRaisesRegex(ValueError, "worker_model_not_permitted"):
            config.reserve_usd("worker", request_bytes, "openai/gpt-6-astra")

    def test_custom_family_ceilings_and_explicit_astra(self):
        config = RunConfig(astra_explicitly_authorized=True,
                           worker_luna_input_usd_per_million=0.20,
                           worker_luna_output_usd_per_million=1.0,
                           worker_input_usd_per_million=3.0,
                           worker_output_usd_per_million=12.0,
                           worker_astra_input_usd_per_million=11.0,
                           worker_astra_output_usd_per_million=55.0,
                           max_output_tokens=1000)
        for family, inp, out in (("luna", 0.20, 1.0), ("sol", 3.0, 12.0),
                                 ("astra", 11.0, 55.0)):
            with self.subTest(family=family):
                self.assertAlmostEqual(config.reserve_usd("worker", 500, "openai/gpt-6-" + family),
                                       (500 * inp + 1000 * out) / 1_000_000)
        self.assertEqual([route["id"] for route in config.worker_routes() if "astra" in route["id"]],
                         ["astra_low"])


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.secret = "sk-test-placeholder-do-not-log"
        self.env = patch.dict("os.environ", {"OPENROUTER_API_KEY": self.secret})
        self.env.start()
        self.addCleanup(self.env.stop)

    def gateway(self, config=None):
        return Gateway(self.folder, config or RunConfig())

    def stored_text(self):
        return "\n".join(path.read_text(encoding="utf-8") for path in self.folder.iterdir() if path.is_file())

    def test_checker_is_high_with_structured_schema(self):
        gateway = self.gateway(RunConfig(worker_effort="low"))
        with patch.object(gateway, "_request", return_value=chat_response(role="checker")) as request:
            gateway.high_check({"unit": {"id": "input"}})
        role, payload, _ = request.call_args.args
        self.assertEqual(role, "checker")
        self.assertEqual(payload["reasoning"]["effort"], "high")
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], CHECK_SCHEMA)
        self.assertFalse(payload["provider"]["allow_fallbacks"])
        self.assertEqual(payload["provider"]["only"], ["azure"])

    def test_model_provider_and_effort_are_configurable(self):
        config = RunConfig(worker_model="openai/gpt-6-luna",worker_effort="xhigh",
                           provider_route="openai", provider_name="OpenAI")
        gateway = self.gateway(config)
        with patch.object(gateway, "_request", return_value=chat_response(config)) as request:
            self.assertEqual(gateway.ask("worker", "Bounded task", {"value": 1}), {"value": 1})
        payload = request.call_args.args[1]
        self.assertEqual(payload["model"], config.worker_model)
        self.assertEqual(payload["reasoning"]["effort"], "xhigh")
        self.assertEqual(payload["provider"]["only"], ["openai"])
        self.assertEqual(gateway.calls[0]["provider"], "OpenAI")

    def test_jev_selected_luna_and_sol_routes_reach_exact_model_and_effort(self):
        gateway=self.gateway()
        for route_id in ('luna_low','luna_xhigh','sol_low','sol_xhigh'):
            route=next(r for r in gateway.config.worker_routes() if r['id']==route_id)
            response=chat_response(gateway.config,role='worker')
            response['model']=route['model']
            with patch.object(gateway,'_request',return_value=response) as request:
                gateway.ask('worker','Task',{'value':1},worker_route=route)
            payload=request.call_args.args[1]
            self.assertEqual((payload['model'],payload['reasoning']['effort']),
                             (route['model'],route['effort']))
            self.assertAlmostEqual(gateway.calls[-1]['reserved_usd'],
                                   gateway.config.reserve_usd('worker', len(packed(payload).encode()),
                                                              route['model']))
        self.assertEqual(len(gateway.calls),4)

    def test_luna_call_admitted_when_same_budget_rejects_sol(self):
        config = RunConfig(max_usd=0.005)
        gateway = self.gateway(config)
        luna = next(route for route in config.worker_routes() if route['id'] == 'luna_low')
        sol = next(route for route in config.worker_routes() if route['id'] == 'sol_low')
        luna_response = chat_response(config)
        luna_response['model'] = luna['model']
        with patch.object(gateway, '_request', return_value=luna_response) as request:
            gateway.ask('worker', 'Task', {'value': 1}, worker_route=luna)
            with self.assertRaisesRegex(MeshError, 'call_or_cost_budget_exhausted'):
                gateway.ask('worker', 'Task', {'value': 1}, worker_route=sol)
        request.assert_called_once()
        self.assertEqual(gateway.calls[0]['requested_model'], luna['model'])
        self.assertLess(gateway.calls[0]['reserved_usd'], config.max_usd)
        self.assertLess(gateway.spent, config.max_usd)

    def test_luna_actual_charge_above_family_ceiling_blocks(self):
        gateway = self.gateway()
        luna = next(route for route in gateway.config.worker_routes() if route['id'] == 'luna_low')
        response = chat_response(role='worker', cost=0.005)
        response['model'] = luna['model']
        with patch.object(gateway, '_request', return_value=response), self.assertRaises(MeshError):
            gateway.ask('worker', 'Task', {'value': 1}, worker_route=luna)
        self.assertEqual(gateway.spent, 0.005)
        self.assertEqual(gateway.calls[0]['error']['code'], 'price_ceiling_exceeded')
        self.assertTrue(gateway.blocked)

    def test_unlisted_worker_route_is_rejected_before_dispatch(self):
        gateway=self.gateway()
        routes=[{'id':'astra_low','model':'openai/gpt-6-astra','effort':'low'},
                {'id':'terra_low','model':'openai/gpt-5.6-terra','effort':'low'},
                {'id':'luna_max','model':'openai/gpt-6-luna','effort':'max'}]
        with patch.object(gateway,'_request') as request:
            for route in routes:
                with self.assertRaisesRegex(MeshError,'worker_route_not_permitted'):
                    gateway.ask('worker','Task',{'value':1},worker_route=route)
        request.assert_not_called()

    def test_cache_and_reasoning_are_not_added_twice(self):
        gateway = self.gateway()
        with patch.object(gateway, "_request", return_value=chat_response()):
            gateway.ask("worker", "Task", {"value": 1})
        usage = gateway.calls[0]["usage"]
        self.assertEqual((usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]), (10, 6, 16))
        self.assertEqual((usage["cached_input_tokens"], usage["reasoning_tokens"]), (4, 2))
        self.assertEqual(gateway.spent, 0.0001)

    def test_default_jev_snapshot_is_explicitly_accepted(self):
        gateway = self.gateway()
        with patch.object(gateway, "_request", return_value=decision_response()) as request:
            result = gateway.network_judge("authorize_unit", {"compute": "Compute", "stop": "Stop"}, {"unit": "input"})
        self.assertEqual(result["choice"], "compute")
        self.assertTrue(result["live"])
        self.assertEqual(request.call_args.args[1]["model"], "typesafe/jev-1.13")
        self.assertGreater(gateway.calls[0]["reserved_usd"], 0)

    def test_no_parameter_activation_phase(self):
        gateway = self.gateway()
        with patch.object(gateway, "_request") as request, self.assertRaises(MeshError):
            gateway.network_judge("authorize_parameter_check", {"check": "Check", "stop": "Stop"}, {"unit": "input"})
        request.assert_not_called()

    def test_unlisted_model_is_rejected_and_cost_preserved(self):
        gateway = self.gateway()
        response = chat_response()
        response["model"] = "openai/unexpected-model"
        with patch.object(gateway, "_request", return_value=response), self.assertRaises(MeshError):
            gateway.ask("worker", "Task", {"value": 1})
        self.assertEqual(gateway.calls[0]["error"]["code"], "response_model_mismatch")
        self.assertEqual(gateway.spent, 0.0001)
        self.assertTrue(gateway.blocked)

    def test_explicit_model_alias_accepted(self):
        config = RunConfig(worker_model_aliases=("openai/gpt-6-sol-20260922",))
        gateway = self.gateway(config)
        response = chat_response(config)
        response["model"] = config.worker_model_aliases[0]
        with patch.object(gateway, "_request", return_value=response):
            gateway.ask("worker", "Task", {"value": 1})
        self.assertEqual(gateway.calls[0]["status"], "ok")

    def test_unexpected_provider_is_rejected(self):
        gateway = self.gateway()
        response = chat_response()
        response["provider"] = "UnexpectedProvider"
        with patch.object(gateway, "_request", return_value=response), self.assertRaises(MeshError):
            gateway.ask("worker", "Task", {"value": 1})
        self.assertEqual(gateway.calls[0]["error"]["code"], "response_provider_mismatch")

    def test_unknown_usage_remains_null_and_blocks_more_calls(self):
        gateway = self.gateway()
        response = chat_response()
        del response["usage"]
        with patch.object(gateway, "_request", return_value=response) as request:
            with self.assertRaises(MeshError):
                gateway.ask("worker", "Task", {"value": 1})
            with self.assertRaises(MeshError):
                gateway.ask("worker", "Task", {"value": 1})
        self.assertEqual(request.call_count, 1)
        for key in ("input_tokens", "output_tokens", "total_tokens", "cost"):
            self.assertIsNone(gateway.calls[0]["usage"][key])
        self.assertTrue(gateway.blocked)

    def test_missing_cost_stops_with_known_tokens_preserved(self):
        gateway = self.gateway()
        response = chat_response()
        del response["usage"]["cost"]
        with patch.object(gateway, "_request", return_value=response), self.assertRaises(MeshError):
            gateway.ask("worker", "Task", {"value": 1})
        self.assertEqual(gateway.calls[0]["usage"]["input_tokens"], 10)
        self.assertIsNone(gateway.calls[0]["usage"]["cost"])
        self.assertEqual(gateway.calls[0]["error"]["code"], "missing_cost")

    def test_malformed_reported_total_is_not_silently_repaired(self):
        gateway = self.gateway()
        response = chat_response()
        response["usage"]["total_tokens"] = "bad"
        with patch.object(gateway, "_request", return_value=response), self.assertRaises(MeshError):
            gateway.ask("worker", "Task", {"value": 1})
        self.assertEqual(gateway.calls[0]["error"]["code"], "invalid_token_usage")

    def test_http_200_error_code_preserved_without_message_or_credential(self):
        gateway = self.gateway()
        response = {"error": {"code": 502, "message": "private details " + self.secret,
                               "metadata": {"authorization": self.secret}},
                    "usage": {"prompt_tokens": 2, "completion_tokens": 0, "cost": 0.00001}}
        with patch.object(gateway, "_request", return_value=response), self.assertRaises(MeshError):
            gateway.ask("worker", "Task", {"value": 1})
        self.assertEqual(gateway.calls[0]["error"], {"code": "upstream_error", "upstream_code": 502, "http_status": 200})
        self.assertEqual(gateway.spent, 0.00001)
        self.assertNotIn(self.secret, self.stored_text())
        self.assertNotIn("private details", self.stored_text())

    def test_http_error_has_no_retry_or_credential_leak(self):
        gateway = self.gateway()
        error = urllib.error.HTTPError("https://openrouter.ai/", 429, self.secret, {}, None)
        with patch.object(gateway, "_request", side_effect=error) as request, self.assertRaises(MeshError):
            gateway.ask("worker", "Task", {"value": 1})
        self.assertEqual(request.call_count, 1)
        self.assertEqual(gateway.calls[0]["error"], {"code": "http_error", "http_status": 429})
        self.assertIsNone(gateway.calls[0]["usage"]["cost"])
        self.assertNotIn(self.secret, self.stored_text())

    def test_checker_invalid_json_returns_bounded_redacted_envelope(self):
        gateway = self.gateway()
        response = chat_response(role="checker", content="x" * 1190 + self.secret + "x" * 2000)
        with patch.object(gateway, "_request", return_value=response):
            result = gateway.high_check({"unit": {"id": "input"}})
        self.assertEqual(result["contract_error"], "invalid_json")
        self.assertNotIn("verdict", result)
        self.assertLessEqual(len(result["invalid_json_output_preview"]), 1200)
        self.assertNotIn("sk-test-", result["invalid_json_output_preview"])
        self.assertNotIn(self.secret, json.dumps(result) + self.stored_text())
        self.assertTrue((self.folder / "output-validation.jsonl").exists())

    def test_duplicate_checker_json_is_invalid(self):
        gateway = self.gateway()
        response = chat_response(role="checker", content='{"verdict":"pass","verdict":"reject"}')
        with patch.object(gateway, "_request", return_value=response):
            result = gateway.high_check({"unit": {"id": "input"}})
        self.assertEqual(result["contract_error"], "invalid_json")

    def test_configuration_replacement_prevents_dispatch(self):
        gateway = self.gateway()
        gateway.config = RunConfig(worker_effort="low")
        with patch.object(gateway, "_request") as request, self.assertRaises(MeshError):
            gateway.ask("worker", "Task", {"value": 1})
        request.assert_not_called()

    def test_direct_call_cannot_lower_checker_effort(self):
        gateway = self.gateway()
        with patch.object(gateway, "_request") as request, self.assertRaises(MeshError):
            gateway.call("checker", {"model": gateway.config.checker_model, "reasoning": {"effort": "low"}})
        request.assert_not_called()

    def test_budget_reservation_applies_to_jev_before_dispatch(self):
        gateway = self.gateway(RunConfig(max_usd=0.000000001))
        with patch.object(gateway, "_request") as request, self.assertRaises(MeshError):
            gateway.network_judge("authorize_unit", {"compute": "Compute", "stop": "Stop"}, {"unit": "input"})
        request.assert_not_called()

    def test_actual_charge_above_reserve_is_recorded_and_stops(self):
        gateway = self.gateway()
        with patch.object(gateway, "_request", return_value=chat_response(cost=2.0)), self.assertRaises(MeshError):
            gateway.ask("worker", "Task", {"value": 1})
        self.assertEqual(gateway.spent, 2.0)
        self.assertEqual(gateway.calls[0]["error"]["code"], "price_ceiling_exceeded")
        self.assertTrue(gateway.blocked)

    def test_checker_cannot_take_last_call_slot_needed_by_jev(self):
        gateway = self.gateway(RunConfig(max_calls=2))
        with patch.object(gateway, "_request", return_value=chat_response()) as request:
            gateway.ask("worker", "Task", {"value": 1})
            with self.assertRaisesRegex(MeshError, "call_or_cost_budget_exhausted"):
                gateway.high_check({"unit": {"id": "input"}})
        self.assertEqual(request.call_count, 1)
        self.assertEqual([event["role"] for event in gateway.calls], ["worker"])

    def test_jev_call_budget_blocks_another_decision_before_dispatch(self):
        gateway=self.gateway(RunConfig(max_jev_calls=1))
        opts={"compute":"Compute","stop":"Stop"}
        with patch.object(gateway,"_request",return_value=decision_response()) as request:
            gateway.network_judge("authorize_unit",opts,{"unit":"input"})
            with self.assertRaisesRegex(MeshError,"role_call_budget_exhausted"):
                gateway.network_judge("authorize_unit",opts,{"unit":"input"})
        self.assertEqual(request.call_count,1)

    def test_jev_token_budget_blocks_using_an_over_budget_decision(self):
        gateway=self.gateway(RunConfig(max_jev_tokens=15))
        with patch.object(gateway,"_request",return_value=decision_response()) as request:
            with self.assertRaisesRegex(MeshError,"provider_call_failed"):
                gateway.network_judge("authorize_unit",{"compute":"Compute","stop":"Stop"},
                                      {"unit":"input"})
        self.assertEqual(request.call_count,1)
        self.assertEqual(gateway.calls[0]['error']['code'],'jev_token_budget_exceeded')
        self.assertEqual(gateway.calls[0]['usage']['total_tokens'],16)
        self.assertTrue(gateway.blocked)

    def test_worker_and_checker_role_caps_are_independent(self):
        gateway=self.gateway(RunConfig(max_worker_calls=1,max_checker_calls=0))
        with patch.object(gateway,"_request",return_value=chat_response()) as request:
            gateway.ask("worker","Task",{"value":1})
            with self.assertRaisesRegex(MeshError,"role_call_budget_exhausted"):
                gateway.ask("worker","Task",{"value":2})
            with self.assertRaisesRegex(MeshError,"role_call_budget_exhausted"):
                gateway.high_check({"unit":{"id":"input"}})
        self.assertEqual(request.call_count,1)

    def test_cidm_worker_cannot_consume_the_followup_jev_slot(self):
        gateway = self.gateway(RunConfig(max_calls=1))
        route=next(r for r in gateway.config.worker_routes() if r['id']=='luna_low')
        with patch.object(gateway, "_request") as request:
            with self.assertRaisesRegex(MeshError,"call_or_cost_budget_exhausted"):
                gateway.ask("worker","Bounded unit",{"value":1},worker_route=route,followup_required=True)
        request.assert_not_called()
        self.assertEqual(gateway.calls,[])

    def test_direct_baseline_worker_needs_no_jev_followup_slot(self):
        gateway = self.gateway(RunConfig(max_calls=1))
        with patch.object(gateway, "_request", return_value=chat_response()) as request:
            gateway.ask("worker","Direct baseline",{"value":1})
        self.assertEqual(request.call_count,1)
        self.assertEqual(gateway.calls[0]["followup_jev_required"],False)

    def test_checker_requires_cost_headroom_for_maximum_jev_request(self):
        default = RunConfig()
        payload = checker_payload(default)
        checker_reserve = default.reserve_usd("checker", len(packed(payload).encode()))
        jev_reserve = default.reserve_usd("jev", MAX_REQUEST_BYTES)
        config = RunConfig(max_usd=checker_reserve + jev_reserve / 2)
        gateway = self.gateway(config)
        self.assertLess(checker_reserve, config.max_usd, "The checker alone fits this budget")
        with patch.object(gateway, "_request") as request:
            with self.assertRaisesRegex(MeshError, "call_or_cost_budget_exhausted"):
                gateway.call("checker", payload)
        request.assert_not_called()
        self.assertEqual(gateway.calls, [])
        self.assertEqual(gateway.spent, 0)

    def test_checker_and_maximum_followup_jev_fit_exact_budget_boundary(self):
        default = RunConfig()
        payload = checker_payload(default)
        checker_reserve = default.reserve_usd("checker", len(packed(payload).encode()))
        jev_reserve = default.reserve_usd("jev", MAX_REQUEST_BYTES)
        config = RunConfig(max_calls=2, max_usd=checker_reserve + jev_reserve)
        gateway = self.gateway(config)
        following = {"model": config.jev_model, "state": {"padding": ""},
                     "questions": {"next": {"type": "choice", "instructions": "Choose after this checker return.",
                                            "criteria": {"forward": "Forward", "stop": "Stop"}}}}
        following["state"]["padding"] = "x" * (MAX_REQUEST_BYTES - len(packed(following).encode()))
        self.assertEqual(len(packed(following).encode()), MAX_REQUEST_BYTES)
        checker_result = chat_response(config, role="checker", cost=checker_reserve)
        jev_result = decision_response()
        jev_result["usage"]["cost"] = jev_reserve
        jev_result["answers"]["next"].update(choice="forward", probabilities={"forward": 1.0, "stop": 0.0})
        with patch.object(gateway, "_request", side_effect=[checker_result, jev_result]) as request:
            gateway.call("checker", payload)
            response, _ = gateway.call("jev", following)
            with self.assertRaisesRegex(MeshError, "call_or_cost_budget_exhausted"):
                gateway.call("jev", following)
        self.assertEqual(response["answers"]["next"]["choice"], "forward")
        self.assertEqual(request.call_count, 2)
        self.assertEqual([event["role"] for event in gateway.calls], ["checker", "jev"])
        self.assertTrue(all(event["status"] == "ok" for event in gateway.calls))
        self.assertEqual(gateway.calls[0]["reserved_usd"], checker_reserve)
        self.assertEqual(gateway.calls[0]["followup_jev_reserved_usd"], jev_reserve)
        self.assertEqual(gateway.spent, config.max_usd)
        self.assertTrue(gateway.blocked)


if __name__ == "__main__":
    unittest.main()

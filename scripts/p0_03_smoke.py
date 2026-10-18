"""Capped P0-03 live smoke runner: Jev via OpenRouter, worker via Claude CLI (slice 3b).

    python scripts/p0_03_smoke.py --dry-run                        # preflight + command, no calls
    python scripts/p0_03_smoke.py --live                           # one capped run, then the audit
    python scripts/p0_03_smoke.py --live --negative low-budget     # must stop before a paid call

Every run is capped at SMOKE_CEILING_USD on both sides: RunConfig.max_usd for
Jev and max_cumulative_usd on the Claude permit ledger. The preflight never
calls a model and refuses before any launch when a check fails.

Negative runs must stop before any paid call:
- provider-unavailable: the Claude CLI path does not exist, so the preflight refuses;
- wrong-model: a Jev model other than the pinned one, so the preflight refuses;
- low-budget: max_usd below one Jev reservation, so the broker launches and the
  gateway refuses the first Jev call at admission (no HTTP request is made).

Each launched run writes `<out-root>/<UTC stamp>-<mode>/` with `config.json`,
`broker/` (the broker --out folder), the broker's stdout/stderr and
`smoke-report.json` (preflight, command, result status, offline audit).
Claude Code session variables (CLAUDECODE, CLAUDE_CODE_*, and ANTHROPIC_BASE_URL
when inherited from a session) are removed before the preflight and the broker;
their names are listed in the report.
Exit 0 when the run met its expectation, 1 when it did not, 2 when refused.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from capability_permits import PermitAuthority
from config import RunConfig
from frontier_providers import ClaudeCodeProvider
from native_transition_broker import validate_spec
from p0_03_audit import audit_run

ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / 'scripts' / 'native_transition_broker.py'
SMOKE_CEILING_USD = 1.0
PINNED_JEV_MODEL = RunConfig().jev_model
WRONG_JEV_MODEL = 'typesafe/jev-0.0-wrong'
LOW_BUDGET_USD = 1e-6
NEGATIVES = ('low-budget', 'wrong-model', 'provider-unavailable')
PREFLIGHT_NEGATIVES = {'wrong-model': 'models_pinned', 'provider-unavailable': 'claude_cli'}
BROKER_TIMEOUT_SECONDS = 3600
# Variables a Claude Code session (CLI or desktop app) sets for its own children.
# Launched from inside one, the worker `claude` would inherit them and could run
# as a child session or through the host's ANTHROPIC_BASE_URL instead of the
# operator's own sign-in, so they are removed before the broker starts.
SESSION_ENV_PREFIXES = ('CLAUDE_CODE_', 'CLAUDE_AGENT_SDK_', 'CLAUDE_PREVIEW_')
SESSION_ENV_NAMES = ('CLAUDECODE', 'CLAUDE_PID')


def run_env(env) -> tuple[dict, list]:
    """The broker's environment and the sorted names removed from it (never values)."""
    inside_session = 'CLAUDECODE' in env
    removed = sorted(name for name in env
                     if name.upper().startswith(SESSION_ENV_PREFIXES) or name.upper() in SESSION_ENV_NAMES
                     or (inside_session and name.upper() == 'ANTHROPIC_BASE_URL'))
    return {k: v for k, v in env.items() if k not in removed}, removed


def build_config(settings: dict, *, max_usd: float, max_cumulative_usd: float,
                 negative: str | None) -> RunConfig:
    settings = dict(settings)
    if settings.get('worker_family', 'claude') != 'claude':
        raise ValueError('smoke_requires_claude_worker_family')
    settings.update(worker_family='claude', max_usd=max_usd, max_cumulative_usd=max_cumulative_usd)
    if negative == 'low-budget':
        settings['max_usd'] = LOW_BUDGET_USD
    elif negative == 'wrong-model':
        settings['jev_model'] = WRONG_JEV_MODEL
        settings['jev_model_aliases'] = []
    return RunConfig.from_dict(settings)


def preflight(config: RunConfig, spec: dict, claude_executable: str, env) -> dict:
    """Checks that need no model call. Never reports secret values."""
    checks = {}
    try:
        normalized = validate_spec(spec)
        checks['task'] = {'ok': True, 'route': normalized['classification']['scope'],
                          'task_hash': normalized['snapshot_hash']}
    except Exception as error:
        checks['task'] = {'ok': False, 'detail': str(error)[:200]}
    checks['models_pinned'] = {'ok': config.worker_family == 'claude' and config.jev_model == PINNED_JEV_MODEL,
                               'jev_model': config.jev_model, 'pinned_jev_model': PINNED_JEV_MODEL,
                               'worker_routes': [r['id'] for r in config.worker_routes()],
                               'checker': [config.checker_model, config.checker_effort]}
    checks['jev_cap'] = {'ok': 0 < config.max_usd <= SMOKE_CEILING_USD, 'max_usd': config.max_usd,
                         'ceiling_usd': SMOKE_CEILING_USD}
    cap = config.max_cumulative_usd
    checks['cumulative_cap'] = {'ok': cap is not None and cap <= SMOKE_CEILING_USD,
                                'max_cumulative_usd': cap, 'ceiling_usd': SMOKE_CEILING_USD}
    checks['openrouter_key'] = {'ok': bool(env.get('OPENROUTER_API_KEY')), 'present': bool(env.get('OPENROUTER_API_KEY'))}
    status = ClaudeCodeProvider(PermitAuthority(), executable=claude_executable, env=env).status()
    checks['claude_cli'] = {'ok': status.get('installed') is True and status.get('logged_in') is True,
                            **{k: status.get(k) for k in ('installed', 'logged_in', 'auth_method', 'billing',
                                                          'subscription_type', 'warnings', 'detail')}}
    return {'ok': all(check['ok'] for check in checks.values()), 'checks': checks}


def broker_command(task: Path, out: Path, config_path: Path, config: RunConfig, claude_executable: str) -> list:
    return [sys.executable, str(BROKER), '--task', str(task), '--out', str(out), '--host', 'claude',
            '--gate-policy', 'recovery', '--config', str(config_path),
            '--max-cumulative-usd', repr(config.max_cumulative_usd),
            '--claude-executable', claude_executable, '--live']


def expectation(mode: str, result: dict, audit: dict) -> dict:
    reasons = []
    if not audit['ok']:
        reasons.append('audit_failed')
    if mode == 'smoke':
        if result.get('status') != 'complete' or result.get('answer') is None:
            reasons.append('run_not_complete:' + str(result.get('status')))
    else:  # low-budget: the broker ran but nothing paid was launched
        frontier = [c for c in result.get('calls') or [] if c.get('role') in ('worker', 'checker')]
        if result.get('status') == 'complete' or result.get('answer') is not None:
            reasons.append('negative_run_released_an_answer')
        if result.get('jev_provider_events'):
            reasons.append('jev_request_made')
        if any(c.get('usage_status') != 'not_launched' for c in frontier):
            reasons.append('frontier_call_launched')
        if audit['evidence']['permits_consumed']:
            reasons.append('permit_consumed')
    return {'met': not reasons, 'reasons': reasons}


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def main(argv=None, *, env=None, launch=subprocess.run, clock=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--task', type=Path, default=ROOT / 'examples' / 'p0-03-smoke.request.json')
    parser.add_argument('--config', type=Path, help='RunConfig JSON; worker_family must be claude')
    parser.add_argument('--out-root', type=Path, default=ROOT / 'runs' / 'p0-03-smoke')
    parser.add_argument('--max-usd', type=float, default=SMOKE_CEILING_USD, help='Jev cap (RunConfig.max_usd)')
    parser.add_argument('--max-cumulative-usd', type=float, default=SMOKE_CEILING_USD,
                        help='Claude permit-ledger cap')
    parser.add_argument('--claude-executable', default='claude')
    parser.add_argument('--negative', choices=NEGATIVES)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--dry-run', action='store_true', help='Preflight and print the command only')
    mode_group.add_argument('--live', action='store_true', help='Launch the capped run (paid unless negative)')
    args = parser.parse_args(argv)
    env, scrubbed = run_env(os.environ if env is None else env)
    mode = args.negative or 'smoke'
    stamp = (clock or (lambda: datetime.datetime.now(datetime.timezone.utc)))().strftime('%Y%m%dT%H%M%SZ')
    run_dir = args.out_root / (stamp + '-' + mode)
    claude_executable = (str(run_dir / 'claude-not-installed') if args.negative == 'provider-unavailable'
                         else args.claude_executable)

    settings = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
    try:
        config = build_config(settings, max_usd=args.max_usd, max_cumulative_usd=args.max_cumulative_usd,
                              negative=args.negative)
    except ValueError as error:
        print(json.dumps({'mode': mode, 'status': 'refused', 'reason': str(error)}, indent=2))
        return 2
    spec = json.loads(args.task.read_text(encoding='utf-8-sig'))
    checks = preflight(config, spec, claude_executable, env)
    command = broker_command(args.task.resolve(), run_dir / 'broker', run_dir / 'config.json',
                             config, claude_executable)
    report = {'slice': 'p0-03-3b', 'mode': mode, 'started_at': stamp, 'preflight': checks,
              'config_policy_hash': config.policy_hash, 'command': command,
              'session_env_removed': scrubbed}

    if args.dry_run:
        print(json.dumps({**report, 'status': 'dry_run'}, indent=2))
        return 0 if checks['ok'] else 2
    if not checks['ok']:
        # Preflight refusal is the expected outcome of these negatives, provided the
        # targeted check is one that refused; nothing launches either way.
        failed = sorted(name for name, check in checks['checks'].items() if not check['ok'])
        expected = PREFLIGHT_NEGATIVES.get(args.negative) in failed
        report.update(status='refused_before_launch', refused_checks=failed,
                      expectation={'met': expected, 'reasons': [] if expected else ['preflight_refused']})
        run_dir.mkdir(parents=True)
        _write_json(run_dir / 'smoke-report.json', report)
        print(json.dumps(report, indent=2))
        return 0 if expected else (1 if args.negative in PREFLIGHT_NEGATIVES else 2)
    if args.negative in PREFLIGHT_NEGATIVES:
        report.update(status='negative_not_refused',
                      expectation={'met': False, 'reasons': ['preflight_did_not_refuse']})
        print(json.dumps(report, indent=2))
        return 1

    run_dir.mkdir(parents=True)
    _write_json(run_dir / 'config.json', config.to_dict())
    with (run_dir / 'broker.stdout.txt').open('wb') as stdout, (run_dir / 'broker.stderr.txt').open('wb') as stderr:
        completed = launch(command, cwd=str(ROOT), env=dict(env), stdout=stdout, stderr=stderr,
                           timeout=BROKER_TIMEOUT_SECONDS)
    audit = audit_run(run_dir / 'broker', config)
    result_path = run_dir / 'broker' / 'result.json'
    result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.is_file() else {}
    met = expectation(mode, result, audit)
    report.update(status='ran', broker_exit_code=completed.returncode, result_status=result.get('status'),
                  jev_api_cost_usd=result.get('jev_api_cost_usd'), audit=audit, expectation=met)
    _write_json(run_dir / 'smoke-report.json', report)
    print(json.dumps({k: report[k] for k in ('mode', 'status', 'broker_exit_code', 'result_status',
                                             'jev_api_cost_usd', 'expectation')}, indent=2))
    return 0 if met['met'] else 1


if __name__ == '__main__':
    sys.exit(main())

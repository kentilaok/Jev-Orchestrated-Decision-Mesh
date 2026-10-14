"""Arsenal Phase F: sandbox provider, secret references, browser permit classes (offline)."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from browser_capability import BrowserSession, classify
from capability_permits import PermitAuthority, PermitError, audit_permit_ledger
from sandbox import DockerSandboxProvider, SandboxSpec, SecretBroker, build_snapshot

JEV = {'kind': 'jev_decision', 'decision_id': 'e3', 'choice': 'run_tests', 'state_hash': 'c' * 64, 'live': True}
OPERATOR = {'kind': 'operator', 'operator': 'console', 'reason': 'test'}


class FakeDocker:
    def __init__(self, export_tar=b''):
        self.calls, self.export_tar = [], export_tar

    def __call__(self, argv, *, input_bytes=None, timeout=120, env=None):
        self.calls.append({'argv': argv, 'input': input_bytes, 'env': env})
        command = argv[1]
        if command == 'cp' and argv[-1] == '-':
            return 0, self.export_tar, b''
        if command == 'exec' and 'printenv' in argv:
            name = argv[-1]
            return 0, ('value=' + (env or {}).get(name, '')).encode(), b''
        if command == 'ps':
            return 0, b'cidm-old 100\ncidm-new 99999999999\n', b''
        return 0, b'', b''


def project(temp):
    root = Path(temp) / 'project'
    (root / 'src').mkdir(parents=True)
    (root / 'src' / 'app.py').write_text('print(1)\n', encoding='utf-8')
    (root / 'node_modules').mkdir()
    (root / 'node_modules' / 'big.js').write_text('x', encoding='utf-8')
    return root


class SandboxTests(unittest.TestCase):
    def provider(self, docker, **options):
        authority = PermitAuthority()
        return DockerSandboxProvider(authority, runner=docker, **options), authority

    def create(self, provider, authority, spec, snapshot):
        snapshot_hash = build_snapshot(snapshot)[1] if snapshot else None
        permit = authority.issue('sandbox.create', provider.create_scope(spec, snapshot_hash), OPERATOR)
        return provider.create(spec, snapshot, permit)

    def test_create_applies_isolation_limits_and_copies_snapshot(self):
        docker = FakeDocker()
        provider, authority = self.provider(docker)
        with tempfile.TemporaryDirectory() as temp:
            record = self.create(provider, authority, SandboxSpec(image='python:3.12-slim'), project(temp))
        create = docker.calls[0]['argv']
        for flag in ('--network', 'none', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                     '--pids-limit', '--memory', '1024m'):
            self.assertIn(flag, create)
        self.assertEqual(create[-2:], ['sleep', '900'])
        copy = next(c for c in docker.calls if c['argv'][1] == 'cp')
        names = tarfile.open(fileobj=io.BytesIO(copy['input'])).getnames()
        self.assertEqual(names, ['src/app.py'])
        self.assertEqual(record['snapshot_files'], 1)
        self.assertTrue(audit_permit_ledger(authority.events())['valid'])

    def test_allowlist_egress_is_refused_by_docker_provider(self):
        provider, authority = self.provider(FakeDocker())
        spec = SandboxSpec(image='python:3.12-slim', network='allowlist')
        permit = authority.issue('sandbox.create', provider.create_scope(spec, None), OPERATOR)
        with self.assertRaisesRegex(PermitError, 'egress_allowlist_requires_proxy_provider'):
            provider.create(spec, None, permit)

    def test_secrets_are_passed_by_name_and_redacted(self):
        docker = FakeDocker()
        secrets = SecretBroker(['secret://env/DEPLOY_TOKEN'], env={'DEPLOY_TOKEN': 'tok-123'})
        provider, authority = self.provider(docker, secrets=secrets)
        record = self.create(provider, authority, SandboxSpec(image='alpine:3'), None)
        argv = ['printenv', 'DEPLOY_TOKEN']
        refs = ['secret://env/DEPLOY_TOKEN']
        scope = provider.exec_scope(record['sandbox_id'], argv, refs)
        run = authority.issue('sandbox.exec', scope, OPERATOR)
        with self.assertRaisesRegex(PermitError, 'strong_capability_requires_jev_basis'):
            authority.issue('secret.use', scope, OPERATOR)
        secret = authority.issue('secret.use', scope, JEV)
        result = provider.exec(record['sandbox_id'], argv, run, secret_refs=refs, secret_permit_id=secret)
        call = docker.calls[-1]
        self.assertIn('DEPLOY_TOKEN', call['argv'])
        self.assertNotIn('tok-123', json.dumps(call['argv']))
        self.assertEqual(call['env']['DEPLOY_TOKEN'], 'tok-123')
        self.assertEqual(result['stdout'], 'value=***')
        self.assertNotIn('tok-123', json.dumps(authority.events()))

    def test_unregistered_secret_reference_is_refused(self):
        secrets = SecretBroker([], env={'X': '1'})
        with self.assertRaisesRegex(PermitError, 'secret_reference_not_registered'):
            secrets.resolve(['secret://env/X'])

    def test_artifact_import_is_strong_filtered_and_path_safe(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            for name, data in (('./dist/app.js', b'ok'), ('./secrets.env', b'no'), ('../escape.js', b'bad')):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        provider, authority = self.provider(FakeDocker(export_tar=buffer.getvalue()))
        record = self.create(provider, authority, SandboxSpec(image='alpine:3'), None)
        with tempfile.TemporaryDirectory() as dest:
            scope = provider.export_scope(record['sandbox_id'], ['dist/*', '*.js'], Path(dest))
            with self.assertRaisesRegex(PermitError, 'strong_capability_requires_jev_basis'):
                authority.issue('sandbox.import_artifacts', scope, OPERATOR)
            permit = authority.issue('sandbox.import_artifacts', scope, JEV)
            result = provider.export_artifacts(record['sandbox_id'], ['dist/*', '*.js'], Path(dest), permit)
            self.assertEqual([a['path'] for a in result['artifacts']], ['dist/app.js'])
            self.assertFalse((Path(dest).parent / 'escape.js').exists())

    def test_ttl_expiry_blocks_exec_and_reaper_removes_expired(self):
        now = [1000.0]
        docker = FakeDocker()
        provider, authority = self.provider(docker, clock=lambda: now[0])
        record = self.create(provider, authority, SandboxSpec(image='alpine:3', ttl_seconds=60), None)
        now[0] += 61
        permit = authority.issue('sandbox.exec', provider.exec_scope(record['sandbox_id'], ['true'], []), OPERATOR)
        with self.assertRaisesRegex(PermitError, 'sandbox_ttl_expired'):
            provider.exec(record['sandbox_id'], ['true'], permit)
        self.assertEqual(provider.reap_expired()['removed'], ['cidm-old'])


def docker_image_available(image):
    if not shutil.which('docker'):
        return False
    try:
        return subprocess.run(['docker', 'image', 'inspect', image], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


@unittest.skipUnless(os.environ.get('CIDM_RUN_DOCKER_TESTS') == '1' and docker_image_available('node:22-alpine'),
                     'set CIDM_RUN_DOCKER_TESTS=1 with local image node:22-alpine to run the container smoke test')
class DockerSmokeTest(unittest.TestCase):
    def test_real_container_round_trip_without_network(self):
        authority = PermitAuthority()
        provider = DockerSandboxProvider(authority)
        spec = SandboxSpec(image='node:22-alpine', ttl_seconds=120, memory_mb=256)
        with tempfile.TemporaryDirectory() as temp:
            root = project(temp)
            snapshot_hash = build_snapshot(root)[1]
            record = provider.create(spec, root, authority.issue(
                'sandbox.create', provider.create_scope(spec, snapshot_hash), OPERATOR))
            try:
                argv = ['sh', '-c', 'cat src/app.py > out.txt && wget -q -T 3 http://example.com -O - || echo offline']
                run = provider.exec(record['sandbox_id'], argv, authority.issue(
                    'sandbox.exec', provider.exec_scope(record['sandbox_id'], argv, []), OPERATOR))
                self.assertIn('offline', run['stdout'])
                dest = Path(temp) / 'imported'
                scope = provider.export_scope(record['sandbox_id'], ['out.txt'], dest)
                exported = provider.export_artifacts(record['sandbox_id'], ['out.txt'], dest,
                                                     authority.issue('sandbox.import_artifacts', scope, JEV))
                self.assertEqual((dest / 'out.txt').read_text(), 'print(1)\n')
                self.assertEqual(len(exported['artifacts']), 1)
            finally:
                provider.destroy(record['sandbox_id'])
        self.assertTrue(audit_permit_ledger(authority.events())['valid'])


class FakePage:
    def __init__(self):
        self.url, self.actions = 'about:blank', []

    def goto(self, url):
        self.url = url
        self.actions.append(('goto', url))

    def inner_text(self, selector):
        return 'Order total: $10'

    def click(self, selector):
        self.actions.append(('click', selector))

    def fill(self, selector, value):
        self.actions.append(('fill', selector))


class BrowserTests(unittest.TestCase):
    def test_classification_escalates_transactional_controls(self):
        self.assertEqual(classify('goto'), 'browser.read')
        self.assertEqual(classify('text'), 'browser.extract')
        self.assertEqual(classify('click', 'button:has-text("Details")'), 'browser.mutate')
        self.assertEqual(classify('click', 'button:has-text("Place order")'), 'browser.submit_transaction')
        self.assertEqual(classify('press', 'Enter'), 'browser.submit_transaction')

    def test_session_enforces_origin_and_permit_class(self):
        authority = PermitAuthority()
        page = FakePage()
        session = BrowserSession(page, authority, allowed_origins=['https://shop.example.test'])
        from browser_capability import action_scope
        url = 'https://shop.example.test/cart'
        session.perform('goto', authority.issue('browser.read', action_scope('goto', url, None, None), OPERATOR),
                        url=url)
        text = session.perform('text', authority.issue(
            'browser.extract', action_scope('text', url, 'body', None), OPERATOR), target='body')
        self.assertIn('$10', text)
        target = 'button:has-text("Place order")'
        scope = action_scope('click', url, target, None)
        with self.assertRaisesRegex(PermitError, 'strong_capability_requires_jev_basis'):
            authority.issue('browser.submit_transaction', scope, OPERATOR)
        mutate = authority.issue('browser.mutate', scope, JEV)
        with self.assertRaisesRegex(PermitError, 'permit_capability_mismatch'):
            session.perform('click', mutate, target=target)
        self.assertNotIn(('click', target), page.actions)
        off_site = 'https://evil.example.test/'
        permit = authority.issue('browser.read', action_scope('goto', off_site, None, None), OPERATOR)
        with self.assertRaisesRegex(PermitError, 'browser_origin_not_allowed'):
            session.perform('goto', permit, url=off_site)


if __name__ == '__main__':
    unittest.main()

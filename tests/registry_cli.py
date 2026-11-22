# SPDX-License-Identifier: Apache-2.0
"""Black-box client tests with a counted loopback HTTP registry."""
import contextlib
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import threading
import time
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
NEST = Path(os.environ.get('NEST', ROOT / '.build/nest')).resolve()
HONK = Path(os.environ.get('HONK', ROOT / '.build/honk')).resolve()
import shutil
GOOSE = Path(os.environ.get('GOOSE', shutil.which('goose') or '/nonexistent/goose'))

def q(value):
    return json.dumps(str(value))

class Registry:
    def __init__(self, root, *, index_delay=0):
        self.root = Path(root)
        self.requests = []
        self.archive_barrier = None
        self.index_barrier = None
        fixture = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                fixture.requests.append((self.path, self.headers.get('If-None-Match')))
                path = fixture.root / self.path.lstrip('/')
                if not path.is_file():
                    self.send_error(404)
                    return
                barrier = {'.gz': fixture.archive_barrier, '.toml': fixture.index_barrier}.get(path.suffix)
                if barrier is not None:
                    try:
                        barrier.wait()
                    except threading.BrokenBarrierError:
                        self.send_error(503)
                        return
                if index_delay and self.path.startswith(('/index/', '/cargo-index/')):
                    time.sleep(index_delay)
                data = path.read_bytes()
                etag = '"' + hashlib.sha256(data).hexdigest() + '"'
                if self.headers.get('If-None-Match') == etag:
                    self.send_response(304)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('ETag', etag)
                self.end_headers()
                self.wfile.write(data)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def package(self, name='demo', version='1.0.0', deps=(), payload=None, extra=None, compiler=None, dependency_options=None, features=None, target_dependencies=None):
        label = f'{name}-{version}'
        manifest = f'[package]\nname={q(name)}\nversion={q(version)}\nkind="lib"\nentry="lib.goose"\n[dependencies]\n'
        dependencies = []
        for target_os, rows in [(None, deps), *(target_dependencies or {}).items()]:
            if target_os:
                manifest += f'[target.{target_os}.dependencies]\n'
            for alias, package, requirement in rows:
                fields = dict(package=package, version=requirement, **(dependency_options or {}).get(alias, {}))
                record_dep = dict(alias=alias, **fields)
                if target_os:
                    os_name, separator, arch = target_os.partition('-')
                    record_dep['target-os'] = os_name
                    if separator:
                        record_dep['target-arch'] = arch
                dependencies.append(record_dep)
                fields['registry'] = self.url + '/index'
                manifest += f'{alias} = {{ ' + ', '.join(f'{key}={json.dumps(value)}' for key, value in fields.items()) + ' }\n'
        if features:
            manifest += '[features]\n' + ''.join(f'{name}={json.dumps(items)}\n' for name, items in features.items())
        if compiler:
            manifest += f'[toolchain]\nrevision={q(compiler)}\n'
        content = {'Honk.toml': manifest.encode(), 'lib.goose': payload or b'namespace demo;\nfn value() -> i64 { 42 }\n'}
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as archive:
            for filename, data in content.items():
                info = tarfile.TarInfo(f'{label}/{filename}')
                info.size = len(data)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(data))
            if extra:
                archive.addfile(extra, io.BytesIO(b'x' * extra.size))
        data = buf.getvalue()
        path = self.root / f'{label}.tar.gz'
        path.write_bytes(data)
        entry = {'version': version, 'url': self.url + '/' + path.name, 'sha256': hashlib.sha256(data).hexdigest(), 'entry': 'lib.goose', 'yanked': False,
                 'dependencies': dependencies}
        if features:
            entry['features'] = features
        self.index(name, [entry])
        return entry

    def index(self, name, entries):
        target = self.root / 'index' / f'{name}.toml'
        target.parent.mkdir(exist_ok=True)
        schema = 2 if any('features' in release or any('optional' in dep or 'features' in dep or 'default-features' in dep or 'target-os' in dep for dep in release['dependencies']) for release in entries) else 1
        text = f'schema={schema}\npackage={q(name)}\n'
        for entry in entries:
            text += '\n[[releases]]\n'
            for key in ('version', 'url', 'sha256', 'entry'):
                text += f'{key}={q(entry[key])}\n'
            text += f'yanked={str(entry.get("yanked", False)).lower()}\n'
            text += 'dependencies=[' + ','.join('{'+','.join(f'{k}={json.dumps(v)}' for k, v in dep.items())+'}' for dep in entry['dependencies']) + ']\n'
            if 'features' in entry:
                text += '[releases.features]\n' + ''.join(f'{name}={json.dumps(items)}\n' for name, items in entry['features'].items())
        target.write_text(text)
        (target.parent / '_catalog.toml').write_text(f'schema=1\n[[packages]]\nname={q(name)}\nversion={q(entries[0]["version"])}\n')

class Client(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = Registry(self.root)
        self.cache = self.root / 'cache'
    def tearDown(self):
        self.registry.close()
        self.temp.cleanup()
    def call(self, *argv, project=None, ok=True, extra=None):
        environment = dict(os.environ, HONK_HOME=str(self.root / 'honk-home'), GOOSE=str(GOOSE), **(extra or {}))
        result = subprocess.run([str(HONK), *argv], cwd=project or self.root, env=environment,
                                text=True, capture_output=True, timeout=90)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        self.assertNotIn('AddressSanitizer', result.stderr)
        self.assertNotIn('runtime error:', result.stderr)
        return result

    def local_library(self, name, dependencies='', source=None, dev_dependencies=''):
        directory = self.root / name
        directory.mkdir()
        (directory / 'Honk.toml').write_text(
            f'[package]\nname={q(name)}\nversion="1.0.0"\nkind="lib"\nentry="lib.goose"\n'
            f'[dependencies]\n{dependencies}\n[dev-dependencies]\n{dev_dependencies}')
        (directory / 'lib.goose').write_text(source or f'namespace {name};\nimport answer;\nfn value() -> i64 {{ answer::value() }}\n')
        return directory

    def application(self, dependencies, source=None):
        project = self.root / 'app'
        project.mkdir()
        (project / 'Honk.toml').write_text(
            '[package]\nname="app"\nversion="1.0.0"\nkind="bin"\nentry="main.goose"\n'
            '[dependencies]\n' + dependencies)
        (project / 'main.goose').write_text(source or 'import bridge;\nimport std;\nfn main() { assert(bridge::value() == 42); print("42"); }\n')
        return project

    def registry_dependency(self, requirement='^1.0.0', package='goose-answer', alias='answer'):
        return f'{alias} = {{package={q(package)}, version={q(requirement)}, registry={q(self.registry.url + "/index")} }}\n'

    def test_path_transitives_resolve_without_root_redeclarations(self):
        self.registry.package('goose-helper', payload=b'namespace helper; fn value() -> i64 { 42 }')
        self.registry.package('goose-answer', deps=[('helper', 'goose-helper', '^1.0.0')],
                              payload=b'namespace answer; import helper; fn value() -> i64 { helper::value() }')
        bridge = self.local_library('bridge', self.registry_dependency(),
                                    dev_dependencies=self.registry_dependency(package='unused-dev', alias='unused'))
        wrapper = self.local_library('wrapper', f'bridge={{path={q(bridge)}}}\n',
                                     'namespace wrapper; import bridge; fn value() -> i64 { bridge::value() }')
        app = self.application(f'wrapper={{path={q(wrapper)}}}\n',
                               'import wrapper; import std; fn main() { assert(wrapper::value() == 42); print("42"); }')
        self.call('fetch', project=app)
        lock = (app / 'Honk.lock').read_bytes()
        names = {node['name'] for node in tomllib.loads(lock.decode())['dependency']}
        self.assertEqual(names, {'wrapper', 'bridge', 'answer', 'helper'})
        requests = len(self.registry.requests)
        self.assertIn('42', self.call('run', '--frozen', project=app).stdout)
        self.assertEqual(len(self.registry.requests), requests)
        self.assertEqual((app / 'Honk.lock').read_bytes(), lock)
        self.assertNotIn('unused-dev.toml', str(self.registry.requests))

    def test_late_path_constraint_changes_registry_selection_before_download(self):
        one = self.registry.package('goose-answer', '1.0.0', payload=b'namespace answer; fn value() -> i64 { 42 }')
        two = self.registry.package('goose-answer', '2.0.0', payload=b'namespace answer; fn value() -> i64 { 99 }')
        self.registry.index('goose-answer', [two, one])
        bridge = self.local_library('bridge', self.registry_dependency('=1.0.0'))
        app = self.application(self.registry_dependency('>=1.0.0, <3.0.0') + f'bridge={{path={q(bridge)}}}\n')
        self.call('fetch', project=app)
        lock = tomllib.loads((app / 'Honk.lock').read_text())
        answer = next(node for node in lock['dependency'] if node['name'] == 'answer')
        self.assertEqual(answer['rev'], '1.0.0')
        self.assertFalse(any('goose-answer-2.0.0.tar.gz' in path for path, _ in self.registry.requests))
        self.assertEqual(sum(path.endswith('/goose-answer.toml') for path, _ in self.registry.requests), 1)
        self.assertIn('42', self.call('run', '--frozen', project=app).stdout)

    def test_existing_mixed_lock_order_is_preserved_across_discovery_changes(self):
        self.registry.package('goose-answer')
        bridge = self.local_library('bridge', self.registry_dependency('=1.0.0'))
        app = self.application(self.registry_dependency('=1.0.0') + f'bridge={{path={q(bridge)}}}\n')
        self.call('fetch', project=app)
        path = app / 'Honk.lock'
        header, *records = path.read_bytes().split(b'\n[[dependency]]\n')
        self.assertEqual(len(records), 2)
        # alpha.1 discovered a direct registry node before the local node.
        previous = header + b''.join(b'\n[[dependency]]\n' + record for record in reversed(records))
        path.write_bytes(previous)
        requests = len(self.registry.requests)
        self.call('fetch', '--frozen', project=app)
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(len(self.registry.requests), requests)

    def test_mixed_conflict_preserves_lock_and_does_not_download_archives(self):
        self.registry.package('goose-answer')
        bridge = self.local_library('bridge', self.registry_dependency('=1.0.0'))
        app = self.application(self.registry_dependency('=1.0.0') + f'bridge={{path={q(bridge)}}}\n')
        self.call('fetch', project=app)
        lock = (app / 'Honk.lock').read_bytes()
        manifest = bridge / 'Honk.toml'
        manifest.write_text(manifest.read_text().replace('=1.0.0', '=2.0.0'))
        requests = len(self.registry.requests)
        result = self.call('fetch', '--frozen', project=app, ok=False)
        self.assertIn('goose-answer', result.stderr)
        self.assertIn('root -> answer', result.stderr)
        self.assertIn('bridge -> answer', result.stderr)
        self.assertEqual(len(self.registry.requests), requests)
        self.assertEqual((app / 'Honk.lock').read_bytes(), lock)
        result = self.call('fetch', project=app, ok=False)
        self.assertIn('goose-answer', result.stderr)
        self.assertFalse(any(path.endswith('.tar.gz') for path, _ in self.registry.requests[requests:]))
        self.assertEqual((app / 'Honk.lock').read_bytes(), lock)

    def test_new_hidden_registry_dependency_cannot_change_a_locked_graph(self):
        self.registry.package('goose-answer')
        bridge = self.local_library('bridge', source='namespace bridge; fn value() -> i64 { 42 }')
        app = self.application(f'bridge={{path={q(bridge)}}}\n')
        self.call('fetch', project=app)
        lock = (app / 'Honk.lock').read_bytes()
        manifest = bridge / 'Honk.toml'
        manifest.write_text(manifest.read_text().replace('[dependencies]\n', '[dependencies]\n' + self.registry_dependency()))
        self.call('fetch', '--locked', project=app, ok=False)
        self.assertEqual(self.registry.requests, [])
        self.assertEqual((app / 'Honk.lock').read_bytes(), lock)
        self.call('fetch', project=app)
        shutil.rmtree(self.root / 'honk-home/nest/index')
        requests = len(self.registry.requests)
        self.call('fetch', '--frozen', project=app)
        self.assertEqual(len(self.registry.requests), requests)

    def test_legacy_sourced_path_import_discovers_registry_transitives(self):
        self.registry.package('goose-answer', payload=b'namespace answer; fn value() -> i64 { 42 }')
        bridge = self.local_library('bridge', self.registry_dependency())
        legacy = self.root / 'legacy'
        legacy.mkdir()
        (legacy / 'legacy.goose').write_text('namespace legacy; import bridge from "../bridge"; fn value() -> i64 { bridge::value() }')
        app = self.application(f'legacy={{path={q(legacy)}}}\n',
                               'import legacy; import std; fn main() { assert(legacy::value() == 42); print("42"); }')
        self.call('fetch', project=app)
        self.assertIn('42', self.call('run', '--frozen', project=app).stdout)

    def test_git_to_path_to_registry_uses_locked_git_commit_offline(self):
        # Only the test shim translates the HTTPS fixture URL to a local Git repo.
        # Production Honk retains its HTTPS-only Git transport policy.
        from version_deps_cli import SHIM
        self.registry.package('goose-answer', payload=b'namespace answer; fn value() -> i64 { 42 }')
        remote = self.root / 'remote'
        remote.mkdir()
        nested = remote / 'nested'
        nested.mkdir()
        (nested / 'Honk.toml').write_text('[package]\nname="bridge"\nversion="1.0.0"\nkind="lib"\nentry="lib.goose"\n[dependencies]\n' + self.registry_dependency())
        (nested / 'lib.goose').write_text('namespace bridge; import answer; fn value() -> i64 { answer::value() }')
        (remote / 'Honk.toml').write_text('[package]\nname="mathx"\nversion="1.0.0"\nkind="lib"\nentry="mathx.goose"\n[dependencies]\nbridge={path="nested"}\n')
        (remote / 'mathx.goose').write_text('namespace mathx; import bridge; fn value() -> i64 { bridge::value() }')
        real_git = shutil.which('git')
        def git(*argv):
            return subprocess.check_output([real_git, '-C', str(remote), *argv], text=True).strip()
        git('init', '-q')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        commit = git('rev-parse', 'HEAD')
        tools = self.root / 'tools'
        tools.mkdir()
        (tools / 'git').write_text(SHIM)
        (tools / 'git').chmod(0o755)
        log = self.root / 'git.log'
        extra = {'PATH': str(tools) + os.pathsep + os.environ['PATH'], 'TEST_GIT': real_git,
                 'TEST_REMOTE': str(remote), 'TEST_GIT_LOG': str(log)}
        app = self.application(f'mathx={{git="https://test.invalid/mathx.git",rev={q(commit)}}}\n',
                               'import mathx; import std; fn main() { assert(mathx::value() == 42); print("42"); }')
        self.call('fetch', project=app, extra=extra)
        lock = (app / 'Honk.lock').read_bytes()
        git_log = [json.loads(line) for line in log.read_text().splitlines()]
        network = sum('fetch' in args or 'ls-remote' in args for args in git_log)
        requests = len(self.registry.requests)
        shutil.rmtree(self.root / 'honk-home/nest/index')
        self.assertIn('42', self.call('run', '--frozen', project=app, extra=extra).stdout)
        self.assertEqual((app / 'Honk.lock').read_bytes(), lock)
        git_log = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(sum('fetch' in args or 'ls-remote' in args for args in git_log), network)
        self.assertEqual(len(self.registry.requests), requests)

    def test_honk_fetch_lock_and_real_compilation(self):
        if not HONK.is_file() or not GOOSE.is_file():
            self.skipTest('set HONK and GOOSE for the compiler integration test')
        entry = self.registry.package('goose-answer', payload=b'namespace answer;\nfn value() -> i64 { 42 }\n')
        project = self.root / 'project'
        project.mkdir()
        (project / 'Honk.toml').write_text('[package]\nname="hello"\nversion="0.1.0"\nentry="main.goose"\nkind="bin"\n')
        (project / 'main.goose').write_text('import answer;\nimport std;\nfn main() { assert(answer::value() == 42); print("42"); }\n')
        env = dict(os.environ, HONK_HOME=str(self.root / 'honk-home'), GOOSE=str(GOOSE))
        def honk(*argv, ok=True):
            result = subprocess.run([str(HONK), *argv], cwd=project, env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
            return result
        self.assertIn('goose-answer', honk('search', 'answer', '--registry', self.registry.url + '/index').stdout)
        self.assertIn(entry['sha256'], honk('info', 'goose-answer', '--registry', self.registry.url + '/index').stdout)
        honk('add', 'goose-answer', '--as', 'answer', '--registry', self.registry.url + '/index')
        honk('fetch')
        lock = (project / 'Honk.lock').read_bytes()
        before = len(self.registry.requests)
        self.assertIn('42', honk('run', '--frozen').stdout)
        self.assertEqual((project / 'Honk.lock').read_bytes(), lock)
        self.assertEqual(len(self.registry.requests), before)
        # Lock survives a yanked release, and even a missing index cache.
        entry['yanked'] = True
        self.registry.index('goose-answer', [entry])
        import shutil
        shutil.rmtree(self.root / 'honk-home' / 'nest' / 'index')
        honk('fetch', '--frozen')
        self.assertEqual(len(self.registry.requests), before)
        honk('update', ok=False)
        self.assertEqual((project / 'Honk.lock').read_bytes(), lock)
        # A changed constraint must not silently reuse an incompatible lock.
        manifest = project / 'Honk.toml'
        manifest.write_text(manifest.read_text().replace('^1.0.0', '^2.0.0'))
        honk('fetch', '--locked', ok=False)
        self.assertEqual((project / 'Honk.lock').read_bytes(), lock)

if __name__ == '__main__':
    unittest.main()

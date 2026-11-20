"""Real Honk -> scoped graph -> Goose JIT/native qualification."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import shutil
import fcntl
import unittest

HONK = Path(os.environ.get('HONK', '.build/honk')).resolve()
GOOSE = Path(os.environ['GRAPH_GOOSE']).resolve()
COMPILER = json.loads(subprocess.check_output([str(GOOSE), 'version', '--json']))
REVISION = COMPILER['compiler_revision']


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GOOSE=str(GOOSE), GOOSE_HOME=str(self.root / 'compiler-cache'), HONK_HOME=str(self.root / 'honk-cache'))

    def package(self, folder, code, dependencies=None, name=None):
        path = self.root / folder
        path.mkdir()
        manifest = f'[package]\nname = "{name or folder}"\nentry = "entry.goose"\n'
        manifest += f'[toolchain]\nrevision = "{REVISION}"\n[dependencies]\n'
        for alias, target in (dependencies or {}).items():
            manifest += f'{alias} = {{ path = "../{target}" }}\n'
        (path / 'Honk.toml').write_text(manifest)
        (path / 'entry.goose').write_text(code)
        return path

    def run_honk(self, command='run', ok=True, extra=(), cwd=None):
        result = subprocess.run([str(HONK), command, '--isolated', *extra], cwd=cwd or self.root / 'app',
                                env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def diamond(self):
        self.package('one', 'namespace versioned; struct Value { x: i64 } fn make() -> Value { Value { 1 } }', name='dep')
        self.package('two', 'namespace versioned; struct Value { x: i64, y: i64 } fn make() -> Value { Value { 2, 3 } }', name='dep')
        self.package('a', 'namespace client; import dep; fn answer() -> i64 { dep::make().x }', {'dep': 'one'})
        self.package('b', 'namespace client; import dep; fn answer() -> i64 { dep::make().x }', {'dep': 'two'})
        self.package('app', 'import a; import b; import std; fn main() { print(a::answer(), " ", b::answer()); }', {'a': 'a', 'b': 'b'})

    def test_scoped_diamond_jit_and_native(self):
        self.diamond()
        self.run_honk('check')
        self.assertEqual(self.run_honk().stdout.strip(), '1 2')
        self.run_honk('build')
        binary = self.root / 'app/target/isolated/app'
        self.assertEqual(subprocess.check_output([str(binary)], text=True).strip(), '1 2')
        graph = json.loads((binary.parent / 'graph.json').read_text())
        self.assertEqual(len(graph['nodes']), 5)
        owners = [n for n in graph['nodes'] if n['source']['name'] in ('a', 'b')]
        self.assertNotEqual(owners[0]['bindings']['dep'], owners[1]['bindings']['dep'])
        lock = tomllib.loads((self.root / 'app/Honk.lock').read_text())
        self.assertEqual(lock['version'], 2)
        self.assertEqual(len(lock['package']), 5)
        self.assertEqual(len([p for p in lock['package'] if p['name'] == 'dep']), 2)

    def test_shared_alias_instance(self):
        self.package('dep', 'namespace shared; var count: i64 = 0; fn next() -> i64 { count++; count }')
        self.package('app', 'import a; import b; import std; fn main() { let x = a::next(); let y = b::next(); print(x, " ", y); }', {'a': 'dep', 'b': 'dep'})
        self.assertEqual(self.run_honk().stdout.strip(), '1 2')

    def test_snapshot_refresh_and_stability(self):
        self.diamond()
        self.run_honk('check')
        path = self.root / 'app/target/isolated/graph.json'
        original = path.read_bytes()
        self.run_honk('check')
        self.assertEqual(path.read_bytes(), original)
        with (self.root / 'one/entry.goose').open('a') as f:
            f.write('\n// source edit\n')
        self.run_honk('check')
        self.assertNotEqual(path.read_bytes(), original)

    def test_cycle_and_unsupported_lock_preserve_lock(self):
        self.package('app', 'fn main() {}', {'dep': 'dep'})
        self.package('dep', 'fn answer() {}', {'app': 'app'})
        lock = self.root / 'app/Honk.lock'
        lock.write_text('sentinel')
        self.assertIn('cycle', self.run_honk('check', ok=False).stderr)
        self.assertIn('cycle', self.run_honk('check', ok=False, extra=('--frozen',)).stderr)
        self.assertEqual(lock.read_text(), 'sentinel')

    def test_sourced_import_and_embedded_resource_rejected(self):
        self.package('app', 'import dep from "../dep"; fn main() {}')
        self.assertIn('sourced imports', self.run_honk('check', ok=False).stderr)
        (self.root / 'app/entry.goose').write_text('fn main() { embed_file("resource"); }')
        self.assertIn('embedded resources', self.run_honk('check', ok=False).stderr)

    def test_frozen_local_edits_do_not_change_lock(self):
        self.diamond()
        self.assertIn('missing or out of date', self.run_honk('check', ok=False, extra=('--frozen',)).stderr)
        self.run_honk('check')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        self.run_honk('check', extra=('--frozen',))
        with (self.root / 'one/entry.goose').open('a') as f:
            f.write('\n// local development edit\n')
        self.run_honk('check', extra=('--locked', '--offline'))
        self.assertEqual(lock.read_bytes(), original)

    def test_dependency_change_requires_lock_update(self):
        self.diamond()
        self.run_honk('check')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        manifest = self.root / 'a/Honk.toml'
        manifest.write_text(manifest.read_text().replace('../one', '../two'))
        self.assertIn('out of date', self.run_honk('check', ok=False, extra=('--locked',)).stderr)
        self.assertEqual(lock.read_bytes(), original)
        self.run_honk('check')
        self.assertNotEqual(lock.read_bytes(), original)

    def test_legacy_lock_is_not_silently_replaced(self):
        self.package('app', 'fn main() {}')
        lock = self.root / 'app/Honk.lock'
        lock.write_text('version = 1\ncompiler = "legacy"\n')
        original = lock.read_bytes()
        self.assertIn('legacy lockfile is unchanged', self.run_honk('check', ok=False).stderr)
        self.assertEqual(lock.read_bytes(), original)

    def test_lock_survives_reordering_and_relocation(self):
        self.diamond()
        self.run_honk('check')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        manifest = self.root / 'app/Honk.toml'
        text = manifest.read_text()
        a, b = 'a = { path = "../a" }', 'b = { path = "../b" }'
        manifest.write_text(text.replace(a + '\n' + b, b + '\n' + a))
        self.run_honk('check', extra=('--frozen',))
        self.assertEqual(lock.read_bytes(), original)
        moved = self.root / 'relocated'
        moved.mkdir()
        for folder in ('app', 'a', 'b', 'one', 'two'):
            shutil.move(self.root / folder, moved / folder)
        self.root = moved
        self.run_honk('check', extra=('--frozen',))
        self.assertEqual((self.root / 'app/Honk.lock').read_bytes(), original)

    def test_project_lock_contention_preserves_metadata(self):
        self.package('app', 'fn main() {}')
        self.run_honk('check')
        lock = self.root / 'app/Honk.lock'
        graph = self.root / 'app/target/isolated/graph.json'
        before = lock.read_bytes(), graph.read_bytes()
        with (self.root / 'app/.honk/isolated.lock').open('r+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn('locked by another process', self.run_honk('check', ok=False).stderr)
        self.assertEqual((lock.read_bytes(), graph.read_bytes()), before)

    def test_legacy_cache_lock_excludes_isolated_writer(self):
        self.package('app', 'fn main() {}')
        self.run_honk('check')
        lock = self.root / 'app/Honk.lock'
        before = lock.read_bytes()
        with (self.root / 'honk-cache/lock').open('r+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn('Honk cache is locked', self.run_honk('check', ok=False).stderr)
        self.assertEqual(lock.read_bytes(), before)

    def test_malformed_lock_is_preserved(self):
        self.package('app', 'fn main() {}')
        lock = self.root / 'app/Honk.lock'
        lock.write_text('version = [broken')
        self.assertIn('invalid existing lockfile', self.run_honk('check', ok=False).stderr)
        self.assertEqual(lock.read_text(), 'version = [broken')

    def git_fixture(self):
        from version_deps_cli import SHIM
        self.remote = self.root / 'remote'
        self.remote.mkdir()
        self.real_git = shutil.which('git')
        def git(*args):
            return subprocess.check_output([self.real_git, '-C', str(self.remote), *args], text=True, stderr=subprocess.STDOUT).strip()
        self.git = git
        git('init', '-q')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        commits = []
        for version, answer in [('1.0.0', 1), ('2.0.0', 2)]:
            (self.remote / 'Honk.toml').write_text(f'[package]\nname="mathx"\nversion="{version}"\nkind="lib"\nentry="mathx.goose"\n')
            (self.remote / 'mathx.goose').write_text(f'namespace versioned; var counter: i64 = 0; struct Value {{ x: i64 }} fn make() -> Value {{ Value {{ {answer} }} }} fn next() -> i64 {{ counter++; counter }}')
            git('add', '.')
            git('commit', '-qm', version)
            commits.append(git('rev-parse', 'HEAD'))
            git('tag', 'v' + version)
        tools = self.root / 'tools'
        tools.mkdir()
        (tools / 'git').write_text(SHIM)
        (tools / 'git').chmod(0o755)
        self.git_log = self.root / 'git.log'
        self.env.update(PATH=str(tools) + os.pathsep + os.environ['PATH'], TEST_GIT=self.real_git,
                        TEST_REMOTE=str(self.remote), TEST_GIT_LOG=str(self.git_log))
        return commits

    def git_dependency(self, folder, alias, rev=None, version=None):
        manifest = self.root / folder / 'Honk.toml'
        request = f'rev = "{rev}"' if rev else f'version = "{version}"'
        with manifest.open('a') as f:
            f.write(f'{alias} = {{ git = "https://test.invalid/mathx.git", {request} }}\n')

    def network_commands(self):
        return [args for line in self.git_log.read_text().splitlines()
                if 'fetch' in (args := json.loads(line)) or 'ls-remote' in args]

    def test_git_diamond_versions_and_frozen_cache(self):
        commits = self.git_fixture()
        self.package('a', 'namespace client; import dep; fn answer() -> i64 { dep::make().x }')
        self.package('b', 'namespace client; import dep; fn answer() -> i64 { dep::make().x }')
        self.git_dependency('a', 'dep', rev='v1.0.0')
        self.git_dependency('b', 'dep', rev='v2.0.0')
        self.package('app', 'import a; import b; import std; fn main() { print(a::answer(), " ", b::answer()); }', {'a': 'a', 'b': 'b'})
        self.assertEqual(self.run_honk().stdout.strip(), '1 2')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        document = tomllib.loads(original.decode())
        edges = [b for b in document['binding'] if b.get('git')]
        self.assertEqual({b['commit'] for b in edges}, set(commits))
        before = self.network_commands()
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '1 2')
        self.assertEqual(self.network_commands(), before)
        self.assertEqual(lock.read_bytes(), original)
        self.run_honk('build', extra=('--frozen',))
        self.assertEqual(subprocess.check_output([str(self.root / 'app/target/isolated/app')], text=True).strip(), '1 2')

    def test_git_tag_lock_preference_and_wrong_version_types(self):
        self.git_fixture()
        self.package('app', 'import old; import newer; fn take(v: newer::Value) {} fn main() { take(old::make()); }')
        self.git_dependency('app', 'old', rev='v1.0.0')
        self.git_dependency('app', 'newer', rev='v2.0.0')
        self.assertIn('mathx@', self.run_honk('check', ok=False).stderr)
        self.git('tag', '-f', 'v1.0.0', 'v2.0.0')
        before = self.network_commands()
        self.assertIn('mathx@', self.run_honk('check', ok=False, extra=('--locked',)).stderr)
        self.assertEqual(self.network_commands(), before)

    def test_git_changed_request_locked_and_uncached_frozen_preserve_lock(self):
        self.git_fixture()
        self.package('app', 'import dep; fn main() { dep::make(); }')
        self.git_dependency('app', 'dep', rev='v1.0.0')
        self.run_honk('check')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        manifest = self.root / 'app/Honk.toml'
        text = manifest.read_text()
        manifest.write_text(text.replace('v1.0.0', 'v2.0.0'))
        before = self.network_commands()
        self.assertIn('lockfile must change', self.run_honk('check', ok=False, extra=('--locked',)).stderr)
        self.assertEqual(self.network_commands(), before)
        self.assertEqual(lock.read_bytes(), original)
        manifest.write_text(text)
        shutil.rmtree(self.root / 'honk-cache/sources')
        self.assertIn('source missing from cache', self.run_honk('check', ok=False, extra=('--frozen',)).stderr)
        self.assertEqual(self.network_commands(), before)
        self.assertEqual(lock.read_bytes(), original)

    def test_git_version_range_locks_selected_tag(self):
        commits = self.git_fixture()
        self.package('app', 'import dep; import std; fn main() { print(dep::make().x); }')
        self.git_dependency('app', 'dep', version='^1.0.0')
        self.assertEqual(self.run_honk().stdout.strip(), '1')
        lock = tomllib.loads((self.root / 'app/Honk.lock').read_text())
        edge = next(b for b in lock['binding'] if b.get('git'))
        self.assertEqual(edge['commit'], commits[0])
        self.assertEqual(edge['selected_ref'], 'refs/tags/v1.0.0')
        before = self.network_commands()
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '1')
        self.assertEqual(self.network_commands(), before)

    def test_git_locked_can_rebuild_a_cold_cache_without_reresolving_tags(self):
        self.git_fixture()
        self.package('app', 'import dep; import std; fn main() { print(dep::make().x); }')
        self.git_dependency('app', 'dep', rev='v1.0.0')
        self.run_honk('fetch')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        self.git('tag', '-f', 'v1.0.0', 'v2.0.0')
        self.env['HONK_HOME'] = str(self.root / 'fresh-cache')
        self.assertEqual(self.run_honk(extra=('--locked',)).stdout.strip(), '1')
        self.assertEqual(lock.read_bytes(), original)

    def test_git_dirty_cached_source_is_rejected(self):
        self.git_fixture()
        self.package('app', 'import dep; fn main() { dep::make(); }')
        self.git_dependency('app', 'dep', rev='v1.0.0')
        self.run_honk('fetch')
        lock = (self.root / 'app/Honk.lock').read_bytes()
        metadata = json.loads((self.root / 'app/target/isolated/graph.json').read_text())
        cached = next(Path(n['directory']) for n in metadata['nodes'] if n['source']['locator'].startswith('git:'))
        (cached / 'mathx.goose').write_text('namespace versioned; fn make() -> i64 { 999 }')
        before = self.network_commands()
        self.assertIn('local changes', self.run_honk('check', ok=False, extra=('--frozen',)).stderr)
        self.assertEqual(self.network_commands(), before)
        self.assertEqual((self.root / 'app/Honk.lock').read_bytes(), lock)

    def test_git_nested_path_preserves_provenance(self):
        self.git_fixture()
        nested = self.remote / 'nested'
        nested.mkdir()
        (nested / 'Honk.toml').write_text('[package]\nname="helper"\nkind="lib"\nentry="helper.goose"\n')
        (nested / 'helper.goose').write_text('namespace helper; fn answer() -> i64 { 7 }')
        with (self.remote / 'Honk.toml').open('a') as f:
            f.write('[dependencies]\nhelper = { path="nested" }\n')
        with (self.remote / 'mathx.goose').open('a') as f:
            f.write(' import helper; fn nested_answer() -> i64 { helper::answer() }')
        self.git('add', '.')
        self.git('commit', '-qm', 'nested')
        commit = self.git('rev-parse', 'HEAD')
        self.package('app', 'import dep; import std; fn main() { print(dep::nested_answer()); }')
        self.git_dependency('app', 'dep', rev=commit)
        self.assertEqual(self.run_honk().stdout.strip(), '7')
        graph = json.loads((self.root / 'app/target/isolated/graph.json').read_text())
        nested = next(n for n in graph['nodes'] if n['source']['name'] == 'helper')
        self.assertEqual(nested['source']['revision'], commit)
        self.assertEqual(nested['source']['subdir'], 'nested')
        before = self.network_commands()
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '7')
        self.assertEqual(self.network_commands(), before)

    def test_git_update_selects_new_tag_but_locked_keeps_old(self):
        self.git_fixture()
        self.package('app', 'import dep; import std; fn main() { print(dep::make().x); }')
        self.git_dependency('app', 'dep', version='^1.0.0')
        self.run_honk('fetch')
        (self.remote / 'Honk.toml').write_text('[package]\nname="mathx"\nversion="1.1.0"\nkind="lib"\nentry="mathx.goose"\n')
        (self.remote / 'mathx.goose').write_text('namespace versioned; struct Value { x: i64 } fn make() -> Value { Value { 7 } }')
        self.git('add', '.')
        self.git('commit', '-qm', '1.1.0')
        self.git('tag', 'v1.1.0')
        before = self.network_commands()
        self.assertEqual(self.run_honk(extra=('--locked',)).stdout.strip(), '1')
        self.assertEqual(self.network_commands(), before)
        self.assertIn('cannot be combined', self.run_honk('update', ok=False, extra=('--frozen',)).stderr)
        self.run_honk('update')
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '7')

    def test_git_same_request_is_resolved_once_even_if_tag_moves(self):
        commits = self.git_fixture()
        shim = self.root / 'tools/git'
        source = shim.read_text()
        source = source.replace('os.execv(real,[real,*a])', 'if "fetch" in a and a[-1] == "v1.0.0":\n    result = subprocess.run([real,*a])\n    subprocess.run([real,"-C",os.environ["TEST_REMOTE"],"tag","-f","v1.0.0",os.environ["TEST_AFTER_FETCH"]],stdout=subprocess.DEVNULL,check=True)\n    sys.exit(result.returncode)\nos.execv(real,[real,*a])')
        shim.write_text(source)
        self.env['TEST_AFTER_FETCH'] = commits[1]
        self.package('app', 'import a; import b; import std; fn main() { let x = a::next(); let y = b::next(); print(x, " ", y); }')
        self.git_dependency('app', 'a', rev='v1.0.0')
        self.git_dependency('app', 'b', rev='v1.0.0')
        self.assertEqual(self.run_honk().stdout.strip(), '1 2')
        graph = json.loads((self.root / 'app/target/isolated/graph.json').read_text())
        self.assertEqual(len(graph['nodes']), 2)
        calls = [a for a in self.network_commands() if 'fetch' in a and a[-1] == 'v1.0.0']
        self.assertEqual(len(calls), 1)

    def test_git_forged_pin_rejected_before_fetch(self):
        commits = self.git_fixture()
        self.package('app', 'import dep; fn main() { dep::make(); }')
        self.git_dependency('app', 'dep', rev=commits[0])
        self.run_honk('fetch')
        lock = self.root / 'app/Honk.lock'
        text = lock.read_text().replace('commit = "' + commits[0] + '"', 'commit = "' + commits[1] + '"')
        lock.write_text(text)
        before = self.network_commands()
        self.assertIn('differs from exact requested commit', self.run_honk('check', ok=False, extra=('--frozen',)).stderr)
        self.assertEqual(self.network_commands(), before)
        self.assertEqual(lock.read_text(), text)

    def test_git_path_dependency_cannot_escape_checkout(self):
        self.git_fixture()
        outside = self.package('outside', 'namespace outside; fn answer() -> i64 { 7 }')
        with (self.remote / 'Honk.toml').open('a') as f:
            f.write('[dependencies]\nhelper = { path = ' + json.dumps(str(outside)) + ' }\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'escape')
        commit = self.git('rev-parse', 'HEAD')
        self.package('app', 'import dep; fn main() { dep::make(); }')
        self.git_dependency('app', 'dep', rev=commit)
        self.assertIn('escapes its checkout', self.run_honk('check', ok=False).stderr)
        self.assertFalse((self.root / 'app/Honk.lock').exists())

    def test_git_owner_specific_pins_precede_shared_request_cache(self):
        self.git_fixture()
        self.package('a', 'namespace client; import dep; fn answer() -> i64 { dep::make().x }')
        self.package('b', 'namespace client; import dep; fn answer() -> i64 { dep::make().x }')
        self.git_dependency('a', 'dep', rev='v1.0.0')
        self.git_dependency('b', 'dep', rev='v2.0.0')
        self.package('app', 'import a; import b; import std; fn main() { print(a::answer(), " ", b::answer()); }', {'a': 'a', 'b': 'b'})
        self.run_honk('fetch')
        manifest = self.root / 'b/Honk.toml'
        manifest.write_text(manifest.read_text().replace('v2.0.0', 'v1.0.0'))
        lock = self.root / 'app/Honk.lock'
        # Model a valid historical pin from before a mutable ref was moved.
        text = lock.read_text().replace('rev = "v2.0.0"', 'rev = "v1.0.0"').replace('selected_ref = "v2.0.0"', 'selected_ref = "v1.0.0"')
        lock.write_text(text)
        before = self.network_commands()
        self.assertEqual(self.run_honk().stdout.strip(), '1 2')
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '1 2')
        self.assertEqual(self.network_commands(), before)
        self.assertEqual(lock.read_text(), text)

    def registry_fixture(self):
        from registry_cli import Registry
        directory = self.root / 'registry'
        directory.mkdir()
        self.registry = Registry(directory)
        self.addCleanup(self.registry.close)
        self.registry_versions = {}

    def registry_release(self, name, version, deps=(), code=None, compiler=None, **options):
        record = self.registry.package(name, version, deps=deps, payload=(code.encode() if code else None), compiler=compiler, **options)
        self.registry_versions.setdefault(name, []).append(record)
        self.registry.index(name, self.registry_versions[name])
        return record

    def registry_dependency(self, folder, alias, package, requirement, features=()):
        with (self.root / folder / 'Honk.toml').open('a') as f:
            selection = f', features = {json.dumps(list(features))}' if features else ''
            f.write(f'{alias} = {{ package = "{package}", version = "{requirement}", registry = "{self.registry.url}/index"{selection} }}\n')

    def test_registry_incompatible_diamond_and_frozen(self):
        self.registry_fixture()
        for version, value in [('1.0.0', 1), ('2.0.0', 2)]:
            self.registry_release('answer', version, code=f'namespace versioned; fn value() -> i64 {{ {value} }}')
        self.registry_release('client-a', '1.0.0', [('dep', 'answer', '^1.0.0')], 'namespace client; import dep; fn value() -> i64 { dep::value() }')
        self.registry_release('client-b', '1.0.0', [('dep', 'answer', '^2.0.0')], 'namespace client; import dep; fn value() -> i64 { dep::value() }')
        self.package('app', 'import a; import b; import std; fn main() { print(a::value(), " ", b::value()); }')
        self.registry_dependency('app', 'a', 'client-a', '^1.0.0')
        self.registry_dependency('app', 'b', 'client-b', '^1.0.0')
        self.assertEqual(self.run_honk().stdout.strip(), '1 2')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        before = list(self.registry.requests)
        shutil.rmtree(self.root / 'honk-cache/nest/index')
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '1 2')
        self.run_honk('build', extra=('--frozen',))
        self.assertEqual(subprocess.check_output([str(self.root / 'app/target/isolated/app')], text=True).strip(), '1 2')
        self.assertEqual(self.registry.requests, before)
        self.assertEqual(lock.read_bytes(), original)

    @unittest.skipUnless(COMPILER.get('package_graph_features'), 'graph compiler lacks feature blocks')
    def test_registry_features_unify_backtrack_and_replay_frozen(self):
        self.registry_fixture()
        self.registry_release('helper', '1.0.0')
        self.registry_release('unused', '1.0.0')
        self.registry_release('rejected', '1.0.0', [('fail', 'missing', '=2.0.0')])
        code = ('namespace codec; if feature("extra") { import helper; '
                'fn value() -> i64 { helper::value() } }')
        for version, child in [('1.0.0', 'helper'), ('1.1.0', 'rejected')]:
            self.registry_release(
                'codec', version, [('helper', child, '*'), ('unused', 'unused', '*')], code,
                dependency_options={'helper': {'optional': True}, 'unused': {'optional': True}},
                features={'default': [], 'root': [], 'extra': ['internal'], 'internal': ['extra', 'dep:helper'],
                          'unused': ['dep:unused']})
        self.registry_release('bridge', '1.0.0', [('codec', 'codec', '^1.0.0')],
                              dependency_options={'codec': {'features': ['extra']}})
        self.package('app', 'import codec; import bridge; import std; fn main() { print(codec::value()); }')
        self.registry_dependency('app', 'codec', 'codec', '^1.0.0', ['root'])
        self.registry_dependency('app', 'bridge', 'bridge', '*')
        # Publish the missing package without any version accepted by the rejected branch.
        self.registry_release('missing', '1.0.0')
        self.assertEqual(self.run_honk().stdout.strip(), '42')
        self.assertFalse(any('unused.toml' in path or 'rejected-1.0.0.tar.gz' in path or
                             'codec-1.1.0.tar.gz' in path for path, _ in self.registry.requests))
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        data = tomllib.loads(original.decode())
        self.assertEqual({f['name'] for f in data['feature']}, {'default', 'extra', 'internal', 'root'})
        self.assertEqual(len(data['feature']), 4)
        self.assertEqual(len(data['binding']), 4)
        before = list(self.registry.requests)
        shutil.rmtree(self.root / 'honk-cache/nest/index')
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '42')
        self.run_honk('build', extra=('--frozen',))
        self.assertEqual(subprocess.check_output([str(self.root / 'app/target/isolated/app')], text=True).strip(), '42')
        self.assertEqual(self.registry.requests, before)
        self.assertEqual(lock.read_bytes(), original)

    @unittest.skipUnless(COMPILER.get('package_graph_features'), 'graph compiler lacks feature blocks')
    def test_registry_feature_filters_versions_and_reports_missing_name(self):
        self.registry_fixture()
        self.registry_release('codec', '1.0.0', features={'extra': []})
        self.registry_release('codec', '1.1.0')
        app = self.package('app', 'fn main() {}')
        self.registry_dependency('app', 'codec', 'codec', '^1.0.0', ['extra'])
        self.run_honk('fetch')
        self.assertFalse(any('codec-1.1.0.tar.gz' in path for path, _ in self.registry.requests))
        lock = app / 'Honk.lock'
        original = lock.read_bytes()
        manifest = app / 'Honk.toml'
        manifest.write_text(manifest.read_text().replace('"extra"', '"unknown"'))
        result = self.run_honk('fetch', ok=False)
        self.assertIn('unknown feature unknown', result.stderr)
        self.assertEqual(lock.read_bytes(), original)

    @unittest.skipUnless(COMPILER.get('package_graph_features'), 'graph compiler lacks feature blocks')
    def test_registry_archive_feature_metadata_must_match(self):
        self.registry_fixture()
        record = self.registry_release('codec', '1.0.0', features={'default': []})
        record['features']['extra'] = []
        self.registry.index('codec', [record])
        self.package('app', 'fn main() {}')
        self.registry_dependency('app', 'codec', 'codec', '*', ['extra'])
        result = self.run_honk('fetch', ok=False)
        self.assertIn('archive feature count differs', result.stderr)
        self.assertFalse((self.root / 'app/Honk.lock').exists())

    def test_registry_compatible_versions_backtrack_before_download(self):
        self.registry_fixture()
        code = 'namespace versioned; var count: i64 = 0; fn next() -> i64 { count++; count }'
        self.registry_release('answer', '1.0.0', code=code)
        self.registry_release('answer', '1.1.0', code=code)
        self.package('app', 'import a; import b; import std; fn main() { let x = a::next(); let y = b::next(); print(x, " ", y); }')
        self.registry_dependency('app', 'a', 'answer', '^1.0.0')
        self.registry_dependency('app', 'b', 'answer', '=1.0.0')
        self.assertEqual(self.run_honk().stdout.strip(), '1 2')
        self.assertFalse(any('answer-1.1.0.tar.gz' in path for path, _ in self.registry.requests))
        graph = json.loads((self.root / 'app/target/isolated/graph.json').read_text())
        self.assertEqual(len(graph['nodes']), 2)

    def test_registry_conflicting_compatible_pins_preserve_lock_without_archives(self):
        self.registry_fixture()
        self.registry_release('answer', '1.0.0')
        self.registry_release('answer', '1.1.0')
        self.package('app', 'fn main() {}')
        self.run_honk('check')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        self.registry_dependency('app', 'a', 'answer', '=1.0.0')
        self.registry_dependency('app', 'b', 'answer', '=1.1.0')
        self.assertIn('no compatible scoped registry graph', self.run_honk('fetch', ok=False).stderr)
        self.assertEqual(lock.read_bytes(), original)
        self.assertFalse(any(path.endswith('.tar.gz') for path, _ in self.registry.requests))

    def test_registry_locked_constraint_change_and_missing_source_preserve_lock(self):
        self.registry_fixture()
        self.registry_release('answer', '1.0.0')
        self.registry_release('answer', '2.0.0')
        self.package('app', 'fn main() {}')
        self.registry_dependency('app', 'dep', 'answer', '^1.0.0')
        self.run_honk('fetch')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        manifest = self.root / 'app/Honk.toml'
        text = manifest.read_text()
        manifest.write_text(text.replace('^1.0.0', '^2.0.0'))
        before = list(self.registry.requests)
        self.run_honk('fetch', ok=False, extra=('--locked',))
        self.assertEqual(self.registry.requests, before)
        self.assertEqual(lock.read_bytes(), original)
        manifest.write_text(text)
        shutil.rmtree(self.root / 'honk-cache/nest/packages')
        self.run_honk('fetch', ok=False, extra=('--frozen',))
        self.assertEqual(self.registry.requests, before)
        self.assertEqual(lock.read_bytes(), original)

    def test_registry_lock_preference_update_and_yanks(self):
        self.registry_fixture()
        first = self.registry_release('answer', '1.0.0', code='namespace answer; fn value() -> i64 { 1 }')
        self.package('app', 'import dep; import std; fn main() { print(dep::value()); }')
        self.registry_dependency('app', 'dep', 'answer', '^1.0.0')
        self.run_honk('fetch')
        second = self.registry_release('answer', '1.1.0', code='namespace answer; fn value() -> i64 { 2 }')
        before = list(self.registry.requests)
        self.assertEqual(self.run_honk(extra=('--locked',)).stdout.strip(), '1')
        self.assertEqual(self.registry.requests, before)
        self.run_honk('update')
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '2')
        second['yanked'] = True
        self.registry.index('answer', [first, second])
        before = list(self.registry.requests)
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '2')
        self.assertEqual(self.registry.requests, before)
        self.run_honk('update')
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '1')

    def test_registry_wrong_version_nominal_types_rejected(self):
        self.registry_fixture()
        for version in ('1.0.0', '2.0.0'):
            self.registry_release('answer', version, code='namespace versioned; struct Value { x: i64 } fn make() -> Value { Value { 1 } }')
        self.package('app', 'import a; import b; fn take(v: b::Value) {} fn main() { take(a::make()); }')
        self.registry_dependency('app', 'a', 'answer', '^1.0.0')
        self.registry_dependency('app', 'b', 'answer', '^2.0.0')
        self.assertIn('answer@', self.run_honk('check', ok=False).stderr)

    def test_registry_cycle_can_backtrack_to_older_release(self):
        self.registry_fixture()
        self.registry_release('client', '1.0.0')
        self.registry_release('client', '1.1.0', [('dep', 'answer', '^1.0.0')])
        self.registry_release('answer', '1.0.0', [('dep', 'client', '=1.1.0')])
        self.package('app', 'fn main() {}')
        self.registry_dependency('app', 'dep', 'client', '^1.0.0')
        self.run_honk('fetch')
        archives = [path for path, _ in self.registry.requests if path.endswith('.tar.gz')]
        self.assertEqual(archives, ['/client-1.0.0.tar.gz'])

    def test_registry_distinct_origins_with_identical_archive_keep_separate_state(self):
        from registry_cli import Registry
        self.registry_fixture()
        record = self.registry_release('answer', '1.0.0', code='namespace answer; var count: i64 = 0; fn next() -> i64 { count++; count }')
        other_root = self.root / 'other-registry'
        other_root.mkdir()
        other = Registry(other_root)
        self.addCleanup(other.close)
        (other_root / 'answer-1.0.0.tar.gz').write_bytes((self.root / 'registry/answer-1.0.0.tar.gz').read_bytes())
        second = {**record, 'url': other.url + '/answer-1.0.0.tar.gz'}
        other.index('answer', [second])
        self.package('app', 'import a; import b; import std; fn main() { let x = a::next(); let y = b::next(); print(x, " ", y); }')
        self.registry_dependency('app', 'a', 'answer', '^1.0.0')
        with (self.root / 'app/Honk.toml').open('a') as f:
            f.write(f'b = {{package="answer", version="^1.0.0", registry="{other.url}/index"}}\n')
        self.assertEqual(self.run_honk().stdout.strip(), '1 1')

    def test_registry_cached_tree_integrity_and_archive_manifest_validation(self):
        self.registry_fixture()
        self.registry_release('answer', '1.0.0')
        self.package('app', 'fn main() {}')
        self.registry_dependency('app', 'dep', 'answer', '^1.0.0')
        self.run_honk('fetch')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        graph = json.loads((self.root / 'app/target/isolated/graph.json').read_text())
        cached = next(Path(n['directory']) for n in graph['nodes'] if n['source']['locator'].startswith('registry:'))
        (cached / 'lib.goose').write_text('fn corrupted() {}')
        before = list(self.registry.requests)
        self.run_honk('fetch', ok=False, extra=('--frozen',))
        self.assertEqual(self.registry.requests, before)
        self.assertEqual(lock.read_bytes(), original)

    def test_registry_generated_graphs_against_exhaustive_oracle(self):
        from scoped_registry_oracle import check
        self.registry_fixture()
        check(self)

    def test_registry_qualified_base_compiler_and_unknown_pin(self):
        self.registry_fixture()
        self.registry_release('answer', '1.0.0', code='namespace answer; fn value() -> i64 { 1 }', compiler='eadca409f68210893f366e60d0c2f0dc29a339be')
        self.registry_release('answer', '2.0.0', compiler='f' * 40)
        self.package('app', 'import dep; import std; fn main() { print(dep::value()); }')
        self.registry_dependency('app', 'dep', 'answer', '^1.0.0')
        self.assertEqual(self.run_honk().stdout.strip(), '1')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        manifest = self.root / 'app/Honk.toml'
        manifest.write_text(manifest.read_text().replace('^1.0.0', '^2.0.0'))
        self.assertIn('matching compiler revision', self.run_honk('fetch', ok=False).stderr)
        self.assertEqual(lock.read_bytes(), original)

    def test_registry_new_root_retains_existing_yanked_pin(self):
        self.registry_fixture()
        first = self.registry_release('answer', '1.0.0', code='namespace answer; fn value() -> i64 { 1 }')
        self.package('app', 'import dep; import std; fn main() { print(dep::value()); }')
        self.registry_dependency('app', 'dep', 'answer', '^1.0.0')
        self.run_honk('fetch')
        lock = self.root / 'app/Honk.lock'
        pinned = next(b['record'] for b in tomllib.loads(lock.read_text())['binding'] if b.get('registry'))
        second = self.registry_release('answer', '1.1.0', code='namespace answer; fn value() -> i64 { 2 }')
        first['yanked'] = True
        self.registry.index('answer', [first, second])
        self.registry_release('other', '1.0.0')
        self.registry_dependency('app', 'other', 'other', '^1.0.0')
        self.assertEqual(self.run_honk().stdout.strip(), '1')
        updated = next(b['record'] for b in tomllib.loads(lock.read_text())['binding'] if b['alias'] == 'dep')
        self.assertEqual(updated, pinned)
        self.assertFalse(any('answer-1.1.0.tar.gz' in path for path, _ in self.registry.requests))

    def test_registry_immutable_metadata_change_rejected(self):
        self.registry_fixture()
        first = self.registry_release('answer', '1.0.0')
        self.package('app', 'fn main() {}')
        self.registry_dependency('app', 'dep', 'answer', '^1.0.0')
        self.run_honk('fetch')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        first['sha256'] = 'f' * 64
        self.registry.index('answer', [first])
        before = len(self.registry.requests)
        self.assertIn('published registry metadata changed', self.run_honk('update', ok=False).stderr)
        self.assertEqual(lock.read_bytes(), original)
        self.assertFalse(any(path.endswith('.tar.gz') for path, _ in self.registry.requests[before:]))

    def test_registry_archive_manifest_mismatch_preserves_lock(self):
        self.registry_fixture()
        record = self.registry_release('answer', '1.0.0')
        record['entry'] = 'other.goose'
        self.registry.index('answer', [record])
        self.package('app', 'fn main() {}')
        self.run_honk('check')
        lock = self.root / 'app/Honk.lock'
        original = lock.read_bytes()
        self.registry_dependency('app', 'dep', 'answer', '^1.0.0')
        self.assertIn('archive manifest differs', self.run_honk('fetch', ok=False).stderr)
        self.assertEqual(lock.read_bytes(), original)

    def test_registry_discovered_inside_git_package(self):
        self.git_fixture()
        self.registry_fixture()
        self.registry_release('answer', '1.0.0', code='namespace answer; fn value() -> i64 { 42 }')
        with (self.remote / 'Honk.toml').open('a') as f:
            f.write('[dependencies]\nanswer = {package="answer", version="^1.0.0", registry="' + self.registry.url + '/index"}\n')
        with (self.remote / 'mathx.goose').open('a') as f:
            f.write(' import answer; fn registry_value() -> i64 { answer::value() }')
        self.git('add', '.')
        self.git('commit', '-qm', 'registry dependency')
        commit = self.git('rev-parse', 'HEAD')
        self.package('app', 'import dep; import std; fn main() { print(dep::registry_value()); }')
        self.git_dependency('app', 'dep', rev=commit)
        self.assertEqual(self.run_honk().stdout.strip(), '42')
        before = list(self.registry.requests), self.network_commands()
        self.assertEqual(self.run_honk(extra=('--frozen',)).stdout.strip(), '42')
        self.assertEqual((self.registry.requests, self.network_commands()), before)

    def workspace(self):
        for member in ('a', 'b'):
            self.package(member, 'import dep; import std; fn main() { print(dep::value()); }')
        manifest = self.root / 'Honk.toml'
        manifest.write_text(f'[workspace]\nmembers = ["b", "a"]\n[toolchain]\nrevision = "{REVISION}"\n')
        return manifest

    def test_workspace_resolves_all_members_and_compiles_selected_closure(self):
        self.registry_fixture()
        self.registry_release('answer', '1.0.0', code='namespace answer; fn value() -> i64 { 10 }')
        self.registry_release('answer', '1.1.0', code='namespace answer; fn value() -> i64 { 11 }')
        manifest = self.workspace()
        self.registry_dependency('a', 'dep', 'answer', '^1.0.0')
        self.registry_dependency('b', 'dep', 'answer', '=1.0.0')
        self.assertEqual(self.run_honk(extra=('-p', 'a'), cwd=self.root).stdout.strip(), '10')
        lock = self.root / 'Honk.lock'
        original = lock.read_bytes()
        data = tomllib.loads(original.decode())
        self.assertEqual(data['members'], ['a', 'b'])
        self.assertEqual({e['owner'] for e in data['binding']}, {'a', 'b'})
        graph = json.loads((self.root / 'target/isolated/members/0/graph.json').read_text())
        self.assertEqual({n['source']['name'] for n in graph['nodes']}, {'a', 'answer'})
        self.assertFalse(any('answer-1.1.0.tar.gz' in p for p, _ in self.registry.requests))
        self.assertFalse(any((self.root / m / 'Honk.lock').exists() for m in ('a', 'b')))
        before = list(self.registry.requests)
        manifest.write_text(manifest.read_text().replace('"b", "a"', '"a", "b"'))
        self.run_honk('build', extra=('--workspace', '--frozen'), cwd=self.root)
        for index, member in enumerate(('a', 'b')):
            binary = self.root / f'target/isolated/members/{index}/{member}'
            self.assertEqual(subprocess.check_output([str(binary)], text=True).strip(), '10')
        self.assertEqual(lock.read_bytes(), original)
        self.assertEqual(self.registry.requests, before)

    def test_workspace_conflict_preserves_lock_even_when_selecting_one_member(self):
        self.registry_fixture()
        self.registry_release('answer', '1.0.0')
        self.registry_release('answer', '1.1.0')
        self.workspace()
        self.registry_dependency('a', 'dep', 'answer', '=1.0.0')
        self.registry_dependency('b', 'dep', 'answer', '=1.0.0')
        self.run_honk('fetch', cwd=self.root)
        lock = self.root / 'Honk.lock'
        original = lock.read_bytes()
        other = self.root / 'b/Honk.toml'
        other.write_text(other.read_text().replace('=1.0.0', '=1.1.0'))
        before = list(self.registry.requests)
        self.run_honk('fetch', ok=False, extra=('-p', 'a', '--frozen'), cwd=self.root)
        self.assertEqual(self.registry.requests, before)
        result = self.run_honk('check', ok=False, extra=('-p', 'a'), cwd=self.root)
        self.assertIn('no compatible scoped registry graph', result.stderr)
        self.assertEqual(lock.read_bytes(), original)

    def test_workspace_check_library_and_member_manifest_selection(self):
        self.workspace()
        manifest = self.root / 'b/Honk.toml'
        manifest.write_text(manifest.read_text().replace('name = "b"', 'name = "b"\nkind = "lib"'))
        (self.root / 'b/entry.goose').write_text('namespace library; fn value() -> i64 { 1 }')
        (self.root / 'a/entry.goose').write_text('fn main() {}')
        self.run_honk('check', extra=('--workspace',), cwd=self.root)
        self.run_honk('check', extra=('--manifest-path', '../Honk.toml', '-p', 'b', '--frozen'), cwd=self.root / 'b')
        self.assertIn('single target', self.run_honk(ok=False, cwd=self.root).stderr)

    def test_features_activate_transitive_optional_dependencies_and_lock_selection(self):
        app = self.package('app', 'import client; import std; fn main() { print(client::value()); }')
        client = self.package('client', 'namespace client; import helper; fn value() -> i64 { helper::value() }')
        self.package('helper', 'namespace helper; fn value() -> i64 { 17 }')
        with (app / 'Honk.toml').open('a') as f:
            f.write('client = {path="../client", optional=true}\n[features]\nfull=["io"]\nio=["dep:client", "full"]\n')
        with (client / 'Honk.toml').open('a') as f:
            f.write('helper = {path="../helper", optional=true}\n[features]\ndefault=["dep:helper"]\n')
        self.run_honk('fetch')
        lock = app / 'Honk.lock'
        self.assertNotIn('[[binding]]', lock.read_text())
        before = lock.read_bytes()
        self.assertIn('out of date', self.run_honk('fetch', ok=False, extra=('--features', 'full', '--frozen')).stderr)
        self.assertEqual(lock.read_bytes(), before)
        self.assertEqual(self.run_honk(extra=('--features', 'full')).stdout.strip(), '17')
        data = tomllib.loads(lock.read_text())
        self.assertEqual({(f['owner'], f['name']) for f in data['feature']},
                         {('.', 'full'), ('.', 'io'), ('../client', 'default')})
        before = lock.read_bytes()
        self.assertEqual(self.run_honk(extra=('--features', 'io,full', '--frozen')).stdout.strip(), '17')
        self.assertEqual(lock.read_bytes(), before)

    def test_features_default_can_disable_optional_registry_requests(self):
        self.registry_fixture()
        self.registry_release('answer', '1.0.0')
        app = self.package('app', 'fn main() {}')
        (app / 'Honk.toml').write_text((app / 'Honk.toml').read_text()
            + f'dep={{package="answer", version="^1.0.0", registry="{self.registry.url}/index", optional=true}}\n'
            + '[features]\ndefault=["dep:dep"]\n')
        self.run_honk('fetch', extra=('--no-default-features',))
        self.assertEqual(self.registry.requests, [])
        self.run_honk('fetch')
        self.assertTrue(any(path.endswith('.tar.gz') for path, _ in self.registry.requests))
        before = list(self.registry.requests)
        self.run_honk('check', extra=('--frozen',))
        self.assertEqual(self.registry.requests, before)

    def test_invalid_features_preserve_lock_and_fail_closed(self):
        app = self.package('app', 'fn main() {}')
        self.run_honk('fetch')
        lock = app / 'Honk.lock'
        before = lock.read_bytes()
        self.assertIn('unknown feature missing', self.run_honk('fetch', ok=False, extra=('--features', 'missing')).stderr)
        with (app / 'Honk.toml').open('a') as f:
            f.write('[features]\ndefault=["dep:missing"]\n')
        self.assertIn('unknown optional dependency', self.run_honk('fetch', ok=False).stderr)
        self.assertEqual(lock.read_bytes(), before)
        normal = subprocess.run([str(HONK), 'fetch'], cwd=app, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(normal.returncode, 0)
        self.assertIn('features require an isolated package manifest', normal.stderr)

    def test_dependency_features_unify_late_requests_and_replay_frozen(self):
        app = self.package('app', 'fn main() {}')
        shared = self.package('shared', 'namespace shared; fn value() -> i64 { 1 }')
        bridge = self.package('bridge', 'namespace bridge; fn value() -> i64 { 2 }')
        self.package('first', 'namespace first; fn value() -> i64 { 3 }')
        self.package('second', 'namespace second; fn value() -> i64 { 4 }')
        with (app / 'Honk.toml').open('a') as f:
            f.write('shared={path="../shared",features=["one"]}\nbridge={path="../bridge"}\n')
        with (bridge / 'Honk.toml').open('a') as f:
            f.write('shared={path="../shared",features=["two","one"]}\n')
        with (shared / 'Honk.toml').open('a') as f:
            f.write('first={path="../first",optional=true}\nsecond={path="../second",optional=true}\n'
                    '[features]\none=["dep:first"]\ntwo=["dep:second"]\n')
        self.run_honk('fetch')
        lock = app / 'Honk.lock'
        before = lock.read_bytes()
        data = tomllib.loads(before.decode())
        self.assertEqual([(f['owner'], f['name']) for f in data['feature']],
                         [('../shared', 'one'), ('../shared', 'two')])
        self.assertEqual({b['alias'] for b in data['binding'] if b['owner'] == '../shared'},
                         {'first', 'second'})
        self.assertEqual(len(data['binding']), 5)
        self.run_honk('check', extra=('--frozen',))
        self.assertEqual(lock.read_bytes(), before)
        manifest = bridge / 'Honk.toml'
        manifest.write_text(manifest.read_text().replace('"two","one"', '"missing"'))
        result = self.run_honk('fetch', ok=False)
        self.assertIn('unknown feature missing in shared requested through shared', result.stderr)
        self.assertEqual(lock.read_bytes(), before)

    def test_git_dependency_feature_selection_is_per_commit(self):
        old, _ = self.git_fixture()
        with (self.remote / 'Honk.toml').open('a') as f:
            f.write('[features]\nextra=[]\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'declare feature')
        new = self.git('rev-parse', 'HEAD')
        app = self.package('app', 'fn main() {}')
        with (app / 'Honk.toml').open('a') as f:
            f.write(f'old={{git="https://test.invalid/mathx.git",rev="{old}"}}\n'
                    f'new={{git="https://test.invalid/mathx.git",rev="{new}",features=["extra"]}}\n')
        self.run_honk('fetch')
        lock = app / 'Honk.lock'
        before = lock.read_bytes()
        self.assertEqual(tomllib.loads(before.decode())['feature'],
                         [{'owner': f'git:https://test.invalid/mathx.git@{new}', 'name': 'extra'}])
        network = self.network_commands()
        self.run_honk('check', extra=('--frozen',))
        self.assertEqual(self.network_commands(), network)
        self.assertEqual(lock.read_bytes(), before)

    @unittest.skipUnless(COMPILER.get('package_graph_features'), 'graph compiler lacks feature blocks')
    def test_feature_blocks_gate_optional_import_end_to_end(self):
        self.package('extra', 'namespace extra; fn value() -> i64 { 9 }')
        app = self.package('app', 'import std; if feature("io") { import extra; '
                           'fn main() { print(extra::value()); } } else { fn main() { print(0); } }')
        with (app / 'Honk.toml').open('a') as f:
            f.write('extra={path="../extra",optional=true}\n[features]\nio=["dep:extra"]\n')
        self.assertEqual(self.run_honk().stdout.strip(), '0')
        self.assertEqual(self.run_honk(extra=('--features', 'io')).stdout.strip(), '9')
        self.run_honk('build', extra=('--frozen', '--features', 'io'))
        binary = app / 'target/isolated/app'
        self.assertEqual(subprocess.check_output([str(binary)], text=True).strip(), '9')

    def test_wrong_nominal_version_rejected(self):
        self.diamond()
        p = self.root / 'app'
        text = (p / 'Honk.toml').read_text()
        (p / 'Honk.toml').write_text(text + 'old = { path = "../one" }\nnewer = { path = "../two" }\n')
        (p / 'entry.goose').write_text('import old; import newer; fn take(v: newer::Value) {} fn main() { take(old::make()); }')
        self.assertIn('dep@', self.run_honk('check', ok=False).stderr)


if __name__ == '__main__':
    unittest.main()

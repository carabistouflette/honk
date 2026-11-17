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
REVISION = json.loads(subprocess.check_output([str(GOOSE), 'version', '--json']))['compiler_revision']


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

    def run_honk(self, command='run', ok=True, extra=()):
        result = subprocess.run([str(HONK), command, '--isolated', *extra], cwd=self.root / 'app',
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

    def test_wrong_nominal_version_rejected(self):
        self.diamond()
        p = self.root / 'app'
        text = (p / 'Honk.toml').read_text()
        (p / 'Honk.toml').write_text(text + 'old = { path = "../one" }\nnewer = { path = "../two" }\n')
        (p / 'entry.goose').write_text('import old; import newer; fn take(v: newer::Value) {} fn main() { take(old::make()); }')
        self.assertIn('dep@', self.run_honk('check', ok=False).stderr)


if __name__ == '__main__':
    unittest.main()

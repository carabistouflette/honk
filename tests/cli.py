#!/usr/bin/env python3
"""Black-box regressions: real files, real executable, no shell interpolation."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import tarfile
import tempfile
import unittest

HONK = os.environ['HONK']
GOOSE = os.environ['GOOSE']

class CLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk test ')
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def run_honk(self, *args, cwd=None, ok=True, env=None):
        proc = subprocess.run([HONK, *map(str, args)], cwd=cwd or self.root,
                              env={**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache'), **(env or {})},
                              capture_output=True, text=True, timeout=90)
        self.assertEqual(proc.returncode == 0, ok, proc.stdout + proc.stderr)
        self.assertNotIn('AddressSanitizer', proc.stderr)
        self.assertNotIn('runtime error:', proc.stderr)
        return proc
    def new(self, name='hello', *args):
        self.run_honk('new', name, *args)
        return self.root / name
    def test_new_metadata_and_discovery(self):
        p = self.new('hello world', '--name', 'hello')
        meta = json.loads(self.run_honk('metadata', cwd=p/'src').stdout)
        self.assertEqual(meta['name'], 'hello')
        self.assertEqual(meta['entry'], 'src/main.goose')
        self.run_honk('new', p, ok=False)
    def test_init_preserves_existing(self):
        self.run_honk('init', '--name', 'hello')
        original = (self.root/'src/main.goose').read_bytes()
        self.run_honk('init', '--name', 'other', ok=False)
        self.assertEqual((self.root/'src/main.goose').read_bytes(), original)
    def test_invalid_manifests(self):
        for manifest in ['[package]\nname="../bad"', '[package]\nname="ok"\nentry="../outside.goose"',
                         '[package]\nname="ok"\nunknown=true', '[package]\nname="ok"\nname="ok"',
                         '[package]\nname="ok"\n[dependencies]\nx={git="ext::evil",rev="main"}',
                         '[package]\nname="ok"\n[dependencies]\nx={path="x",git="https://a/b",rev="main"}']:
            with self.subTest(manifest=manifest):
                (self.root/'Honk.toml').write_text(manifest)
                self.run_honk('metadata', ok=False)
    def test_manifest_bound(self):
        (self.root/'Honk.toml').write_bytes(b'#' * (1048576+1))
        self.run_honk('metadata', ok=False)
    def test_symlink_manifest(self):
        (self.root/'real.toml').write_text('[package]\nname="ok"')
        (self.root/'Honk.toml').symlink_to('real.toml')
        self.run_honk('metadata', ok=False)
    def test_build_run_check_fmt_test_and_bench(self):
        p = self.new()
        self.run_honk('fetch', cwd=p)
        self.run_honk('check', '--frozen', cwd=p)
        self.assertIn('Hello, Goose!', self.run_honk('run', '--locked', cwd=p).stdout)
        self.run_honk('build', '--release', cwd=p)
        self.assertTrue((p/'target/release/hello').is_file())
        self.run_honk('doc', cwd=p)
        self.assertTrue((p/'target/doc/hello.goose').is_file())
        self.run_honk('fmt', cwd=p)
        self.run_honk('fmt', '--check', cwd=p)
        (p/'tests').mkdir()
        (p/'tests/answer.goose').write_text('fn main() { assert(6 * 7 == 42); }')
        self.assertIn('Passed 1 test', self.run_honk('test', cwd=p).stdout)
        (p/'bench').mkdir()
        (p/'bench/timing.goose').write_text('fn main() { print("bench-ok"); }')
        self.assertIn('bench-ok', self.run_honk('bench', '--release', cwd=p).stdout)
        self.run_honk('clean', cwd=p)
        self.assertFalse((p/'target').exists())
    def test_argument_boundaries_and_exit_codes(self):
        p = self.new()
        (p/'src/main.goose').write_text('import os; fn main() { let a = args(); for x in a[1..] { print(x); } exit(7); }')
        proc = self.run_honk('run', '--', 'a b', '', '; touch /tmp/honk-injected', '--release', cwd=p, ok=False)
        self.assertEqual(proc.returncode, 7)
        self.assertIn('a b\n\n; touch /tmp/honk-injected\n--release\n', proc.stdout)
    def test_local_dependency_and_transitive_graph(self):
        lib = self.root/'lib'; lib.mkdir()
        (lib/'mathx.goose').write_text('namespace mathx; fn answer() -> i64 { 42 }')
        p = self.new()
        self.run_honk('add', 'mathx', '--path', '../lib', cwd=p)
        (p/'src/main.goose').write_text('import mathx; fn main() { print(mathx::answer()); }')
        self.assertIn('42', self.run_honk('run', cwd=p).stdout)
        self.assertIn('mathx', self.run_honk('tree', '--locked', cwd=p).stdout)
        old = (p/'Honk.lock').read_bytes()
        self.run_honk('fetch', '--frozen', cwd=p)
        self.assertEqual(old, (p/'Honk.lock').read_bytes())
        self.run_honk('remove', 'mathx', cwd=p)
        self.run_honk('fetch', '--locked', cwd=p, ok=False)
        self.run_honk('fetch', cwd=p)
    def test_manifest_library_dependency(self):
        lib = self.new('mathx', '--lib')
        (lib/'src/lib.goose').write_text('namespace mathx; fn answer() -> i64 { 42 }')
        p = self.new()
        self.run_honk('add', 'mathx', '--path', '../mathx', cwd=p)
        (p/'src/main.goose').write_text('import mathx; fn main() { print(mathx::answer()); }')
        self.assertIn('42', self.run_honk('run', cwd=p).stdout)
    def test_transitive_cycle_and_conflict(self):
        p = self.new()
        a = self.new('alpha', '--lib'); b = self.new('beta', '--lib')
        self.run_honk('add', 'beta', '--path', '../beta', cwd=a)
        self.run_honk('add', 'alpha', '--path', '../alpha', cwd=b)
        self.run_honk('add', 'alpha', '--path', '../alpha', cwd=p)
        self.assertIn('cycle', self.run_honk('fetch', cwd=p, ok=False).stderr)
    def test_lockfile_and_offline_rules(self):
        p = self.new()
        self.run_honk('build', '--locked', cwd=p, ok=False)
        self.run_honk('build', '--offline', cwd=p)
        self.run_honk('build', '--frozen', cwd=p)
        self.run_honk('update', '--locked', cwd=p, ok=False)
        (p/'Honk.lock').write_text('version=99')
        self.run_honk('fetch', cwd=p, ok=False)
    def test_symlink_sources_and_output(self):
        p = self.new()
        outside = self.root/'outside'; outside.mkdir()
        (outside/'keep').write_text('keep')
        (p/'src/link').symlink_to(outside, target_is_directory=True)
        self.run_honk('build', cwd=p, ok=False)
        (p/'src/link').unlink()
        (p/'target').symlink_to(outside, target_is_directory=True)
        self.run_honk('build', cwd=p, ok=False)
        self.run_honk('clean', cwd=p)
        self.assertEqual((outside/'keep').read_text(), 'keep')
    def test_workspace_and_selection(self):
        a = self.new('alpha'); b = self.new('beta')
        (self.root/'Honk.toml').write_text('[workspace]\nmembers=["alpha", "beta"]')
        self.run_honk('check', '--workspace')
        self.run_honk('build', '-p', 'beta')
        self.assertTrue((b/'target/debug/beta').exists())
        self.assertFalse((a/'target/debug/alpha').exists())
        self.run_honk('check', '-p', 'missing', ok=False)
    def test_legacy_source_import_and_scanner(self):
        p = self.new()
        lib = self.root/'lib'; lib.mkdir()
        (lib/'mathx.goose').write_text('namespace mathx; fn answer() -> i64 { 42 }')
        self.run_honk('add', 'mathx', '--path', '../lib', cwd=p)
        text = '/* nested /* import fake from "x"; */ */\nimport mathx from "../../lib";\nfn main() { let s = """import fake from "x";"""; print(mathx::answer(), s); }'
        (p/'src/main.goose').write_text(text)
        self.assertIn('42', self.run_honk('run', cwd=p).stdout)
        self.assertEqual((p/'src/main.goose').read_text(), text)
    def git(self, directory, *args):
        return subprocess.check_output(['git', '-C', str(directory), *args], text=True).strip()
    def git_project(self, directory):
        self.git(directory, 'init', '-q')
        self.git(directory, 'config', 'user.name', 'Honk Tests')
        self.git(directory, 'config', 'user.email', 'tests@example.invalid')
    def test_package_and_install(self):
        p = self.new()
        self.run_honk('fetch', cwd=p)
        self.git_project(p)
        self.git(p, 'add', 'Honk.toml', 'Honk.lock', 'src')
        (p/'secret.txt').write_text('do not distribute')
        self.run_honk('package', '--locked', cwd=p)
        archive = p/'target/package/hello-0.1.0.tar.gz'
        original = archive.read_bytes()
        with tarfile.open(archive) as tar:
            names = tar.getnames()
            self.assertIn('hello-0.1.0/Honk.toml', names)
            self.assertNotIn('hello-0.1.0/secret.txt', names)
        self.run_honk('package', '--locked', cwd=p)
        self.assertEqual(archive.read_bytes(), original)
        dest = self.root/'installed binaries'
        self.run_honk('install', '--root', dest, cwd=p)
        self.assertIn('Hello, Goose!', subprocess.check_output([dest/'bin/hello'], text=True))
        self.run_honk('install', '--root', dest, cwd=p, ok=False)
        self.run_honk('install', '--root', dest, '--force', cwd=p)
        self.run_honk('uninstall', 'hello', '--root', dest)
        self.assertFalse((dest/'bin/hello').exists())
        self.run_honk('uninstall', 'hello', '--root', dest, ok=False)
    def test_https_git_lock_update_offline_and_tamper(self):
        remote = self.root/'remote'; remote.mkdir(); self.git_project(remote)
        (remote/'mathx.goose').write_text('namespace mathx; fn answer() -> i64 { 42 }')
        self.git(remote, 'add', '.'); self.git(remote, 'commit', '-qm', 'initial')
        first = self.git(remote, 'rev-parse', 'HEAD')
        # A transport shim maps one HTTPS test origin to a local Git repository.
        # Honk still runs all real init/fetch/rev-parse/worktree operations.
        shim = self.root/'tools'; shim.mkdir(); real_git = shutil.which('git')
        (shim/'git').write_text('#!/usr/bin/env python3\nimport os, sys\na = [x.replace("protocol.file.allow=never", "protocol.file.allow=always") for x in sys.argv[1:]]\na = [os.environ["TEST_REMOTE"] if x == "https://test.invalid/mathx.git" else x for x in a]\nos.environ["GIT_ALLOW_PROTOCOL"] = "file"\nos.execv(os.environ["TEST_GIT"], [os.environ["TEST_GIT"], *a])\n')
        (shim/'git').chmod(0o755)
        env = {'PATH': str(shim)+os.pathsep+os.environ['PATH'], 'TEST_REMOTE': str(remote), 'TEST_GIT': real_git}
        p = self.new()
        self.run_honk('add', 'mathx', '--git', 'https://test.invalid/mathx.git', '--rev', 'HEAD', cwd=p)
        (p/'src/main.goose').write_text('import mathx; fn main() { print(mathx::answer()); }')
        self.assertIn('42', self.run_honk('run', cwd=p, env=env).stdout)
        self.assertIn(first, (p/'Honk.lock').read_text())
        (remote/'mathx.goose').write_text('namespace mathx; fn answer() -> i64 { 43 }')
        self.git(remote, 'add', '.'); self.git(remote, 'commit', '-qm', 'update')
        second = self.git(remote, 'rev-parse', 'HEAD')
        self.assertIn('42', self.run_honk('run', '--frozen', cwd=p, env=env).stdout)
        self.run_honk('update', cwd=p, env=env)
        self.assertIn(second, (p/'Honk.lock').read_text())
        self.assertIn('43', self.run_honk('run', '--frozen', cwd=p, env=env).stdout)
        cached = next((self.root/'cache/sources').glob('*'+second))
        (cached/'mathx.goose').write_text('namespace mathx; fn answer() -> i64 { 99 }')
        self.assertIn('local changes', self.run_honk('fetch', '--frozen', cwd=p, env=env, ok=False).stderr)
        self.git(cached, 'restore', 'mathx.goose')
        # A wrong cached checkout must fail instead of silently compiling it.
        cached = next((self.root/'cache/sources').glob('*'+second))
        shutil.rmtree(cached)
        self.run_honk('fetch', cwd=p, env=env)
        self.assertTrue(cached.is_dir())
        self.git(cached, '-c', 'advice.detachedHead=false', 'checkout', '--quiet', '--detach', first)
        self.run_honk('fetch', '--frozen', cwd=p, env=env, ok=False)
    def test_cache_and_project_lock_contention(self):
        import fcntl
        p = self.new()
        state = p/'.honk'; state.mkdir()
        with (state/'lock').open('w') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertIn('locked', self.run_honk('build', cwd=p, ok=False).stderr)
        self.run_honk('check', cwd=p)
        with (self.root/'cache/lock').open('w') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertIn('locked', self.run_honk('build', cwd=p, ok=False).stderr)
    def test_metadata_preservation_and_diagnostic_escaping(self):
        p = self.new()
        with (p/'Honk.toml').open('a') as stream:
            stream.write('\n')
        text = (p/'Honk.toml').read_text().replace('name = "hello"', 'name = "hello"\ndescription = "A useful package"\nlicense = "Apache-2.0"')
        (p/'Honk.toml').write_text(text)
        lib = self.root/'lib'; lib.mkdir(); (lib/'mathx.goose').write_text('namespace mathx; fn value() -> i64 { 1 }')
        self.run_honk('add', 'mathx', '--path', '../lib', cwd=p)
        self.assertIn('A useful package', (p/'Honk.toml').read_text())
        (p/'Honk.toml').write_text('[package]\nname="hello"\n"\\u001b[31m"=true')
        proc = self.run_honk('metadata', cwd=p, ok=False)
        self.assertNotIn('\x1b', proc.stderr)
        self.assertIn('\\x1b', proc.stderr)
    def test_cached_git_content_tamper(self):
        # Native fs safety is also exercised on an already populated source stage.
        p = self.new(); self.run_honk('build', cwd=p)
        stage = p/'.honk/stage/app/src/main.goose'
        stage.unlink(); stage.symlink_to(p/'src/main.goose')
        self.run_honk('build', cwd=p)
        self.assertFalse(stage.is_symlink())
    def test_dev_dependencies_are_not_loaded_by_build(self):
        lib = self.root/'lib'; lib.mkdir()
        (lib/'testonly.goose').write_text('let s="unterminated')
        p = self.new()
        self.run_honk('add', 'testonly', '--path', '../lib', '--dev', cwd=p)
        self.run_honk('build', cwd=p)
        (p/'tests').mkdir(); (p/'tests/test.goose').write_text('fn main() {}')
        self.run_honk('test', cwd=p, ok=False)
    def test_fmt_rejects_symlinks_without_touching_outside(self):
        p = self.new(); outside = self.root/'outside'; outside.mkdir()
        secret = outside/'secret.goose'; original = 'fn main(){print("private");}'; secret.write_text(original)
        (p/'src/link').symlink_to(outside, target_is_directory=True)
        self.run_honk('fmt', cwd=p, ok=False)
        self.assertEqual(secret.read_text(), original)
        (p/'src/link').unlink(); (p/'src/link.goose').symlink_to(secret)
        self.run_honk('fmt', cwd=p, ok=False)
        self.assertEqual(secret.read_text(), original)
    def test_legacy_dependency_conflict_and_cycle(self):
        p = self.new()
        for name, text in [('a', 'import c from "../c1";'), ('b', 'import c from "../c2";'),
                           ('c1', 'namespace c; fn value() -> i64 { 1 }'), ('c2', 'namespace c; fn value() -> i64 { 2 }')]:
            directory = self.root/name; directory.mkdir()
            (directory/('c.goose' if name.startswith('c') else name+'.goose')).write_text(text)
        self.run_honk('add', 'a', '--path', '../a', cwd=p)
        self.run_honk('add', 'b', '--path', '../b', cwd=p)
        self.assertIn('conflicting dependency', self.run_honk('fetch', cwd=p, ok=False).stderr)
        self.run_honk('remove', 'b', cwd=p)
        (self.root/'c1/c.goose').write_text('import a from "../a";')
        self.assertIn('cycle', self.run_honk('fetch', cwd=p, ok=False).stderr)
    def test_malformed_import_cannot_escape_staging(self):
        p = self.new(); (p/'"x').mkdir()
        victim = p/'src/owned".goose'; original = 'fn value() -> i64 { 7 }'; victim.write_text(original)
        (p/'src/main.goose').write_text('import "x/../../../../src/owned" from ".."; fn main() {}')
        self.assertIn('invalid sourced import name', self.run_honk('build', cwd=p, ok=False).stderr)
        self.assertEqual(victim.read_text(), original)
    def test_fetch_tree_do_not_need_compiler(self):
        p = self.new()
        env = {'GOOSE': '/does/not/exist'}
        self.run_honk('fetch', '--offline', cwd=p, env=env)
        self.run_honk('tree', '--frozen', cwd=p, env=env)
        self.run_honk('build', cwd=p, env=env, ok=False)
    def test_explicit_manifest_selection_is_exact(self):
        p = self.new()
        (p/'other.toml').write_text('[package]\nname="other"')
        self.run_honk('metadata', '--manifest-path', p/'other.toml', ok=False)
        self.assertEqual(json.loads(self.run_honk('metadata', '--manifest-path', p/'Honk.toml').stdout)['name'], 'hello')
        (p/'real.toml').write_text((p/'Honk.toml').read_text())
        (p/'Honk.toml').unlink(); (p/'Honk.toml').symlink_to('real.toml')
        self.run_honk('metadata', '--manifest-path', p/'Honk.toml', ok=False)
    def test_help_and_errors(self):
        self.run_honk('--help')
        self.run_honk('version')
        self.run_honk('new', '--name', '../bad', 'app', ok=False)
        self.run_honk('new', '--unknown', ok=False)

if __name__ == '__main__':
    unittest.main()

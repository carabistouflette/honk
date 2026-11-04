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
        # A source needed by the build but absent from Git must not produce a broken archive.
        main = p/'src/main.goose'; saved = main.read_text()
        main.write_text('import .helper; fn main() { print(helper()); }')
        (p/'src/helper.goose').write_text('fn helper() -> i64 { 42 }')
        self.run_honk('package', '--locked', cwd=p, ok=False)
        self.assertEqual(archive.read_bytes(), original)
        self.assertFalse((p/'.honk/package/hello-0.1.0/secret.txt').exists())
        main.write_text(saved)
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
    def test_existing_root_package_entry_is_preserved(self):
        p = self.new(); (p/'tests').mkdir()
        (p/'helper.goose').write_text('namespace helper; fn value() -> i64 { 42 }')
        (p/'tests/test.goose').write_text('import helper from ".."; fn main() { assert(helper::value() == 42); }')
        self.run_honk('test', cwd=p)
        self.assertIn('namespace helper', (p/'helper.goose').read_text())
    def test_binary_output_symlink_cannot_overwrite_outside(self):
        p = self.new(); output = p/'target/debug'; output.mkdir(parents=True)
        victim = self.root/'victim'; victim.write_bytes(b'private unchanged marker')
        (output/'hello').symlink_to(victim)
        self.run_honk('build', cwd=p, ok=False)
        self.assertEqual(victim.read_bytes(), b'private unchanged marker')
    def test_test_binary_does_not_overwrite_application(self):
        p = self.new('test-0'); (p/'tests').mkdir()
        (p/'tests/check.goose').write_text('fn main() { print("test program"); }')
        self.run_honk('build', cwd=p)
        binary = p/'target/debug/test-0'; original = binary.read_bytes()
        self.run_honk('test', cwd=p)
        self.assertEqual(binary.read_bytes(), original)
        self.assertIn('Hello, Goose!', subprocess.check_output([binary], text=True))
    def test_closed_standard_descriptors(self):
        p = self.new()
        def close_stdin_stdout():
            os.close(0); os.close(1)
        proc = subprocess.run([HONK, 'check'], cwd=p,
                              env={**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache')},
                              preexec_fn=close_stdin_stdout, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
    def test_failed_compiler_preserves_last_good_binary(self):
        import sys
        p = self.new(); self.run_honk('build', cwd=p)
        binary = p/'target/debug/hello'; original = binary.read_bytes()
        compiler = self.root/'failing-compiler'
        version = subprocess.check_output([GOOSE, 'version'], text=True).strip()
        compiler.write_text('#!'+sys.executable+'\nimport sys\nif "version" in sys.argv: print('+repr(version)+'); sys.exit(0)\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index("-o")+1]).write_bytes(b"partial output")\nsys.exit(9)\n')
        compiler.chmod(0o755)
        proc = self.run_honk('build', cwd=p, env={'GOOSE': str(compiler)}, ok=False)
        self.assertEqual(proc.returncode, 9)
        self.assertEqual(binary.read_bytes(), original)
    def test_package_stages_only_tracked_files(self):
        p = self.new(); self.run_honk('fetch', cwd=p); self.git_project(p)
        self.git(p, 'add', 'Honk.toml', 'Honk.lock', 'src')
        os.mkfifo(p/'untracked-pipe')
        (p/'untracked-link').symlink_to('/does/not/exist')
        self.run_honk('package', '--frozen', cwd=p)
        with tarfile.open(p/'target/package/hello-0.1.0.tar.gz') as archive:
            self.assertNotIn('hello-0.1.0/untracked-pipe', archive.getnames())
            self.assertNotIn('hello-0.1.0/untracked-link', archive.getnames())
    def test_cancellation_waits_for_child_cleanup(self):
        import signal
        import sys
        import time
        p = self.new(); marker = self.root/'child'; compiler = self.root/'slow-compiler'
        version = subprocess.check_output([GOOSE, 'version'], text=True).strip()
        compiler.write_text('#!'+sys.executable+'\nimport os,signal,sys,time\nfrom pathlib import Path\nif "version" in sys.argv: print('+repr(version)+'); sys.exit(0)\nm=Path(os.environ["TEST_MARKER"])\ndef stop(sig, frame):\n m.with_suffix(".stopping").write_text("stopping")\n time.sleep(0.3)\n m.with_suffix(".done").write_text("done")\n sys.exit(0)\nsignal.signal(signal.SIGTERM, stop)\nm.write_text(str(os.getpid()))\nwhile True: time.sleep(1)\n')
        compiler.chmod(0o755)
        proc = subprocess.Popen([HONK, 'check'], cwd=p, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env={**os.environ, 'GOOSE': str(compiler), 'HONK_HOME': str(self.root/'cache'), 'TEST_MARKER': str(marker)})
        child = None
        try:
            deadline = time.monotonic()+10
            while not marker.exists() and time.monotonic() < deadline: time.sleep(0.01)
            self.assertTrue(marker.exists(), 'compiler never started'); child = int(marker.read_text())
            proc.send_signal(signal.SIGTERM)
            stdout, stderr = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 143, stdout+stderr)
            self.assertTrue(marker.with_suffix('.done').exists(), 'parent exited before child cleanup')
            with self.assertRaises(ProcessLookupError): os.kill(child, 0)
            child = None
            self.run_honk('clean', cwd=p)
        finally:
            if proc.poll() is None: proc.kill(); proc.communicate()
            if child:
                try: os.kill(child, signal.SIGKILL)
                except ProcessLookupError: pass
            proc.communicate(timeout=5)
    def test_package_ignores_ambient_git_index(self):
        p = self.new(); self.run_honk('fetch', cwd=p); self.git_project(p)
        self.git(p, 'add', 'Honk.toml', 'Honk.lock', 'src')
        alternate = self.root/'alternate-index'; shutil.copyfile(p/'.git/index', alternate)
        (p/'secret.txt').write_text('not tracked in the project index')
        subprocess.run(['git', '-C', str(p), 'add', 'secret.txt'],
                       env={**os.environ, 'GIT_INDEX_FILE': str(alternate)}, check=True)
        self.run_honk('package', '--frozen', cwd=p, env={'GIT_INDEX_FILE': str(alternate)})
        with tarfile.open(p/'target/package/hello-0.1.0.tar.gz') as archive:
            self.assertNotIn('hello-0.1.0/secret.txt', archive.getnames())
    def test_workspace_clean_rejects_symlink_members(self):
        outside = self.new('outside'); workspace = self.root/'workspace'; workspace.mkdir()
        (workspace/'link').symlink_to(outside, target_is_directory=True)
        (workspace/'nested').symlink_to(self.root, target_is_directory=True)
        for member in ['link', 'nested/outside']:
            with self.subTest(member=member):
                target = outside/'target'; target.mkdir(exist_ok=True)
                victim = target/'keep'; victim.write_text('outside workspace')
                (workspace/'Honk.toml').write_text('[workspace]\nmembers=['+json.dumps(member)+']')
                self.run_honk('clean', '--workspace', cwd=workspace, ok=False)
                self.assertEqual(victim.read_text(), 'outside workspace')
    def test_add_rejects_invalid_utf8_without_changing_manifest(self):
        p = self.new(); original = (p/'Honk.toml').read_bytes()
        proc = subprocess.run([HONK, 'add', 'helper', '--path', b'\xff'], cwd=p,
                              env={**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache')},
                              capture_output=True, timeout=10)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual((p/'Honk.toml').read_bytes(), original)
    def test_archive_environment_cannot_execute_hook(self):
        import shlex
        p = self.new(); self.run_honk('fetch', cwd=p); self.git_project(p)
        self.git(p, 'add', 'Honk.toml', 'Honk.lock', 'src')
        with tempfile.TemporaryDirectory(prefix='honk-tar-hook-') as helper_dir:
            hook = Path(helper_dir)/'hook'; marker = Path(helper_dir)/'ran'
            hook.write_text('#!/bin/sh\nprintf invoked >'+shlex.quote(str(marker))+'\n'); hook.chmod(0o755)
            options = '--checkpoint=1 --checkpoint-action=exec='+str(hook)
            self.run_honk('package', '--frozen', cwd=p, env={'TAR_OPTIONS': options})
            self.assertFalse(marker.exists(), 'tar executed an inherited environment hook')
    def test_archive_ignores_compression_environment(self):
        p = self.new(); self.run_honk('fetch', cwd=p); self.git_project(p)
        self.git(p, 'add', 'Honk.toml', 'Honk.lock', 'src')
        self.run_honk('package', '--frozen', cwd=p)
        archive = p/'target/package/hello-0.1.0.tar.gz'; original = archive.read_bytes()
        self.run_honk('package', '--frozen', cwd=p, env={'GZIP': '-1'})
        self.assertEqual(archive.read_bytes(), original)
    def test_uninstall_rejects_symlink_prefix_components(self):
        outside = self.root/'outside'; outside.mkdir()
        prefix = self.root/'prefix'; prefix.mkdir()
        (prefix/'bin').symlink_to(outside, target_is_directory=True)
        victim = outside/'hello'; victim.write_text('outside executable')
        self.run_honk('uninstall', 'hello', '--root', prefix, ok=False)
        self.assertEqual(victim.read_text(), 'outside executable')
    def test_compiler_version_must_be_a_goose_response(self):
        import sys
        p = self.new(); compiler = self.root/'not-goose'
        short = (Path(__file__).resolve().parents[1]/'GOOSE_REVISION').read_text().strip()[:7]
        compiler.write_text('#!'+sys.executable+'\nprint("noise!'+short+' arbitrary text")\n')
        compiler.chmod(0o755)
        self.run_honk('check', cwd=p, env={'GOOSE': str(compiler)}, ok=False)
    def test_add_preserves_manifest_at_dependency_limit(self):
        p = self.new(); original = ('[package]\nname="hello"\n[dependencies]\n'+''.join(f'd{i:03}={{path="."}}\n' for i in range(256))).encode()
        (p/'Honk.toml').write_bytes(original)
        self.run_honk('add', 'extra', '--path', '.', cwd=p, ok=False)
        self.assertEqual((p/'Honk.toml').read_bytes(), original)
    def test_add_preserves_manifest_at_byte_limit(self):
        p = self.new(); head = '[package]\nname="hello"\n[dependencies]\n'
        empty = ''.join(f'd{i:03} = {{ git = "https://example.invalid/", rev = "main" }}\n' for i in range(255))
        width = (1047000-len(head)-len(empty))//255
        original = (head+''.join(f'd{i:03} = {{ git = "https://example.invalid/{"x"*width}", rev = "main" }}\n' for i in range(255))).encode()
        self.assertLess(len(original), 1048576)
        (p/'Honk.toml').write_bytes(original)
        self.run_honk('add', 'extra', '--git', 'https://example.invalid/'+'y'*4000, '--rev', 'main', cwd=p, ok=False)
        self.assertEqual((p/'Honk.toml').read_bytes(), original)
    def test_fetch_preserves_lockfile_at_byte_limit(self):
        p = self.new(); self.run_honk('fetch', cwd=p); original = (p/'Honk.lock').read_bytes()
        lib = self.root/'lib'; lib.mkdir()
        for i in range(256): (lib/f'd{i:03}.goose').write_text(f'namespace d{i:03}; fn value() -> i64 {{ 1 }}')
        path = './'*2012+'../lib'
        manifest = '[package]\nname="hello"\n[dependencies]\n'+''.join(f'd{i:03}={{path="{path}"}}\n' for i in range(256))
        self.assertLess(len(manifest), 1048576); (p/'Honk.toml').write_text(manifest)
        self.run_honk('fetch', cwd=p, ok=False)
        self.assertEqual((p/'Honk.lock').read_bytes(), original)
    def test_binary_source_snapshots_are_independent(self):
        import random
        import stat
        p = self.new(); data = p/'data'; data.mkdir()
        rng = random.Random(0x484F4E4B)
        payloads = {f'asset{i}.bin': rng.randbytes(size) for i,size in enumerate([0,1,65535,65536,65537,1048576,2097155])}
        for name, content in payloads.items(): (data/name).write_bytes(content)
        (data/'tool').write_bytes(b'executable asset'); (data/'tool').chmod(0o755)
        self.run_honk('check', cwd=p)
        staged = p/'.honk/stage/app/data'
        for name, content in payloads.items(): self.assertEqual((staged/name).read_bytes(), content)
        self.assertTrue(stat.S_IMODE((staged/'tool').stat().st_mode) & stat.S_IXUSR)
        source = data/'asset6.bin'; original = payloads['asset6.bin']
        with source.open('r+b') as stream: stream.write(b'changed')
        self.assertEqual((staged/'asset6.bin').read_bytes(), original)
        self.run_honk('check', '--frozen', cwd=p)
        self.assertEqual((staged/'asset6.bin').read_bytes(), source.read_bytes())
    def test_oversized_staging_file_fails_before_copy(self):
        p = self.new()
        with (p/'oversized.bin').open('wb') as stream: stream.truncate(268435457)
        self.run_honk('check', cwd=p, ok=False)
        self.assertFalse((p/'.honk/stage/app/oversized.bin').exists())
    def test_manifest_update_preserves_private_permissions(self):
        import stat
        p = self.new(); manifest = p/'Honk.toml'; manifest.chmod(0o600)
        self.run_honk('add', 'helper', '--path', '.', cwd=p)
        self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
    def test_package_is_deterministic_across_umasks(self):
        import stat
        p = self.new(); self.run_honk('fetch', cwd=p); self.git_project(p)
        (p/'tool.sh').write_text('#!/bin/sh\nexit 0\n'); (p/'tool.sh').chmod(0o755)
        self.git(p, 'add', 'Honk.toml', 'Honk.lock', 'src', 'tool.sh')
        results = []
        for mask in [0o022, 0o077]:
            proc = subprocess.run([HONK, 'package', '--frozen'], cwd=p,
                                  env={**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache')},
                                  preexec_fn=lambda: os.umask(mask), capture_output=True, timeout=90)
            self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
            archive = p/'target/package/hello-0.1.0.tar.gz'; results.append(archive.read_bytes())
            with tarfile.open(archive) as tar:
                self.assertEqual(tar.getmember('hello-0.1.0/tool.sh').mode, 0o755)
                self.assertEqual(tar.getmember('hello-0.1.0/Honk.toml').mode, 0o644)
        self.assertEqual(*results)
    def test_package_disables_git_fsmonitor(self):
        import shlex
        p = self.new(); self.run_honk('fetch', cwd=p); self.git_project(p)
        self.git(p, 'add', 'Honk.toml', 'Honk.lock', 'src')
        marker = self.root/'monitor-ran'; hook = self.root/'monitor'
        hook.write_text('#!/bin/sh\nprintf invoked >'+shlex.quote(str(marker))+"\nprintf 'token\\0'\n"); hook.chmod(0o755)
        self.git(p, 'config', 'core.fsmonitor', str(hook))
        self.run_honk('package', '--frozen', cwd=p)
        self.assertFalse(marker.exists())
    def test_library_namespace_is_validated_before_creation(self):
        for name in ['fn','as','in','defer','reusable','bool','u8','std']:
            with self.subTest(name=name):
                self.run_honk('new', name, '--lib', ok=False)
                self.assertFalse((self.root/name).exists())
        self.run_honk('init', '--lib', '--name', 'fn', ok=False)
        self.assertFalse((self.root/'Honk.toml').exists())
        self.assertFalse((self.root/'src').exists())
        lib = self.new('my-lib', '--lib'); self.run_honk('check', '--offline', cwd=lib)
    def test_deep_sources_remain_rebuildable_and_cleanable(self):
        p = self.new(); deepest = p/'assets'
        deepest.mkdir()
        for _ in range(63): deepest = deepest/'d'; deepest.mkdir()
        (deepest/'asset.bin').write_bytes(b'deep source')
        self.run_honk('check', cwd=p)
        self.run_honk('check', '--frozen', cwd=p)
        self.git_project(p); self.git(p, 'add', 'Honk.toml', 'Honk.lock', 'src', 'assets')
        self.run_honk('package', '--frozen', cwd=p)
        self.run_honk('package', '--frozen', cwd=p)
        self.assertFalse((p/'.honk/package').exists())
        self.run_honk('clean', cwd=p)
        self.assertFalse((p/'.honk/stage').exists())
        (deepest/'too-deep').mkdir()
        self.run_honk('check', '--frozen', cwd=p, ok=False)
        self.run_honk('clean', cwd=p)
        self.assertEqual((deepest/'asset.bin').read_bytes(), b'deep source')
    def test_fmt_batches_supported_file_and_argument_byte_limits(self):
        p = self.new(); directory = p/('d'*220); directory.mkdir()
        files = [p/'src/main.goose']
        for i in range(4095):
            file = directory/f'f{i:04}.goose'; file.write_text('fn helper(){print(1);}')
            files.append(file)
        self.assertGreater(sum(len(os.fsencode(f))+1 for f in files), 1048576)
        self.run_honk('fmt', cwd=p)
        self.run_honk('fmt', '--check', cwd=p)
        self.assertIn('fn helper() {', files[-1].read_text())
    def test_fmt_without_sources_does_not_consume_stdin(self):
        p = self.new(); (p/'src/main.goose').unlink()
        proc = subprocess.run([HONK, 'fmt'], cwd=p, input=b'fn main(){print(42);}',
                              env={**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache')},
                              capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, b'')
    def test_git_enforces_certificate_and_hostname_verification(self):
        import http.server
        import ssl
        import threading
        cert = self.root/'cert.pem'; key = self.root/'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-days', '1', '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
                        '-keyout', str(key), '-out', str(cert)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        requests = []; plain_requests = []; redirect = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def handle(self):
                try: super().handle()
                except (ssl.SSLError, ConnectionError): pass  # Rejected TLS peers may abort before HTTP.
            def do_GET(self):
                requests.append(self.path)
                self.send_response(302 if redirect else 404)
                if redirect: self.send_header('Location', redirect[0])
                self.send_header('Content-Length', '0'); self.end_headers()
            def log_message(self, *args): pass
        class PlainHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                plain_requests.append(self.path)
                self.send_response(404); self.send_header('Content-Length', '0'); self.end_headers()
            def log_message(self, *args): pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        plain = http.server.HTTPServer(('127.0.0.1', 0), PlainHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threads = [threading.Thread(target=lambda s=s: s.serve_forever(poll_interval=0.02), daemon=True) for s in (server, plain)]
        for thread in threads: thread.start()
        try:
            p = self.new(); url = f'https://localhost:{server.server_port}/repo=fixture.git'
            self.run_honk('add', 'helper', '--git', url, '--rev', 'HEAD', cwd=p)
            insecure = {'GIT_SSL_NO_VERIFY': '1', 'HONK_GIT_SSL_VERIFY': 'false'}
            self.run_honk('fetch', cwd=p, env=insecure, ok=False)
            self.assertEqual(requests, [], 'Git contacted untrusted TLS endpoint')
            repo = next((self.root/'cache/git').iterdir())
            self.git(repo, 'config', f'http.{url}.sslVerify', 'false')
            self.run_honk('fetch', cwd=p, env=insecure, ok=False)
            self.assertEqual(requests, [], 'URL-specific config disabled verification')
            trusted = {**insecure, 'GIT_SSL_CAINFO': str(cert)}
            self.run_honk('fetch', cwd=p, env=trusted, ok=False)
            self.assertGreater(len(requests), 0, 'trusted TLS never reached the HTTP handler')
            previous = len(requests)
            redirect.append(f'http://127.0.0.1:{plain.server_port}/repo.git')
            self.run_honk('fetch', cwd=p, env=trusted, ok=False)
            self.assertGreater(len(requests), previous)
            self.assertEqual(plain_requests, [], 'HTTPS downgraded to HTTP')
            previous = len(requests)
            self.run_honk('remove', 'helper', cwd=p)
            self.run_honk('add', 'helper', '--git', f'https://127.0.0.1:{server.server_port}/repo.git', '--rev', 'HEAD', cwd=p)
            self.run_honk('fetch', cwd=p, env=trusted, ok=False)
            self.assertEqual(len(requests), previous, 'Git ignored hostname mismatch')
        finally:
            for active in (server, plain): active.shutdown(); active.server_close()
            for thread in threads: thread.join(timeout=5)
    def test_metadata_selects_workspace_members_without_cache(self):
        a = self.new('alpha'); b = self.new('beta')
        (self.root/'Honk.toml').write_text('[workspace]\nmembers=["alpha", "beta"]')
        member = json.loads(self.run_honk('metadata', '-p', 'beta').stdout)
        self.assertEqual(member['name'], 'beta'); self.assertEqual(member['root'], str(b))
        members = json.loads(self.run_honk('metadata', '--workspace').stdout)
        self.assertEqual([m['name'] for m in members], ['alpha', 'beta'])
        self.assertEqual(len(json.loads(self.run_honk('metadata', '--workspace', '-p', 'beta').stdout)), 1)
        self.assertEqual(self.run_honk('metadata', '-p', 'missing', ok=False).stdout, '')
        self.run_honk('metadata', 'unexpected', ok=False)
        self.assertFalse((self.root/'cache').exists())
        (b/'Honk.toml').write_text((b/'Honk.toml').read_text().replace('"beta"', '"alpha"'))
        self.assertEqual(self.run_honk('metadata', '-p', 'alpha', ok=False).stdout, '')
        (self.root/'Honk.toml').write_text('[workspace]\nmembers=["link"]')
        (self.root/'link').symlink_to(a, target_is_directory=True)
        self.run_honk('metadata', '-p', 'alpha', ok=False)
    def test_metadata_rejects_non_utf8_project_root(self):
        directory = os.fsencode(self.root)+b'/bad\xff'
        env = {**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache')}
        created = subprocess.run([HONK, 'new', directory, '--name', 'hello'], env=env, capture_output=True, timeout=10)
        self.assertEqual(created.returncode, 0, created.stderr)
        proc = subprocess.run([HONK, 'metadata'], cwd=directory, env=env, capture_output=True, timeout=10)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b''); self.assertIn(b'UTF-8 project path', proc.stderr)
    def test_bootstrap_ignores_ambient_git_policy_and_origin(self):
        import shlex
        import sys
        upstream = self.root/'upstream'; upstream.mkdir(); self.git_project(upstream)
        (upstream/'source').write_text('reviewed fixture')
        self.git(upstream, 'add', 'source'); self.git(upstream, 'commit', '-qm', 'fixture')
        revision = self.git(upstream, 'rev-parse', 'HEAD')
        bootstrap = self.root/'bootstrap'; (bootstrap/'scripts').mkdir(parents=True)
        script = bootstrap/'scripts/setup-goose.sh'
        shutil.copyfile(Path(__file__).resolve().parents[1]/'scripts/setup-goose.sh', script)
        (bootstrap/'GOOSE_REVISION').write_text(revision+'\n')
        toolchain = bootstrap/'.toolchain/goose'
        subprocess.run(['git', 'clone', '-q', str(upstream), str(toolchain)], check=True)
        self.git(toolchain, 'remote', 'set-url', 'origin', 'https://example.invalid/wrong-upstream')
        hooks = self.root/'hooks'; hooks.mkdir(); marker = self.root/'hook-ran'
        hook = hooks/'post-checkout'
        hook.write_text('#!/bin/sh\nprintf invoked >'+shlex.quote(str(marker))+'\n'); hook.chmod(0o755)
        self.git(toolchain, 'config', 'core.hooksPath', str(hooks))
        global_config = self.root/'global-config'
        global_config.write_text('[core]\n hooksPath = '+json.dumps(str(hooks))+'\n')
        helpers = self.root/'helpers'; helpers.mkdir(); real_git = shutil.which('git')
        # Substitute only the fixed network endpoint with a real local Git repo.
        # Checkout/config/hook handling still executes real Git; CMake is inert.
        proxy = helpers/'git'; proxy.write_text('#!'+sys.executable+\
            '\nimport json,os,subprocess,sys\nfrom pathlib import Path\na=sys.argv[1:]\n'\
            'if "fetch" in a:\n url="https://github.com/aardappel/goose.git"\n'\
            ' if url not in a: sys.exit(89)\n'\
            ' Path(os.environ["BOOTSTRAP_ENV_LOG"]).write_text(json.dumps(dict(os.environ)))\n'\
            ' a[a.index(url)]='+repr(str(upstream))+'\n os.environ["GIT_ALLOW_PROTOCOL"]="file"\n'\
            'sys.exit(subprocess.call(['+repr(real_git)+']+a))\n'); proxy.chmod(0o755)
        configured = self.root/'cmake-ran'; cmake = helpers/'cmake'
        cmake.write_text('#!/bin/sh\nprintf configured >'+shlex.quote(str(configured))+'\n'); cmake.chmod(0o755)
        env_log = self.root/'bootstrap-env.json'
        proc = subprocess.run(['bash', str(script)], cwd=bootstrap, capture_output=True, timeout=30,
                              env={**os.environ, 'PATH': str(helpers)+os.pathsep+os.environ['PATH'],
                                   'GIT_CONFIG_GLOBAL': str(global_config), 'GIT_SSL_NO_VERIFY': '1',
                                   'GIT_DIR': str(self.root/'wrong-context'), 'BOOTSTRAP_ENV_LOG': str(env_log)})
        self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
        self.assertFalse(marker.exists(), 'bootstrap executed a checkout hook')
        self.assertTrue(configured.exists()); self.assertEqual(self.git(toolchain, 'rev-parse', 'HEAD'), revision)
        observed = json.loads(env_log.read_text())
        self.assertNotIn('GIT_SSL_NO_VERIFY', observed); self.assertNotIn('GIT_DIR', observed)
        self.assertEqual(observed['GIT_CONFIG_GLOBAL'], '/dev/null')
        self.assertEqual(observed['HONK_GIT_SSL_VERIFY'], 'true')
        configured.unlink(); (bootstrap/'GOOSE_REVISION').write_text('not-a-full-pin\n')
        proc = subprocess.run(['bash', str(script)], cwd=bootstrap, capture_output=True, timeout=10)
        self.assertNotEqual(proc.returncode, 0); self.assertFalse(configured.exists())
    def test_help_and_errors(self):
        self.run_honk('--help')
        self.run_honk('version')
        self.run_honk('new', '--name', '../bad', 'app', ok=False)
        self.run_honk('new', '--unknown', ok=False)

if __name__ == '__main__':
    unittest.main()

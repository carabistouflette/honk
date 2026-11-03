#!/usr/bin/env python3
"""Black-box regressions: real files, real executable, no shell interpolation."""
import json
import os
from pathlib import Path
import subprocess
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
    def test_help_and_errors(self):
        self.run_honk('--help')
        self.run_honk('version')
        self.run_honk('new', '--name', '../bad', 'app', ok=False)
        self.run_honk('new', '--unknown', ok=False)

if __name__ == '__main__':
    unittest.main()

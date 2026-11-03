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
                              env={**os.environ, 'GOOSE': GOOSE, **(env or {})},
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
    def test_help_and_errors(self):
        self.run_honk('--help')
        self.run_honk('version')
        self.run_honk('new', '--name', '../bad', 'app', ok=False)
        self.run_honk('new', '--unknown', ok=False)

if __name__ == '__main__':
    unittest.main()

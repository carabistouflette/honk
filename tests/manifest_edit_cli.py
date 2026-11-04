#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Byte-exact dependency editing via the real CLI; no network."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

class ManifestEditing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk edit ')
        self.root = Path(self.temp.name)
        self.path = self.root / 'Honk.toml'
    def tearDown(self):
        self.temp.cleanup()
    def call(self, *args, ok=True):
        before = self.path.read_bytes()
        result = subprocess.run([os.environ['HONK'], *args], cwd=self.root,
            capture_output=True, timeout=20, env={**os.environ, 'HONK_HOME': str(self.root/'cache')})
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        self.assertNotIn(b'AddressSanitizer', result.stderr)
        self.assertNotIn(b'runtime error:', result.stderr)
        if not ok: self.assertEqual(self.path.read_bytes(), before)
        return self.path.read_bytes()
    def test_inline_add_remove(self):
        for nl in (b'\n', b'\r\n'):
            original = nl.join([b'# notes', b'[package]', b"name='hello' # title", b'[dependencies] # group', b"keep={path='../keep'} # keep", b'[dev-dependencies]', b"dev={path='../dev'}", b''])
            self.path.write_bytes(original)
            added = original.replace(b'[dependencies] # group'+nl, b'[dependencies] # group'+nl+b'"helper" = { path = "../helper" }'+nl)
            self.assertEqual(self.call('add','helper','--path','../helper'), added)
            self.assertEqual(self.call('remove','helper'), added.replace(b'"helper" = { path = "../helper" }', b''))
    def test_remove_layouts(self):
        for source, expected in [
            (b"[package]\nname='hello'\n[dependencies.helper] # dep\npath='../helper' # path\n[dev-dependencies]\nother={path='../other'}\n", b"[package]\nname='hello'\n # dep\n # path\n[dev-dependencies]\nother={path='../other'}\n"),
            (b"dependencies.helper.path='../helper' # note\n[package]\nname='hello'\n", b" # note\n[package]\nname='hello'\n"),
            (b"[package]\nname='hello'\n['dependencies'] # table\n'helper'.path='../helper'\n", b"[package]\nname='hello'\n['dependencies'] # table\n\n")]:
            self.path.write_bytes(source)
            self.assertEqual(self.call('remove','helper'),expected)
    def test_missing_section_dev_and_eof(self):
        source=b"# keep\n[package]\nname='hello'";self.path.write_bytes(source)
        self.assertEqual(self.call('add','helper','--path','../helper','--dev'),b'"dev-dependencies"."helper" = { path = "../helper" }\n'+source)
        source=b"[package]\nname='hello'\n[dependencies] # EOF";self.path.write_bytes(source)
        self.assertEqual(self.call('add','helper','--path','../helper'),source+b'\n"helper" = { path = "../helper" }\n')
    def test_failures_are_atomic(self):
        self.path.write_bytes(b"dependencies={helper={path='../helper'}}\n[package]\nname='hello'\n")
        self.call('remove','helper',ok=False);self.call('add','other','--path','../other',ok=False)
        self.path.write_bytes(b"[package]\nname='hello'\n[dependencies]\nhelper={path='../helper'}\n")
        self.call('add','helper','--path','../other',ok=False);self.call('remove','missing',ok=False)
        self.call('add','other','--path','bad\nvalue',ok=False)
    def test_output_limit(self):
        source=b"[package]\nname='hello'\n#";self.path.write_bytes(source+b' '*(1048576-len(source)))
        self.call('add','helper','--path','../helper',ok=False)

if __name__=='__main__': unittest.main()

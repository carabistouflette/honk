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
    def call(self, *args, ok=True, env=None):
        before = self.path.read_bytes()
        status = self.path.stat()
        identity = (status.st_ino, status.st_mtime_ns, status.st_ctime_ns)
        result = subprocess.run([os.environ['HONK'], *args], cwd=self.root,
            capture_output=True, timeout=20, env={**os.environ, 'HONK_HOME': str(self.root/'cache'), **(env or {})})
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        self.assertNotIn(b'AddressSanitizer', result.stderr)
        self.assertNotIn(b'runtime error:', result.stderr)
        self.last_result = result
        if not ok:
            self.assertEqual(self.path.read_bytes(), before)
            status = self.path.stat()
            self.assertEqual((status.st_ino, status.st_mtime_ns, status.st_ctime_ns), identity)
            self.assertEqual(result.stdout, b'')
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
    def test_batch_remove_preserves_unedited_bytes(self):
        for nl in (b'\n', b'\r\n'):
            original = nl.join([b'# retain', b'[package]', b"name='hello' # name", b'[dependencies] # deps',
                b"alpha={path='../alpha'} # alpha note", b"keep={path='../keep'} # keep note",
                b'[dev-dependencies.beta] # beta note', b"path='../beta' # path note", b''])
            self.path.write_bytes(original)
            lock = self.root/'Honk.lock'; lock.write_bytes(b'old lock: refresh explicitly\n')
            expected = original.replace(b"alpha={path='../alpha'}", b'').replace(b'[dev-dependencies.beta]', b'').replace(b"path='../beta'", b'')
            self.assertEqual(self.call('remove','alpha','beta'), expected)
            self.assertEqual(lock.read_bytes(), b'old lock: refresh explicitly\n')
            self.assertEqual(self.last_result.stdout, b'Removed 2 dependencies; run honk fetch to update Honk.lock\n')

    def test_batch_missing_duplicate_and_invalid_are_no_write(self):
        self.path.write_bytes(b"[package]\nname='hello'\n[dependencies]\nalpha={path='../alpha'}\nbeta={path='../beta'}\n")
        for names in ((), ('alpha','missing'), ('alpha','alpha'), ('alpha','bad-name'), ('alpha','a'*65), ('alpha','fn')):
            with self.subTest(names=names): self.call('remove', *names, ok=False)
        self.call('add','gamma','delta','--path','../gamma',ok=False)
        self.call('remove','alpha','beta','--dev',ok=False)

    def test_batch_count_and_name_bounds(self):
        import tomllib
        names = [f'dep_{i:02d}' for i in range(63)]+['a'*64]
        original = "[package]\nname='hello'\n[dependencies]\n"+''.join(name+"={path='../lib'}\n" for name in [*names,'keep'])
        self.path.write_text(original)
        self.call('remove', *names, 'keep', ok=False)
        result = self.call('remove', *names)
        self.assertEqual(list(tomllib.loads(result.decode())['dependencies']), ['keep'])

    def test_batch_late_plan_error_preserves_first_dependency(self):
        self.path.write_bytes(b"dependencies={beta={path='../beta'}}\n[package]\nname='hello'\n[dev-dependencies]\nalpha={path='../alpha'} # remain\n")
        self.call('remove','alpha','beta',ok=False)

    def test_batch_project_lock_and_outputs(self):
        import fcntl
        self.path.write_bytes(b"[package]\nname='hello'\n[dependencies]\nalpha.path='../alpha' # alpha\nbeta.path='../beta' # beta\n")
        state=self.root/'.honk'; state.mkdir(mode=0o700)
        output=self.root/'target/debug/hello'; output.parent.mkdir(parents=True); output.write_bytes(b'last-good executable')
        lock=self.root/'Honk.lock'; lock.write_bytes(b'unchanged lock')
        with (state/'lock').open('wb') as owner:
            fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.call('remove','alpha','beta',ok=False)
        self.call('remove','alpha','beta',env={'GOOSE':str(self.root/'forbidden-compiler'),'PATH':''})
        self.assertEqual(lock.read_bytes(), b'unchanged lock')
        self.assertEqual(output.read_bytes(), b'last-good executable')

    def test_batch_manifest_size_bound(self):
        base=b"[package]\nname='hello'\n[dependencies]\nalpha.path='../alpha'\nbeta.path='../beta'\n#"
        source=base+b' '*(1048576-len(base))
        self.path.write_bytes(source+b' ')
        self.call('remove','alpha','beta',ok=False)
        self.path.write_bytes(source)
        expected=source.replace(b"alpha.path='../alpha'",b'').replace(b"beta.path='../beta'",b'')
        self.assertEqual(self.call('remove','alpha','beta'), expected)

    def test_single_remove_retains_legacy_bytes_and_output(self):
        original=b"[package]\nname='hello'\n[dependencies]\nalpha={path='../alpha'} # keep note\n"
        self.path.write_bytes(original)
        self.assertEqual(self.call('remove','alpha'), original.replace(b"alpha={path='../alpha'}",b''))
        self.assertEqual(self.last_result.stdout, b'Removed alpha; run honk fetch to update Honk.lock\n')

    def test_output_limit(self):
        source=b"[package]\nname='hello'\n#";self.path.write_bytes(source+b' '*(1048576-len(source)))
        self.call('add','helper','--path','../helper',ok=False)

if __name__=='__main__': unittest.main()

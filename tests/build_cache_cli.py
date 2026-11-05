#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real compiler reuse, content invalidation and failure/publication contracts."""
import hashlib
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest

HONK = str(Path(os.environ['HONK']).resolve())
GOOSE = str(Path(os.environ['GOOSE']).resolve())


class BuildCache(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk reuse ')
        self.root = Path(self.temp.name)
        self.env = {**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache'),
                    'GOOSE_HOME': str(self.root/'goose')}
        self.env.pop('GOOSE_CC', None)
        self.call('new', 'demo')
        self.project = self.root/'demo'
        self.call('fetch', cwd=self.project)
        self.slot = self.project/'.honk/reuse/debug'

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args, cwd=None, ok=True, extra=None):
        result = subprocess.run([HONK, *map(str, args)], cwd=cwd or self.root,
                                env={**self.env, **(extra or {})}, capture_output=True,
                                text=True, timeout=120)
        self.assertEqual(result.returncode == 0, ok, result.stdout+result.stderr)
        self.assertNotIn('AddressSanitizer', result.stderr)
        self.assertNotIn('runtime error:', result.stderr)
        return result

    def run_cached(self, expected='Hello, Goose!\n', **kwargs):
        result = self.call('run', '--reuse-build', '--frozen', cwd=self.project, **kwargs)
        self.assertEqual(result.stdout, 'built '+str(self.project/'target/debug/demo')+'\n'+expected)
        return result

    def mark_compiler_logs(self):
        logs = sorted((self.root/'goose/build/prog').rglob('cc.log'))
        self.assertTrue(logs, 'real compiler produced no backend log')
        for path in logs:
            path.write_text('cache-test: no backend invocation\n')
        return logs

    def assert_logs(self, logs, reused):
        for path in logs:
            self.assertEqual(path.read_text() == 'cache-test: no backend invocation\n', reused)

    def test_verified_hit_republishes_independent_output(self):
        self.run_cached()
        self.assertEqual((self.slot/'record').stat().st_size, 130)
        self.assertEqual((self.slot/'record').read_text()[65:129], hashlib.sha256((self.slot/'program').read_bytes()).hexdigest())
        self.assertEqual((self.slot/'program').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.slot.stat().st_mode & 0o777, 0o700)
        logs = self.mark_compiler_logs()
        binary = self.project/'target/debug/demo'
        binary.write_bytes(b'corrupt public output')
        self.run_cached()
        self.assert_logs(logs, True)
        self.assertNotEqual(binary.stat().st_ino, (self.slot/'program').stat().st_ino)
        self.assertEqual(binary.stat().st_nlink, 1)
        self.assertEqual(binary.stat().st_mode & 0o777, 0o755)
        victim = self.root/'victim'; victim.write_bytes(b'keep')
        binary.unlink(); binary.symlink_to(victim)
        self.call('build', '--reuse-build', '--frozen', cwd=self.project, ok=False)
        self.assertEqual(victim.read_bytes(), b'keep')

    def test_same_size_source_dependency_and_asset_invalidation(self):
        library = self.root/'library'; library.mkdir()
        dependency = library/'dep.goose'; dependency.write_text('namespace dep; fn value() -> i64 { 42 }\n')
        manifest = self.project/'Honk.toml'
        manifest.write_text(manifest.read_text().replace('[dependencies]', '[dependencies]\ndep = { path = "../library" }'))
        source = self.project/'src/main.goose'
        source.write_text('import dep; fn main() { print(dep::value()); }\n')
        self.call('fetch', cwd=self.project)
        self.run_cached('42\n')
        old = dependency.stat(); logs = self.mark_compiler_logs()
        dependency.write_text(dependency.read_text().replace('42', '43'))
        os.utime(dependency, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.run_cached('43\n'); self.assert_logs(logs, False)
        old = source.stat(); logs = self.mark_compiler_logs()
        source.write_text(source.read_text().replace('value()', 'value()+1'))
        os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.run_cached('44\n'); self.assert_logs(logs, False)
        asset = self.project/'asset.bin'; asset.write_bytes(b'one')
        self.run_cached('44\n'); logs = self.mark_compiler_logs(); old = asset.stat()
        asset.write_bytes(b'two'); os.utime(asset, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.run_cached('44\n'); self.assert_logs(logs, False)

    def standard_copy(self):
        candidates = [Path(self.env.get('GOOSE_STDLIB', '/nonexistent'))]
        candidates += [p/'stdlib' for p in Path(GOOSE).parents]
        source = next((p/'std.goose' for p in candidates if (p/'std.goose').is_file()), None)
        self.assertIsNotNone(source)
        directory = self.root/'standard'; directory.mkdir()
        target = directory/'std.goose'; shutil.copyfile(source, target)
        self.env['GOOSE_STDLIB'] = str(directory)
        return target

    def test_standard_environment_and_compiler_bytes_invalidate(self):
        standard = self.standard_copy()
        standard.write_text(standard.read_text()+'\nfn cache_test_value() -> i64 { 42 }\n')
        (self.project/'src/main.goose').write_text('import std; fn main() { print(cache_test_value()); }\n')
        self.run_cached('42\n'); logs = self.mark_compiler_logs()
        standard.write_text(standard.read_text().replace('value() -> i64 { 42 }', 'value() -> i64 { 43 }'))
        self.run_cached('43\n'); self.assert_logs(logs, False)
        logs = self.mark_compiler_logs(); self.env['CACHE_TEST_CONTEXT'] = 'changed'
        self.run_cached('43\n'); self.assert_logs(logs, False)
        compiler = self.root/'copied-goose'; shutil.copyfile(GOOSE, compiler); compiler.chmod(0o755)
        self.env['GOOSE'] = str(compiler)
        self.run_cached('43\n'); logs = self.mark_compiler_logs()
        with compiler.open('ab') as output: output.write(b'\0')
        self.run_cached('43\n'); self.assert_logs(logs, False)

    def test_compiler_paths_use_child_cwd_and_skip_empty_path_entries(self):
        # Pinned Goose skips empty PATH components, rather than searching cwd.
        shutil.copyfile('/bin/false', self.project/'cc'); (self.project/'cc').chmod(0o755)
        self.env['PATH'] = ':'+self.env.get('PATH', '')
        self.run_cached()
        relative_home = self.project/'runtime-home'; relative_home.mkdir()
        marker = self.root/'compiler-used'
        wrapper = self.root/'configured-cc'
        real_cc = shutil.which('cc', path=os.environ.get('PATH', ''))
        self.assertIsNotNone(real_cc)
        wrapper.write_text('#!'+sys.executable+'\nimport os,sys\nfrom pathlib import Path\n'
                           +'with Path('+repr(str(marker))+').open("a") as output: output.write("called\\n")\n'
                           +'os.execv('+repr(real_cc)+', ['+repr(real_cc)+', *sys.argv[1:]])\n')
        wrapper.chmod(0o755)
        import json
        (relative_home/'config').write_text('cc = '+json.dumps(str(wrapper))+';\n')
        self.env['GOOSE_HOME'] = 'runtime-home'
        result = self.call('run', '--reuse-build', '--frozen', cwd=self.project/'src')
        self.assertIn('Hello, Goose!', result.stdout)
        self.assertTrue(marker.is_file(), 'configured compiler was bypassed')
        self.assertFalse((self.slot/'record').exists())

    def test_profile_ordinary_build_and_clean(self):
        self.run_cached(); logs = self.mark_compiler_logs()
        self.call('build', '--frozen', cwd=self.project)
        self.assert_logs(logs, False)
        self.assertFalse((self.slot/'record').exists())
        self.run_cached()
        self.call('build', '--release', '--reuse-build', '--frozen', cwd=self.project)
        release = self.project/'.honk/reuse/release'
        self.assertTrue((release/'record').is_file())
        self.assertNotEqual((release/'record').read_bytes()[:64], (self.slot/'record').read_bytes()[:64])
        self.call('clean', cwd=self.project)
        self.assertFalse((self.project/'.honk/reuse').exists())
        self.assertFalse((self.project/'target').exists())

    def test_failed_compile_preserves_binary_and_invalidates_record(self):
        self.run_cached(); binary = self.project/'target/debug/demo'; old = hashlib.sha256(binary.read_bytes()).digest()
        (self.project/'src/main.goose').write_text('fn main() { definitely not valid Goose }\n')
        self.call('build', '--reuse-build', '--frozen', cwd=self.project, ok=False)
        self.assertFalse((self.slot/'record').exists())
        self.assertEqual(hashlib.sha256(binary.read_bytes()).digest(), old)
        self.assertEqual(subprocess.check_output([binary], text=True), 'Hello, Goose!\n')

    def test_corrupt_missing_and_unsafe_cache_entries(self):
        self.run_cached()
        for mutation in ['program', 'record', 'missing']:
            with self.subTest(mutation=mutation):
                if mutation == 'missing': (self.slot/'program').unlink()
                elif mutation == 'program':
                    with (self.slot/'program').open('ab') as output: output.write(b'changed digest; still ELF')
                else: (self.slot/mutation).write_bytes(b'corrupt')
                logs = self.mark_compiler_logs(); self.run_cached(); self.assert_logs(logs, False)
        victim = self.root/'victim'; victim.write_bytes(b'keep')
        (self.slot/'program').unlink(); (self.slot/'program').symlink_to(victim)
        self.run_cached(); self.assertEqual(victim.read_bytes(), b'keep')
        self.assertFalse((self.slot/'record').exists())
        (self.slot/'program').unlink(); self.run_cached()
        (self.slot/'record').unlink(); (self.slot/'record').symlink_to(victim)
        self.run_cached(); self.assertEqual(victim.read_bytes(), b'keep')
        (self.slot/'record').unlink(); self.run_cached()
        self.slot.chmod(0o755)
        logs = self.mark_compiler_logs(); self.run_cached(); self.assert_logs(logs, False)
        self.assertEqual(self.slot.stat().st_mode & 0o777, 0o755)
        self.slot.chmod(0o700)
        self.call('clean', cwd=self.project)
        foreign = self.root/'foreign'; foreign.mkdir(); (foreign/'sentinel').write_bytes(b'keep')
        (self.project/'.honk/reuse').symlink_to(foreign, target_is_directory=True)
        self.run_cached()
        self.assertEqual([p.name for p in foreign.iterdir()], ['sentinel'])
        self.assertEqual((foreign/'sentinel').read_bytes(), b'keep')

    def test_native_embed_and_other_module_fallback(self):
        source = self.project/'src/main.goose'
        for text, expected in [('fn main() { print("Hello, Goose!"); }\nextern fn not_called() = "unused_external";\n', 'Hello, Goose!\n'),
                               ('fn main() { print(embed_file("message.txt")); }\n', 'embedded\n'),
                               ('import os; fn main() { print("Hello, Goose!"); }\n', 'Hello, Goose!\n')]:
            with self.subTest(text=text):
                (self.project/'src/message.txt').write_text('embedded')
                source.write_text(text); self.run_cached(expected)
                self.assertFalse((self.slot/'record').exists())
        source.write_text('fn main() { print("Hello, Goose!"); }\n')
        (self.project/'src/main.build').write_text('c_flags_cc = [];\n')
        self.run_cached(); self.assertFalse((self.slot/'record').exists())

    def test_wrapper_and_excessive_asset_fallback_and_flag_scope(self):
        compiler = self.root/'wrapper'
        compiler.write_text('#!/bin/sh\nexec '+shlex.quote(GOOSE)+' "$@"\n'); compiler.chmod(0o755)
        self.run_cached(extra={'GOOSE': str(compiler)})
        self.assertFalse((self.slot/'record').exists())
        self.env.pop('GOOSE_HOME')
        self.env['HOME'] = str(self.root/'private-home')
        self.run_cached(); self.assertTrue((self.slot/'record').exists())
        (self.project/'large.bin').write_bytes(b'x'*(8388608+1))
        self.run_cached(); self.assertFalse((self.slot/'record').exists())
        for command in ['check', 'test', 'clean', 'package', 'metadata']:
            self.call(command, '--reuse-build', cwd=self.project, ok=False)
        self.assertTrue((self.project/'target/debug/demo').exists())


if __name__ == '__main__':
    unittest.main()

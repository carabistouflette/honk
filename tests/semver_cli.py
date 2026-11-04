#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real Honk package/selection boundaries; exact Git refs remain unsolved."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HONK = str(Path(os.environ['HONK']).resolve())
PROBE = str(Path(os.environ['SEMVER_PROBE']).resolve())

class SemverCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk-semver-')
        self.root = Path(self.temp.name)
        self.env = {**os.environ, 'HONK_HOME': str(self.root / 'cache')}
    def tearDown(self):
        self.temp.cleanup()
    def call(self, *args, cwd=None, ok=True):
        p = subprocess.run([HONK, *args], cwd=cwd or self.root, env=self.env,
                           capture_output=True, timeout=30)
        self.assertEqual(p.returncode == 0, ok, p.stdout + p.stderr)
        self.assertNotIn(b'AddressSanitizer', p.stderr)
        self.assertNotIn(b'runtime error:', p.stderr)
        return p
    def package(self, name, version):
        path = self.root / name
        (path / 'src').mkdir(parents=True, exist_ok=True)
        (path / 'src/main.goose').write_text('fn main() {}\n')
        (path / 'Honk.toml').write_text('[package]\nname = "app"\nversion = ' + json.dumps(version) + '\n')
        return path
    def workspace(self, versions):
        members = [f'm{i}' for i in range(len(versions))]
        (self.root / 'Honk.toml').write_text('[workspace]\nmembers = ' + json.dumps(members) + '\n')
        return [self.package(name, version) for name, version in zip(members, versions)]
    def test_strict_versions_and_filename_bound(self):
        valid = ['1.2.3', '1.2.3-alpha.1+build.5', '999999999999999999999.0.0', '1.0.0-' + 'a' * 58]
        for i, version in enumerate(valid):
            with self.subTest(version=version):
                path = self.package('valid' + str(i), version)
                self.assertEqual(json.loads(self.call('metadata', cwd=path).stdout)['version'], version)
                if len(version) == 64:
                    self.call('fetch', '--offline', cwd=path)
                    subprocess.run(['git', 'init', '-q'], cwd=path, check=True)
                    subprocess.run(['git', 'add', 'Honk.toml', 'Honk.lock', 'src'], cwd=path, check=True)
                    self.call('package', '--frozen', cwd=path)
                    self.assertTrue((path / 'target/package' / ('app-' + version + '.tar.gz')).is_file())
        for i, version in enumerate(['v1.2.3', '1.2', '01.2.3', '1.2.3-01', '1.2.3+', '1.2.3-α', '1.0.0-' + 'a' * 59]):
            with self.subTest(version=version):
                p = self.call('metadata', cwd=self.package('invalid' + str(i), version), ok=False)
                self.assertEqual(p.stdout, b'')
                self.assertIn(b'strict SemVer', p.stderr)
    def test_version_selection_and_early_rejection(self):
        members = self.workspace(['1.2.3', '1.10.0', '1.2.3-alpha.1'])
        for member in members:
            (member / 'target').mkdir()
            (member / 'target/keep').write_text('keep')
        for selector in ['app', 'app@', 'app@v1.2.3', 'app@1.2', 'app@2.0.0', 'app@1.2.3@x', '@1.2.3']:
            with self.subTest(selector=selector):
                self.call('clean', '-p', selector, ok=False)
                self.assertTrue(all((m / 'target/keep').exists() for m in members))
                self.assertEqual(self.call('metadata', '-p', selector, ok=False).stdout, b'')
        for version, member in zip(['1.2.3', '1.10.0', '1.2.3-alpha.1'], members):
            p = json.loads(self.call('metadata', '-p', 'app@' + version).stdout)
            self.assertEqual(p['root'], str(member))
            p = json.loads(self.call('metadata', '--workspace', '-p', 'app@' + version).stdout)
            self.assertEqual(len(p), 1)
            self.assertEqual(p[0]['version'], version)
        self.call('clean', '-p', 'app@1.10.0')
        self.assertFalse((members[1] / 'target').exists())
        self.assertTrue((members[0] / 'target/keep').exists())
    def test_selector_version_length_bound(self):
        version = '1.0.0-' + 'a' * 58
        member = self.workspace([version])[0]
        (member / 'target').mkdir()
        sentinel = member / 'target/keep'
        sentinel.write_text('keep')
        metadata = json.loads(self.call('metadata', '-p', 'app@' + version).stdout)
        self.assertEqual(metadata['root'], str(member))
        self.assertEqual(metadata['version'], version)
        selector = 'app@' + version + 'a'
        failed = self.call('metadata', '-p', selector, ok=False)
        self.assertEqual(failed.stdout, b'')
        self.assertIn(b'exceeds 64 bytes', failed.stderr)
        self.call('clean', '-p', selector, ok=False)
        self.assertEqual(sentinel.read_text(), 'keep')
    def test_build_only_versions_remain_ambiguous(self):
        self.workspace(['1.2.3+first', '1.2.3+second'])
        for selector in ['app', 'app@1.2.3', 'app@1.2.3+first', 'app@1.2.3+other']:
            p = self.call('metadata', '-p', selector, ok=False)
            self.assertEqual(p.stdout, b'')
            self.assertIn(b'ambiguous', p.stderr)
    def probe(self, mode, ref, requirement=None):
        args = [PROBE, mode, ref] + ([] if requirement is None else [requirement])
        p = subprocess.run(args, capture_output=True, timeout=10)
        self.assertNotIn(b'AddressSanitizer', p.stderr)
        self.assertNotIn(b'runtime error:', p.stderr)
        return p
    def test_enumerated_real_git_tags_and_constraints(self):
        subprocess.run(['git', 'init', '-q'], cwd=self.root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture'], cwd=self.root, check=True)
        tags = ['1.2.3', 'v1.10.0', 'v2.0.0-beta.1', 'v2.0.0+build', 'vv1.2.3', 'v01.2.3']
        for tag in tags:
            subprocess.run(['git', 'tag', tag], cwd=self.root, check=True)
        subprocess.run(['git', 'branch', '1.2.3'], cwd=self.root, check=True)
        refs = subprocess.check_output(['git', 'for-each-ref', '--format=%(refname)', 'refs/tags'], cwd=self.root).decode().splitlines()
        self.assertEqual(len(refs), len(tags))
        for ref in refs:
            p = self.probe('tag', ref)
            accepted = ref not in ['refs/tags/vv1.2.3', 'refs/tags/v01.2.3']
            self.assertEqual(p.returncode == 0, accepted, ref)
            if accepted:
                spelling = ref[len('refs/tags/'):]
                if spelling.startswith('v'):
                    spelling = spelling[1:]
                self.assertEqual(p.stdout, (spelling + '\n').encode())
        for ref in ['1.2.3', 'v1.2.3', 'refs/heads/1.2.3', 'refs/tags/']:
            self.assertEqual(self.probe('tag', ref).returncode, 2)
        cases = [('refs/tags/v1.10.0', '>=1.2.3,<2.0.0', 0),
                 ('refs/tags/1.2.3', '1.2.3', 0),
                 ('refs/tags/v1.10.0', '1.2.3', 1),
                 ('refs/tags/v2.0.0-beta.1', '*', 1),
                 ('refs/tags/v2.0.0-beta.1', '>=2.0.0-beta.0,<2.0.0', 0),
                 ('refs/tags/v2.0.0+build', '=2.0.0', 0),
                 ('refs/tags/1.2.3', '^1.2', 2)]
        for ref, requirement, result in cases:
            with self.subTest(ref=ref, requirement=requirement):
                self.assertEqual(self.probe('match', ref, requirement).returncode, result)

if __name__ == '__main__':
    unittest.main()

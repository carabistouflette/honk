#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise real Honk dispatch and its fixed HTTPS endpoint via a test-only shim."""
import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

if not __debug__:
    raise SystemExit('HTTPS fixture assertions require Python without optimization')
sys.path.insert(0, str(Path(__file__).resolve().parent / 'http_fixture'))
import metadata as fixture

HONK = str(Path(os.environ['HONK_METADATA']).resolve())
PIN = (Path(__file__).resolve().parents[1] / 'GOOSE_REVISION').read_text().strip()

class MetadataCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk-https-')
        self.root = Path(self.temp.name)
        self.project = self.root / 'project with spaces'; self.project.mkdir()
        self.cache = self.root / 'cache'
        self.lock = self.project / 'Honk.lock'; self.lock.write_bytes(b'ignored lock sentinel\n')
        self.manifest(fixture.REVISION)
    def tearDown(self): self.temp.cleanup()
    def manifest(self, revision):
        (self.project / 'Honk.toml').write_text('[package]\nname="app"\nversion="1.2.3"\n[toolchain]\nrevision=' + json.dumps(revision) + '\n')
    def untouched(self):
        self.assertFalse(self.cache.exists())
        self.assertEqual(self.lock.read_bytes(), b'ignored lock sentinel\n')
        for name in ['.honk', 'target', '.toolchain']:
            self.assertFalse((self.project / name).exists(), name)
    def call(self, environment, *args, cwd=None, **options):
        env = {**environment, 'GOOSE': '/must-not-run/compiler', 'HONK_HOME': str(self.cache), 'PATH': '/must-not-run/tools'}
        p = subprocess.run([HONK, *args], cwd=cwd or self.project, env=env,
                           stderr=subprocess.PIPE, timeout=12, **options)
        self.untouched()
        self.assertNotIn(b'AddressSanitizer', p.stderr)
        self.assertNotIn(b'runtime error:', p.stderr)
        return p
    def request(self, environment, **options):
        return self.call(environment, 'toolchain', '--metadata', stdout=subprocess.PIPE, **options)
    def failed(self, p):
        self.assertEqual(p.returncode, 1, (p.stdout, p.stderr))
        self.assertEqual(p.stdout, b'')
        self.assertNotIn(fixture.SENTINEL.encode(), p.stderr)
    def test_real_responses_and_request_policy(self):
        with fixture.fixture() as (server, env):
            for name, reply, success in fixture.cases():
                with self.subTest(case=name):
                    server.reply = reply; before = len(server.requests)
                    p = self.request(env)
                    self.assertEqual(len(server.requests), before + 1)
                    self.assertFalse(server.errors, server.errors)
                    if success:
                        self.assertEqual(p.returncode, 0, p.stderr)
                        self.assertEqual(p.stderr, b'')
                        subject = '' if name == 'empty-message' else 'first' if name == 'cr-subject' else fixture.MESSAGE.split('\n')[0]
                        self.assertEqual(json.loads(p.stdout), dict(requested_revision=fixture.REVISION, sha=fixture.REVISION, html_url=fixture.URL, subject=subject))
                        self.assertFalse(any(c < 32 for c in p.stdout.rstrip(b'\n')))
                    else: self.failed(p)
    def test_tls_and_timeout(self):
        with fixture.fixture() as (server, env):
            server.reply = fixture.response(fixture.document())
            for trust in ['untrusted', 'wrong-host']:
                self.failed(self.request({**env, 'GOOSE_METADATA_FIXTURE_TRUST': trust}))
                self.assertEqual(server.requests, [])
            server.delay = 6
            self.failed(self.request(env))
            self.assertEqual(len(server.requests), 1, 'timeout retried')
    def test_flags_and_invalid_pins_do_not_request_network(self):
        with fixture.fixture() as (server, env):
            for options in [['--offline'], ['--frozen'], ['--locked'], ['--workspace'], ['-p', 'app'], ['--bin', 'app'], ['extra']]:
                with self.subTest(options=options):
                    self.failed(self.call(env, 'toolchain', '--metadata', *options, stdout=subprocess.PIPE))
            for command in ['metadata', 'build', 'new']:
                self.failed(self.call(env, command, '--metadata', stdout=subprocess.PIPE))
            for revision in ['a'*39, 'a'*41, 'g'*40, fixture.REVISION.upper(), '../'+'a'*37, 'https://example.invalid/'+'a'*40]:
                self.manifest(revision); self.failed(self.request(env))
            self.manifest(fixture.REVISION)
            plain = self.call(env, 'metadata', stdout=subprocess.PIPE)
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertEqual(json.loads(plain.stdout)['name'], 'app')
            self.assertEqual(self.call(env, 'toolchain', '--metadata', '--help', stdout=subprocess.PIPE).returncode, 0)
            self.assertEqual(server.requests, [])
    @contextlib.contextmanager
    def revision_fixture(self, revision):
        previous_revision, previous_path = fixture.REVISION, fixture.PATH
        fixture.REVISION = revision
        fixture.PATH = f'/repos/aardappel/goose/commits/{revision}'.encode()
        try:
            with fixture.fixture() as pair: yield pair
        finally:
            fixture.REVISION, fixture.PATH = previous_revision, previous_path
    def test_default_pin_and_manifest_override(self):
        outside = self.root / 'outside'; outside.mkdir()
        with self.revision_fixture(PIN) as (server, env):
            server.reply = fixture.response(fixture.document())
            p = self.request(env, cwd=outside)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)['requested_revision'], PIN)
        with fixture.fixture() as (server, env):
            server.reply = fixture.response(fixture.document())
            p = self.call(env, 'toolchain', '--metadata', '--manifest-path', str(self.project/'Honk.toml'), cwd=outside, stdout=subprocess.PIPE)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)['requested_revision'], fixture.REVISION)
            nested = self.project / 'nested'; nested.mkdir()
            self.assertEqual(self.request(env, cwd=nested).returncode, 0)
    def test_checked_output_and_transport_fixture_isolation(self):
        with fixture.fixture() as (server, env):
            server.reply = fixture.response(fixture.document())
            with open('/dev/full', 'wb') as full:
                p = self.call(env, 'toolchain', '--metadata', stdout=full)
            self.assertEqual(p.returncode, 1)
            self.assertIn(b'cannot write standard output', p.stderr)
            p = self.request({k:v for k,v in env.items() if not k.startswith('GOOSE_METADATA_FIXTURE_')})
            self.assertEqual(p.returncode, 90)
            self.assertIn(b'missing fixture environment', p.stderr)

if __name__ == '__main__': unittest.main()

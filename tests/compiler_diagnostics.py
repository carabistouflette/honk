#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real compiler output and inherited-stream regressions for honk check."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HONK = str(Path(os.environ['HONK']).resolve())
GOOSE = str(Path(os.environ['GOOSE']).resolve())


class CompilerDiagnostics(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk diagnostics " é ')
        self.root = Path(self.temp.name)
        self.env = {**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache'), 'NO_COLOR': '1'}
        self.project = self.root/'demo'
        self.call('new', 'demo', cwd=self.root)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args, cwd=None, extra=None):
        return subprocess.run([HONK, *map(str, args)], cwd=cwd or self.project,
                              env={**self.env, **(extra or {})}, capture_output=True, timeout=60)

    def invalid(self):
        (self.project/'src/main.goose').write_text('import std;\nfn main() { missing_identifier(); }\n')

    def test_success_and_progress_keep_json_stdout(self):
        for options in [[], ['--progress', 'always']]:
            result = self.call('check', '--diagnostics', 'json', *options)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [])

    def test_error_preserves_locations_related_text_and_exit(self):
        self.invalid()
        plain = self.call('check')
        explicit = self.call('check', '--diagnostics', 'text')
        structured = self.call('check', '--diagnostics', 'json')
        self.assertEqual(plain.returncode, 1)
        self.assertEqual(explicit.returncode, plain.returncode)
        self.assertEqual((explicit.stdout, explicit.stderr), (plain.stdout, plain.stderr))
        self.assertEqual(structured.returncode, plain.returncode)
        data = json.loads(structured.stdout)
        self.assertEqual(len(data), 1)
        item = data[0]
        self.assertEqual(item['severity'], 'error')
        self.assertIn('missing_identifier', item['message'])
        self.assertTrue(item['file'].endswith('/.honk/stage/app/src/main.goose'))
        self.assertEqual(item['line'], 2)
        self.assertGreater(item['col'], 0)
        self.assertGreater(item['endCol'], item['col'])
        self.assertTrue(item['related'])
        self.assertEqual((''.join(d['text']+'\n' for d in data)).encode(), plain.stderr)
        self.assertEqual(structured.stderr, b'')

    def test_parser_recovery_and_long_message(self):
        identifier = 'missing_' + 'a'*8192
        (self.project/'src/main.goose').write_text('fn main() { '+identifier+'(); }\n')
        result = self.call('check', '--diagnostics', 'json')
        self.assertEqual(result.returncode, 1)
        self.assertIn(identifier, json.loads(result.stdout)[0]['message'])
        (self.project/'src/main.goose').write_text('fn first( {\nfn second( {\n')
        result = self.call('check', '--diagnostics', 'json')
        self.assertEqual(result.returncode, 1)
        self.assertGreaterEqual(len(json.loads(result.stdout)), 1)

    def test_rejects_unsupported_commands_and_modes_before_project_work(self):
        cases = [('build', '--diagnostics', 'json'), ('run', '--diagnostics', 'json'),
                 ('test', '--diagnostics', 'json'), ('bench', '--diagnostics', 'json'),
                 ('watch', 'check', '--watch-dir', str(self.project), '--diagnostics', 'json'),
                 ('check', '--diagnostics', 'yaml'), ('check', '--diagnostics', '')]
        for args in cases:
            with self.subTest(args=args):
                result = self.call(*args, extra={'GOOSE': '/does/not/exist'})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'')
                self.assertIn(b'--diagnostics', result.stderr)
                self.assertFalse((self.project/'.honk').exists())

    def test_workspace_requires_single_selected_member(self):
        (self.root/'Honk.toml').write_text('[workspace]\nmembers=["demo"]\n')
        for args in [('check', '--diagnostics', 'json'), ('check', '--workspace', '--diagnostics', 'json')]:
            result = self.call(*args, cwd=self.root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'')
            self.assertIn(b'single package', result.stderr)
            self.assertFalse((self.project/'.honk').exists())
        result = self.call('check', '-p', 'demo', '--diagnostics', 'json', cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_preflight_failure_remains_stderr(self):
        result = self.call('check', '--diagnostics', 'json', extra={'GOOSE': '/does/not/exist'})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        self.assertTrue(result.stderr)

    def test_inherited_output_above_capture_limit_and_arbitrary_exit(self):
        driver = self.root/'compiler'
        payload = json.dumps([{'message': 'x' * 1048577}]).encode() + b'\n'
        stdout = self.root/'payload'; stdout.write_bytes(payload)
        driver.write_text('#!' + sys.executable + '\nimport os,sys\n'
                          'if "version" in sys.argv: os.execv('+repr(GOOSE)+', ['+repr(GOOSE)+', "version"])\n'
                          'assert sys.argv[-2:]==["--diagnostics","json"]\n'
                          'sys.stdout.buffer.write(open('+repr(str(stdout))+',"rb").read())\n'
                          'sys.stderr.buffer.write(b"driver stderr\\n")\nsys.exit(42)\n')
        driver.chmod(0o755)
        result = self.call('check', '--diagnostics', 'json', extra={'GOOSE': str(driver)})
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(result.stdout, payload)
        self.assertEqual(result.stderr, b'driver stderr\n')


if __name__ == '__main__':
    unittest.main()

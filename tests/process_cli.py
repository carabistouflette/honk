#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real adapter streams, bounds and native ownership-transfer fault routes."""
import os
from pathlib import Path
import subprocess
import signal
import tempfile
import unittest

PROBE = str(Path(os.environ['PROCESS_PROBE']).resolve())
FAULT = str(Path(os.environ['PROCESS_FAULT']).resolve())

class ProcessCLI(unittest.TestCase):
    def call(self, args, **options):
        input_bytes = options.pop('input', None)
        with subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              start_new_session=True, **options) as child:
            try:
                stdout, stderr = child.communicate(input_bytes, timeout=15)
            except subprocess.TimeoutExpired:
                # The leader is still owned/unreaped while a fixture holds its
                # pipes; terminate the private fixture group before draining.
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate(timeout=5)
                raise
            self.assertEqual(child.returncode, 0, stdout + stderr)
            self.assertNotIn(b'AddressSanitizer', stderr)
            self.assertNotIn(b'runtime error:', stderr)
            return subprocess.CompletedProcess(args, child.returncode, stdout, stderr)
    def test_independent_streams(self):
        p = self.call([PROBE, 'streams'])
        self.assertEqual(p.stdout, b'')
        self.assertEqual(p.stderr, b'live-stderr')
    def test_stdin_is_inherited(self):
        self.call([PROBE, 'stdin'], input=b'inherited stdin\n')
    def test_exact_capture_and_argument_bounds(self):
        for mode in ['exact', 'overflow', 'arguments']:
            with self.subTest(mode=mode): self.call([PROBE, mode])
    def test_startup_signal_and_exceptional_recovery(self):
        with tempfile.TemporaryDirectory(prefix='honk-process-fault-') as root:
            lock = str(Path(root) / 'lock')
            self.call([FAULT, lock], env={**os.environ, 'HONK_TEST_PRESTART': '1'})
            self.call([FAULT, lock])
            p = self.call([FAULT, lock, 'transfer'], env={**os.environ, 'HONK_TEST_TRANSFER': '1', 'HONK_TEST_LOCK': lock})
            self.assertIn(b'retaining locks until cleanup completes', p.stderr)

if __name__ == '__main__': unittest.main()

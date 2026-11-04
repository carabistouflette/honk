#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real adapter streams, bounds and native ownership-transfer fault routes."""
import ctypes
import os
from pathlib import Path
import subprocess
import signal
import tempfile
import time
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
            self.assertNotIn(b'LeakSanitizer', stderr)
            self.assertNotIn(b'runtime error:', stderr)
            return subprocess.CompletedProcess(args, child.returncode, stdout, stderr)
    def test_broken_stderr_retains_transferred_child_cleanup(self):
        libc = ctypes.CDLL(None, use_errno=True)
        previous_subreaper = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous_subreaper), 0, 0, 0), 0)
        previous_chld = signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        self.assertEqual(Path(f'/proc/self/task/{os.getpid()}/children').read_text().strip(), '')
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        try:
            for mode, expected_policy in [('default',[1,0]),('ignored',[0,0]),('handler',[0,0]),('blocked',[1,1]),('pending',[1,1])]:
                with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='honk-broken-stderr-') as temporary:
                    root = Path(temporary); lock = root/'lock'; record = root/'child'
                    reader, writer = os.pipe(); os.close(reader)
                    child = None; orphan_alive = False; adopted = False; policy = None; stdout = b''
                    # Keep sanitizer diagnostics observable when stderr itself is the fault.
                    options = os.environ.get('ASAN_OPTIONS', '')
                    sanitizer = str(root/'sanitizer')
                    diagnostic_env = {'ASAN_OPTIONS':options+(':' if options else '')+'log_path='+sanitizer}
                    undefined = os.environ.get('UBSAN_OPTIONS', '')
                    diagnostic_env['UBSAN_OPTIONS'] = undefined+(':' if undefined else '')+'log_path='+sanitizer
                    try:
                        child = subprocess.Popen([FAULT, str(lock), 'transfer'], stdout=subprocess.PIPE,
                            stderr=writer, start_new_session=True,
                            env={**os.environ, 'HONK_TEST_TRANSFER':'1', 'HONK_TEST_LOCK':str(lock), 'HONK_TEST_CHILD':str(record), 'HONK_TEST_PIPE':mode, **diagnostic_env})
                        os.close(writer); writer = None
                        stdout, _ = child.communicate(timeout=5)
                    finally:
                        if writer is not None: os.close(writer)
                        if child is not None and child.returncode is None:
                            # No reaping has occurred: the fixture leader reserves its private group ID.
                            try: os.killpg(child.pid, signal.SIGKILL)
                            except ProcessLookupError: pass
                            child.communicate(timeout=5)
                        # With no pre-existing children or external reaper, every adopted
                        # child here belongs to this private fixture. Cleanup must also
                        # work if registration/record writing itself failed.
                        children = Path(f'/proc/self/task/{os.getpid()}/children')
                        deadline = time.monotonic()+5
                        while children.read_text().split():
                            for owned in map(int, children.read_text().split()):
                                try: waited, _ = os.waitpid(owned, os.WNOHANG)
                                except ChildProcessError: continue
                                adopted = True
                                if waited == 0:
                                    orphan_alive = True
                                    descriptor = os.pidfd_open(owned)
                                    try: signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                                    finally: os.close(descriptor)
                            if time.monotonic() >= deadline: self.fail('adopted fixture child did not terminate')
                            time.sleep(.005)
                        if record.exists():
                            owned, *policy = map(int, record.read_text().split())
                            self.assertGreater(owned, 0)
                        if child is not None and child.stdout is not None: child.stdout.close()
                    self.assertEqual(child.returncode, 0,
                        f'recovery exited {child.returncode}; live adopted child={orphan_alive}; SIGPIPE default/blocked={policy}; stdout={stdout!r}')
                    self.assertFalse(adopted, 'fixture returned before transferred child cleanup')
                    self.assertEqual(stdout, b''); self.assertEqual(policy, expected_policy)
                    reports = list(root.glob('sanitizer.*'))
                    self.assertFalse(reports, ''.join(path.read_text(errors='replace') for path in reports))
        finally:
            self.assertEqual(libc.prctl(36, previous_subreaper.value, 0, 0, 0), 0)
            signal.signal(signal.SIGCHLD, previous_chld)
    def test_independent_streams(self):
        p = self.call([PROBE, 'streams'])
        self.assertEqual(p.stdout, b'')
        self.assertEqual(p.stderr, b'live-stderr')
    def test_stdin_is_inherited(self):
        self.call([PROBE, 'stdin'], input=b'inherited stdin\n')
    def test_exact_capture_and_argument_bounds(self):
        for mode in ['exact', 'overflow', 'arguments']:
            with self.subTest(mode=mode): self.call([PROBE, mode])
        with tempfile.TemporaryDirectory(prefix='honk-deadline-') as root:
            marker = Path(root) / 'started'
            self.call([PROBE, 'deadline', str(marker)])
            self.assertEqual(marker.read_bytes(), b'started')
    def test_startup_signal_and_exceptional_recovery(self):
        with tempfile.TemporaryDirectory(prefix='honk-process-fault-') as root:
            lock = str(Path(root) / 'lock')
            self.call([FAULT, lock], env={**os.environ, 'HONK_TEST_PRESTART': '1'})
            self.call([FAULT, lock])
            p = self.call([FAULT, lock, 'transfer'], env={**os.environ, 'HONK_TEST_TRANSFER': '1', 'HONK_TEST_LOCK': lock})
            self.assertIn(b'retaining locks until cleanup completes', p.stderr)

if __name__ == '__main__': unittest.main()

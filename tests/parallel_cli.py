#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real CLI/binary regressions; file handshakes prove concurrency, never timing speed."""
import array
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import termios
import time
import unittest

HONK = os.environ['HONK']
GOOSE = os.environ['GOOSE']
PRELUDE = 'import std; import os; extern fn getpid() -> i32; extern fn raise(number: i32) -> i32;\n'


class Parallel(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk-parallel-')
        self.root = Path(self.temp.name)
        self.project = self.root/'app'
        (self.project/'src').mkdir(parents=True)
        (self.project/'tests').mkdir()
        (self.project/'Honk.toml').write_text('[package]\nname="parallel_fixture"\nversion="0.1.0"\nentry="src/main.goose"\n')
        (self.project/'src/main.goose').write_text('fn main() {}\n')
        self.env = {**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache')}

    def tearDown(self):
        self.temp.cleanup()

    def target(self, name, body):
        (self.project/'tests'/f'{name}.goose').write_text(PRELUDE + 'fn main() { ' + body + ' }\n')

    def call(self, *args, code=0, cwd=None, input=None):
        result = subprocess.run([HONK, *args], cwd=cwd or self.project, env=self.env,
                                input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn(b'AddressSanitizer', result.stderr)
        self.assertNotIn(b'runtime error:', result.stderr)
        return result

    def wait(self, predicate, proc, seconds=15):
        until = time.monotonic() + seconds
        while not predicate():
            if proc.poll() is not None:
                out, err = proc.communicate()
                self.fail(f'runner exited early: {proc.returncode}: {out[:1024]!r} {err[:1024]!r}')
            if time.monotonic() >= until:
                os.killpg(proc.pid, signal.SIGKILL)
                out, err = proc.communicate()
                self.fail(f'fixture did not reach handshake: {out[:1024]!r} {err[:1024]!r}')
            time.sleep(.01)

    def dead(self, names):
        for name in names:
            pid = int((self.project/name).read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_prevalidation_before_manifest_cache_or_compiler(self):
        bad = [('test', '--jobs', x) for x in ('', '0', '9', '-1', '+2', '02', '1.0', ' 2', '9'*100)]
        bad += [('test', '--jobs', '2', '--test-timeout-ms', x) for x in ('', '0', '-1', '+2', '86400001', '1.1', 'x')]
        bad += [('test', '--test-timeout-ms', '2'), ('build', '--jobs', '2'), ('bench', '--jobs', '2'),
                ('run', '--jobs', '2'), ('watch', 'test', '--reuse-build', '--watch-dir', '/does/not/exist'),
                ('watch', 'test', '--jobs', '2', '--watch-dir', '/does/not/exist')]
        self.env['GOOSE'] = '/does/not/exist'
        for args in bad:
            with self.subTest(args=args):
                self.call(*args, cwd=self.root, code=1)
                self.assertFalse((self.root/'cache').exists())

    def test_partial_cohorts_and_target_order(self):
        for n, jobs in ((1, 8), (3, 8), (3, 2), (3, 1)):
            with self.subTest(n=n, jobs=jobs):
                for path in (self.project/'tests').glob('*.goose'):
                    path.unlink()
                for i in range(n):
                    self.target(f'{i:02}', f'sleep_ms({(n-i)*25}); write_stdout("DATA{i}\\0\\xff"); write_stderr("ERR{i}\\0");')
                result = self.call('test', '--jobs', str(jobs))
                expected = b''.join(f'DATA{i}'.encode()+b'\0\xff' for i in range(n))
                self.assertTrue(result.stdout.endswith(expected + f'Passed {n} test targets\n'.encode()), result.stdout)
                self.assertEqual(result.stderr, b''.join(f'ERR{i}'.encode()+b'\0' for i in range(n)))

    def overlap_fixture(self, n, jobs):
        for i in range(n):
            group = i//jobs
            peers = list(range(group*jobs, min(n, (group+1)*jobs)))
            conditions = ' && '.join(f'file_exists("{p}.started")' for p in peers)
            previous = ''.join(f'assert(file_exists("{p}.done"));' for p in range(group*jobs))
            later = f'assert(!file_exists("{(group+1)*jobs}.started"));' if (group+1)*jobs < n else ''
            self.target(f'{i:02}', previous + f'assert(write_file("{i}.started", "yes"));'
                        + f'let deadline = clock_ns()+2000000000; while !({conditions}) && clock_ns()<deadline {{ sleep_ms(2); }}'
                        + f'assert({conditions}); sleep_ms({80 if i%2 == 0 else 10});' + later
                        + f'assert(write_file("{i}.done", "yes"));')
        self.call('test', '--jobs', str(jobs))
        self.assertTrue(all((self.project/f'{i}.done').exists() for i in range(n)))

    def test_overlap_cohort_bound_and_final_partial_group(self):
        self.overlap_fixture(5, 2)

    def test_all_eight_owners_overlap(self):
        self.overlap_fixture(8, 8)

    def test_default_inherited_stdin_and_explicit_null_stdin(self):
        self.target('one', 'var line: u8[>..] = []; if read_line(line) { print("INPUT:", line); } else { print("EOF"); }')
        self.assertIn(b'INPUT:hello\n', self.call('test', input=b'hello\n').stdout)
        self.assertIn(b'EOF\n', self.call('test', '--jobs', '1', input=b'hello\n').stdout)

    def test_literal_args_cwd_environment_filter_and_release(self):
        (self.project/'marker').write_text('yes')
        self.env['HONK_PARALLEL_VALUE'] = 'environment stays'
        self.target('selected', 'assert(file_exists("marker")); var value: u8[>..]=[]; assert(env("HONK_PARALLEL_VALUE",value));'
                    'assert(value=="environment stays"); let argv=args(); assert(argv.len==4);'
                    'assert(argv[1]=="a b" && argv[2]=="" && argv[3]=="$(touch owned)"); print("FORWARDED");')
        self.target('ignored', 'assert(false);')
        self.assertIn(b'FORWARDED', self.call('test', '--jobs', '2', '--release', '--filter', 'tests/selected.goose', '--', 'a b', '', '$(touch owned)').stdout)
        self.assertFalse((self.project/'owned').exists())

    def test_compile_failure_executes_no_test(self):
        self.target('a', 'assert(write_file("ran", "bad"));')
        (self.project/'tests/b.goose').write_text('this is not valid Goose source')
        result = subprocess.run([HONK, 'test', '--jobs', '2'], cwd=self.project, env=self.env, capture_output=True, timeout=90)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project/'ran').exists())

    def test_failed_cohort_finishes_and_chooses_first_target(self):
        self.target('a', 'sleep_ms(100); write_stdout("first"); exit(7);')
        self.target('b', 'assert(write_file("sibling.done", "yes")); write_stdout("second"); exit(9);')
        self.target('c', 'assert(write_file("later.ran", "bad"));')
        result = self.call('test', '--jobs', '2', code=7)
        self.assertTrue(result.stdout.endswith(b'firstsecond'))
        self.assertTrue((self.project/'sibling.done').exists())
        self.assertFalse((self.project/'later.ran').exists())
        self.assertNotIn(b'Passed', result.stdout)

    def test_child_signal_exit_is_not_parent_cancellation(self):
        self.target('a', 'assert(raise(15)==0);')
        self.target('b', 'sleep_ms(30); assert(write_file("sibling.done","yes"));')
        self.target('c', 'assert(write_file("later.ran","bad"));')
        self.call('test', '--jobs', '2', code=143)
        self.assertTrue((self.project/'sibling.done').exists())
        self.assertFalse((self.project/'later.ran').exists())

    def test_child_exit125_is_not_supervision_failure(self):
        self.target('a', 'exit(125);')
        result = self.call('test', '--jobs', '2', code=125)
        self.assertEqual(result.stderr, b'')

    def test_exact_capture_limits_and_duplex_pressure(self):
        self.target('a', 'var data: u8[>..]=[]; for i in 65536 { data.push(65); } write_stdout(data); write_stderr(data);')
        self.target('b', 'var data: u8[>..]=[]; for i in 65536 { data.push(66); } write_stderr(data); write_stdout(data);')
        result = self.call('test', '--jobs', '2')
        self.assertTrue(result.stdout.endswith(b'A'*65536 + b'B'*65536 + b'Passed 2 test targets\n'))
        self.assertEqual(result.stderr, b'A'*65536 + b'B'*65536)

    def test_output_overflow_closes_running_sibling(self):
        self.target('a', 'assert(write_file("a.pid",str(getpid()))); assert(write_file("ready","yes")); sleep_ms(3000);')
        self.target('b', 'assert(write_file("b.pid",str(getpid()))); let until=clock_ns()+1000000000;'
                    'while !file_exists("ready") && clock_ns()<until { sleep_ms(2); } assert(file_exists("ready"));'
                    'var data: u8[>..]=[]; for i in 65537 { data.push(88); } write_stdout(data);')
        result = self.call('test', '--jobs', '2', code=125)
        self.assertIn(b'output limit exceeded', result.stderr)
        self.dead(('a.pid', 'b.pid'))
        self.call('fetch', '--frozen')

    def test_timeout_closes_and_reaps_direct_children(self):
        for name in ('a', 'b'):
            self.target(name, f'assert(write_file("{name}.pid",str(getpid()))); sleep_ms(3000);')
        result = self.call('test', '--jobs', '2', '--test-timeout-ms', '150', code=125)
        self.assertIn(b'deadline exceeded', result.stderr)
        self.dead(('a.pid', 'b.pid'))
        self.call('fetch', '--frozen')

    def test_cancellation_cleans_every_child_and_releases_locks(self):
        for name in ('a', 'b'):
            self.target(name, f'assert(write_file("{name}.pid",str(getpid()))); sleep_ms(4000);')
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                for name in ('a', 'b'):
                    (self.project/f'{name}.pid').unlink(missing_ok=True)
                proc = subprocess.Popen([HONK, 'test', '--jobs', '2'], cwd=self.project, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                try:
                    self.wait(lambda: all((self.project/f'{name}.pid').exists() for name in ('a', 'b')), proc)
                    os.kill(proc.pid, sig)
                    out, err = proc.communicate(timeout=10)
                    self.assertEqual(proc.returncode, 128+sig, out+err)
                    self.dead(('a.pid', 'b.pid'))
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL); proc.communicate()
                self.call('fetch', '--frozen')

    def test_cancel_during_replay_does_not_admit_next_cohort(self):
        self.target('a', 'var data:u8[>..]=[]; for i in 65536 { data.push(65); } write_stdout(data); assert(write_file("a.done","yes"));')
        self.target('b', 'assert(write_file("b.done","yes")); print("B");')
        self.target('c', 'assert(write_file("later.ran","bad"));')
        proc = subprocess.Popen([HONK, 'test', '--jobs', '2'], cwd=self.project, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            fcntl.fcntl(proc.stdout, fcntl.F_SETPIPE_SZ, 4096)
            def blocked_after_cleanup():
                available = array.array('i', [0])
                fcntl.ioctl(proc.stdout, termios.FIONREAD, available)
                children = Path(f'/proc/{proc.pid}/task/{proc.pid}/children').read_text().strip()
                return available[0] > 0 and not children and all((self.project/f"{name}.done").exists() for name in ("a", "b"))
            self.wait(blocked_after_cleanup, proc)
            os.kill(proc.pid, signal.SIGTERM)
            out, err = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 143, out+err)
            self.assertFalse((self.project/'later.ran').exists())
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL); proc.communicate()

    def test_broken_output_after_cleanup(self):
        self.target('a', 'assert(write_file("a.pid",str(getpid()))); var data:u8[>..]=[]; for i in 65536 { data.push(65); } write_stdout(data); assert(write_file("a.done","yes"));')
        self.target('b', 'assert(write_file("b.pid",str(getpid()))); assert(write_file("b.done","yes"));')
        proc = subprocess.Popen([HONK, 'test', '--jobs', '2'], cwd=self.project, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            fcntl.fcntl(proc.stdout, fcntl.F_SETPIPE_SZ, 4096)
            def replaying():
                return all((self.project/f'{name}.done').exists() for name in ('a', 'b')) and not Path(f'/proc/{proc.pid}/task/{proc.pid}/children').read_text().strip()
            self.wait(replaying, proc)
            proc.stdout.close()
            proc.stdout = None
            _, err = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 125, err)
            self.dead(('a.pid', 'b.pid'))
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL); proc.communicate()
        self.call('fetch', '--frozen')

    def test_workspace_members_stay_sequential(self):
        self.target('a', 'sleep_ms(40); assert(write_file("a.done","yes"));')
        self.target('b', 'assert(write_file("b.done","yes"));')
        other = self.root/'other'
        (other/'src').mkdir(parents=True)
        (other/'tests').mkdir()
        (other/'Honk.toml').write_text('[package]\nname="other_fixture"\nentry="src/main.goose"\n')
        (other/'src/main.goose').write_text('fn main() {}')
        (other/'tests/one.goose').write_text(PRELUDE+'fn main() { assert(file_exists("../app/a.done") && file_exists("../app/b.done")); print("OTHER"); }')
        (self.root/'Honk.toml').write_text('[workspace]\nmembers=["app","other"]\n')
        result = self.call('test', '--workspace', '--jobs', '2', cwd=self.root)
        self.assertIn(b'Passed 2 test targets', result.stdout)
        self.assertIn(b'Passed 1 test targets', result.stdout)
        self.assertIn(b'OTHER', result.stdout)


if __name__ == '__main__':
    unittest.main()

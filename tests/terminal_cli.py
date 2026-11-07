#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real Honk processes with PTY destinations and deterministic local children."""
import errno
import fcntl
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

HONK = str(Path(os.environ['HONK']).resolve())
GOOSE = str(Path(os.environ['GOOSE']).resolve())


class Terminal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk-terminal-')
        self.root = Path(self.temp.name)
        self.project = self.root/'project'; (self.project/'src').mkdir(parents=True)
        (self.project/'src/main.goose').write_text('fn main() {}\n')
        (self.project/'Honk.toml').write_text('[package]\nname="hello"\nversion="0.1.0"\nentry="src/main.goose"\n')
        version = subprocess.check_output([GOOSE, 'version'], text=True).strip()
        compiler = self.root/'compiler'
        compiler.write_text('#!'+sys.executable+'\n'+'''
import os,sys,time
from pathlib import Path
if "version" in sys.argv:
    print(VERSION); sys.exit(0)
if os.environ.get("FAULT"):
    print("compiler failure", file=sys.stderr); sys.exit(7)
if "-o" in sys.argv:
    if os.environ.get("RESIZE"):
        counter = Path(os.environ["RESIZE"])
        index = int(counter.read_text())+1 if counter.exists() else 1
        counter.write_text(str(index))
        release = counter.with_suffix(".release"+str(index))
        deadline = time.monotonic()+10
        while not release.exists():
            if time.monotonic() > deadline: sys.exit(90)
            time.sleep(.005)
    output = Path(sys.argv[sys.argv.index("-o")+1]); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text("#!/bin/sh\\nprintf 'child stdout\\\\n'\\n" + ("" if os.environ.get("QUIET") else "printf 'child stderr\\\\n' >&2\\n"))
    output.chmod(0o755)
if not os.environ.get("QUIET"): print("compiler diagnostic", file=sys.stderr, end="" if os.environ.get("NOLINE") else chr(10))
'''.replace('VERSION', repr(version)))
        compiler.chmod(0o755)
        self.env = {**os.environ, 'GOOSE': str(compiler), 'HONK_HOME': str(self.root/'cache'),
                    'TERM': 'xterm-256color', 'NO_COLOR': ''}
    def tearDown(self):
        self.temp.cleanup()
    def run_honk(self, *args, env=None):
        return subprocess.run([HONK,*args], cwd=self.project, env={**self.env,**(env or {})},
                              capture_output=True, timeout=20)
    def targets(self):
        (self.project/'tests').mkdir()
        for name in ('one','two'): (self.project/'tests'/f'{name}.goose').write_text('fn main() {}\n')
    def terminal(self, *args, env=None, width=80, resize=False):
        master, slave = pty.openpty()
        attrs = termios.tcgetattr(slave); attrs[1] &= ~termios.OPOST; termios.tcsetattr(slave, termios.TCSANOW, attrs)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH',24,width,0,0))
        counter = self.root/'resize'
        proc = subprocess.Popen([HONK,*args], cwd=self.project, stdout=subprocess.PIPE, stderr=slave,
                                env={**self.env,**(env or {}),**({'RESIZE':str(counter)} if resize else {})})
        received = bytearray(); deadline = time.monotonic()+20
        try:
            if resize:
                for index, cols in ((1,8),(2,80)):
                    while not counter.exists() or counter.read_text() != str(index):
                        if time.monotonic() > deadline: self.fail('compiler barrier not reached')
                        time.sleep(.005)
                    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH',24,cols,0,0))
                    counter.with_suffix('.release'+str(index)).touch()
            os.close(slave); slave = -1
            while time.monotonic() < deadline:
                ready,_,_ = select.select([master],[],[],.05)
                if ready:
                    try: chunk = os.read(master,65536)
                    except OSError as error:
                        if error.errno == errno.EIO: break
                        raise
                    if not chunk: break
                    received.extend(chunk)
                elif proc.poll() is not None: break
            stdout,_ = proc.communicate(timeout=5)
            return proc.returncode, stdout, bytes(received)
        finally:
            if proc.poll() is None: proc.kill(); proc.communicate(timeout=5)
            if slave >= 0: os.close(slave)
            os.close(master)
    def test_redirected_defaults_and_policy(self):
        default = self.run_honk('check'); never = self.run_honk('check','--progress','never')
        auto = self.run_honk('check','--progress','auto'); always = self.run_honk('check','--progress','always')
        for result in (default,never,auto,always): self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(default.stdout,never.stdout); self.assertEqual(default.stderr,never.stderr)
        self.assertEqual(default.stderr,auto.stderr)
        self.assertEqual(always.stderr,b'compiler diagnostic\n\nCheck complete\n')
        self.assertNotIn(b'\x1b',always.stderr); self.assertNotIn(b'\r',always.stderr)
    def test_filtered_progress_counts_only_selected_targets(self):
        self.targets()
        (self.project/'tests/three.goose').write_text('fn main() {}\n')
        baseline = self.run_honk('test','--filter','tests/t*.goose')
        shown = self.run_honk('test','--filter','tests/t*.goose','--progress','always')
        self.assertEqual(baseline.returncode,0,baseline.stderr)
        self.assertEqual(shown.returncode,0,shown.stderr)
        self.assertEqual(shown.stdout,baseline.stdout)
        self.assertIn(b'Passed 2 test targets\n',shown.stdout)
        self.assertIn(b'1/2 test\n',shown.stderr); self.assertIn(b'2/2 test\n',shown.stderr)
        self.assertNotIn(b'/3 test',shown.stderr)
        self.assertNotIn(b'\x1b',shown.stderr); self.assertNotIn(b'\r',shown.stderr)
    def test_pty_color_policy_and_narrow_fallback(self):
        self.targets()
        for extra,colored in (({},True),({'TERM':'dumb'},False),({'NO_COLOR':'1'},False),({'TERM':''},False)):
            with self.subTest(env=extra):
                code,stdout,stderr = self.terminal('test','--progress','auto',env=extra)
                self.assertEqual(code,0,stderr); self.assertIn(b'Passed 2 test targets\n',stdout)
                self.assertEqual(b'\x1b[32m' in stderr,colored)
                self.assertIn(b'1/2 test',stderr); self.assertIn(b'2/2 test',stderr)
                self.assertTrue(stderr.endswith(b'\n')); self.assertNotIn(b'\r',stderr); self.assertNotIn(b'\x1b[2K',stderr)
        code,_,stderr = self.terminal('test','--progress','auto',width=8)
        self.assertEqual(code,0,stderr); self.assertIn(b'Completed target',stderr)
        self.assertNotIn(b'1/2 test',stderr)
    def test_resize_between_targets(self):
        self.targets(); code,_,stderr = self.terminal('test','--progress','auto',resize=True)
        self.assertEqual(code,0,stderr); self.assertIn(b'Completed target',stderr)
        self.assertNotIn(b'1/2 test',stderr); self.assertIn(b'2/2 test',stderr)
    def test_child_bytes_and_failure_are_preserved(self):
        baseline = self.run_honk('run'); shown = self.run_honk('run','--progress','always')
        self.assertEqual(shown.returncode,0,shown.stderr); self.assertEqual(shown.stdout,baseline.stdout)
        self.assertIn(b'child stderr\n',shown.stderr); self.assertIn(b'Run complete\n',shown.stderr)
        code,stdout,stderr = self.terminal('check','--progress','auto',env={'FAULT':'1'})
        self.assertEqual(code,7,stdout+stderr); self.assertEqual(stderr,b'compiler failure\n')
    def test_unterminated_child_diagnostics_are_not_erased(self):
        code,_,stderr = self.terminal('check','--progress','auto',env={'NOLINE':'1','NO_COLOR':'1'})
        self.assertEqual(code,0,stderr)
        self.assertEqual(stderr,b'compiler diagnostic\nCheck complete\n')
        self.assertNotIn(b'\r',stderr); self.assertNotIn(b'\x1b[2K',stderr)
    def test_broken_progress_pipe_preserves_success(self):
        read_fd, write_fd = os.pipe(); os.close(read_fd)
        try:
            result = subprocess.run([HONK,'check','--progress','always'],cwd=self.project,
                                    env={**self.env,'QUIET':'1'},stdout=subprocess.PIPE,stderr=write_fd,timeout=20,
                                    restore_signals=True)
            self.assertEqual(result.returncode,0,result.stdout)
        finally: os.close(write_fd)
    def test_invalid_policies_and_machine_commands(self):
        for args in (('check','--progress','bad'),('metadata','--progress','always'),
                     ('tree','--progress','auto'),('toolchain','--metadata','--progress','always')):
            result = self.run_honk(*args); self.assertNotEqual(result.returncode,0)
            self.assertNotIn(b'Check complete',result.stderr); self.assertNotIn(b'\x1b',result.stderr)


if __name__ == '__main__': unittest.main()

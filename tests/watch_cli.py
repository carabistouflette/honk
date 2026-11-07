#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real watcher/Honk processes with controlled compiler barriers; no shell argv."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
HONK = str(Path(os.environ['HONK']).resolve())
GOOSE = str(Path(os.environ['GOOSE']).resolve())

class Watch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk-watch-')
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'; self.src = self.project / 'src'; self.src.mkdir(parents=True)
        (self.src/'main.goose').write_text('fn main() {}\n')
        (self.project/'Honk.toml').write_text('[package]\nname="hello"\nversion="0.1.0"\nentry="src/main.goose"\n')
        version = subprocess.check_output([GOOSE,'version'],text=True).strip()
        compiler = self.root/'compiler'
        compiler.write_text('#!'+sys.executable+'\n'+r'''
import json,os,signal,sys,time
from pathlib import Path
if 'version' in sys.argv:
    print(VERSION); sys.exit(0)
root=Path(os.environ['CONTROL'])
active=root/'active'
fd=os.open(active,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
count=root/'count'
n=int(count.read_text())+1 if count.exists() else 1
(root/'next').write_text(str(n));(root/'next').replace(count)
def stop(number,frame):
    if os.environ.get('DELAY_CLEANUP'):
        with (root/'signals').open('ab') as out: out.write(bytes([number]))
        end=time.monotonic()+10
        while not (root/'cleanup-release').exists():
            if time.monotonic()>end: raise SystemExit(91)
            time.sleep(.005)
    raise SystemExit(128+number)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
try:
    (root/'pid').write_text(str(os.getpid()))
    if n==1 and os.environ.get('GATE_FIRST'):
        end=time.monotonic()+15
        while not (root/'release').exists():
            if time.monotonic()>end: sys.exit(90)
            time.sleep(.005)
    if '-o' in sys.argv:
        out=Path(sys.argv[sys.argv.index('-o')+1])
        out.write_text('#!'+sys.executable+'\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["CONTROL"],"args").write_text(json.dumps(sys.argv[1:]))\n')
        out.chmod(0o755)
    sys.exit(7 if n==1 and os.environ.get('FAIL_FIRST') else 0)
finally:
    active.unlink()
'''.replace('VERSION',repr(version)))
        compiler.chmod(0o755)
        self.env={**os.environ,'GOOSE':str(compiler),'HONK_HOME':str(self.root/'cache'),'CONTROL':str(self.root)}
        self.proc=None; self.log=None
    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid,signal.SIGKILL);self.proc.communicate(timeout=5)
        if self.log: self.log.close()
        self.temp.cleanup()
    def wait(self,predicate):
        end=time.monotonic()+12
        while not predicate():
            if time.monotonic()>end:
                self.fail('barrier timed out: '+(self.root/'stderr').read_text())
            if self.proc.poll() is not None:
                self.fail('early exit: '+(self.root/'stderr').read_text())
            time.sleep(.005)
    def count(self):
        path=self.root/'count'; return int(path.read_text()) if path.exists() else 0
    def start(self,command='check',runs=0,extra=(),directory=None,**env):
        self.log=(self.root/'stderr').open('wb')
        self.proc=subprocess.Popen([HONK,'watch',command,'--watch-dir',str(directory or self.src),'--watch-runs',str(runs),'--offline',*extra],cwd=self.project,env={**self.env,**env},stdout=subprocess.PIPE,stderr=self.log,start_new_session=True)
    def finish(self,expected=0):
        output,_=self.proc.communicate(timeout=15)
        self.assertEqual(self.proc.returncode,expected,(output,(self.root/'stderr').read_text()))
        return output
    def idle(self):
        self.wait(lambda:'command finished; waiting' in (self.root/'stderr').read_text())
    def test_initial_run_and_finite_exit(self):
        self.start(runs=1);self.finish();self.assertEqual(self.count(),1)
    def test_changes_coalesce_during_child_and_failure_can_retry(self):
        self.start(runs=2,GATE_FIRST='1',FAIL_FIRST='1')
        self.wait(lambda:self.count()==1 and (self.root/'pid').exists())
        for i in range(20): (self.src/'main.goose').write_text('fn main() {} // '+str(i))
        (self.root/'release').touch();self.finish();self.assertEqual(self.count(),2)
        self.assertFalse((self.root/'active').exists())
    def test_filter_nonrecursive_rename_and_no_idle_cache_lock(self):
        self.start(runs=2);self.idle()
        for i in range(400): (self.src/f'output{i}.o').write_bytes(b'ignored')
        nested=self.src/'nested';nested.mkdir();(nested/'other.goose').write_bytes(b'ignored')
        # A concurrent ordinary command proves the supervisor holds no idle lock.
        checked=subprocess.run([HONK,'check','--offline'],cwd=self.project,env=self.env,capture_output=True,timeout=10)
        self.assertEqual(checked.returncode,0,checked.stderr)
        self.assertEqual(self.count(),2)
        (self.src/'temporary').write_text('fn main() {}'); (self.src/'temporary').rename(self.src/'main.goose')
        self.finish();self.assertEqual(self.count(),3)
    def test_literal_test_args_and_filter_forwarding(self):
        (self.project/'tests').mkdir();(self.project/'tests/unit.goose').write_text('fn main() {}')
        weird='literal;$(touch SHOULD_NOT_EXIST)'
        self.start('test',runs=1,extra=('--filter','tests/*.goose','--',weird))
        self.finish();self.assertEqual(json.loads((self.root/'args').read_text()),[weird])
        self.assertFalse((self.project/'SHOULD_NOT_EXIST').exists())
    def test_project_root_ignores_generated_lockfile(self):
        self.start(directory=self.project);self.idle()
        time.sleep(.15);self.assertEqual(self.count(),1)
        self.proc.terminate();self.finish(143)
    def test_signal_idle(self):
        self.start();self.idle();self.proc.send_signal(signal.SIGINT);self.finish(130)
    def test_signal_active_reaps_compiler_without_rerun(self):
        self.start(GATE_FIRST='1');self.wait(lambda:(self.root/'pid').exists())
        pid=int((self.root/'pid').read_text());self.proc.terminate();self.finish(143)
        self.assertEqual(self.count(),1);self.assertFalse((self.root/'active').exists())
        with self.assertRaises(ProcessLookupError): os.kill(pid,0)
    def test_group_signal_does_not_restart(self):
        self.start(GATE_FIRST='1');self.wait(lambda:(self.root/'pid').exists())
        os.killpg(self.proc.pid,signal.SIGINT);self.finish(130);self.assertEqual(self.count(),1)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires test-only linked fault adapter')
    def test_overflow_reopens_and_coalesces_without_active_diagnostic(self):
        trigger=self.root/'trigger'
        self.start(runs=2,GATE_FIRST='1',WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='overflow')
        self.wait(lambda:(self.root/'pid').exists());trigger.touch()
        self.wait(lambda:not trigger.exists())
        self.assertNotIn('events lost',(self.root/'stderr').read_text())
        (self.root/'release').touch();self.finish();self.assertEqual(self.count(),2)
        self.assertIn('events lost',(self.root/'stderr').read_text())
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires test-only linked fault adapter')
    def test_full_ignored_batch_never_schedules_a_rerun(self):
        trigger=self.root/'trigger'
        self.start(runs=2,GATE_FIRST='1',WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='ignored')
        self.wait(lambda:(self.root/'pid').exists());trigger.touch()
        self.wait(lambda:not trigger.exists());(self.root/'release').touch()
        self.idle();self.assertEqual(self.count(),1)
        (self.src/'main.goose').write_text('fn main() {} // edited')
        self.finish();self.assertEqual(self.count(),2)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires test-only linked fault adapter')
    def test_corruption_requests_one_term_and_waits_for_cleanup(self):
        trigger=self.root/'trigger'
        self.start(GATE_FIRST='1',DELAY_CLEANUP='1',WATCH_FAULT_TRIGGER=str(trigger))
        self.wait(lambda:(self.root/'pid').exists());trigger.touch()
        self.wait(lambda:(self.root/'signals').exists())
        time.sleep(.15)
        self.assertIsNone(self.proc.poll());self.assertEqual((self.root/'signals').read_bytes(),bytes([signal.SIGTERM]))
        (self.root/'cleanup-release').touch();self.finish(125)
        self.assertEqual(self.count(),1);self.assertFalse((self.root/'active').exists())
    def test_root_move_active_reaps_child(self):
        self.start(GATE_FIRST='1');self.wait(lambda:(self.root/'pid').exists())
        pid=int((self.root/'pid').read_text());self.src.rename(self.project/'moved');self.finish(125)
        self.assertFalse((self.root/'active').exists())
        with self.assertRaises(ProcessLookupError): os.kill(pid,0)
    def test_bin_option_value_forwarded(self):
        (self.src/'bin').mkdir();(self.src/'bin/other.goose').write_text('fn main() {}')
        self.start(runs=1,extra=('--bin','other'));self.finish();self.assertEqual(self.count(),1)
    def test_root_move_stops(self):
        self.start();self.idle();self.src.rename(self.project/'moved');self.finish(125)
    def test_final_child_failure_status(self):
        self.start(runs=1,FAIL_FIRST='1');self.finish(7)
    def test_jit_watch_rejected_without_launching_command(self):
        source=Path(__file__).resolve().parents[1]/'honk.goose'
        result=subprocess.run([GOOSE,'run',str(source),'--','watch','check','--watch-dir',str(self.src),'--watch-runs','1'],cwd=self.project,env=self.env,capture_output=True,timeout=30)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'watch requires a compiled Honk',result.stderr)
        self.assertEqual(self.count(),0)
    def test_bad_options_and_symlink_fail_before_compiler(self):
        link=self.project/'link';link.symlink_to(self.src,target_is_directory=True)
        for args in [('watch','run','--watch-dir',str(self.src)),('watch','check'),('watch','check','--watch-dir','src'),('watch','check','--watch-dir',str(link)),('watch','check','--watch-dir',str(self.src),'--watch-runs','-1'),('check','--watch-dir',str(self.src)),('watch','check','--watch-dir',str(self.src),'--release')]:
            result=subprocess.run([HONK,*args],cwd=self.project,env=self.env,capture_output=True,timeout=10)
            self.assertNotEqual(result.returncode,0,args)
        self.assertEqual(self.count(),0)

if __name__=='__main__': unittest.main()

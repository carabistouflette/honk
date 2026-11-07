#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real watcher/Honk processes with controlled compiler barriers; no shell argv."""
import json
import threading
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
    def start(self,command='check',runs=0,extra=(),directory=None,directories=None,**env):
        self.log=(self.root/'stderr').open('wb')
        selected = directories if directories is not None else [directory or self.src]
        watched = [word for path in selected for word in ('--watch-dir',str(path))]
        self.proc=subprocess.Popen([HONK,'watch',command,*watched,'--watch-runs',str(runs),'--offline',*extra],cwd=self.project,env={**self.env,**env},stdout=subprocess.PIPE,stderr=self.log,start_new_session=True)
    def finish(self,expected=0):
        output,_=self.proc.communicate(timeout=15)
        self.assertEqual(self.proc.returncode,expected,(output,(self.root/'stderr').read_text()))
        return output
    def idle(self):
        self.wait(lambda:'command finished; waiting' in (self.root/'stderr').read_text())
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked tree adapter')
    def test_recursive_root_aba_during_candidate_scan(self):
        self.tree_fault('tree-aba',125)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked tree adapter')
    def test_recursive_root_aba_during_candidate_verification(self):
        self.tree_fault('tree-verify-aba',125)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked tree adapter')
    def test_recursive_cancel_during_discovery(self):
        self.tree_fault('tree-cancel',130)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked tree adapter')
    def test_recursive_unstable_reconciliation_fails_boundedly(self):
        self.tree_fault('tree-retry',125)
    def tree_fault(self,mode,code):
        trigger=self.root/'trigger';trigger.touch()
        self.start(runs=1,extra=('--watch-recursive',),WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE=mode,WATCH_TREE_ROOT=str(self.src))
        self.finish(code);self.assertEqual(self.count(),0)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked tree adapter')
    def test_recursive_root_aba_during_repair_stops(self):
        trigger=self.root/'trigger'
        self.start(extra=('--watch-recursive',),WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='tree-aba',WATCH_TREE_ROOT=str(self.src))
        self.idle();trigger.touch();(self.src/'added').mkdir()
        self.finish(125);self.assertEqual(self.count(),1)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked watch adapter')
    def test_recursive_data_overflow_recovers_complete_tree(self):
        nested=self.src/'nested';nested.mkdir();trigger=self.root/'trigger'
        self.start(runs=3,extra=('--watch-recursive',),GATE_FIRST='1',WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='overflow',WATCH_FAULT_TARGET='data')
        self.wait(lambda:(self.root/'pid').exists());trigger.touch();self.wait(lambda:not trigger.exists())
        (self.root/'release').touch()
        self.wait(lambda:self.count()==2 and 'command finished; waiting' in (self.root/'stderr').read_text())
        (nested/'unit.goose').write_text('fn main() {}');self.finish();self.assertEqual(self.count(),3)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked watch adapter')
    def test_recursive_root_guard_overflow_stops_after_child_cleanup(self):
        trigger=self.root/'trigger'
        self.start(extra=('--watch-recursive',),GATE_FIRST='1',WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='overflow')
        self.wait(lambda:(self.root/'pid').exists());trigger.touch()
        self.finish(125);self.assertEqual(self.count(),1);self.assertFalse((self.root/'active').exists())
    def test_recursive_empty_self_attribute_event_is_ignored(self):
        self.start(runs=2,extra=('--watch-recursive',));self.idle()
        self.src.chmod(0o750)
        time.sleep(.1);self.assertEqual(self.count(),1)
        (self.src/'main.goose').write_text('fn main() {} // edited')
        self.finish();self.assertEqual(self.count(),2)
    def test_recursive_signal_active_preserves_sigint(self):
        self.start(extra=('--watch-recursive',),GATE_FIRST='1');self.wait(lambda:(self.root/'pid').exists())
        self.proc.send_signal(signal.SIGINT);self.finish(130)
        self.assertEqual(self.count(),1);self.assertFalse((self.root/'active').exists())
    def test_recursive_depth_limit_fails_before_compiler(self):
        nested=self.src
        for _ in range(33):nested=nested/'d';nested.mkdir()
        self.start(runs=1,extra=('--watch-recursive',));self.finish(125);self.assertEqual(self.count(),0)
    def test_recursive_root_limit_and_overlaps_reject(self):
        roots=[self.src]
        for i in range(8):path=self.project/f'root{i}';path.mkdir();roots.append(path)
        self.start(runs=1,directories=roots,extra=('--watch-recursive',));self.finish(125);self.assertEqual(self.count(),0)
    def test_recursive_nested_roots_reject(self):
        nested=self.src/'nested';nested.mkdir()
        self.start(runs=1,directories=[self.src,nested],extra=('--watch-recursive',));self.finish(125);self.assertEqual(self.count(),0)
    def test_recursive_existing_nested_edit(self):
        nested=self.src/'nested';nested.mkdir();file=nested/'unit.goose';file.write_text('fn main() {}')
        self.start(runs=2,extra=('--watch-recursive',));self.idle()
        file.write_text('fn main() {} // edit');self.finish();self.assertEqual(self.count(),2)
    def test_recursive_new_populated_subtree_and_later_edit(self):
        staged=self.project/'staged';staged.mkdir();file=staged/'unit.goose';file.write_text('fn main() {}')
        self.start(runs=3,extra=('--watch-recursive',));self.idle()
        staged.rename(self.src/'added')
        self.wait(lambda:self.count()==2 and (self.root/'stderr').read_text().count('command finished; waiting')==2)
        (self.src/'added/unit.goose').write_text('fn main() {} // edit')
        self.finish();self.assertEqual(self.count(),3)
    def test_recursive_nested_removal_recovers(self):
        nested=self.src/'nested';nested.mkdir()
        self.start(runs=2,extra=('--watch-recursive',));self.idle()
        nested.rmdir();self.finish();self.assertEqual(self.count(),2)
    def test_recursive_ignored_paths_and_parent_sibling(self):
        outside=self.project/'outside';outside.mkdir();(outside/'test.goose').write_text('fn main() {}')
        self.start(runs=2,extra=('--watch-recursive',));self.idle()
        (self.src/'link').symlink_to(outside,target_is_directory=True)
        (self.project/'outside.goose').write_text('fn main() {}')
        (outside/'test.goose').write_text('fn main() {} // ignored')
        for name in ('target','.git','.honk','.build','.toolchain'):
            path=self.src/name;path.mkdir();(path/'ignored.goose').write_text('ignored');(path/'ignored.goose').unlink();path.rmdir()
        # Parent sentinel and excluded names must not become source changes.
        time.sleep(.2);self.assertEqual(self.count(),1)
        (self.src/'link').unlink()
        (self.src/'main.goose').write_text('fn main() {} // valid')
        self.finish();self.assertEqual(self.count(),2)
    def test_ignore_invalid_patterns_fail_before_compiler(self):
        for patterns in (['['],[''],['x'*1025],['x']*17):
            with self.subTest(patterns=patterns):
                args=[word for pattern in patterns for word in ('--watch-ignore',pattern)]
                result=subprocess.run([HONK,'watch','check','--watch-dir',str(self.src),*args],cwd=self.project,env=self.env,capture_output=True,timeout=10)
                self.assertNotEqual(result.returncode,0);self.assertEqual(self.count(),0)
        result=subprocess.run([HONK,'check','--watch-ignore','x'],cwd=self.project,env=self.env,capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0);self.assertEqual(self.count(),0)
    def test_ignore_single_match_work_exhaustion_fails_closed(self):
        (self.src/'aaaaaaaa').mkdir()
        pattern='*['+'a'*900+']z*'
        self.start(runs=1,extra=('--watch-recursive','--watch-ignore',pattern))
        self.finish(125);self.assertEqual(self.count(),0)
        self.assertIn('--watch-ignore path or matcher work limit',(self.root/'stderr').read_text())
    def test_ignore_scan_work_exhaustion_fails_before_child(self):
        for i in range(4097):(self.src/f'ignored{i}').mkdir()
        self.start(runs=1,extra=('--watch-recursive','--watch-ignore','*'))
        self.finish(125);self.assertEqual(self.count(),0)
        self.assertIn('--watch-ignore path or matcher work limit', (self.root/'stderr').read_text())
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'),'requires linked watch adapter')
    def test_ignore_exhaustion_cannot_be_retried_into_success(self):
        for i in range(4097):(self.src/f'ignored{i}').mkdir()
        counter=self.root/'filter-count'
        self.start(runs=1,extra=('--watch-recursive','--watch-ignore','*'),WATCH_FAULT_MODE='ignore-retry',WATCH_FAULT_FILTER_COUNT=str(counter))
        self.finish(125);self.assertEqual(self.count(),0)
        self.assertEqual(counter.read_text(),'1')
    def test_ignore_relative_path_overflow_fails_before_child(self):
        deep=self.root/'deep';deep.mkdir();fd=os.open(deep,os.O_RDONLY|os.O_DIRECTORY)
        try:
            for _ in range(17):
                os.mkdir('d'*250,dir_fd=fd)
                child=os.open('d'*250,os.O_RDONLY|os.O_DIRECTORY,dir_fd=fd)
                os.close(fd);fd=child
        finally:os.close(fd)
        self.start(directory=deep,runs=1,extra=('--watch-recursive','--watch-ignore','never'))
        self.finish(125);self.assertEqual(self.count(),0)
        self.assertIn('--watch-ignore path or matcher work limit',(self.root/'stderr').read_text())
    def test_ignore_prunes_before_directory_limit_and_filters_topology(self):
        generated=self.src/'generated';generated.mkdir()
        for i in range(300):(generated/str(i)).mkdir()
        self.start(runs=2,extra=('--watch-recursive','--watch-ignore','generated'));self.idle()
        (generated/'0/unit.goose').write_text('fn main() {}')
        (generated/'added').mkdir()
        time.sleep(.2);self.assertEqual(self.count(),1)
        (self.src/'main.goose').write_text('fn main() {} // included')
        self.finish();self.assertEqual(self.count(),2)
    def test_ignore_file_patterns_are_relative_to_each_explicit_root(self):
        other=self.root/'other';other.mkdir()
        self.start(runs=2,directories=[self.src,other],extra=('--watch-ignore','skip.goose','--watch-ignore','skip_?.goose'))
        self.idle()
        for root in (self.src,other):(root/'skip.goose').write_text('fn main() {}')
        fd=os.open(os.fsencode(other)+b'/skip_\xff.goose',os.O_CREAT|os.O_WRONLY,0o600);os.close(fd)
        time.sleep(.2);self.assertEqual(self.count(),1)
        (other/'included.goose').write_text('fn main() {}')
        self.finish();self.assertEqual(self.count(),2)
    def test_ignore_rename_into_included_tree_restores_nested_coverage(self):
        generated=self.src/'generated';generated.mkdir();(generated/'unit.goose').write_text('fn main() {}')
        self.start(runs=3,extra=('--watch-recursive','--watch-ignore','generated'));self.idle()
        generated.rename(self.src/'included')
        self.wait(lambda:self.count()==2 and (self.root/'stderr').read_text().count('command finished; waiting')==2)
        (self.src/'included/unit.goose').write_text('fn main() {} // covered')
        self.finish();self.assertEqual(self.count(),3)
    def test_ignore_matches_hidden_recursive_file_paths(self):
        nested=self.src/'.hidden';nested.mkdir()
        self.start(runs=2,extra=('--watch-recursive','--watch-ignore','**/skip.goose'));self.idle()
        (nested/'skip.goose').write_text('fn main() {}')
        time.sleep(.2);self.assertEqual(self.count(),1)
        (nested/'included.goose').write_text('fn main() {}')
        self.finish();self.assertEqual(self.count(),2)
    def test_ignore_cannot_hide_explicit_root_loss(self):
        self.start(extra=('--watch-recursive','--watch-ignore','**'));self.idle()
        moved=self.src.with_name('moved');self.src.rename(moved);moved.rename(self.src)
        self.finish(125);self.assertEqual(self.count(),1)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'),'requires linked watch adapter')
    def test_ignore_survives_data_overflow_reconciliation(self):
        generated=self.src/'generated';generated.mkdir()
        for i in range(260):(generated/str(i)).mkdir()
        trigger=self.root/'trigger'
        self.start(runs=3,extra=('--watch-recursive','--watch-ignore','generated'),GATE_FIRST='1',WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='overflow',WATCH_FAULT_TARGET='data')
        self.wait(lambda:(self.root/'pid').exists());trigger.touch();(self.root/'release').touch()
        self.wait(lambda:self.count()==2 and (self.root/'stderr').read_text().count('command finished; waiting')>=1)
        (generated/'0/unit.goose').write_text('fn main() {}')
        time.sleep(.2);self.assertEqual(self.count(),2)
        (self.src/'main.goose').write_text('fn main() {} // covered after loss')
        self.finish();self.assertEqual(self.count(),3)
    def test_recursive_explicit_roots_override_excluded_basenames(self):
        parent=self.root/'selected';parent.mkdir();roots=[]
        for name in ('.git','.honk','target','.build','.toolchain'):
            directory=parent/name;directory.mkdir();(directory/'main.goose').write_text('// initial')
            roots.append(directory)
        self.start(runs=6,directories=roots,extra=('--watch-recursive',));self.idle()
        for index,directory in enumerate(roots):
            (directory/'main.goose').write_text('// changed')
            if index<4:
                self.wait(lambda:self.count()==index+2 and (self.root/'stderr').read_text().count('command finished; waiting')==index+2)
        self.finish();self.assertEqual(self.count(),6)
    def test_recursive_root_delete_with_held_anchor_stops(self):
        empty=self.project/'empty';empty.mkdir()
        self.start(directory=empty,extra=('--watch-recursive',));self.idle()
        empty.rmdir();self.finish(125);self.assertEqual(self.count(),1)
    def test_recursive_root_aba_during_active_child_stops(self):
        self.start(extra=('--watch-recursive',),GATE_FIRST='1');self.wait(lambda:(self.root/'pid').exists())
        moved=self.project/'moved';self.src.rename(moved);moved.rename(self.src)
        self.finish(125);self.assertEqual(self.count(),1);self.assertFalse((self.root/'active').exists())
    def test_recursive_repair_waits_for_active_child(self):
        self.start(runs=2,extra=('--watch-recursive',),GATE_FIRST='1');self.wait(lambda:(self.root/'pid').exists())
        nested=self.src/'new';nested.mkdir();(nested/'unit.goose').write_text('fn main() {}')
        time.sleep(.1);self.assertEqual(self.count(),1)
        (self.root/'release').touch();self.finish();self.assertEqual(self.count(),2)
    def test_recursive_limits_fail_before_compiler(self):
        for i in range(255):(self.src/f'd{i}').mkdir()
        self.start(runs=1,extra=('--watch-recursive',));self.finish(125);self.assertEqual(self.count(),0)
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
    def test_debounce_coalesces_cross_directory_burst(self):
        other=self.project/'other';other.mkdir()
        self.start(runs=2,directories=[self.src,other],extra=('--watch-debounce-ms','500'));self.idle()
        (self.src/'main.goose').write_text('fn main() {} // first')
        self.wait(lambda:'batching pending' in (self.root/'stderr').read_text())
        for i in range(8):
            (other/'second.goose').write_text('fn main() {} // '+str(i));time.sleep(.02)
        self.finish();self.assertEqual(self.count(),2)
        self.assertEqual((self.root/'stderr').read_text().count('batching pending'),1)
    def test_debounce_continuous_edits_eventually_rerun(self):
        # Keep source staging stable: this test targets admission under a
        # continuous event stream, not concurrent source snapshot mutation.
        events=self.root/'events';events.mkdir()
        self.start(runs=2,directories=[self.src,events],extra=('--watch-debounce-ms','900'));self.idle()
        stop=threading.Event()
        def produce():
            deadline=time.monotonic()+30; i=0
            while not stop.is_set() and time.monotonic()<deadline:
                (events/'changed.goose').write_text('fn main() {} // '+str(i));i+=1
                stop.wait(.01)
        producer=threading.Thread(target=produce);producer.start()
        try:
            self.wait(lambda:self.count()==2)
        finally:stop.set();producer.join(timeout=10)
        self.finish();self.assertEqual(self.count(),2)
    def test_debounce_cancellation_has_no_rerun(self):
        self.start(extra=('--watch-debounce-ms','1000'));self.idle()
        (self.src/'main.goose').write_text('fn main() {} // edited')
        self.wait(lambda:'batching pending' in (self.root/'stderr').read_text())
        self.proc.send_signal(signal.SIGINT);self.finish(130);self.assertEqual(self.count(),1)
    def test_debounce_directory_move_stops_waiting(self):
        self.start(extra=('--watch-debounce-ms','1000'));self.idle()
        (self.src/'main.goose').write_text('fn main() {} // edited')
        self.wait(lambda:'batching pending' in (self.root/'stderr').read_text())
        self.src.rename(self.project/'moved');self.finish(125);self.assertEqual(self.count(),1)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_debounce_initial_run_never_batches(self):
        trigger=self.root/'trigger';trigger.touch()
        self.start(runs=1,extra=('--watch-debounce-ms','500'),WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='clock')
        self.finish();self.assertTrue(trigger.exists());self.assertEqual(self.count(),1)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_debounce_cancellation_at_cap_never_launches_child(self):
        self.clock_batch('clock-cap',130,WATCH_FAULT_CANCEL_AT_CAP='1')
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_debounce_relevant_event_extends_quiet_interval(self):
        done=self.root/'clock-done';done.touch()
        self.clock_batch('clock-quiet',0,WATCH_FAULT_CLOCK_DONE=str(done))
        self.assertFalse(done.exists())
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_debounce_clock_failure_stops_pending_run(self):
        self.clock_batch('clock',125)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_debounce_backwards_clock_stops_pending_run(self):
        self.clock_batch('clock-backwards',125)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_debounce_fixed_cap_survives_quiet_reset(self):
        self.clock_batch('clock-cap',0)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_debounce_ignored_event_does_not_reset_quiet(self):
        self.clock_batch('clock-ignored',0)
    def clock_batch(self,mode,expected,**env):
        trigger=self.root/'trigger'
        self.start(runs=2,extra=('--watch-debounce-ms','500'),WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE=mode,**env)
        self.idle();trigger.touch();(self.src/'main.goose').write_text('fn main() {} // edited')
        self.finish(expected);self.assertFalse(trigger.exists());self.assertEqual(self.count(),2 if expected==0 else 1)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_default_debounce_never_reads_clock(self):
        trigger=self.root/'trigger'
        self.start(runs=2,WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='clock')
        self.idle();trigger.touch();(self.src/'main.goose').write_text('fn main() {} // edited')
        self.finish();self.assertTrue(trigger.exists());self.assertEqual(self.count(),2)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_debounce_overflow_bypasses_remaining_quiet(self):
        trigger=self.root/'trigger'
        self.start(runs=2,extra=('--watch-debounce-ms','1000'),WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='overflow',WATCH_FAULT_CLOCK_AFTER_OVERFLOW='1')
        self.idle();(self.src/'main.goose').write_text('fn main() {} // edited')
        self.wait(lambda:'batching pending' in (self.root/'stderr').read_text())
        trigger.touch();self.finish();self.assertEqual(self.count(),2)
    @unittest.skipUnless(os.environ.get('WATCH_FAULT_TEST'), 'requires linked clock adapter')
    def test_debounce_active_overflow_bypasses_next_batch(self):
        trigger=self.root/'trigger'
        self.start(runs=2,GATE_FIRST='1',extra=('--watch-debounce-ms','1000'),WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='overflow',WATCH_FAULT_CLOCK_AFTER_OVERFLOW='1')
        self.wait(lambda:(self.root/'pid').exists());trigger.touch();self.wait(lambda:not trigger.exists())
        (self.root/'release').touch();self.finish();self.assertEqual(self.count(),2)
    def test_debounce_option_validation_before_compiler(self):
        for value in ('-1','1001','no','9223372036854775808'):
            result=subprocess.run([HONK,'watch','check','--watch-dir',str(self.src),'--watch-debounce-ms',value],cwd=self.project,env=self.env,capture_output=True,timeout=10)
            self.assertNotEqual(result.returncode,0,value)
        result=subprocess.run([HONK,'check','--watch-debounce-ms','1'],cwd=self.project,env=self.env,capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0);self.assertEqual(self.count(),0)
    def test_multiple_directories_rerun_from_each(self):
        other=self.project/'other';other.mkdir()
        self.start(runs=3,directories=[self.src,other]);self.idle()
        (other/'second.goose').write_text('fn main() {}')
        self.wait(lambda:self.count()==2 and (self.root/'stderr').read_text().count('command finished; waiting')==2)
        (self.src/'main.goose').write_text('fn main() {} // edited')
        self.finish();self.assertEqual(self.count(),3)
    def test_multiple_directories_coalesce_during_active_command(self):
        other=self.project/'other';other.mkdir()
        self.start(runs=2,directories=[self.src,other],GATE_FIRST='1')
        self.wait(lambda:(self.root/'pid').exists())
        for i in range(20):
            (self.src/'main.goose').write_text('fn main() {} // '+str(i))
            (other/'second.goose').write_text('fn main() {} // '+str(i))
        (self.root/'release').touch();self.finish();self.assertEqual(self.count(),2)
    def test_later_directory_move_reaps_active_child(self):
        other=self.project/'other';other.mkdir()
        self.start(directories=[self.src,other],GATE_FIRST='1')
        self.wait(lambda:(self.root/'pid').exists());pid=int((self.root/'pid').read_text())
        other.rename(self.project/'moved');self.finish(125)
        self.assertEqual(self.count(),1);self.assertFalse((self.root/'active').exists())
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)
    def test_full_directory_limit_initial_run(self):
        paths=[self.src]
        for i in range(255):
            path=self.project/f'watched-{i}';path.mkdir();paths.append(path)
        self.start(runs=1,directories=paths);self.finish();self.assertEqual(self.count(),1)
    def test_invalid_set_never_launches_compiler(self):
        alias=self.project/'alias';alias.symlink_to(self.project,target_is_directory=True)
        cases=[[self.src,self.src],[self.src,alias/'src'],[self.src,self.project/'missing'],
               [self.src,'relative'],[self.src]*257]
        for paths in cases:
            watched=[word for path in paths for word in ('--watch-dir',str(path))]
            result=subprocess.run([HONK,'watch','check',*watched,'--watch-runs','1','--offline'],cwd=self.project,env=self.env,capture_output=True,timeout=15)
            self.assertNotEqual(result.returncode,0,paths)
        self.assertEqual(self.count(),0)
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
        other=self.project/'other';other.mkdir()
        self.start(runs=3,directories=[self.src,other],GATE_FIRST='1',WATCH_FAULT_TRIGGER=str(trigger),WATCH_FAULT_MODE='overflow')
        self.wait(lambda:(self.root/'pid').exists());trigger.touch()
        self.wait(lambda:not trigger.exists())
        self.assertNotIn('events lost',(self.root/'stderr').read_text())
        (self.root/'release').touch()
        self.wait(lambda:self.count()==2 and 'command finished; waiting' in (self.root/'stderr').read_text())
        (other/'second.goose').write_text('fn main() {}')
        self.finish();self.assertEqual(self.count(),3)
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

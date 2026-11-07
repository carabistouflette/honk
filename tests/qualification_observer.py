#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Calibrate exact checkpoint inspection and expose sampling limitations."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bench'))
from process_observer import execute

from observer_calibration import calibrate


class ObserverTests(unittest.TestCase):
    def test_fd_memory_and_burst_calibrations(self):
        with tempfile.TemporaryDirectory(prefix='observer-control-') as raw:
            results=calibrate(raw)
            self.assertEqual(set(results),{'fd','memory','burst'})

    def test_failure_record_and_group_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='observer-failure-') as raw:
            result=execute([sys.executable,'-S','-c','import time;time.sleep(5)'],raw,os.environ.copy(),timeout=.1)
            self.assertFalse(result['complete'])
            self.assertIn('finite deadline',result['error'])
            self.assertIsNotNone(result['exit_code'])

    def test_launch_failure_record(self):
        with tempfile.TemporaryDirectory(prefix='observer-launch-') as raw:
            result=execute(['/does/not/exist/qualification'],raw,os.environ.copy())
            self.assertFalse(result['complete'])
            self.assertIn('FileNotFoundError',result['error'])
            self.assertIsNone(result['exit_code'])

    def test_timeout_kills_owned_child(self):
        with tempfile.TemporaryDirectory(prefix='observer-child-') as raw:
            program="import subprocess,time; p=subprocess.Popen(['/bin/sleep','5']); print(p.pid,flush=True); time.sleep(5)"
            result=execute([sys.executable,'-S','-c',program],raw,os.environ.copy(),timeout=.2)
            self.assertFalse(result['complete'])
            self.assertIn('finite deadline',result['error'])
            pid=int(result['stdout'].strip())
            from process_observer import ProcessObserver
            identity=ProcessObserver.identity(pid)
            self.assertTrue(identity is None or identity['state']=='Z', identity)

    def test_orphan_after_leader_exit_is_failure(self):
        with tempfile.TemporaryDirectory(prefix='observer-orphan-') as raw:
            program="import subprocess; p=subprocess.Popen(['/bin/sleep','5']); print(p.pid,flush=True)"
            result=execute([sys.executable,'-S','-c',program],raw,os.environ.copy(),timeout=2)
            self.assertFalse(result['complete'])
            self.assertIn('descendants after leader exit',result['error'])
            self.assertTrue(result['post_exit_group_members'])


if __name__=='__main__':
    unittest.main()

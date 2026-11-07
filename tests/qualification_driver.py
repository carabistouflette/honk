#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Synthetic correctness controls; real-suite performance is measured separately."""
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bench'))
from process_observer import execute


class DriverTests(unittest.TestCase):
    def test_supervision_controls(self):
        for mode in ('endurance', 'failure', 'timeout', 'cancel', 'pressure', 'overflow'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='qualification-driver-') as raw:
                baseline=[]; sent=[]

                def checkpoint(process,line,row):
                    self.assertEqual(row['children'],[])
                    self.assertEqual(row['group_members'],[])
                    if not baseline: baseline.append(row['fds'])
                    self.assertEqual(row['fds'],baseline[0])

                def trigger(process,row):
                    if len(row['nodes'])==3 and not sent:
                        process.send_signal(signal.SIGTERM);sent.append(True)

                result=execute([os.environ['QUALIFICATION_DRIVER'],mode,*(['/bin/true']*4),
                                os.environ['QUALIFICATION_PRESSURE']],raw,os.environ.copy(),
                               trace=Path(raw)/'trace.jsonl.gz',checkpoint=checkpoint,
                               trigger=trigger if mode=='cancel' else None,timeout=30)
                self.assertTrue(result['complete'],result)
                self.assertEqual(result['exit_code'],0,result)
                self.assertEqual(len(result['checkpoints']),9 if mode=='endurance' else 2)
                self.assertFalse(result['post_exit_group_members'])
                if mode=='cancel':self.assertTrue(sent)
                if mode=='pressure':self.assertEqual(result['stderr'],'x'*65536)


if __name__=='__main__':
    unittest.main()

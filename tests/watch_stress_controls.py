#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Negative controls for watch evidence interpretation; no compiler dependency."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bench'))
import watch_stress as w


def event(kind,code=0):
    return f'[INFO] timestamp="2026-11-07T00:00:00Z" {kind} duration_ns=1 outcome={code}\n'.encode()


class Controls(unittest.TestCase):
    def test_serial_success_and_failure(self):
        data=event('started')+event('item_completed')+event('returned')+event('started')+event('child_failed',1)
        self.assertEqual(w.terminals(data),[dict(kind='returned',code=0),dict(kind='child_failed',code=1)])
    def test_partial_append_is_not_completion(self):
        self.assertEqual(w.terminals(event('started')+event('returned')[:-1]),[])
    def test_corrupt_and_overlapping_lifecycle_rejected(self):
        for data in (event('returned'),event('item_completed'),event('started')+event('started'),b'bad\n'):
            with self.assertRaises(RuntimeError):w.terminals(data)
    def test_normalization_is_narrow(self):
        project=Path('/project')
        prefix=b'built /project/target/debug/.honk/tests/0\n'
        suffix=b'Passed 1 test targets\n'
        suite=b'\ncodec tests passed\nbuilt suite data\nPassed suite data\n\n'
        self.assertEqual(w.canonical(prefix+suite+suffix,project),suite)
        self.assertNotEqual(w.canonical(prefix+b'broken\n'+suffix,project),b'codec tests passed\n')
        with self.assertRaises(RuntimeError):w.canonical(b'codec tests passed\n',project)
        self.assertTrue(w.canonical(b'built /other/target\n'+suite+suffix,project).startswith(b'built /other/'))
    def test_fd_anchor_identity_is_required(self):
        anchor=dict(target='anon_inode:inotify',dev=1,inode=2,mode=3,watches=[['aa','bb','cc']])
        self.assertEqual(w.fd_roles({'fd_anchors':[anchor]}),w.fd_roles({'fd_anchors':[dict(anchor)]}))
        self.assertNotEqual(w.fd_roles({'fd_anchors':[anchor]}),w.fd_roles({'fd_anchors':[{**anchor,'inode':9}]}))
        self.assertNotEqual(w.fd_roles({'fd_anchors':[anchor]}),w.fd_roles({'fd_anchors':[anchor,anchor]}))
    def test_fd_roles_ignore_only_allocation_numbers(self):
        self.assertEqual(w.fd_roles({'fds':{'3':'a','4':'b'}}),w.fd_roles({'fds':{'8':'a','5':'b'}}))
        self.assertNotEqual(w.fd_roles({'fds':{'3':'a'}}),w.fd_roles({'fds':{'3':'a','4':'a'}}))


if __name__=='__main__':unittest.main()

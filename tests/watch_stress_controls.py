#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Negative controls for watch evidence interpretation; no compiler dependency."""
import importlib.util
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
        self.assertEqual(w.canonical(b'built target\ncodec tests passed\nPassed 1 test targets\n'),b'codec tests passed\n')
        self.assertNotEqual(w.canonical(b'codec tests broken\n'),w.canonical(b'codec tests passed\n'))
    def test_fd_roles_ignore_only_allocation_numbers(self):
        self.assertEqual(w.fd_roles({'fds':{'3':'a','4':'b'}}),w.fd_roles({'fds':{'8':'a','5':'b'}}))
        self.assertNotEqual(w.fd_roles({'fds':{'3':'a'}}),w.fd_roles({'fds':{'3':'a','4':'a'}}))


if __name__=='__main__':unittest.main()

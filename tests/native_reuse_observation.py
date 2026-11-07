#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check that qualification evidence detects content and identity changes."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bench'))
from native_reuse import backend, cache_records


class Observation(unittest.TestCase):
    def test_same_size_same_timestamp_backend_change(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);log=root/'build/prog/example/cc.log';log.parent.mkdir(parents=True)
            log.write_bytes(b'first');before=backend(root);old=log.stat()
            log.write_bytes(b'other');os.utime(log,ns=(old.st_atime_ns,old.st_mtime_ns))
            after=backend(root);self.assertNotEqual(before,after)
            self.assertEqual(next(iter(before.values()))['mtime_ns'],next(iter(after.values()))['mtime_ns'])

    def test_cache_record_certificate_fields(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);path=root/'.honk/reuse/release/tests/1/record';path.parent.mkdir(parents=True)
            path.write_text('a'*64+'\n'+'b'*64+'\n')
            record=next(iter(cache_records(root).values()))
            self.assertEqual(record['key'],'a'*64)
            self.assertEqual(record['artifact_sha256'],'b'*64)

    def test_cache_records_ignore_external_symlinks(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);directory=root/'.honk/reuse/release/tests/1';directory.mkdir(parents=True)
            sentinel=root/'sentinel';sentinel.write_bytes(b'unchanged')
            (directory/'record').symlink_to(sentinel)
            self.assertEqual(cache_records(root),{})
            self.assertEqual(sentinel.read_bytes(),b'unchanged')


if __name__=='__main__':unittest.main()

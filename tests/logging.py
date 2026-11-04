#!/usr/bin/env python3
"""Isolated application integration of the pinned goose-log consumer."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

HONK = os.environ['HONK']
GOOSE = os.environ['GOOSE']
EVENT = re.compile(rb'\[(INFO|ERROR)\] (started|item_completed|returned|failed|child_failed) duration_ns=([0-9]+) outcome=([0-9]+)\n')

class Logging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk logging ')
        self.root = Path(self.temp.name)
        self.log = self.root/'events.log'
        self.env = {**os.environ, 'GOOSE': GOOSE, 'HONK_HOME': str(self.root/'cache'), 'HONK_SECRET': 'private-marker-value'}
    def tearDown(self):
        self.temp.cleanup()
    def run_honk(self, *args, cwd=None, **kwargs):
        result = subprocess.run([HONK,*map(str,args)], cwd=cwd or self.root, env=self.env,
                                capture_output=True, timeout=90, **kwargs)
        self.assertNotIn(b'AddressSanitizer', result.stderr)
        self.assertNotIn(b'runtime error:', result.stderr)
        return result
    def new(self, name='demo', cwd=None):
        result=self.run_honk('new',name,cwd=cwd)
        self.assertEqual(result.returncode,0,result.stderr)
        return (cwd or self.root)/name
    def rows(self):
        data=self.log.read_bytes()
        self.assertEqual(b''.join(m.group() for m in EVENT.finditer(data)),data)
        self.assertNotIn(b'private-marker-value',data)
        self.assertNotIn(str(self.log).encode(),data)
        return EVENT.findall(data)
    def test_metadata_stdout_and_privacy(self):
        project=self.new()
        manifest=project/'Honk.toml'
        manifest.write_text(manifest.read_text().replace('[package]','[package]\ndescription = "private-marker-value"'))
        before=self.run_honk('metadata',cwd=project)
        after=self.run_honk('metadata','--log-file',self.log,cwd=project)
        self.assertEqual((after.returncode,after.stdout,after.stderr),(0,before.stdout,b''))
        json.loads(after.stdout)
        self.assertEqual([r[1] for r in self.rows()],[b'started',b'returned'])
        self.assertEqual(self.log.stat().st_mode&0o777,0o600)
    def test_workspace_progress(self):
        workspace=self.root/'workspace';workspace.mkdir()
        self.new('one',workspace);self.new('two',workspace)
        (workspace/'Honk.toml').write_text('[workspace]\nmembers=["one","two"]\n')
        result=self.run_honk('check','--workspace','--log-file',self.log,cwd=workspace)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([r[1] for r in self.rows()],[b'started',b'item_completed',b'item_completed',b'returned'])
    def test_child_exit_code_and_output_preserved(self):
        project=self.new()
        (project/'src/main.goose').write_text('import os;fn main(){print("private-marker-value");exit(7);}')
        before=self.run_honk('run',cwd=project)
        after=self.run_honk('run','--log-file',self.log,cwd=project)
        self.assertEqual((after.returncode,after.stdout,after.stderr),(7,before.stdout,before.stderr))
        self.assertEqual(self.rows()[-1][1::2],(b'child_failed',b'7'))
        self.assertNotIn(b'returned',self.log.read_bytes())
    def test_business_error_has_fixed_event_only(self):
        project=self.new()
        result=self.run_honk('metadata','--manifest-path','private-marker-value/Honk.toml','--log-file',self.log,cwd=project)
        self.assertEqual(result.returncode,1)
        self.assertEqual([r[1] for r in self.rows()],[b'started',b'failed'])
    def test_invalid_sink_fails_without_metadata(self):
        project=self.new(); target=self.root/'target';target.write_bytes(b'unchanged')
        self.log.symlink_to(target)
        result=self.run_honk('metadata','--log-file',self.log,cwd=project)
        self.assertEqual((result.returncode,result.stdout),(1,b''))
        self.assertIn(b'diagnostic log failed',result.stderr)
        self.assertEqual(target.read_bytes(),b'unchanged')
    def test_stdout_failure_is_not_returned(self):
        project=self.new()
        with open('/dev/full','wb') as output:
            result=subprocess.run([HONK,'metadata','--log-file',str(self.log)],cwd=project,env=self.env,stdout=output,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(result.returncode,1)
        self.assertIn(b'cannot write standard output',result.stderr)
        self.assertEqual([r[1] for r in self.rows()],[b'started',b'failed'])

    def test_sustained_fixed_records(self):
        project=self.new()
        for i in range(100):
            result=self.run_honk('metadata','--log-file',self.log,cwd=project)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['name'],'demo')
        rows=self.rows()
        self.assertEqual(len(rows),200)
        self.assertEqual([row[1] for row in rows], [b'started',b'returned']*100)
    def test_file_safety_and_capacity(self):
        project=self.new()
        target=self.root/'target-log';target.write_bytes(b'unchanged');target.chmod(0o600)
        self.log.hardlink_to(target)
        result=self.run_honk('metadata','--log-file',self.log,cwd=project)
        self.assertEqual((result.returncode,result.stdout),(1,b''))
        self.assertEqual(target.read_bytes(),b'unchanged')
        self.log.unlink()
        self.log.write_bytes(b'unchanged');self.log.chmod(0o644)
        result=self.run_honk('metadata','--log-file',self.log,cwd=project)
        self.assertEqual((result.returncode,result.stdout),(1,b''))
        self.assertEqual(self.log.read_bytes(),b'unchanged')
        self.log.unlink();os.mkfifo(self.log)
        result=self.run_honk('metadata','--log-file',self.log,cwd=project)
        self.assertEqual((result.returncode,result.stdout),(1,b''))
        self.log.unlink();self.log.touch(mode=0o600)
        with self.log.open('r+b') as stream: stream.truncate(16*1024*1024)
        result=self.run_honk('metadata','--log-file',self.log,cwd=project)
        self.assertEqual((result.returncode,result.stdout),(1,b''))
        self.assertEqual(self.log.stat().st_size,16*1024*1024)
    def test_return_log_failure_does_not_claim_command_success(self):
        project=self.new()
        started=b'[INFO] started duration_ns=0 outcome=0\n'
        limit=16*1024*1024
        self.log.touch(mode=0o600)
        with self.log.open('r+b') as stream: stream.truncate(limit-len(started))
        result=self.run_honk('metadata','--log-file',self.log,cwd=project)
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)['name'],'demo')
        self.assertIn(b'diagnostic log failed',result.stderr)
        with self.log.open('rb') as stream:
            stream.seek(-len(started),os.SEEK_END)
            self.assertEqual(stream.read(),started)
        self.assertEqual(self.log.stat().st_size,limit)

if __name__=='__main__':unittest.main()

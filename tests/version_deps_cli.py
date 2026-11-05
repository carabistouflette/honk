#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded Git-tag requirements through real Git; the transport shim is test-only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SHIM = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
a = [x.replace("protocol.file.allow=never", "protocol.file.allow=always") for x in sys.argv[1:]]
with open(os.environ["TEST_GIT_LOG"], "a") as f: f.write(json.dumps(a)+"\\n")
a = [os.environ["TEST_REMOTE"] if x == "https://test.invalid/mathx.git" else x for x in a]
os.environ["GIT_ALLOW_PROTOCOL"] = "file"
real = os.environ["TEST_GIT"]
if "ls-remote" in a:
    if os.environ.get("TEST_ADVERTISEMENT"):
        sys.stdout.buffer.write(pathlib.Path(os.environ["TEST_ADVERTISEMENT"]).read_bytes()); sys.exit(0)
    result = subprocess.run([real,*a], capture_output=True)
    if os.environ.get("TEST_MOVE_TO"):
        subprocess.run([real,"-C",os.environ["TEST_REMOTE"],"tag","-f",os.environ["TEST_MOVE_TAG"],os.environ["TEST_MOVE_TO"]], stdout=subprocess.DEVNULL, check=True)
    sys.stdout.buffer.write(result.stdout); sys.stderr.buffer.write(result.stderr); sys.exit(result.returncode)
os.execv(real,[real,*a])
'''

class VersionDependencies(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='honk version deps ')
        self.root = Path(self.temp.name)
        self.remote = self.root/'remote'; self.remote.mkdir()
        self.real_git = shutil.which('git')
        self.git('init','-q'); self.git('config','user.name','Fixture'); self.git('config','user.email','fixture@example.invalid')
        self.commits = {}
        for version, answer, annotated in [('1.2.3',12,False),('1.10.0',110,True),('2.0.0-alpha.1',200,False)]:
            self.release(version, answer, annotated)
        tools = self.root/'tools'; tools.mkdir(); (tools/'git').write_text(SHIM); (tools/'git').chmod(0o755)
        self.log = self.root/'git.log'
        self.env = {**os.environ,'GOOSE':os.environ['GOOSE'],'HONK_HOME':str(self.root/'cache'),
            'PATH':str(tools)+os.pathsep+os.environ['PATH'],'TEST_GIT':self.real_git,'TEST_REMOTE':str(self.remote),'TEST_GIT_LOG':str(self.log)}
        self.project = self.root/'hello'
        self.call('new','hello',cwd=self.root)
        (self.project/'src/main.goose').write_text('import mathx; fn main() { print(mathx::answer()); }')
    def tearDown(self): self.temp.cleanup()
    def git(self,*args):
        return subprocess.check_output([self.real_git,'-C',str(self.remote),*args],stderr=subprocess.STDOUT,text=True).strip()
    def release(self,version,answer,annotated=False):
        (self.remote/'Honk.toml').write_text(f'[package]\nname="mathx"\nversion="{version}"\nkind="lib"\nentry="mathx.goose"\n')
        (self.remote/'mathx.goose').write_text(f'namespace mathx; fn answer() -> i64 {{ {answer} }}')
        self.git('add','.'); self.git('commit','-qm',version)
        commit = self.git('rev-parse','HEAD'); self.commits[version] = commit
        args = ['tag'] + (['-a','-m','fixture'] if annotated else [])
        self.git(*args,'v'+version)
        return commit
    def call(self,*args,cwd=None,ok=True,extra=None):
        result = subprocess.run([os.environ['HONK'],*map(str,args)],cwd=cwd or self.project,
            env={**self.env,**(extra or {})},capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode==0,ok,result.stdout+result.stderr)
        self.assertNotIn('AddressSanitizer',result.stderr); self.assertNotIn('runtime error:',result.stderr)
        return result
    def add(self,requirement): self.call('add','mathx','--git','https://test.invalid/mathx.git','--version',requirement)
    def commands(self, verb):
        return [args for line in self.log.read_text().splitlines() if verb in (args := json.loads(line))] if self.log.exists() else []
    def queries(self): return len(self.commands('ls-remote'))
    def fetches(self): return len(self.commands('fetch'))
    def lock(self): return (self.project/'Honk.lock').read_bytes()
    def test_highest_annotated_lock_update_and_cold_cache(self):
        self.add('^1.2.3'); self.assertIn('110',self.call('run').stdout)
        first = self.lock(); self.assertIn(b'requirement = "^1.2.3"',first); self.assertIn(b'rev = "refs/tags/v1.10.0"',first)
        self.assertIn(self.commits['1.10.0'].encode(),first); self.assertEqual(self.queries(),1)
        later = self.release('1.11.0',111)
        self.git('tag','-f','v1.10.0',later)
        # A cold online locked cache must fetch the OLD commit OID, not enumerate/refetch a moved tag.
        shutil.rmtree(self.root/'cache/sources')
        fetches=self.fetches()
        for mode in ('--frozen','--offline'):
            self.call('fetch',mode,ok=False); self.assertEqual(self.lock(),first); self.assertEqual(self.queries(),1); self.assertEqual(self.fetches(),fetches)
        self.assertIn('110',self.call('run','--locked').stdout); self.assertEqual(self.queries(),1); self.assertEqual(self.lock(),first)
        rehydration=self.commands('fetch')[fetches:]; self.assertTrue(rehydration)
        for args in rehydration:
            self.assertEqual(args[args.index('--')+1:],['https://test.invalid/mathx.git',self.commits['1.10.0']])
        fetches=self.fetches()
        for mode in ('--frozen','--offline'):
            self.assertIn('110',self.call('run',mode).stdout); self.assertEqual(self.queries(),1); self.assertEqual(self.fetches(),fetches); self.assertEqual(self.lock(),first)
        self.call('update'); self.assertEqual(self.queries(),2); self.assertIn(later.encode(),self.lock())
        fetches=self.fetches(); queries=self.queries()
        self.assertIn('111',self.call('run','--frozen').stdout); self.assertEqual(self.fetches(),fetches); self.assertEqual(self.queries(),queries)
    def test_reused_build_still_validates_git_sources(self):
        self.env['GOOSE_HOME'] = str(self.root/'goose')
        self.add('^1.2.3'); self.call('fetch')
        self.assertIn('110', self.call('run', '--reuse-build', '--frozen').stdout)
        record = self.project/'.honk/reuse/debug/record'
        self.assertTrue(record.is_file(), 'Git fixture did not qualify for reuse')
        old_record = record.read_bytes(); lock = self.lock()
        queries = self.queries(); fetches = self.fetches()
        self.assertIn('110', self.call('run', '--reuse-build', '--frozen').stdout)
        self.assertEqual(record.read_bytes(), old_record)
        self.assertEqual(self.lock(), lock)
        self.assertEqual(self.queries(), queries); self.assertEqual(self.fetches(), fetches)
        sources = list((self.root/'cache/sources').glob('*/mathx.goose'))
        self.assertEqual(len(sources), 1)
        sources[0].write_text(sources[0].read_text().replace('110', '999'))
        result = self.call('run', '--reuse-build', '--frozen', ok=False)
        self.assertIn('local changes', result.stderr); self.assertEqual(result.stdout, '')
        self.assertEqual(record.read_bytes(), old_record); self.assertEqual(self.lock(), lock)
        self.assertEqual(self.queries(), queries); self.assertEqual(self.fetches(), fetches)

    def test_prerelease_and_changed_requirement_locked(self):
        self.add('>=2.0.0-alpha.0,<2.0.0'); self.assertIn('200',self.call('run').stdout)
        before = self.lock(); queries=self.queries(); fetches=self.fetches()
        self.call('remove','mathx'); self.add('=1.2.3')
        self.call('fetch','--locked',ok=False); self.assertEqual(self.lock(),before); self.assertEqual(self.queries(),queries); self.assertEqual(self.fetches(),fetches)
        self.call('fetch','--offline',ok=False); self.assertEqual(self.lock(),before); self.assertEqual(self.queries(),queries); self.assertEqual(self.fetches(),fetches)
        self.call('fetch'); self.assertIn(self.commits['1.2.3'].encode(),self.lock())
    def test_no_match_alias_build_and_moved_tag_preserve_lock(self):
        self.call('fetch'); empty=self.lock(); self.add('=1.10.0')
        for alias in ('1.10.0','v1.10.0+build'):
            self.git('tag',alias,self.commits['1.10.0'])
            self.assertIn('ambiguous',self.call('fetch',ok=False).stderr); self.assertEqual(self.lock(),empty)
            self.git('tag','-d',alias)
        moved=self.call('fetch',ok=False,extra={'TEST_MOVE_TAG':'v1.10.0','TEST_MOVE_TO':self.commits['2.0.0-alpha.1']})
        self.assertIn('moved',moved.stderr); self.assertEqual(self.lock(),empty)
        self.call('remove','mathx'); self.add('=9.0.0')
        self.assertIn('no Git tag',self.call('fetch',ok=False).stderr); self.assertEqual(self.lock(),empty)
    def test_same_commit_tag_object_replacement_is_allowed(self):
        self.add('=1.10.0')
        commit=self.commits['1.10.0']; self.assertNotEqual(self.git('rev-parse','refs/tags/v1.10.0'),commit)
        self.call('fetch',extra={'TEST_MOVE_TAG':'v1.10.0','TEST_MOVE_TO':commit})
        self.assertEqual(self.git('rev-parse','refs/tags/v1.10.0'),commit)
        self.assertIn(commit.encode(),self.lock()); self.assertEqual(self.queries(),1)
        self.assertIn('110',self.call('run','--frozen').stdout)
    def test_field_presence_controls_and_lock_empty_requirement(self):
        path=self.project/'Honk.toml'; original=path.read_bytes()
        for args in [('--git','https://test.invalid/mathx.git','--version',''),('--path','../remote','--version',''),
                     ('--git','https://test.invalid/mathx.git','--rev','','--version','^1.2.3'),
                     ('--git','https://test.invalid/mathx.git','--version','\t^1.2.3')]:
            self.call('add','mathx',*args,ok=False); self.assertEqual(path.read_bytes(),original)
        for value in ['{git="https://test.invalid/mathx.git",rev="",version="^1.2.3"}',
                      '{git="https://test.invalid/mathx.git",rev="HEAD",version=""}',
                      '{path="../remote",version=""}', '{git="https://test.invalid/mathx.git",version=""}',
                      '{git="https://test.invalid/mathx.git",version="\\t^1.2.3"}']:
            self.assertEqual(original.count(b'[dependencies]\n'),1)
            path.write_bytes(original.replace(b'[dependencies]\n',b'[dependencies]\nmathx = '+value.encode()+b'\n'))
            result=self.call('metadata',ok=False); self.assertEqual(result.stdout,'')
        path.write_bytes(original); self.add(' ^1.2.3 ')
        self.assertEqual(json.loads(self.call('metadata').stdout)['dependencies'][0]['version'],' ^1.2.3 ')
        self.call('remove','mathx'); self.add('^1.2.3'); self.call('fetch')
        damaged=self.lock().replace(b'requirement = "^1.2.3"',b'requirement = ""'); (self.project/'Honk.lock').write_bytes(damaged)
        queries=self.queries(); result=self.call('fetch','--frozen',ok=False)
        self.assertIn('invalid version requirement/tag identity',result.stderr); self.assertEqual(self.lock(),damaged); self.assertEqual(self.queries(),queries)
        path.write_bytes(original); self.call('add','mathx','--git','https://test.invalid/mathx.git','--rev','v1.2.3'); (self.project/'Honk.lock').unlink(); self.call('fetch')
        damaged=self.lock()+b'\nrequirement = \"\"\n'; (self.project/'Honk.lock').write_bytes(damaged)
        result=self.call('fetch','--frozen',ok=False); self.assertIn('invalid version requirement/tag identity',result.stderr); self.assertEqual(self.lock(),damaged)
    def test_malformed_catalog_and_version_mismatch(self):
        self.call('fetch'); before=self.lock(); self.add('=1.2.3')
        ad=self.root/'advertisement'
        for body in [b'truncated',b'0'*40+b'\trefs/tags/v1.2.3\n',b'x'*1048577,
                     b'1'*40+b'\trefs/tags/v1.2.3\n'+b'2'*40+b'\trefs/tags/v1.2.3\n']:
            ad.write_bytes(body); self.call('fetch',ok=False,extra={'TEST_ADVERTISEMENT':str(ad)}); self.assertEqual(self.lock(),before)
        self.call('remove','mathx'); self.add('=3.0.0'); self.git('tag','v3.0.0',self.commits['1.2.3'])
        self.assertIn('package version',self.call('fetch',ok=False).stderr); self.assertEqual(self.lock(),before)
    def test_distinct_requirements_conflict_without_lock_rewrite(self):
        self.call('fetch'); before=self.lock()
        for name,requirement in [('one','^1.2.3'),('two','=1.2.3')]:
            folder=self.root/name; folder.mkdir()
            (folder/'Honk.toml').write_text(f'[package]\nname="{name}"\nkind="lib"\nentry="{name}.goose"\n[dependencies]\nmathx={{git="https://test.invalid/mathx.git",version="{requirement}"}}\n')
            (folder/(name+'.goose')).write_text(f'namespace {name}; fn answer() -> i64 {{ 1 }}')
            self.call('add',name,'--path','../'+name)
        result=self.call('fetch',ok=False); self.assertIn('conflicting dependency',result.stderr); self.assertEqual(self.lock(),before)

if __name__=='__main__': unittest.main()

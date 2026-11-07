# SPDX-License-Identifier: Apache-2.0
"""Check retained correctness evidence; do not infer speed from control durations."""
import hashlib
import json
from pathlib import Path
import sys
rpath,target=map(Path,sys.argv[1:]);r=json.loads(rpath.read_text())
assert r['complete'] and not r.get('error') and len(r['records'])==26
assert all(x['complete'] and x['exit_code']==x['expected_code'] for x in r['records'])
native=[x for x in r['records'] if x['profile']=='crypto']
pure=[x for x in r['records'] if x['profile']=='diff']
assert len(native)==8 and len(pure)==18
assert all(not x['cache_records'] for x in native)
for row in r['records']:
 if row['expected_work']=='hit':assert row['backend_before']==row['backend_after']
 if row['expected_work']=='compile':assert row['backend_before']!=row['backend_after']
for name,profile in r['profiles'].items():assert profile['files']==r['restored_files'][name]
p=r['postconditions']
assert p['native_publication_before']==p['native_publication_after_failure']
assert p['sentinel_before']==p['sentinel_after']
assert p['corrupt_elf_magic']=={'before':'7f454c46','after':'7f454c46'}
assert p['corruption_record_before']==p['corruption_record_after_edit']
corrupt=next(m for m in r['mutations'] if m['label']=='corrupt-cached-executable')
assert corrupt['before_size']==corrupt['after_size']
assert corrupt['before_sha256']==p['corruption_record_before']['artifact_sha256']
assert corrupt['after_sha256']!=p['corruption_record_before']['artifact_sha256']
assert p['alternate_compiler_version_before']==p['alternate_compiler_version_after']
summary=dict(source=r['head'],raw_sha256=hashlib.sha256(rpath.read_bytes()).hexdigest(),
             expected_outcomes=26,native_outcomes=8,pure_outcomes=18,
             expected_native_compiler_failures=1,verified_hits=sum(x['expected_work']=='hit' for x in pure),
             restored_extracted_source_bytes_and_modes=True,preserved_native_executable=True,external_sentinel_unchanged=True,
             controls=[dict(profile=x['profile'],label=x['label'],result='expected failure' if x['expected_code'] else 'pass',expected_work=x['expected_work']) for x in r['records']],
             scope='Correctness only. Native fallback cannot prove cache invalidation. Native CMake caches may remain warm. No production caching support or performance guarantee added.')
target.write_text(json.dumps(summary,indent=2)+'\n')

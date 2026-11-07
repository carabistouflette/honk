#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare ordinary compilation, cache population and verified hits; retain all samples."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import tarfile
from process_observer import execute
from qualify_parallel import FILES, REV, clean, digest, git, save

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-repo','honk','goose','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--rounds',type=int,default=3)
    args=parser.parse_args()
    if not 1<=args.rounds<=5:parser.error('rounds must be 1..5')
    if git(ROOT,'status','--porcelain').strip():parser.error('clean committed Honk checkout required')
    honk=args.honk.resolve(strict=True);goose=args.goose.resolve(strict=True)
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    project=output/'project';project.mkdir();(output/'tmp').mkdir()
    report=dict(complete=False,head=git(ROOT,'rev-parse','HEAD').decode().strip(),
                source_revision=REV,records=[],platform=platform.platform(),affinity=sorted(os.sched_getaffinity(0)),
                load_before=os.getloadavg(),tool_hashes={'honk':digest(honk),'goose':digest(goose)},
                harness_hash=digest(__file__),scope='Uninstrumented full command wall time; release jobs4; warm shared compiler caches; shared host; no time gates')
    path=output/'raw.json';save(path,report)
    env={**os.environ,'GOOSE':str(goose),'HONK_HOME':str(output/'cache'),'GOOSE_HOME':str(output/'goose'),'TMPDIR':str(output/'tmp')}
    env.pop('GOOSE_CC',None)
    expected=None

    def run(label,reuse):
        nonlocal expected
        before={str(p):p.stat().st_mtime_ns for p in (output/'goose/build/prog').rglob('cc.log')}
        result=execute([str(honk),'test','--release','--jobs','4',*(['--reuse-build'] if reuse else [])],project,env)
        after={str(p):p.stat().st_mtime_ns for p in (output/'goose/build/prog').rglob('cc.log')}
        result['backend_logs_before']=before;result['backend_logs_after']=after
        result['label']=label;report['records'].append(result);save(path,report)
        cold_notice = label=='warmup_ordinary' and len(result['stderr'].splitlines())==1 and result['stderr'].startswith('compiling the runtime for ')
        if not result['complete'] or result['exit_code']!=0 or (result['stderr'] and not cold_notice):
            raise RuntimeError('failed invocation; raw record retained')
        if (label.startswith('hit_') or label=='warmup_hit') and before!=after:
            raise RuntimeError('expected verified hit invoked compiler backend')
        text=clean(result['stdout'])
        if expected is None:
            lines=text.splitlines()
            if len(lines)!=4 or any(not line.startswith(name+': ') for line,name in zip(lines,['context','core','sparse','unified'])):
                raise RuntimeError('unexpected real suite identities/output')
            expected=text
        if text!=expected:raise RuntimeError('suite output changed')
        print(label,round(result['elapsed_ns']/1e6),flush=True)

    try:
        cc=Path(shutil.which('cc')).resolve(strict=True)
        report['c_compiler']={'path':str(cc),'sha256':digest(cc),'version':subprocess.check_output([str(cc),'--version'],text=True,timeout=10)}
        report['compiler_pin']=(ROOT/'GOOSE_REVISION').read_text().strip()
        report['compiler_version']=subprocess.check_output([str(goose),'version'],text=True,timeout=10)
        report['harness_hashes']={str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__),ROOT/'bench/process_observer.py',ROOT/'bench/qualify_parallel.py',ROOT/'bench/observer_calibration.py')}
        report['environment_sha256']=hashlib.sha256(json.dumps(sorted(env.items())).encode()).hexdigest()
        report['flags']=['test','--release','--jobs','4'];report['seed']=20261107
        if git(args.source_repo,'rev-parse','v0.1.0^{commit}').decode().strip()!=REV:raise RuntimeError('tag mismatch')
        archive=git(args.source_repo,'archive','--format=tar',REV,'--',*FILES)
        (output/'source.tar').write_bytes(archive)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:bundle.extractall(project,filter='data')
        if (project/'GOOSE_REVISION').read_text().strip()!=report['compiler_pin']:raise RuntimeError('compiler pin mismatch')
        files={name:digest(project/name) for name in FILES};report['source_files']=files
        report['archive_sha256']=hashlib.sha256(archive).hexdigest()
        (project/'Honk.toml').write_text('[package]\nname="diff"\nkind="lib"\nversion="0.1.0"\nentry="diff.goose"\n')
        run('warmup_ordinary',False);run('warmup_population',True);run('warmup_hit',True)
        rng=random.Random(20261107)
        # Ordinary builds invalidate selected test slots; each hit therefore has
        # an explicitly populated snapshot immediately beforehand.
        for i in range(args.rounds):
            order=['ordinary','reuse'];rng.shuffle(order)
            for mode in order:
                if mode=='ordinary':run(f'ordinary_{i}',False)
                else:
                    for record in (project/'.honk/reuse/release/tests').glob('*/record'):record.unlink()
                    run(f'population_{i}',True);run(f'hit_{i}',True)
        if {name:digest(project/name) for name in FILES}!=files:raise RuntimeError('source changed')
        if report['tool_hashes']!={'honk':digest(honk),'goose':digest(goose)}:raise RuntimeError('tool bytes changed')
        if digest(cc)!=report['c_compiler']['sha256'] or {name:digest(ROOT/name) for name in report['harness_hashes']}!=report['harness_hashes']:raise RuntimeError('compiler or transitive harness changed')
        if digest(__file__)!=report['harness_hash'] or git(ROOT,'rev-parse','HEAD').decode().strip()!=report['head'] or git(ROOT,'status','--porcelain').strip():raise RuntimeError('Honk/harness changed')
        report['load_after']=os.getloadavg();report['complete']=True
    except BaseException as failure:
        report['error']=repr(failure);raise
    finally:save(path,report)


if __name__=='__main__':main()

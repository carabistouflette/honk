#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Matched local debug builds: ordinary, cold reuse, warm reuse and fallback."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import resource
import select
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PIN = '2311ae69a7edacb545f284b02e345be07dd2fb05'


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def execute(argv, cwd, env, work, label):
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter_ns()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        descriptor = None
        try:
            descriptor = os.pidfd_open(child.pid)
            waiter = select.poll(); waiter.register(descriptor, select.POLLIN)
            if not any(mask & select.POLLIN for _, mask in waiter.poll(120000)):
                raise RuntimeError(label+': timeout or invalid pidfd event')
            child.wait()
        finally:
            try:
                if child.returncode is None:
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    child.wait(timeout=5)
            finally:
                if descriptor is not None: os.close(descriptor)
        wall = (time.perf_counter_ns()-started)/1e6
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        out.seek(0); err.seek(0); stdout = out.read(1048577); stderr = err.read(1048577)
    record = {'label': label, 'wall_ms': wall,
              'cpu_ms': 1000*((after.ru_utime-usage.ru_utime)+(after.ru_stime-usage.ru_stime)),
              'exit': child.returncode, 'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
              'stderr_sha256': hashlib.sha256(stderr).hexdigest()}
    with (work/'events.jsonl').open('a') as output: output.write(json.dumps(record)+'\n')
    if child.returncode or len(stdout) > 1048576 or stderr:
        raise RuntimeError(label+': failed or unexpected output\n'+(stdout+stderr)[:4096].decode(errors='replace'))
    return record, stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--honk', required=True, type=Path)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--goose', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--rounds', type=int, default=9)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.output.exists() or not 1 <= args.rounds <= 21:
        parser.error('require a new output path and 1..21 rounds')
    if os.environ.get('GOOSE_CC'):
        parser.error('first reuse implementation requires the default C compiler')
    for name in ['honk', 'baseline', 'goose']:
        setattr(args, name, getattr(args, name).resolve(strict=True))
    if subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain']).strip():
        parser.error('commit the harness and implementation before measuring')
    revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    (ROOT/'.build').mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='reuse-profile-', dir=ROOT/'.build'))
    print('Retained work '+str(work), flush=True)
    env = {**os.environ, 'GOOSE': str(args.goose), 'GOOSE_HOME': str(work/'goose'), 'HONK_HOME': str(work/'cache')}
    inputs = {'harness': sha(Path(__file__)), 'candidate': sha(args.honk), 'baseline': sha(args.baseline), 'compiler': sha(args.goose)}
    fixtures = {}; fingerprints = {}; operations = []
    for name in ['source_only', 'conservative_fallback']:
        project = work/name; (project/'src').mkdir(parents=True); (project/'vendor/semver').mkdir(parents=True)
        (project/'Honk.toml').write_text('[package]\nname="reuse_gate"\nversion="0.1.0"\nentry="src/main.goose"\n[dependencies]\nsemver={path="vendor/semver"}\n')
        (project/'src/main.goose').write_text('import semver; fn main() { let r, e = semver::parse_requirement("^1.2.3"); let v, f = semver::parse("1.8.0"); assert(e.kind == semver::ErrorKind.None && f.kind == semver::ErrorKind.None); assert(semver::matches(r,v)); print("match"); }\n')
        for file in ['semver.goose', 'LICENSE']:
            (project/'vendor/semver'/file).write_bytes((ROOT/'vendor/goose-semver'/file).read_bytes())
        if name == 'conservative_fallback':
            # An unused sidecar is enough to disable first-version reuse.
            (project/'unused.build').write_text('c_flags_cc = [];\n')
        operation, _ = execute([str(args.honk), 'fetch'], project, env, work, name+'_resolve')
        operations.append(operation)
        fixtures[name] = project
        fingerprints[name] = {p.relative_to(project).as_posix(): sha(p) for p in project.rglob('*') if p.is_file() and not any(part in {'.honk', 'target'} for part in p.relative_to(project).parts)}
    modes = ['baseline_plain', 'candidate_plain', 'candidate_cold', 'candidate_warm']

    def call(name, mode, label):
        project = fixtures[name]
        executable = args.baseline if mode == 'baseline_plain' else args.honk
        argv = [str(executable), 'build', '--frozen']
        if mode in {'candidate_cold', 'candidate_warm'}: argv.append('--reuse-build')
        record, stdout = execute(argv, project, env, work, label)
        if stdout != ('built '+str(project/'target/debug/reuse_gate')+'\n').encode():
            raise RuntimeError('unexpected build stdout')
        functional, output = execute([str(project/'target/debug/reuse_gate')], project, env, work, label+'_output')
        if output != b'match\n': raise RuntimeError('compiled application behavior differs')
        operations.append(functional)
        record.update(fixture=name, mode=mode)
        return record

    for name in fixtures:
        for mode in modes: operations.append(call(name, mode, name+'_warmup_'+mode))
    # The normal toolchain still invokes C; a cache hit must leave its log alone.
    project = fixtures['source_only']; slot = project/'.honk/reuse/debug'
    if not (slot/'record').is_file(): raise RuntimeError('source-only fixture did not qualify')
    logs = list((work/'goose/build/prog').rglob('cc.log'))
    if not logs: raise RuntimeError('compiler backend logs absent')
    for path in logs: path.write_text('reuse-profile: backend not invoked\n')
    operations.append(call('source_only', 'candidate_warm', 'verified_hit'))
    if any(path.read_text() != 'reuse-profile: backend not invoked\n' for path in logs):
        raise RuntimeError('purported warm hit invoked the C backend')
    metadata = (slot/'record').read_text()
    if metadata[65:129] != sha(slot/'program'):
        raise RuntimeError('artifact digest differs from independent Python SHA-256')
    rng = random.Random(20261105); samples = []; preparations = []
    started_utc = datetime.now(timezone.utc).isoformat()
    for round_number in range(args.rounds):
        order = [(name, mode) for name in fixtures for mode in modes]; rng.shuffle(order)
        for name, mode in order:
            slot = fixtures[name]/'.honk/reuse/debug'
            if mode == 'candidate_cold':
                for file in ['record', 'program']:
                    path = slot/file
                    if path.exists(): path.unlink()
            if mode == 'candidate_warm' and name == 'source_only' and not (slot/'record').exists():
                preparations.append(call(name, mode, 'prepare_'+name))
            record = call(name, mode, name+'_'+mode)
            record['round'] = round_number; samples.append(record)
            print(round_number, name, mode, record['wall_ms'], flush=True)
    for name, project in fixtures.items():
        for file, expected in fingerprints[name].items():
            if sha(project/file) != expected: raise RuntimeError('fixture/lock changed')
    if any(inputs[name] != sha(path) for name, path in [('harness', Path(__file__)), ('candidate', args.honk), ('baseline', args.baseline), ('compiler', args.goose)]):
        raise RuntimeError('measurement executable/source inputs changed')
    report = {'revision': revision, 'source_clean': True, 'sha256': inputs,
              'compiler_revision': (ROOT/'GOOSE_REVISION').read_text().strip(), 'semver_pin': PIN,
              'fixtures_sha256': fingerprints, 'started_utc': started_utc,
              'finished_utc': datetime.now(timezone.utc).isoformat(), 'platform': platform.platform(),
              'affinity': sorted(os.sched_getaffinity(0)), 'seed': 20261105,
              'scope': 'Same project/compiler/output paths per fixture, shared host. Real source-only SemVer CLI versus conservative unused-sidecar fallback. Selected debug builds. Cold means empty Honk reuse slot only: compiler/runtime and OS page caches are warm. Warm preparation/functional checks outside timing are retained separately. Cached builds use standalone runtime; no equal-cold-codegen claim. RSS not measured. No timing threshold.',
              'backend_skip_and_independent_artifact_digest_verified': True,
              'samples': samples, 'preparations': preparations, 'operations': operations}
    with args.output.open('x') as output: output.write(json.dumps(report, indent=2)+'\n')
    print('Wrote '+str(args.output), flush=True)


if __name__ == '__main__':
    main()

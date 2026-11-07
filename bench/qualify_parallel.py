#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Linux real-project qualification; outputs include every failed/slow sample."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import random
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import time
from process_observer import execute
from observer_calibration import calibrate

ROOT = Path(__file__).resolve().parents[1]
REV = '129dc794b62ad987784db0a1d52ef618c85fccf4'
FILES = ('diff.goose', 'sparse.goose', 'unified.goose', 'LICENSE', 'GOOSE_REVISION',
         'tests/core.goose', 'tests/sparse.goose', 'tests/unified.goose', 'tests/context.goose')
MODES = {'default': [], 'jobs1': ['--jobs', '1'], 'jobs2': ['--jobs', '2'], 'jobs4': ['--jobs', '4']}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(repo, *argv):
    return subprocess.check_output(['git', '-C', str(repo), *argv], timeout=30)


def save(path, report):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2)+'\n')
    temporary.replace(path)


def clean(stdout):
    return ''.join(line+'\n' for line in stdout.splitlines() if line and
                   not line.startswith(('built ', 'Passed ', '@@QUAL ')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-repo', 'honk', 'goose', 'driver', 'pressure', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 5:
        parser.error('rounds must be 1..5')
    for name in ('source_repo', 'honk', 'goose', 'driver', 'pressure'):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    project = output/'project'; project.mkdir(); (output/'tmp').mkdir()
    env = {**os.environ, 'GOOSE': str(args.goose), 'HONK_HOME': str(output/'cache'), 'TMPDIR': str(output/'tmp')}
    report = dict(complete=False, started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  platform=platform.platform(), python=sys.version, affinity=sorted(os.sched_getaffinity(0)),
                  load_before=os.getloadavg(), rounds=args.rounds, seed=20261107, records=[], source_revision=REV,
                  semantics=dict(timing='uninstrumented wall time; serial compilation included; warm cache, rebuilt outputs',
                                 resources='separate perturbed invocations; sampled lower bounds; RSS sums double-count shared pages',
                                 phase='execution: observed test; non_test_descendants does not prove compilation',
                                 stress='512 real suite executions in 128 cohorts; amplified supervisor stress'))
    path = output/'report.json'; save(path, report)

    def run(label, argv, **options):
        result = execute(list(map(str, argv)), project, env, **options)
        result['label'] = label; report['records'].append(result); save(path, report)
        print(label, result['exit_code'], f"{result['elapsed_ns']/1e9:.3f}s", flush=True)
        if not result['complete'] or result['exit_code'] != 0:
            raise RuntimeError('invocation failed; see retained raw record')
        return result

    try:
        if git(ROOT, 'status', '--porcelain').strip():
            raise RuntimeError('qualification requires clean committed Honk source')
        (output/'calibration').mkdir()
        report['calibration'] = calibrate(output/'calibration')
        save(path, report)
        tag = git(args.source_repo, 'rev-parse', 'v0.1.0^{commit}').decode().strip()
        if tag != REV:
            raise RuntimeError('public v0.1.0 mismatch')
        archive = git(args.source_repo, 'archive', '--format=tar', REV, '--', *FILES)
        (output/'source.tar').write_bytes(archive)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(project, filter='data')
        sources = {name: digest(project/name) for name in FILES}
        manifest = '[package]\nname="diff"\nkind="lib"\nversion="0.1.0"\nentry="diff.goose"\n'
        (project/'Honk.toml').write_text(manifest)
        report.update(source_tag=tag, archive_sha256=hashlib.sha256(archive).hexdigest(), files=sources,
                      adapter_manifest=manifest, suite_order=['context', 'core', 'sparse', 'unified'],
                      honk_revision=git(ROOT, 'rev-parse', 'HEAD').decode().strip(),
                      honk_worktree=git(ROOT, 'status', '--short').decode(),
                      tool_sha256={name: digest(getattr(args, name)) for name in ('honk', 'goose', 'driver', 'pressure')},
                      harness_sha256={str(p.relative_to(ROOT)): digest(p) for p in
                                      (Path(__file__), ROOT/'bench/process_observer.py', ROOT/'bench/qualification_driver.goose', ROOT/'bench/qualification_pressure.goose', ROOT/'bench/observer_calibration.py')},
                      c_compiler_sha256=digest(shutil.which('cc')), compiler_pin=(ROOT/'GOOSE_REVISION').read_text().strip())
        if (project/'GOOSE_REVISION').read_text().strip() != report['compiler_pin']:
            raise RuntimeError('workload and Honk compiler pins differ')
        report['compiler_version'] = subprocess.check_output([str(args.goose), '--version'], text=True, timeout=10)
        report['c_compiler_path'] = str(Path(shutil.which('cc')).resolve())
        report['c_compiler_version'] = subprocess.check_output(['cc', '--version'], text=True, timeout=10)
        command = [args.honk, 'test', '--release', '--manifest-path', project/'Honk.toml']
        run('preparation', [*command, '--jobs', '4'])
        stage = project/'.honk/stage/app'
        staged = {}
        for name in FILES:
            if not name.endswith('.goose'):
                continue
            expected_source = (project/name).read_bytes().replace(b'from ".."', ('from "'+str(stage)+'"').encode())
            actual = (stage/name).read_bytes()
            if actual != expected_source:
                raise RuntimeError('unexpected staged source transformation: '+name)
            staged[name] = hashlib.sha256(actual).hexdigest()
            retained = output/'staged-source'/name
            retained.parent.mkdir(parents=True, exist_ok=True)
            retained.write_bytes(actual)
        report['staged_source_sha256'] = staged
        report['staging_transformation'] = 'only from ".." rewritten to absolute .honk/stage/app; no work inserted'
        binaries = [project/'target/release/.honk/tests'/str(i) for i in range(4)]
        report['suite_binary_sha256'] = [digest(p) for p in binaries]
        canonical = []
        for i, binary in enumerate(binaries):
            canonical.append(run(f'direct_warmup_{i}', [binary])['stdout'])
            if not canonical[-1].startswith(report['suite_order'][i]+': '):
                raise RuntimeError('numeric executable does not identify expected suite')
            for n in range(args.rounds):
                result = run(f'direct_{i}_{n}', [binary])
                if result['stdout'] != canonical[i] or result['stderr']:
                    raise RuntimeError('direct suite output changed')
        expected = ''.join(canonical); report['canonical_suite_stdout'] = canonical
        for mode, flags in MODES.items():
            result = run('warmup_'+mode, [*command, *flags])
            if clean(result['stdout']) != expected or result['stderr']:
                raise RuntimeError('warmup output mismatch')
        rng = random.Random(report['seed'])
        for n in range(args.rounds):
            modes = list(MODES); rng.shuffle(modes)
            for mode in modes:
                result = run(f'timing_{mode}_{n}', [*command, *MODES[mode]])
                if clean(result['stdout']) != expected or result['stderr']:
                    raise RuntimeError('timing output mismatch')
        for mode, flags in MODES.items():
            result = run('resources_'+mode, [*command, *flags], trace=output/f'{mode}.jsonl.gz', test_executables=binaries)
            if clean(result['stdout']) != expected or result['stderr'] or result['observation']['permission_errors']:
                raise RuntimeError('resource observation/output mismatch')

        def checkpoint(process, line, row):
            if row['children'] or row['group_members']:
                raise RuntimeError('children remain at paused checkpoint')
            if checkpoint.baseline is None:
                checkpoint.baseline = row['fds']
            elif row['fds'] != checkpoint.baseline:
                raise RuntimeError('descriptor identities changed at paused checkpoint')

        for mode in ('endurance', 'failure', 'timeout', 'cancel', 'pressure', 'overflow'):
            checkpoint.baseline = None; sent = []

            def trigger(process, row):
                children = [node for node in row['nodes'] if node['pid'] != process.pid]
                if len(children) == 2 and not sent:
                    process.send_signal(signal.SIGTERM); sent.append(time.monotonic_ns())

            result = run('control_'+mode, [args.driver, mode, *binaries, args.pressure],
                         trace=output/f'control_{mode}.jsonl.gz', test_executables=[*binaries, args.pressure],
                         checkpoint=checkpoint, trigger=trigger if mode == 'cancel' else None)
            text = clean(result['stdout'])
            if mode == 'endurance' and (text != expected*128 or len(result['checkpoints']) != 9):
                raise RuntimeError('endurance output/checkpoint mismatch')
            if mode == 'failure' and text != expected+canonical[0]+canonical[2]+canonical[3]:
                raise RuntimeError('failed cohort output/order mismatch')
            if mode == 'cancel' and not sent:
                raise RuntimeError('cancellation was never signaled')
            if mode in ('timeout', 'cancel') and (text or result['stderr']):
                raise RuntimeError('silent control output mismatch')
            if mode == 'pressure' and (text != canonical[0]+'x'*65536+'\n' or result['stderr'] != 'x'*65536):
                raise RuntimeError('pressure output mismatch')
            if mode != 'endurance' and len(result['checkpoints']) != 2:
                raise RuntimeError('control cleanup checkpoint missing')
            if result['observation']['permission_errors']:
                raise RuntimeError('owned observations denied')
        if {name: digest(project/name) for name in FILES} != sources:
            raise RuntimeError('upstream source bytes changed')
        if [digest(p) for p in binaries] != report['suite_binary_sha256']:
            raise RuntimeError('suite binary bytes changed')
        if {name: digest(stage/name) for name in staged} != staged:
            raise RuntimeError('staged sources changed during campaign')
        if digest(shutil.which('cc')) != report['c_compiler_sha256']:
            raise RuntimeError('C compiler changed during campaign')
        if report['tool_sha256'] != {name: digest(getattr(args, name)) for name in report['tool_sha256']}:
            raise RuntimeError('qualification executable bytes changed')
        if report['harness_sha256'] != {name: digest(ROOT/name) for name in report['harness_sha256']}:
            raise RuntimeError('qualification harness bytes changed')
        if git(ROOT, 'status', '--porcelain').strip():
            raise RuntimeError('Honk source changed during qualification')
        if git(ROOT, 'rev-parse', 'HEAD').decode().strip() != report['honk_revision']:
            raise RuntimeError('Honk revision changed during campaign')
        report['medians_ms'] = {mode: statistics.median(r['elapsed_ns']/1e6 for r in report['records']
                                if r['label'].startswith('timing_'+mode+'_')) for mode in MODES}
        report['load_after'] = os.getloadavg(); report['complete'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        save(path, report)
    print(path)


if __name__ == '__main__':
    main()

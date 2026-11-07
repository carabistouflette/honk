#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Finite real-Goose end-to-end comparison; preserve every sample, never gate on time."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def output(*argv):
    return subprocess.check_output(argv, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--honk', required=True)
    parser.add_argument('--goose', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 5:
        parser.error('rounds must be1..5')
    target = Path(args.output).resolve()
    if target.exists():
        parser.error('preserve old evidence; select another output path')
    honk, goose = Path(args.honk).resolve(), Path(args.goose).resolve()
    count = 4 if args.smoke else 8
    rounds = 1 if args.smoke else args.rounds
    modes = [('default', []), ('jobs1', ['--jobs', '1']), ('jobs2', ['--jobs', '2']), ('jobs4', ['--jobs', '4'])]
    workloads = ['tiny', 'waiting'] if args.smoke else ['tiny', 'waiting', 'cpu', 'uneven']
    rng = random.Random(20261107)
    source_files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).split(b'\0')
    source_hashes = {os.fsdecode(p): digest(ROOT/os.fsdecode(p)) for p in source_files if p}
    cc = Path(shutil.which('cc')).resolve()
    report = dict(schema=1, timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  head=output('git', '-C', str(ROOT), 'rev-parse', 'HEAD'),
                  status=output('git', '-C', str(ROOT), 'status', '--porcelain'),
                  source_hashes=source_hashes, benchmark_script_sha256=digest(__file__), honk_sha256=digest(honk), goose_sha256=digest(goose),
                  goose_revision=(ROOT/'GOOSE_REVISION').read_text().strip(),
                  goose_version=output(str(goose), 'version'), c_compiler=output(str(cc), '--version'), c_compiler_sha256=digest(cc),
                  platform=platform.platform(), affinity=sorted(os.sched_getaffinity(0)),
                  cpu_model=next((x.split(':', 1)[1].strip() for x in Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')), ''),
                  load_before=os.getloadavg(), targets=count, rounds=rounds, seed=20261107,
                  scope='End-to-end Honk test --release, serial compilation included, warm compiler caches. Shared-host synthetic local fixtures; no timing threshold or general performance claim.',
                  fixtures={}, samples=[], complete=False)
    if args.smoke:
        report['scope'] += ' CI smoke is execution evidence only.'
    def save():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2)+'\n')
    save()
    try:
        with tempfile.TemporaryDirectory(prefix='parallel-bench-') as raw:
            base = Path(raw)
            env = {**os.environ, 'GOOSE': str(goose), 'HONK_HOME': str(base/'cache')}
            for workload in workloads:
                project = base/workload
                (project/'src').mkdir(parents=True)
                (project/'tests').mkdir()
                manifest = '[package]\nname="parallel_benchmark"\nversion="0.1.0"\nentry="src/main.goose"\n'
                (project/'Honk.toml').write_text(manifest)
                (project/'src/main.goose').write_text('fn main() {}\n')
                fixtures = {}
                for i in range(count):
                    delay = (10 if args.smoke else 200) if workload == 'waiting' else 0
                    if workload == 'uneven':
                        delay = 400 if i in (0, count-1) else 0
                    body = f'sleep_ms({delay});'
                    if workload == 'cpu':
                        body = 'var value: u64 = arg_count() as u64; for i in 50000000 { value = (value ^ (value >> 13)) * 6364136223846793005; } assert(value != 0); print("CHECKSUM:", value);'
                    source = 'import std; import os; fn main() { '+body+f' print("CASE:{workload}:{i}"); }}\n'
                    fixtures[f'tests/{i:02}.goose'] = source
                    (project/'tests'/f'{i:02}.goose').write_text(source)
                report['fixtures'][workload] = dict(manifest=manifest, sources=fixtures)
                def invoke(label, options, phase):
                    began = time.perf_counter_ns()
                    timed_out = False
                    interrupted = None
                    with subprocess.Popen([str(honk), 'test', '--release', *options], cwd=project, env=env,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True) as process:
                        try:
                            stdout, stderr = process.communicate(timeout=120)
                        except BaseException as error:
                            interrupted = error
                            timed_out = isinstance(error, subprocess.TimeoutExpired)
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            stdout, stderr = process.communicate()
                        returncode = process.returncode
                    elapsed = time.perf_counter_ns() - began
                    normalized = stdout.replace(str(project).encode(), b'${FIXTURE}')
                    record = dict(workload=workload, mode=label, phase=phase, elapsed_ns=elapsed,
                                  exit_code=returncode, timed_out=timed_out, stdout=normalized.decode('utf-8', errors='backslashreplace'),
                                  stderr=stderr.decode('utf-8', errors='backslashreplace'))
                    report['samples'].append(record)
                    save()
                    if interrupted is not None:
                        raise interrupted
                    lines = stdout.splitlines()
                    checksums = [x for x in lines if x.startswith(b'CHECKSUM:')]
                    if workload == 'cpu':
                        assert len(checksums) == count and all(int(x.split(b':')[1]) > 0 for x in checksums)
                        prior = report['fixtures'][workload].setdefault('checksums', [x.decode() for x in checksums])
                        assert prior == [x.decode() for x in checksums], 'CPU fixture results differ across modes'

                    expected = [f'CASE:{workload}:{i}'.encode() for i in range(count)]
                    if returncode or timed_out or [x for x in lines if x.startswith(b'CASE:')] != expected or stderr:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(json.dumps(report, indent=2)+'\n')
                        raise RuntimeError(f'benchmark correctness failure: {workload}/{label}; evidence preserved')
                for label, options in modes:
                    invoke(label, options, 'warmup')
                for round_id in range(rounds):
                    order = modes.copy()
                    rng.shuffle(order)
                    for label, options in order:
                        invoke(label, options, f'round{round_id}')
                report['fixtures'][workload]['executables_sha256'] = {
                    str(i): digest(project/'target/release/.honk/tests'/str(i)) for i in range(count)}
        assert report['honk_sha256'] == digest(honk) and report['goose_sha256'] == digest(goose), 'tools changed during measurement'
        assert source_hashes == {p: digest(ROOT/p) for p in source_hashes}, 'tracked source changed during measurement'
        assert report['c_compiler_sha256'] == digest(cc), 'C compiler changed during measurement'
        report['load_after'] = os.getloadavg()
        report['complete'] = True
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2)+'\n')
        print(f'parallel benchmark raw evidence: {target}')
    except BaseException as error:
        report['error'] = repr(error)
        save()
        raise


if __name__ == '__main__':
    main()

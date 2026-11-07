#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Finite real-compiler wall-time and optional parent-process allocation evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='a39216aba524dc4bffe2e0d038f86ccecf4d013d')
    parser.add_argument('--goose', required=True)
    parser.add_argument('--runs', type=int, default=7)
    parser.add_argument('--allocations', action='store_true')
    parser.add_argument('--output', default='.build/compiler-diagnostics-measurement.json')
    args = parser.parse_args()
    if not 1 <= args.runs <= 100:
        parser.error('runs must be 1..100')
    goose = str(Path(args.goose).resolve())
    baseline_commit = subprocess.check_output(['git', 'rev-parse', '--verify', args.baseline_ref+'^{commit}'], cwd=ROOT, text=True).strip()
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    samples = {}
    allocations = {}
    with tempfile.TemporaryDirectory(prefix='honk diagnostic benchmark ') as temporary:
        root = Path(temporary)
        baseline_source = root/'baseline-source'
        baseline_source.mkdir()
        archive = subprocess.check_output(['git', 'archive', baseline_commit], cwd=ROOT)
        subprocess.run(['tar', '-x', '-C', str(baseline_source)], input=archive, check=True)
        binary, baseline = str(root/'honk-candidate'), str(root/'honk-baseline')
        commands = [[goose, 'build', str(ROOT/'honk.goose'), '--standalone', '-O2', '--cc', 'cc', '-o', binary],
                    [goose, 'build', str(baseline_source/'honk.goose'), '--standalone', '-O2', '--cc', 'cc', '-o', baseline]]
        profile_candidate, profile_baseline = str(root/'honk-profile-candidate'), str(root/'honk-profile-baseline')
        if args.allocations:
            commands.extend([commands[0][:-2]+['--stack-reserve', '16M', '-o', profile_candidate],
                             commands[1][:-2]+['--stack-reserve', '16M', '-o', profile_baseline]])
        for command in commands:
            subprocess.run(command, cwd=ROOT, check=True)
        binary_hashes = {'candidate': sha(binary), 'baseline': sha(baseline), 'goose': sha(goose)}
        if args.allocations:
            binary_hashes.update(profile_candidate=sha(profile_candidate), profile_baseline=sha(profile_baseline))
        env = {**os.environ, 'GOOSE': goose, 'HONK_HOME': str(root/'home'), 'NO_COLOR': '1'}
        subprocess.run([binary, 'new', 'demo'], cwd=root, env=env, check=True, stdout=subprocess.DEVNULL)
        project = root/'demo'
        cases = {'baseline': (baseline, []), 'default': (binary, []),
                 'text': (binary, ['--diagnostics', 'text']), 'json': (binary, ['--diagnostics', 'json'])}
        for fixture in ('success', 'error'):
            (project/'src/main.goose').write_text('fn main() {}\n' if fixture == 'success' else 'fn main() { unknown_function(); }\n')
            expected = 0 if fixture == 'success' else 1
            def run(mode, prefix=()):
                executable, options = cases[mode]
                if prefix:
                    executable = profile_baseline if mode == 'baseline' else profile_candidate
                start = time.perf_counter_ns()
                result = subprocess.run([*prefix, executable, 'check', *options], cwd=project,
                                        env=env, capture_output=True, timeout=120)
                elapsed = time.perf_counter_ns()-start
                if result.returncode != expected:
                    raise RuntimeError(f'{fixture}/{mode}: {result.returncode}: {result.stderr!r}')
                if mode == 'json':
                    data = json.loads(result.stdout)
                    if len(data) != expected:
                        raise RuntimeError('unexpected diagnostic count')
                return elapsed, result
            for mode in cases:
                run(mode)
                samples[f'{fixture}.{mode}'] = []
            for iteration in range(args.runs):
                order = list(cases) if iteration % 2 == 0 else list(reversed(cases))
                for mode in order:
                    elapsed, result = run(mode)
                    samples[f'{fixture}.{mode}'].append({'wall_ns': elapsed, 'stdout_bytes': len(result.stdout),
                                                       'stderr_bytes': len(result.stderr), 'exit': result.returncode})
            if args.allocations:
                for mode in cases:
                    log = destination.parent / f'valgrind-{fixture}-{mode}.log'
                    run(mode, ['valgrind', '--tool=memcheck', '--trace-children=no', '--child-silent-after-fork=yes',
                               '--log-file='+str(log), '--leak-check=no'])
                    raw = log.read_text()
                    if not re.search(r'ERROR SUMMARY: 0 errors', raw):
                        raise RuntimeError(f'Valgrind reported errors: {log}')
                    summary = re.search(r'total heap usage: ([\d,]+) allocs, ([\d,]+) frees, ([\d,]+) bytes allocated', raw)
                    if not summary:
                        raise RuntimeError(f'allocation summary missing: {log}')
                    allocations[f'{fixture}.{mode}'] = dict(zip(('allocs', 'frees', 'requested_bytes'),
                                                              (int(value.replace(',', '')) for value in summary.groups())))
                    allocations[f'{fixture}.{mode}']['log_sha256'] = sha(log)
    tracked = ['honk.goose', 'src/build.goose', 'src/commands.goose', 'bench/compiler_diagnostics.py']
    report = {'build_commands': commands,
              'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True).strip()),
              'cc': subprocess.check_output(['cc', '--version'], text=True).strip(),
              'valgrind': subprocess.check_output(['valgrind', '--version'], text=True).strip() if args.allocations else None,
              'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'baseline_commit': baseline_commit,
              'source_sha256': {name: sha(ROOT/name) for name in tracked},
              'binary_sha256': binary_hashes,
              'compiler_pin': (ROOT/'GOOSE_REVISION').read_text().strip(),
              'platform': platform.platform(), 'affinity': sorted(os.sched_getaffinity(0)),
              'samples': samples, 'allocations': allocations,
              'limits': ['End-to-end check includes project staging, compiler validation and child compiler execution.',
                         'No universal speed claim; two tiny fixtures on a shared host; startup/scheduling noise included.',
                         'Valgrind counts parent Honk allocations, including loaded libraries; exec child compiler allocations excluded.',
                         'Requested byte totals are cumulative, not peak live memory or RSS; profiling is separate from timing.',
                         'Allocation profiling uses separate 16 MiB stack-reservation executables; timings use default reservations.']}
    destination.write_text(json.dumps(report, indent=2)+'\n')
    print(destination)


if __name__ == '__main__':
    main()

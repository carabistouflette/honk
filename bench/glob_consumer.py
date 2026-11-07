#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build two committed Honk snapshots and measure complete warm local commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def call(command, **kwargs):
    # Keep build/target logs off the Python heap until bounded reads.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        result = subprocess.run(list(map(str, command)), stdout=out, stderr=err,
                                timeout=300, **kwargs)
        values = []
        for stream in (out, err):
            stream.seek(0)
            data = stream.read(1048577)
            if len(data) > 1048576:
                raise SystemExit('Benchmark subprocess output exceeded 1 MiB')
            values.append(data.decode('utf-8'))
        result.stdout, result.stderr = values
        result.check_returncode()
        return result


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture_inputs(fixture):
    return {str(p): digest(p) for p in fixture.rglob('*') if p.is_file() and
            not any(part in ('.honk', 'target') for part in p.relative_to(fixture).parts)}


def archive(revision, destination):
    destination.mkdir(parents=True)
    tar = destination.parent/(destination.name + '.tar')
    call(['git', '-C', ROOT, 'archive', '--format=tar', f'--output={tar}', revision])
    with tarfile.open(tar) as data:
        data.extractall(destination, filter='data')
    tar.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', default='7583ebe4ccb19cca530ccd295359dd808d8de3c9')
    parser.add_argument('--after', default='HEAD')
    parser.add_argument('--goose', required=True)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--rounds', type=int, default=7)
    parser.add_argument('--cpu', type=int, default=2)
    parser.add_argument('--output', type=Path, default=ROOT/'.build/glob-comparison')
    args = parser.parse_args()
    driver = Path(__file__).resolve()
    driver_hash = digest(driver)
    if args.rounds < 1 or args.cpu not in os.sched_getaffinity(0):
        parser.error('positive rounds and an available CPU required')
    goose = Path(args.goose).resolve(strict=True)
    cc = Path(shutil.which(args.cc)).resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True)  # Retain previous experiments.
    revisions = {name: call(['git', '-C', ROOT, 'rev-parse', f'{ref}^{{commit}}']).stdout.strip()
                 for name, ref in [('before', args.before), ('after', args.after)]}
    binaries = {}
    for name, revision in revisions.items():
        source = output/name
        archive(revision, source)
        binary = output/f'honk-{name}'
        result = call([goose, 'build', source/'honk.goose', '--cc', cc, '-O2', '-o', binary])
        (output/f'{name}-build.log').write_text(result.stdout + result.stderr)
        binaries[name] = binary
        print(f'Built {name} {revision}', flush=True)
    fixture = output/'fixture'
    archive(revisions['before'], fixture)
    env = {**os.environ, 'GOOSE': str(goose), 'HONK_HOME': str(output/'home')}
    call([binaries['before'], 'fetch'], cwd=fixture, env=env)
    # The source fixture is one exact real Honk tree for both versions. State and
    # compiler outputs are excluded; the generated lock is explicitly frozen.
    fixture_hashes = fixture_inputs(fixture)
    inputs = fixture_hashes.copy()
    inputs[str(driver)] = driver_hash
    stdlib = Path(os.environ['GOOSE_STDLIB']).resolve() if os.environ.get('GOOSE_STDLIB') else next(
        p for p in (goose.parent/'stdlib', goose.parent.parent/'stdlib',
                    goose.parent.parent.parent/'stdlib') if p.is_dir())
    inputs.update({str(p): digest(p) for p in stdlib.rglob('*')
                   if p.is_file() and p.suffix in ('.goose', '.build', '.c', '.h')})
    inputs.update({str(p): digest(p) for p in [goose, cc, Path('/usr/bin/time'), *binaries.values()]})
    for tool in ('cmake', 'g++', 'ld', 'as'):
        path = shutil.which(tool)
        if path:
            inputs[path] = digest(path)
    cases = {'version': ['version'], 'metadata': ['metadata'],
             'test_literal': ['test', '--frozen', '--filter', 'tests/core.goose'],
             'test_recursive': ['test', '--frozen', '--filter', 'tests/**/core*.goose'],
             'bench_recursive': ['bench', '--frozen', '--filter', 'bench/**/process.goose', '--', 'tiny']}
    expected = {}
    os.sched_setaffinity(0, {args.cpu})
    for name, binary in binaries.items():
        for case, command in cases.items():
            result = call([binary, *command], cwd=fixture, env=env)
            observed = (result.stdout, result.stderr)
            if name == 'before':
                expected[case] = observed
            elif observed != expected[case]:
                raise SystemExit(f'Output differs for {case}')
    def verify():
        if fixture_inputs(fixture) != fixture_hashes or any(digest(path) != value for path, value in inputs.items()):
            raise SystemExit('Benchmark inputs changed')
    verify()
    samples = []
    report = {'revisions': revisions, 'driver_sha256': driver_hash,
              'args': {**vars(args), 'output': str(output)},
              'recorded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'commands': cases, 'inputs_sha256': inputs, 'platform': platform.platform(), 'python': sys.version,
              'cpuinfo': Path('/proc/cpuinfo').read_text(),
              'compiler': call([goose, 'version']).stdout,
              'cc': call([cc, '--version']).stdout,
              'environment': {key: os.environ.get(key) for key in
                              ('GOOSE_HOME', 'GOOSE_STDLIB', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'ASAN_OPTIONS',
                               'CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS',
                               'CPATH', 'LIBRARY_PATH', 'CMAKE_GENERATOR')},
              'expected_outputs': {case: {'stdout': out, 'stderr': err} for case, (out, err) in expected.items()},
              'samples': samples,
              'scope': 'Sequential randomized warm-cache invocations on one CPU on a shared host. '
                       'Includes process startup, validation, staging, compilation and target execution as applicable. '
                       'One untimed invocation of every binary/case checks exact output before timing. '
                       'GNU time max RSS is the largest reported process/descendant high-water mark, '
                       'not simultaneous aggregate memory. No cold-storage or network timing.'}
    rng = random.Random(20261107)
    tasks = [(name, case) for name in binaries for case in cases]
    for round_index in range(args.rounds):
        order = tasks.copy()
        rng.shuffle(order)
        for name, case in order:
            verify()
            rss_file = output/'rss.txt'
            start = time.perf_counter_ns()
            result = call(['/usr/bin/time', '-f', '%M', '-o', rss_file,
                           binaries[name], *cases[case]], cwd=fixture, env=env)
            elapsed = time.perf_counter_ns() - start
            if (result.stdout, result.stderr) != expected[case]:
                raise SystemExit(f'Output changed: {name} {case}')
            samples.append({'round': round_index, 'engine': name, 'case': case,
                            'elapsed_ns': elapsed, 'max_rss_kib': int(rss_file.read_text())})
            (output/'raw.partial.json').write_text(json.dumps(report, indent=2) + '\n')
            print(f'{round_index + 1}/{args.rounds} {name} {case}', flush=True)
    verify()
    summary = {}
    for case in cases:
        summary[case] = {}
        for name in binaries:
            subset = [s for s in samples if s['engine'] == name and s['case'] == case]
            summary[case][name] = {key: {'median': statistics.median(s[key] for s in subset),
                                       'min': min(s[key] for s in subset),
                                       'max': max(s[key] for s in subset)}
                                   for key in ('elapsed_ns', 'max_rss_kib')}
    report['summary'] = summary
    (output/'raw.json').write_text(json.dumps(report, indent=2) + '\n')
    (output/'raw.partial.json').unlink()
    print(output/'raw.json')


if __name__ == '__main__':
    main()

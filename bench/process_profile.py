#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Paired real caller workloads; retain every sample and verify frozen inputs."""
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
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--before', required=True)
parser.add_argument('--after', required=True)
parser.add_argument('--goose', required=True)
parser.add_argument('--before-revision', required=True)
parser.add_argument('--output', default='.build/process-profile.json')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
binaries = {key: Path(value).resolve() for key, value in [('before', args.before), ('after', args.after)]}
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def identity():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    paths = sorted(name for name in tracked if name and Path(name).suffix in {'.goose', '.c', '.h', '.build'})
    paths += ['bench/process_profile.py', 'scripts/sanitizer-cc.sh', 'scripts/process-fault-cc.sh', 'Makefile', 'GOOSE_REVISION']
    return {name: digest(root / name) for name in sorted(set(paths))}
source = identity()
binary_hashes = {key: digest(path) for key, path in binaries.items()}
goose = Path(args.goose).resolve()
compiler = Path(shutil.which('cc')).resolve()
report = dict(revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
              dirty=subprocess.run(['git', 'diff', '--quiet', 'HEAD'], cwd=root).returncode != 0,
              source_sha256=source, binaries_sha256=binary_hashes,
              before_requested_revision=args.before_revision, goose_sha256=digest(goose), cc_sha256=digest(compiler),
              goose_version=subprocess.check_output([str(goose), 'version'], text=True).strip(),
              cc_version=subprocess.check_output([str(compiler), '--version'], text=True).splitlines()[0],
              platform=platform.platform(), affinity=sorted(os.sched_getaffinity(0)),
              cpu_model=next(line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),
              seed=491, rounds=9, children_per_batch=200, samples=[])
report['method'] = 'Goose default optimized build/C backend -O2; matched argv/stdin/stderr/capture caps/no deadline. Different launch/ownership implementations, not a language ranking. Shared host; no exclusive isolation. Wall includes batch startup; CPU and maxRSS are wait4 reports for the batch and kernel-accounted waited children, not combined simultaneous memory or allocation counts.'
rng = random.Random(491)
with tempfile.TemporaryFile() as errors:
    null = os.open('/dev/null', os.O_WRONLY)
    try:
        def run(label, case):
            errors.seek(0); errors.truncate()
            start = time.perf_counter_ns()
            pid = os.posix_spawn(str(binaries[label]), [str(binaries[label]), case], dict(os.environ),
                file_actions=[(os.POSIX_SPAWN_DUP2, null, 1), (os.POSIX_SPAWN_DUP2, errors.fileno(), 2)])
            while True:
                try: _, status, usage = os.wait4(pid, 0); break
                except InterruptedError: pass
            wall = (time.perf_counter_ns() - start) / 1e6
            if os.waitstatus_to_exitcode(status) != 0:
                errors.seek(0); raise SystemExit(errors.read().decode(errors='replace'))
            return dict(wall_ms=wall, cpu_ms=(usage.ru_utime + usage.ru_stime) * 1000, max_rss_kib=usage.ru_maxrss)
        for label in binaries:
            for case in ['inherit', 'tiny', '64k']: run(label, case)
        for round_number in range(9):
            cases = ['inherit', 'tiny', '64k']; rng.shuffle(cases)
            for case in cases:
                order = list(binaries); rng.shuffle(order)
                for label in order:
                    report['samples'].append(dict(round=round_number, case=case, binary=label, **run(label, case)))
    finally: os.close(null)
if identity() != source or {key: digest(path) for key, path in binaries.items()} != binary_hashes:
    raise SystemExit('measurement inputs changed; refusing results')
if digest(goose) != report['goose_sha256'] or digest(compiler) != report['cc_sha256']:
    raise SystemExit('compiler identity changed; refusing results')
report['summary'] = {case: {label: {metric: dict(median=statistics.median(values), minimum=min(values), maximum=max(values))
    for metric in ['wall_ms', 'cpu_ms', 'max_rss_kib']
    for values in [[sample[metric] for sample in report['samples'] if sample['case'] == case and sample['binary'] == label]]}
    for label in binaries} for case in ['inherit', 'tiny', '64k']}
Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
print('Wrote ' + args.output)

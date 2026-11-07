#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Retain bounded discovery/verification/root-check samples; no speed comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--cc', default='gcc')
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()

def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True, timeout=90).strip()

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

sources = ['native/watch_tree.c', 'bench/recursive/driver.c', 'bench/recursive/measure.py']
def snapshot():
    return dict(commit=run('git', 'rev-parse', 'HEAD'), status=run('git', 'status', '--porcelain'),
                sources={x: sha(ROOT/x) for x in sources}, compiler=run(a.cc, '--version'))

before = snapshot()
assert not before['status'], 'retained qualification needs clean sources'
binary = ROOT/'.build/tree-bench'
run(a.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', 'bench/recursive/driver.c', '-o', str(binary))
binary_sha = sha(binary)
samples = []
for iteration in range(5):
    for count in (2, 16, 64, 256):
        with tempfile.TemporaryDirectory(prefix='tree-bench-') as raw:
            root = Path(raw)/'root'
            root.mkdir()
            for i in range(count-2):
                (root/f'd{i}').mkdir()
            actual, scan, verify, checks = map(int, run(str(binary), str(root)).split())
            assert actual == count
            samples.append(dict(round=iteration, identities=count, roots=1,
                                scan_open_ns=scan, verify_ns=verify, root_checks_ns=checks,
                                root_checks=1000))
assert before == snapshot() and sha(binary) == binary_sha
report = dict(**before, binary_sha256=binary_sha, platform=platform.platform(),
              affinity=sorted(os.sched_getaffinity(0)), flags='-O2', stable_inputs=True,
              samples=samples,
              limits='Shared-host shallow local trees; scanner/native validation only, no kernel watch registration, Goose/event dispatch or child time. No competitor or percentile claim. Root checks validate one short configured path1000times. Counts include root-parent sentinels.')
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(json.dumps(report, indent=2)+'\n')
print(a.output)

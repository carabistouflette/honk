#!/usr/bin/env python3
"""Reproducible CLI latency samples, with fixture creation outside timing."""
import json
import hashlib
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time

honk = os.environ['HONK']
goose = os.environ['GOOSE']
report = {'binary': Path(honk).name, 'binary_sha256': hashlib.sha256(Path(honk).read_bytes()).hexdigest(), 'platform': platform.platform(), 'compiler': subprocess.check_output([goose, 'version'], text=True).strip(),
          'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
          'dirty': subprocess.run(['git', 'diff', '--quiet', 'HEAD']).returncode != 0,
          'scope': '25 sequential warm local invocations; includes process startup; no network; no timing threshold', 'samples': {}}
cpuinfo = Path('/proc/cpuinfo')
report['cpu_model'] = next((line.split(':',1)[1].strip() for line in cpuinfo.read_text().splitlines() if line.startswith('model name')), platform.processor()) if cpuinfo.exists() else platform.processor()
report['build_method'] = 'make build: Goose default optimization and C backend default -O2; caller-supplied comparison binaries must use the same flags'
with tempfile.TemporaryDirectory(prefix='honk bench ') as directory:
    env = {**os.environ, 'GOOSE': goose, 'HONK_HOME': directory+'/cache'}
    def run(*args, cwd=directory):
        subprocess.run([honk, *args], cwd=cwd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    run('new', 'hello')
    project = directory+'/hello'
    run('build', cwd=project)
    for label, args in [('version', ['version']), ('metadata', ['metadata']), ('warm_check', ['check', '--frozen']), ('warm_build', ['build', '--frozen'])]:
        samples = []
        for _ in range(25):
            start = time.perf_counter_ns(); run(*args, cwd=project); samples.append((time.perf_counter_ns()-start)/1e6)
        report['samples'][label] = {'milliseconds': samples, 'median_ms': statistics.median(samples), 'p95_ms': sorted(samples)[23]}
Path('.build').mkdir(exist_ok=True)
Path('.build/bench.json').write_text(json.dumps(report, indent=2)+'\n')
print('Wrote raw samples and environment to .build/bench.json')

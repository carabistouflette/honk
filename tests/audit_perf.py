#!/usr/bin/env python3
"""Local audit workloads; compare identical fixtures/binaries, never timing gates."""
import json
import hashlib
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import tempfile
import time

honk = os.environ['HONK']
goose = os.environ['GOOSE']
report = {'binary': Path(honk).name, 'binary_sha256': hashlib.sha256(Path(honk).read_bytes()).hexdigest(), 'platform': platform.platform(), 'revision': subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(), 'compiler': subprocess.check_output([goose,'version'],text=True).strip(), 'dirty': subprocess.run(['git','diff','--quiet','HEAD']).returncode != 0, 'samples': {}}
baseline = os.environ.get('HONK_BASELINE')
if baseline:
    report['baseline'] = Path(baseline).name
    report['baseline_binary_sha256'] = hashlib.sha256(Path(baseline).read_bytes()).hexdigest()
    report['baseline_revision'] = os.environ.get('HONK_BASELINE_REVISION', 'unspecified')
cpuinfo = Path('/proc/cpuinfo')
report['cpu_model'] = next((line.split(':',1)[1].strip() for line in cpuinfo.read_text().splitlines() if line.startswith('model name')), platform.processor()) if cpuinfo.exists() else platform.processor()
report['build_method'] = 'make build: Goose default optimization and C backend default -O2; caller-supplied comparison binaries must use the same flags'
with tempfile.TemporaryDirectory(prefix='honk audit perf ', dir=os.environ.get('AUDIT_TEMP_ROOT')) as directory:
    root = Path(directory)
    report['filesystem'] = subprocess.check_output(['stat','-f','-c','%T',str(root)],text=True).strip()
    env = {**os.environ, 'GOOSE': goose, 'HONK_HOME': str(root/'cache')}
    def run(*args, cwd=root, binary=honk):
        subprocess.run([binary, *args], cwd=cwd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90)
    run('new', 'wide')
    wide = root/'wide'
    for i in range(1200):
        (wide/f'folder{i:04}').mkdir()
    run('check', cwd=wide)
    run('new', 'graph')
    graph = root/'graph'
    libs = root/'libs'; libs.mkdir()
    count = 120
    for i in range(count):
        dep = libs/f'p{i:03}'; dep.mkdir()
        imports = ''.join(f'import p{j:03} from "../p{j:03}";\n' for j in range(i+1, min(i+9, count)))
        (dep/f'p{i:03}.goose').write_text(imports+f'namespace p{i:03}; fn value() -> i64 {{ {i} }}\n')
    manifest = graph/'Honk.toml'
    manifest.write_text(manifest.read_text().replace('[dependencies]', '[dependencies]\np000 = { path = "../libs/p000" }'))
    run('new', 'dev_graph')
    dev_graph = root/'dev_graph'
    with (dev_graph/'Honk.toml').open('a') as stream: stream.write('p000 = { path = "../libs/p000" }\n')
    run('check', cwd=graph)
    run('new', 'assets')
    assets = root/'assets'; (assets/'data').mkdir()
    payload = random.Random(0x484F4E4B).randbytes(262144)
    for i in range(128): (assets/'data'/f'asset{i:03}.bin').write_bytes(payload)
    for name, cwd in [('wide_check', wide), ('dense_graph_check', graph), ('dense_dev_graph_check', dev_graph), ('asset_32mib_check', assets)]:
        binaries = {'after': honk}
        if baseline: binaries['before'] = baseline
        samples = {key: [] for key in binaries}
        for binary in binaries.values(): run('check', cwd=cwd, binary=binary)
        for round in range(int(os.environ.get('AUDIT_SAMPLES','9'))):
            order = list(binaries)
            if round % 2: order.reverse()
            for label in order:
                start = time.perf_counter_ns(); run('check', '--frozen', cwd=cwd, binary=binaries[label]); samples[label].append((time.perf_counter_ns()-start)/1e6)
        report['samples'][name] = {label: {'milliseconds': values, 'median_ms': statistics.median(values)} for label, values in samples.items()}
path = Path(os.environ.get('AUDIT_REPORT','.build/audit-perf.json'))
path.write_text(json.dumps(report, indent=2)+'\n')
print('Wrote '+str(path))

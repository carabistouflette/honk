#!/usr/bin/env python3
"""Local audit workloads; compare identical fixtures/binaries, never timing gates."""
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time

honk = os.environ['HONK']
goose = os.environ['GOOSE']
report = {'binary': honk, 'platform': platform.platform(), 'revision': subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(), 'compiler': subprocess.check_output([goose,'version'],text=True).strip(), 'dirty': subprocess.run(['git','diff','--quiet','HEAD']).returncode != 0, 'samples': {}}
baseline = os.environ.get('HONK_BASELINE')
if baseline:
    report['baseline'] = baseline
    report['baseline_revision'] = os.environ.get('HONK_BASELINE_REVISION', 'unspecified')
with tempfile.TemporaryDirectory(prefix='honk audit perf ') as directory:
    root = Path(directory)
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
    for name, cwd in [('wide_check', wide), ('dense_graph_check', graph), ('dense_dev_graph_check', dev_graph)]:
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

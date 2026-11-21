#!/usr/bin/env python3
"""Compare Honk and Cargo registry workflows on equivalent loopback graphs."""
import argparse
import gzip
import hashlib
import io
import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from registry_cli import Registry

APP = 'benchmark-app'
BASE = '1.0.0'
UPGRADE = '1.1.0'
PAYLOAD_BYTES = 4096


def graph(size):
    names = [f'pkg{i:03d}' for i in range(size)]
    edges = {name: names[i + 1:i + 3] for i, name in enumerate(names)}
    return names, dict(edges, **{APP: names[:2]})


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def archive(path, name, version, files):
    prefix = f'{name}-{version}'
    payload = random.Random(prefix).randbytes(PAYLOAD_BYTES)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for filename, data in sorted(dict(files, **{'payload.bin': payload}).items()):
            entry = tarfile.TarInfo(f'{prefix}/{filename}')
            entry.size, entry.mode = len(data), 0o644
            tar.addfile(entry, io.BytesIO(data))
    data = gzip.compress(stream.getvalue(), mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def goose_manifest(name, version, edges, url, revision=None):
    manifest = f'[package]\nname="{name}"\nversion="{version}"\nkind="lib"\nentry="lib.goose"\n'
    if revision:
        manifest += f'[toolchain]\nrevision="{revision}"\n'
    manifest += '[dependencies]\n'
    for dep in edges:
        manifest += f'{dep} = {{ version = "^1.0.0", registry = "{url}/index" }}\n'
    return manifest


def rust_manifest(name, version, edges):
    manifest = f'[package]\nname="{name}"\nversion="{version}"\nedition="2021"\n[dependencies]\n'
    for dep in edges:
        manifest += f'{dep} = {{ version = "^1.0.0", registry = "bench" }}\n'
    return manifest


def create_releases(server, names, edges, changed):
    records = {'honk': {}, 'cargo': {}}
    write(server.root / 'cargo-index/config.json', json.dumps({
        'dl': server.url + '/cargo-archives/{crate}-{version}.crate',
    }))
    for name in names:
        records['honk'][name], records['cargo'][name] = [], []
        for version in ((BASE, UPGRADE) if name in changed else (BASE,)):
            deps = edges[name]
            stem = f'{name}-{version}'
            filename = stem + '.tar.gz'
            digest = archive(server.root / filename, name, version, {
                'Honk.toml': goose_manifest(name, version, deps, server.url).encode(),
                'lib.goose': b'namespace payload; fn value() -> i64 { 42 }\n',
            })
            records['honk'][name].append(dict(version=version, url=server.url + '/' + filename,
                                               sha256=digest, entry='lib.goose', dependencies=[
                                                   dict(alias=dep, package=dep, version='^1.0.0') for dep in deps]))
            digest = archive(server.root / 'cargo-archives' / (stem + '.crate'), name, version, {
                'Cargo.toml': rust_manifest(name, version, deps).encode(),
                'src/lib.rs': b'pub fn value() -> i64 { 42 }\n',
            })
            records['cargo'][name].append(dict(name=name, vers=version, cksum=digest, features={}, yanked=False,
                                                deps=[dict(name=dep, req='^1.0.0', features=[], optional=False,
                                                           default_features=True, kind='normal', target=None,
                                                           registry=None) for dep in deps]))
    return records


def publish(server, records, names, upgraded=False):
    for name in names:
        server.index(name, records['honk'][name] if upgraded else records['honk'][name][:1])
        rows = records['cargo'][name] if upgraded else records['cargo'][name][:1]
        write(server.root / 'cargo-index' / name[:2] / name[2:4] / name,
              ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows))


def invocation(command, cwd, env, timer, rss_file):
    start = time.perf_counter_ns()
    result = subprocess.run([timer, '-f', '%M', '-o', str(rss_file), '--', *command],
                            cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
    elapsed_ms = (time.perf_counter_ns() - start) / 1e6
    if result.returncode:
        raise RuntimeError(f'{command} failed ({result.returncode})\n{result.stdout}{result.stderr}')
    return dict(wall_ms=elapsed_ms, peak_rss_kib=int(rss_file.read_text()))


def measure(commands, root, env, timer, server):
    steps = []
    for command in commands:
        before = len(server.requests)
        step = invocation(command, root, env, timer, root / 'rss.txt')
        requests = [path for path, _ in server.requests[before:]]
        step['archive_requests'] = sum(p.endswith(('.crate', '.tar.gz')) for p in requests)
        step['index_requests'] = len(requests) - step['archive_requests']
        steps.append(step)
    return dict(wall_ms=sum(s['wall_ms'] for s in steps),
                peak_rss_kib=max(s['peak_rss_kib'] for s in steps),
                index_requests=sum(s['index_requests'] for s in steps),
                archive_requests=sum(s['archive_requests'] for s in steps), steps=steps)


def check_lock(path, manager, edges, updated=None):
    doc = tomllib.loads(path.read_text())
    versions = {pkg['name']: pkg['version'] for pkg in doc['package']}
    expected = {name: (UPGRADE if name == updated else BASE) for name in edges}
    if versions != expected or len(doc['package']) != len(expected):
        raise ValueError(f'{manager} selected unexpected releases: {versions}')
    if manager == 'cargo':
        actual = {pkg['name']: sorted(pkg.get('dependencies', [])) for pkg in doc['package']}
    else:
        actual = {name: [] for name in edges}
        names = {pkg['directory']: pkg['name'] for pkg in doc['package']}
        for binding in doc['binding']:
            actual[names[binding['owner']]].append(names[binding['target']])
        actual = {name: sorted(deps) for name, deps in actual.items()}
    if actual != {name: sorted(deps) for name, deps in edges.items()}:
        raise ValueError(f'{manager} selected unexpected edges: {actual}')


def relocate_env(env, source, destination):
    return {key: (value.replace(str(source), str(destination), 1)
                  if key in {'CARGO_HOME', 'HONK_HOME', 'GOOSE_HOME'} else value)
            for key, value in env.items()}


def sample(args, manager, root, server, edges, target, env, revision, publish_update, reset_index):
    project = root / "project"
    project.mkdir(parents=True)
    bench_env = env.copy()
    if manager == 'honk':
        write(project / 'Honk.toml', goose_manifest(APP, BASE, edges[APP], server.url, revision))
        write(project / 'lib.goose', 'namespace benchmark; fn value() -> i64 { 42 }\n')
        bench_env.update(HONK_HOME=str(root / 'cache'), GOOSE_HOME=str(root / 'goose-home'))
        fetch = [args.honk, 'fetch', '--isolated']
        update = [args.honk, 'update', '--isolated', '--dependency', target]
        apply = [update]
        cold_resolve = [args.honk, 'update', '--isolated', '--dry-run']
        lock_name = 'Honk.lock'
    else:
        write(project / 'Cargo.toml', rust_manifest(APP, BASE, edges[APP]))
        write(project / 'src/lib.rs', 'pub fn value() -> i64 { 42 }\n')
        write(root / 'cache/config.toml', f'[registries.bench]\nindex = "sparse+{server.url}/cargo-index/"\n')
        bench_env['CARGO_HOME'] = str(root / 'cache')
        fetch = [args.cargo, 'fetch']
        update = [args.cargo, 'update', '-p', target]
        apply = [update, [*fetch, '--locked']]
        cold_resolve = [args.cargo, 'generate-lockfile']
        lock_name = 'Cargo.lock'

    cold_root = root.with_name(root.name + '-resolve')
    shutil.copytree(root, cold_root)
    cold_env = relocate_env(bench_env, root, cold_root)
    lock = project / lock_name
    cold = measure([fetch], project, bench_env, args.time, server)
    check_lock(lock, manager, edges)
    if cold['archive_requests'] != len(edges) - 1:
        raise ValueError(f'{manager} cold fetch did not download the expected archives: {cold}')
    initial_lock = lock.read_bytes()
    warm = measure([[*fetch, '--frozen']], project, bench_env, args.time, server)
    if warm['index_requests'] or warm['archive_requests'] or lock.read_bytes() != initial_lock:
        raise ValueError(f'{manager} frozen fetch accessed the registry or changed the lock')

    preview_root = root.with_name(root.name + '-preview')
    shutil.copytree(root, preview_root)
    preview_env = relocate_env(bench_env, root, preview_root)
    publish_update()
    preview = measure([[*update, '--dry-run']], preview_root / "project", preview_env, args.time, server)
    if preview['archive_requests'] or (preview_root / "project" / lock_name).read_bytes() != initial_lock:
        raise ValueError(f'{manager} preview acquired archives or changed the lock')
    updated = measure(apply, project, bench_env, args.time, server)
    check_lock(lock, manager, edges, updated=target)
    if updated['archive_requests'] != 1:
        raise ValueError(f'{manager} targeted update did not download exactly one archive: {updated}')
    reset_index()
    resolve = measure([cold_resolve], cold_root / 'project', cold_env, args.time, server)
    cold_lock = cold_root / 'project' / lock_name
    if resolve['archive_requests']:
        raise ValueError(f'{manager} cold resolution acquired archives')
    if manager == 'cargo':
        check_lock(cold_lock, manager, edges)
    elif cold_lock.exists():
        raise ValueError('Honk cold preview wrote a lock')
    return dict(cold_resolve=resolve, cold_fetch=cold, frozen_fetch=warm,
                update_preview=preview, update_and_fetch=updated)


def summarize(samples):
    return {manager: {case: {key: statistics.median(run[case][key] for run in runs)
                             for key in ('wall_ms', 'peak_rss_kib', 'index_requests', 'archive_requests')}
                      for case in runs[0]} for manager, runs in samples.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('honk', 'goose', 'cargo', 'rustc'):
        parser.add_argument('--' + option, required=True, type=lambda path: str(Path(path).resolve(strict=True)))
    parser.add_argument('--time', default='/usr/bin/time', help='GNU time executable')
    parser.add_argument('--honk-revision', required=True, help='Git revision used to build the Honk executable')
    parser.add_argument('--sizes', nargs='+', type=int, default=[24, 96])
    parser.add_argument('--rounds', type=int, default=7)
    parser.add_argument('--temp-root', type=Path, default=Path(tempfile.gettempdir()))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1 or any(not 4 <= size <= 120 for size in args.sizes):
        parser.error('require positive rounds and graph sizes from 4 through 120')
    args.temp_root = args.temp_root.resolve(strict=True)
    goose = json.loads(subprocess.check_output([args.goose, 'version', '--json']))
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('CARGO_', 'RUST', 'GOOSE_', 'HONK_'))}
    env.update(GOOSE=args.goose, RUSTC=args.rustc, NO_PROXY='localhost,127.0.0.1',
               no_proxy='localhost,127.0.0.1', LC_ALL='C')
    cpu = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                if line.startswith('model name')), 'unknown')
    filesystem = subprocess.check_output(['stat', '-f', '-c', '%T', str(args.temp_root)], text=True).strip()
    report = dict(platform=platform.platform(), cpu=cpu, cpu_count=os.cpu_count(), filesystem=filesystem,
                  affinity=sorted(os.sched_getaffinity(0)), temp_root=str(args.temp_root.resolve()),
                  cargo=subprocess.check_output([args.cargo, '--version'], text=True).strip(),
                  rustc=subprocess.check_output([args.rustc, '--version'], text=True).strip(),
                  goose=goose, honk_revision=args.honk_revision,
                  honk_sha256=hashlib.sha256(Path(args.honk).read_bytes()).hexdigest(),
                  rounds=args.rounds, payload_bytes=PAYLOAD_BYTES, sizes={})
    for size in args.sizes:
        names, edges = graph(size)
        target, unrelated = names[size // 2], names[-1]
        changed = (target, unrelated)
        samples = {'honk': [], 'cargo': []}
        with tempfile.TemporaryDirectory(prefix='honk-cargo-', dir=args.temp_root) as temp:
            directory = Path(temp)
            with closing(Registry(directory / 'registry')) as server:
                records = create_releases(server, names, edges, changed)
                publish(server, records, names)
                for round_number in range(args.rounds + 1):
                    for manager in (('honk', 'cargo') if round_number % 2 else ('cargo', 'honk')):
                        publish(server, records, changed)
                        result = sample(args, manager, directory / f'{manager}-{round_number}', server,
                                        edges, target, env, goose['compiler_revision'],
                                        lambda: publish(server, records, changed, upgraded=True),
                                        lambda: publish(server, records, changed))
                        if round_number:
                            samples[manager].append(result)
        report['sizes'][str(size)] = dict(edges=sum(map(len, edges.values())), samples=samples,
                                          median=summarize(samples))
        print(f'Completed {size} packages × {args.rounds} measured rounds', flush=True)
    write(args.output, json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()

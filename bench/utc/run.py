#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Paired real Honk diagnostics paths with benchmark-only native sink capture."""
import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import random
import re
import shutil
import stat
import statistics
import struct
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
STAGES = ('no_log', 'off', 'filtered', 'accepted_fixed', 'accepted_os', 'file')
EVENTS = ('started', 'item_completed', 'returned', 'failed', 'child_failed')
SEED = 650343


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command(args, *, cwd=ROOT, env=None, cpu=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env, capture_output=True,
                            text=True, timeout=240,
                            preexec_fn=(lambda: os.sched_setaffinity(0, {cpu})) if cpu is not None else None)
    if result.returncode:
        raise RuntimeError(f'command failed ({result.returncode}): {args}\n{result.stdout}\n{result.stderr}')
    return result.stdout.strip()


def source_hashes(root):
    result = {}
    skipped = {'.git', '.build', '.toolchain', '__pycache__', 'target'}
    for directory, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders if name not in skipped)
        for name in sorted(files):
            path = Path(directory)/name
            if (path.suffix in ('.goose', '.c', '.h', '.build') or name in
                    ('GOOSE_REVISION', 'Honk.toml', 'Honk.lock', 'manifest.json', 'CMakeLists.txt') or
                    path.parent == root/'bench/utc'):
                result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def compiler_hashes(goose):
    root = goose.parents[1]
    paths = [p for folder in ('stdlib', 'src/runtime') for p in (root/folder).rglob('*') if p.is_file()]
    return dict(binary=digest(goose.read_bytes()), sources={p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(paths)})


def timestamp(ns):
    seconds, fraction = divmod(ns, 1_000_000_000)
    value = dt.datetime(1970, 1, 1) + dt.timedelta(seconds=seconds)
    text = f'{value.year:04}-{value.month:02}-{value.day:02}T{value.hour:02}:{value.minute:02}:{value.second:02}'
    if fraction:
        text += f'.{fraction:09}'.rstrip('0')
    return (text+'Z').encode('ascii')


def line(item, sample=None):
    event, duration, outcome, _ = item
    prefix = b'[ERROR] ' if event in (3, 4) else b'[INFO] '
    if sample is not None:
        prefix += b'timestamp="'+timestamp(sample)+b'" '
    return prefix + f'{EVENTS[event]} duration_ns={duration} outcome={outcome}\n'.encode('ascii')


def checksum(data):
    return len(data) + sum((i+1)*byte for i, byte in enumerate(data))


def fixture():
    rng = random.Random(SEED)
    samples = [-(1<<63), -1, 0, 1, 951827696123400000, 1793813400123456789, (1<<63)-1, -1000000001]
    items = [(i % 5, 0 if i == 0 else (1<<64)-1 if i == 1 else rng.getrandbits(64),
              (1<<32)-1 if i == 1 else rng.getrandbits(32), sample) for i, sample in enumerate(samples)]
    return b''.join(struct.pack('<B Q I q', *item) for item in items), items


def verify(row, variant, stage, items, count, warmup, capture, trace):
    fields = {'elapsed_ns','iterations','successful','clocks','sinks','bytes','checksum'}
    if set(row) != fields or row['elapsed_ns'] <= 0 or row['iterations'] != count or row['successful'] != count:
        raise ValueError('incomplete/invalid benchmark result')
    accepted = stage >= 3
    wanted_clocks = count if variant == 'candidate' and accepted else 0
    wanted_sinks = count if accepted else 0
    if row['clocks'] != wanted_clocks or row['sinks'] != wanted_sinks:
        raise ValueError('incorrect clock or sink invocation count')
    expected_trace_len = (count+warmup)*8 if wanted_clocks else 0
    if len(trace) != expected_trace_len:
        raise ValueError('incomplete or unexpected clock trace')
    samples = [x[0] for x in struct.iter_unpack('<q', trace)]
    expected_output = bytearray()
    byte_count = wanted_checksum = 0
    for offset, iterations in ((0, warmup), (warmup, count)):
        if not accepted:
            continue
        for i in range(iterations):
            item = items[i % len(items)]
            sample = samples[offset+i] if variant == 'candidate' else None
            if variant == 'candidate' and stage == 3 and sample != item[3]:
                raise ValueError('fixed clock changed sample')
            output = line(item, sample)
            expected_output.extend(output)
            if offset == warmup:
                byte_count += len(output)
                wanted_checksum += checksum(output)
    if capture != expected_output:
        raise ValueError('independent complete output-byte mismatch')
    if row['bytes'] != byte_count or row['checksum'] != wanted_checksum:
        raise ValueError('independent all-byte checksum/count mismatch')


def generate_driver(source, target, variant):
    template = (ROOT/'bench/utc/driver.goose').read_text()
    template = re.sub(r'^import \w+ from .*;\n', '', template, flags=re.MULTILINE)
    mappings = re.findall(r'^import (\w+) from "(\./vendor/[^"\n]+)";', (source/'honk.goose').read_text(), flags=re.MULTILINE)
    imports = ''.join(f'import {name} from {json.dumps(str((source/path).resolve()))};\n' for name, path in mappings)
    imports += f'import honk from {json.dumps(str(source))};\n'
    if variant == 'baseline':
        start = template.index('// BEGIN_WRITE')
        end = template.index('// END_WRITE', start)
        template = template[:start] + '''fn actual_write(event: diagnostics::Event, duration: u64, outcome: u32) -> bool {
    diagnostics::write(event, duration, outcome)
}
''' + template[end:]
        # Unused benchmark clock helper is deliberately absent in the old entrypoint.
        start = template.index('fn sampled_clock()')
        end = template.index('// END_WRITE', start)
        actual = template[template.index('fn actual_write', start):end]
        template = template[:start] + actual + template[end:]
    target.write_text(imports + template)


def match_native_manifest(baseline, candidate):
    """Allow only the reviewed additive scanner; flags/exclusions stay matched."""
    if candidate == baseline:
        return 'identical'
    old = b'c_sources = ["native/platform.c", "native/log_sink.c"];'
    new = b'c_sources = ["native/platform.c", "native/log_sink.c", "native/watch_tree.c"];'
    if baseline.count(old) == 1 and candidate == baseline.replace(old, new, 1):
        return 'additive-watch-tree'
    raise ValueError('baseline differs in required matched input: honk.build')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', default=os.environ.get('GOOSE', str(ROOT/'.toolchain/goose/build/goose')))
    parser.add_argument('--baseline', default='65d4e97')
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--iterations', type=int, default=100000)
    parser.add_argument('--rounds', type=int, default=7)
    parser.add_argument('--warmup', type=int, default=64)
    parser.add_argument('--include-file', action='store_true')
    parser.add_argument('--file-iterations', type=int, default=1000)
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--build-cpu', type=int)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--allow-dirty', action='store_true')
    parser.add_argument('--retain-traces', action='store_true')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != 'Linux':
        parser.error('this benchmark uses Linux linker wrapping and affinity')
    if not 1 <= args.iterations <= 1000000 or not 1 <= args.rounds <= 25 or not 1 <= args.file_iterations <= 10000 or not 0 <= args.warmup <= 1024:
        parser.error('iterations 1..1000000, rounds 1..25, file iterations 1..10000 and warmup 0..1024 required')
    if args.smoke:
        args.iterations = min(args.iterations, 32)
        args.file_iterations = min(args.file_iterations, 16)
        args.rounds = min(args.rounds, 2)
        args.warmup = min(args.warmup, 8)
    output = args.output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error('output directory must be absent or empty; evidence is never overwritten')
    cpus = sorted(os.sched_getaffinity(0))
    cpu = cpus[0] if args.cpu is None else args.cpu
    build_cpu = cpus[-1] if args.build_cpu is None else args.build_cpu
    if cpu not in cpus or build_cpu not in cpus:
        parser.error('requested CPUs must be in the available affinity mask')
    source = command(['git','rev-parse','HEAD'])
    dirty = command(['git','status','--porcelain'])
    if dirty and not (args.smoke or args.allow_dirty):
        parser.error('commit source first, or explicitly select --allow-dirty for exploration')
    goose = Path(shutil.which(args.goose) or args.goose).resolve()
    pin = (ROOT/'GOOSE_REVISION').read_text().strip()
    version = command([goose,'version'])
    match = re.search(r'\bgoose ([0-9a-f]{7,40})\b', version)
    if not match or not pin.startswith(match[1]) or command(['git','-C',goose.parents[1],'rev-parse','HEAD']) != pin:
        parser.error('compiler checkout/executable advertised revision must match GOOSE_REVISION')
    baseline = command(['git','rev-parse', args.baseline+'^{commit}'])
    output.mkdir(parents=True, exist_ok=True)
    build_base = ROOT/'.build/utc'
    build_base.mkdir(parents=True, exist_ok=True)
    build = Path(tempfile.mkdtemp(prefix='capture-', dir=build_base))
    export = build/'baseline'; export.mkdir()
    archive = subprocess.check_output(['git','archive',baseline],cwd=ROOT,timeout=60)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(export, filter='data')
    for name in ('GOOSE_REVISION','native/log_sink.c','vendor/goose-log/logger.goose'):
        if (ROOT/name).read_bytes() != (export/name).read_bytes():
            parser.error(f'baseline differs in required matched input: {name}')
    try:
        manifest_basis = match_native_manifest((export/'honk.build').read_bytes(), (ROOT/'honk.build').read_bytes())
    except ValueError as error:
        parser.error(str(error))
    native_manifest = dict(basis=manifest_basis,
        baseline_sha256=digest((export/'honk.build').read_bytes()),
        candidate_sha256=digest((ROOT/'honk.build').read_bytes()),
        additional_sources=({'native/watch_tree.c': digest((ROOT/'native/watch_tree.c').read_bytes())}
                            if manifest_basis == 'additive-watch-tree' else {}),
        scope=('The additive scanner is linked only in the candidate and is not invoked by diagnostics stages; this is not a matched whole-binary comparison.'
               if manifest_basis == 'additive-watch-tree' else 'Native manifests are byte-identical.'))
    before = source_hashes(ROOT)
    compiler_before = compiler_hashes(goose)
    env = os.environ.copy()
    cleared = ('GOOSE_CC','GOOSE_STDLIB','CFLAGS','CXXFLAGS','CPPFLAGS','LDFLAGS')
    for name in cleared:
        env.pop(name, None)
    env.update(GOOSE_HOME=str(build/'cache'), LC_ALL='C')
    shim = build/'capture.o'
    command([args.cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-fPIC','-c',ROOT/'bench/utc/capture.c','-o',shim],cpu=build_cpu)
    cc = shutil.which(args.cc)
    if cc is None:
        parser.error('C compiler not found')
    wrapper = build/'cc'
    wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\n'+f'cc={cc!r}\nshim={str(shim)!r}\n'+
        'args=sys.argv[1:]\nprobe=any(x in args for x in ("--version","-v","-dumpversion","-dumpmachine"))\n'+
        'link=not probe and not any(x in args for x in ("-c","-S","-E"))\n'+
        'extra=[shim,"-Wl,--wrap=goose_cli_log_append"] if link else []\n'+
        'os.execv(cc,[cc,*([] if probe else ["-O2"]),*args,*extra])\n')
    wrapper.chmod(0o755)
    executables = {}; generated = {}
    for variant, directory in (('baseline', export), ('candidate', ROOT)):
        entry = build/(variant+'.goose'); executable = build/variant
        if variant == 'baseline':
            executable = build/'old-executable'
        generate_driver(directory, entry, variant)
        command([goose,'build',entry,'--cc',wrapper,'-O2','--standalone','-o',executable],env=env,cpu=build_cpu)
        executables[variant] = executable
        generated[variant] = digest(entry.read_bytes())
    metadata = dict(schema=1, created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        source_commit=source, source_dirty=bool(dirty), source_status=dirty, source_hashes=before,
        baseline_commit=baseline, baseline_tree=command(['git','rev-parse',baseline+'^{tree}']),
        native_manifest_match=native_manifest,
        baseline_archive_sha256=digest(archive), baseline_source_hashes=source_hashes(export),
        compiler_revision=pin, compiler_version=version, compiler_hashes=compiler_before,
        cc=args.cc, cc_version=command([args.cc,'--version']), platform=platform.platform(),
        machine=platform.machine(), python=platform.python_version(), available_cpus=cpus,
        cpu_model=next((x.split(':',1)[1].strip() for x in Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')), 'unknown'),
        measurement_cpu=cpu, build_cpu=build_cpu, cleared_environment=list(cleared),
        flags=['-O2','--standalone','-Wl,--wrap=goose_cli_log_append'],
        shim_sha256=digest(shim.read_bytes()), wrapper_sha256=digest(wrapper.read_bytes()),
        generated_driver_sha256=generated,
        executable_sha256={v:digest(p.read_bytes()) for v,p in executables.items()},
        iterations=args.iterations, file_iterations=args.file_iterations, rounds=args.rounds,
        warmup=args.warmup, seed=SEED, smoke=args.smoke, include_file=args.include_file,
        retain_traces=args.retain_traces or args.smoke, validation='pending',
        limitations=['Instrumented production diagnostics paths; native capture copies/checksums every output byte.',
          'Candidate Clock callback stores each sample and increments counters. Baseline has no clock callback.',
          'No core/library speed ranking or exact decomposition; candidate emits more bytes and performs UTC work.',
          'Shared host, uncontrolled CPU frequency/turbo/thermal state; affinity does not reserve a CPU.',
          'Without --retain-traces, all captured bytes/samples are checked before discarding; hashes and batch counters remain.'])
    def save():
        (output/'metadata.json').write_text(json.dumps(metadata,indent=2,sort_keys=True)+'\n')
    save()
    data, items = fixture()
    fixture_path=output/'fixture.bin'; fixture_path.write_bytes(data)
    metadata['fixture_sha256']=digest(data)
    (output/'traces').mkdir()
    rows=[]; rng=random.Random(SEED)
    stages=range(6 if args.include_file else 5)
    try:
        with (output/'rounds.jsonl').open('x') as raw:
            for round_index in range(args.rounds):
                jobs=[(v,s) for v in executables for s in stages];rng.shuffle(jobs)
                for variant,stage in jobs:
                    count=args.file_iterations if stage==5 else args.iterations
                    with tempfile.TemporaryDirectory(prefix='sample-',dir=build) as temporary:
                        folder=Path(temporary);destination=folder/'log';capture_path=folder/'capture.bin';trace_path=folder/'clock.bin'
                        sentinel=b'preserved-prefix\n'
                        if stage==5:
                            destination.write_bytes(sentinel);destination.chmod(0o600)
                            original=destination.stat()
                        stdout=command([executables[variant],stage,fixture_path,count,args.warmup,destination,capture_path,trace_path,0],env=env,cpu=cpu)
                        row=json.loads(stdout);capture=capture_path.read_bytes();trace=trace_path.read_bytes()
                        verify(row,variant,stage,items,count,args.warmup,capture,trace)
                        if stage==5:
                            after=destination.stat()
                            if destination.read_bytes()!=sentinel+capture or stat.S_IMODE(after.st_mode)!=0o600 or after.st_uid!=os.getuid() or after.st_nlink!=1 or (after.st_dev,after.st_ino)!=(original.st_dev,original.st_ino):
                                raise ValueError('real native file output/identity/policy mismatch')
                        elif destination.exists():
                            raise ValueError('non-file stage touched the destination')
                        row.update(round=round_index,variant=variant,stage=STAGES[stage],
                            ns_per_call=row['elapsed_ns']/count,capture_sha256=digest(capture),trace_sha256=digest(trace))
                        if metadata['retain_traces']:
                            for name,content in (('capture',capture),('clock',trace)):
                                relative=f'traces/{round_index}-{variant}-{STAGES[stage]}-{name}.gz'
                                (output/relative).write_bytes(gzip.compress(content,mtime=0))
                                row[name+'_file']=relative
                        rows.append(row);raw.write(json.dumps(row,sort_keys=True)+'\n');raw.flush()
        if source_hashes(ROOT)!=before or compiler_hashes(goose)!=compiler_before or any(digest(p.read_bytes())!=metadata['executable_sha256'][v] for v,p in executables.items()):
            raise ValueError('measured source/compiler/executable changed during measurement')
        metadata['validation']='passed'
    except BaseException as error:
        metadata['validation']='failed';metadata['failure']=str(error)
        raise
    finally:
        save()
    summary={}
    for variant in executables:
        summary[variant]={}
        for stage in stages:
            values=[x['ns_per_call'] for x in rows if x['variant']==variant and x['stage']==STAGES[stage]]
            summary[variant][STAGES[stage]]=dict(median_ns_per_call=statistics.median(values),min_ns_per_call=min(values),max_ns_per_call=max(values))
    (output/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(f'{len(rows)} independently validated paired stage samples retained in {output}')


if __name__=='__main__':
    main()

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Diagnose a warmed workspace using numeric probes in a disposable Honk copy."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import resource
import select
import signal
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PROBE = re.compile(rb'\[HONK-PHASE-1\] ([a-z_]+)=([0-9]+)\n')
SKIP = {'.git', '.honk', '.build', '.toolchain', 'target', '__pycache__'}


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def fingerprint(directory):
    result = {}
    for path in directory.rglob('*'):
        name = path.relative_to(directory)
        if any(part in SKIP for part in name.parts):
            continue
        if path.is_symlink():
            raise RuntimeError('workspace input symlink: '+str(name))
        if path.is_file():
            result[name.as_posix()] = digest(path)
    return result


def instrument(directory):
    changes = {}

    def patch(file, old, new):
        path = directory/file
        source = path.read_text()
        if source.count(old) != 1:
            raise RuntimeError('unsupported instrumentation seam: '+file+' '+old[:60])
        changes.setdefault(file, {'original_sha256': digest(path)})
        path.write_text(source.replace(old, new, 1))
        changes[file]['instrumented_sha256'] = digest(path)

    def event(name, variable):
        return 'write_stderr(str("[HONK-PHASE-1] '+name+'=", clock_ns() - '+variable+', "\\n"));'

    patch('src/commands.goose', 'deps::resolve(p, graph);',
          'let hp_resolve = clock_ns(); deps::resolve(p, graph); '+event('resolve_ns', 'hp_resolve'))
    patch('src/commands.goose', '    let compiler = toolchain::compiler(p, cache, offline);\n    if options.has("bin")',
          '    let hp_identity = clock_ns(); let compiler = toolchain::compiler(p, cache, offline); '+event('compiler_identity_ns', 'hp_identity')+'\n    if options.has("bin")')
    patch('src/build.goose', '    let stage = prepare(p, g); let profile =',
          '    let hp_prepare = clock_ns(); let stage = prepare(p, g); '+event('prepare_ns', 'hp_prepare')+' let profile =')
    patch('src/build.goose', '    let entry = root_entry(stage, p.entry, g);',
          '    let hp_entry = clock_ns(); let entry = root_entry(stage, p.entry, g); '+event('entry_ns', 'hp_entry'))
    patch('src/build.goose', '    var captured: u8[>..] = []; let code = platform::spawn(packed, root, true, captured);',
          '    let hp_compile = clock_ns(); var captured: u8[>..] = []; let code = platform::spawn(packed, root, true, captured); '+event('compile_ns', 'hp_compile'))
    patch('src/build.goose', '    platform::require(platform::install(temporary, output, true), "cannot atomically publish executable");',
          '    let hp_publish = clock_ns(); platform::require(platform::install(temporary, output, true), "cannot atomically publish executable"); '+event('publish_ns', 'hp_publish'))
    patch('src/build.goose', '        let argv: const u8[:][] = [compiler, "check", entry, "--offline"]; platform::run(argv, p.root);',
          '        let argv: const u8[:][] = [compiler, "check", entry, "--offline"]; let hp_check = clock_ns(); platform::run(argv, p.root); '+event('check_ns', 'hp_check'))
    patch('src/build.goose', '        var captured: u8[>..] = []; let status = platform::spawn(packed, p.root, false, captured); if status != 0 { platform::child_exit(status); }\n    }',
          '        let hp_run = clock_ns(); var captured: u8[>..] = []; let status = platform::spawn(packed, p.root, false, captured); '+event('run_ns', 'hp_run')+' if status != 0 { platform::child_exit(status); }\n    }')
    return changes


def execute(argv, cwd, env, work, label):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter_ns()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        descriptor = None
        try:
            descriptor = os.pidfd_open(child.pid)
            waiter = select.poll()
            waiter.register(descriptor, select.POLLIN)
            if not any(mask & select.POLLIN for _, mask in waiter.poll(120000)):
                raise RuntimeError(label+': timeout or invalid pidfd event')
            child.wait()
        finally:
            try:
                if child.returncode is None:
                    # The unreaped leader reserves the private group. No other reaper.
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=5)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        wall = (time.perf_counter_ns()-start)/1e6
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(1048577), err.read(1048577)
    record = {'label': label, 'wall_ms': wall,
              'cpu_ms': ((after.ru_utime-before.ru_utime)+(after.ru_stime-before.ru_stime))*1000,
              'exit': child.returncode, 'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
              'stderr_sha256': hashlib.sha256(stderr).hexdigest()}
    with (work/'events.jsonl').open('a') as events:
        events.write(json.dumps(record)+'\n')
    if child.returncode or max(len(stdout), len(stderr)) > 1048576:
        raise RuntimeError(label+': failed or controller log cap exceeded\n'+stderr[:4096].decode(errors='replace'))
    return record, stdout, stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True, help='full immutable Honk source commit')
    parser.add_argument('--baseline', required=True, type=Path, help='plain binary for output equality; not a timed comparator')
    parser.add_argument('--goose', required=True, type=Path)
    parser.add_argument('--goose-home', required=True, type=Path)
    parser.add_argument('--honk-home', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path, help='already warmed bench/workspace fixture')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.revision) or not 1 <= args.rounds <= 9:
        parser.error('require a full commit and 1..9 diagnostic rounds')
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error('output must be new')
    for name in ['baseline', 'goose', 'goose_home', 'honk_home', 'workspace']:
        setattr(args, name, getattr(args, name).resolve(strict=True))
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    (ROOT/'.build').mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='phase-probe-', dir=ROOT/'.build'))
    print('Retaining diagnostic work at '+str(work), flush=True)
    source = work/'source'
    blobs = {}
    for row in git('ls-tree', '-r', '-z', args.revision).split(b'\0'):
        if not row:
            continue
        meta, name = row.split(b'\t')
        mode, kind, oid = meta.decode().split()
        if kind != 'blob' or mode not in {'100644', '100755'}:
            raise RuntimeError('source must contain only regular files')
        relative = name.decode()
        path = source/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(git('cat-file', 'blob', oid))
        path.chmod(0o755 if mode == '100755' else 0o644)
        blobs[relative] = oid
    changes = instrument(source)
    tools = {'baseline': args.baseline, 'compiler': args.goose}
    for name, command in [('git', 'git'), ('cc', os.environ.get('GOOSE_CC', 'cc'))]:
        executable = shutil.which(command)
        if not executable:
            raise RuntimeError('missing tool: '+name)
        tools[name] = Path(executable).resolve()
    binaries = {name: digest(path) for name, path in tools.items()}
    instrumented_sources = fingerprint(source)
    inputs = fingerprint(args.workspace)
    harness = digest(Path(__file__))
    env = {**os.environ, 'GOOSE': str(args.goose), 'GOOSE_HOME': str(args.goose_home), 'HONK_HOME': str(args.honk_home)}
    executable = work/'honk-phase'
    execute([str(args.goose), 'build', str(source/'honk.goose'), '-o', str(executable)], ROOT, env, work, 'build_probe')
    tools['instrumented'] = executable
    binaries['instrumented'] = digest(executable)
    cases = {'tree': ['tree', '--workspace', '--frozen'],
             'check': ['check', '--workspace', '--frozen'],
             'build': ['build', '-p', 'version_gate', '--frozen'],
             'run': ['run', '-p', 'version_gate', '--frozen', '--', '^1.2.3', '1.8.0']}
    expected = {}
    for name, argv in cases.items():
        _, expected[name], stderr = execute([str(args.baseline), *argv], args.workspace, env, work, 'baseline_'+name)
        if stderr:
            raise RuntimeError('plain baseline emitted stderr')
        execute([str(executable), *argv], args.workspace, env, work, 'warmup_'+name)
    samples = []
    rng = random.Random(20261105)
    started = datetime.now(timezone.utc).isoformat()
    for round_number in range(args.rounds):
        order = list(cases)
        rng.shuffle(order)
        for name in order:
            record, stdout, stderr = execute([str(executable), *cases[name]], args.workspace, env, work, name)
            matches = list(PROBE.finditer(stderr))
            if stdout != expected[name] or b''.join(match.group() for match in matches) != stderr:
                raise RuntimeError('probe changed stdout or emitted unknown diagnostics')
            phases = {}
            for match in matches:
                phases.setdefault(match[1].decode(), []).append(int(match[2])/1e6)
            required = {'resolve_ns'} | ({'compiler_identity_ns', 'prepare_ns', 'entry_ns', 'check_ns'} if name == 'check' else
                       {'compiler_identity_ns', 'prepare_ns', 'entry_ns', 'compile_ns', 'publish_ns'} if name in {'build', 'run'} else set())
            if name == 'run':
                required.add('run_ns')
            count = 2 if name in {'tree', 'check'} else 1
            if set(phases) != required or any(len(values) != count for values in phases.values()):
                raise RuntimeError('unexpected phase names or workspace cardinality')
            record.update(case=name, round=round_number, phases_ms=phases)
            samples.append(record)
            print(name, round_number, phases, flush=True)
    if inputs != fingerprint(args.workspace) or instrumented_sources != fingerprint(source) or harness != digest(Path(__file__)) or any(
            binaries[key] != digest(path) for key, path in tools.items()):
        raise RuntimeError('measurement inputs changed')
    report = {'source_revision': args.revision, 'source_git_blobs': blobs, 'changes': changes,
              'binary_sha256': binaries, 'compiler_revision': (source/'GOOSE_REVISION').read_text().strip(),
              'harness_sha256': harness, 'workspace_sha256': inputs, 'instrumented_sources_sha256': instrumented_sources,
              'started_utc': started, 'finished_utc': datetime.now(timezone.utc).isoformat(),
              'platform': platform.platform(), 'affinity': sorted(os.sched_getaffinity(0)),
              'scope': 'Temporary instrumented copy, numeric stderr probes and altered source/build path. Diagnostic phase attribution only; baseline validates stdout, not a latency comparison. Shared host, warm fixture; no network tracing or RSS measurement.',
              'seed': 20261105, 'samples': samples}
    with args.output.open('x') as output:
        output.write(json.dumps(report, indent=2)+'\n')
    print('Wrote '+str(args.output))


if __name__ == '__main__':
    main()

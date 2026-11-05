#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real HTTPS Git/path workspace exercise; retain each timing, no threshold."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import resource
import select
import sys
import shutil
import signal
import statistics
import subprocess
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
RELEASE = '855fb0552aefd5f0c033826af64f3bdd09ae6482'
SEMVER = '2311ae69a7edacb545f284b02e345be07dd2fb05'
ORIGIN = 'https://github.com/carabistouflette/goose-semver.git'
PIN = (ROOT/'GOOSE_REVISION').read_text().strip()
def execute(label, argv, cwd, expected=0, output=None, error=None, timeout=120):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter_ns()
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        timed_out = None
        descriptor = None
        try:
            # An exited leader is still owned and unreaped during pidfd_open.
            # Poll avoids wait(timeout)'s sleep granularity in latency samples.
            descriptor = os.pidfd_open(child.pid)
            waiter = select.poll(); waiter.register(descriptor, select.POLLIN)
            events = waiter.poll(max(1, int(timeout*1000)))
            if not events:
                raise subprocess.TimeoutExpired(argv, timeout)
            if not any(mask & select.POLLIN for _, mask in events):
                raise RuntimeError(label+': unexpected pidfd event')
            child.wait()
        except subprocess.TimeoutExpired as failure:
            timed_out = failure
        finally:
            try:
                if child.returncode is None:
                    # No reaper or concurrent wait: the unreaped leader reserves
                    # its private group. Kill before reading regular-file logs.
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    child.wait(timeout=5)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        wall = (time.perf_counter_ns()-started)/1e6
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        stdout.seek(0); stderr.seek(0)
        out = stdout.read(1048577); err = stderr.read(1048577)
    record = {'label': label, 'started_utc': started_utc, 'wall_ms': wall,
              'cpu_ms': ((after.ru_utime-before.ru_utime)+(after.ru_stime-before.ru_stime))*1000,
              'exit': child.returncode, 'expected_exit': expected,
              'git_recording_wrapper': env.get('HONK_DOGFOOD_WRAPPER_ACTIVE') == '1',
              'timed_out': timed_out is not None, 'log_cap_exceeded': len(out) > 1048576 or len(err) > 1048576,
              'stdout_sha256': hashlib.sha256(out).hexdigest(),
              'stderr_sha256': hashlib.sha256(err).hexdigest()}
    operations.append(record)
    with (work/'events.jsonl').open('a') as events:
        events.write(json.dumps(record)+'\n')
    if record['log_cap_exceeded']:
        raise RuntimeError(label+': controller log cap exceeded')
    if timed_out is not None:
        raise RuntimeError(label+': timed out; private group terminated\n'+(out+err).decode(errors='replace')) from timed_out
    if child.returncode != expected:
        raise RuntimeError(label+': unexpected exit '+str(child.returncode)+'\n'+(out+err).decode(errors='replace'))
    if output is not None and out != output:
        raise RuntimeError(label+': unexpected stdout '+repr(out))
    if error is not None and error not in err:
        raise RuntimeError(label+': missing expected diagnostic '+repr(err))
    if any(x in err for x in [b'AddressSanitizer', b'LeakSanitizer', b'runtime error:']):
        raise RuntimeError(label+': sanitizer report')
    print(label, 'PASS', flush=True)
    return record


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--materialize', type=Path, help='create the usable workspace in a new directory; no build or network')
parser.add_argument('--self-test', action='store_true', help='check real child status, timeout cleanup and descriptor ownership; no network')
parser.add_argument('--honk-source', type=Path)
parser.add_argument('--goose', type=Path)
parser.add_argument('--goose-source', type=Path)
parser.add_argument('--output', type=Path)
parser.add_argument('--smoke', action='store_true', help='one functional round; allow dirty harness source')
parser.add_argument('--rounds', type=int, default=9)
args = parser.parse_args()
fixture = ROOT/'bench/workspace'

if args.self_test:
    if any([args.materialize, args.honk_source, args.goose, args.goose_source, args.output, args.smoke]):
        parser.error('self-test takes no measurement options')
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    env = dict(os.environ); operations = []
    before = len(list(Path('/proc/self/fd').iterdir()))
    with tempfile.TemporaryDirectory(prefix='honk-controller-') as directory:
        work = Path(directory)
        execute('controller_success', [sys.executable, '-c', 'print("ready")'], work, output=b'ready\n')
        execute('controller_exit', [sys.executable, '-c', 'raise SystemExit(7)'], work, expected=7, output=b'')
        try:
            execute('controller_timeout', [sys.executable, '-c', 'import time; time.sleep(30)'], work, timeout=.05)
        except RuntimeError as failure:
            if not isinstance(failure.__cause__, subprocess.TimeoutExpired):
                raise
        else:
            raise SystemExit('controller timeout did not fail')
    try: os.waitpid(-1, os.WNOHANG)
    except ChildProcessError: pass
    else: raise SystemExit('controller retained an unwaited child')
    after = len(list(Path('/proc/self/fd').iterdir()))
    if before != after:
        raise SystemExit('controller descriptor count changed')
    print(json.dumps({'controller_self_test': 'PASS', 'fd_before': before, 'fd_after': after,
                      'success_exit_status': True, 'timeout_cleanup': True, 'unwaited_children': False}))
    raise SystemExit(0)

def materialize(destination):
    shutil.copytree(fixture, destination, ignore=shutil.ignore_patterns('.honk', 'target', '.toolchain', '__pycache__'))
    for template in destination.rglob('*.goose.in'):
        template.rename(template.with_suffix(''))

if args.materialize is not None:
    if args.materialize.exists() or any([args.honk_source, args.goose, args.goose_source, args.output, args.smoke]):
        parser.error('materialize requires a new directory and no measurement options')
    materialize(args.materialize)
    print(args.materialize)
    raise SystemExit(0)
if not all([args.honk_source, args.goose, args.goose_source, args.output]):
    parser.error('measurement requires honk-source, goose, goose-source and output')
if args.output.exists() or not 1 <= args.rounds <= 99:
    raise SystemExit('use a new output path and 1..99 rounds')
args.honk_source = args.honk_source.resolve()
args.goose = args.goose.resolve()
args.goose_source = args.goose_source.resolve()

def git(directory, *argv):
    return subprocess.check_output(['git', '-C', str(directory), *argv], env=env)

env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0')
# This serial controller requires real wait status, including when invoked
# from a parent that ignores SIGCHLD.
signal.signal(signal.SIGCHLD, signal.SIG_DFL)
revision = git(ROOT, 'rev-parse', 'HEAD').decode().strip()
initial_status = git(ROOT, 'status', '--porcelain')
dirty = bool(initial_status.strip())
if dirty and not args.smoke:
    raise SystemExit('commit the harness/fixture before measuring')
if git(args.honk_source, 'rev-parse', 'HEAD').decode().strip() != RELEASE or git(args.honk_source, 'status', '--porcelain').strip():
    raise SystemExit('Honk source must be a clean checkout of the frozen release')
if git(args.goose_source, 'rev-parse', 'HEAD').decode().strip() != PIN or git(args.goose_source, 'status', '--porcelain').strip():
    raise SystemExit('Goose source must be clean at the compiler pin')
inputs = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in fixture.rglob('*') if p.is_file() and not any(x in {'.honk', 'target', '.toolchain'} for x in p.relative_to(fixture).parts)}
inputs['bench/dogfood.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(ROOT/'.build').mkdir(exist_ok=True)
work = Path(tempfile.mkdtemp(prefix='workspace-dogfood-', dir=ROOT/'.build'))
(ROOT/'.build/dogfood-last-path').write_text(str(work)+'\n')
workspace = work/'workspace'
materialize(workspace)
for p in workspace.rglob('Honk.lock'):
    p.unlink()  # First resolution is deliberately unlocked, outside warm sampling.
tools = work/'tools'; tools.mkdir()
original_path = env.get('PATH', '')
real_git = shutil.which('git', path=original_path)
if not real_git:
    raise SystemExit('Git unavailable')
git_hash = hashlib.sha256(Path(real_git).read_bytes()).hexdigest()
(tools/'git').write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['HONK_DOGFOOD_GIT_LOG'], 'a') as f:
    f.write(json.dumps(sys.argv[1:])+'\\n')
real = os.environ['HONK_DOGFOOD_REAL_GIT']
os.execve(real, [real, *sys.argv[1:]], os.environ)
''')
(tools/'git').chmod(0o755)
cache = work/'cache'; gitlog = work/'git.jsonl'
env.update(GOOSE=str(args.goose), GOOSE_HOME=str(work/'goose-home'), HONK_HOME=str(cache),
           PATH=str(tools)+os.pathsep+original_path, HONK_DOGFOOD_WRAPPER_ACTIVE='1',
           HONK_DOGFOOD_GIT_LOG=str(gitlog), HONK_DOGFOOD_REAL_GIT=real_git)
compiler_hash = hashlib.sha256(args.goose.read_bytes()).hexdigest()
(work/'inputs.json').write_text(json.dumps({'harness_revision': revision, 'harness_dirty': dirty,
    'inputs_sha256': inputs, 'release': RELEASE, 'compiler_revision': PIN,
    'compiler_binary_sha256': compiler_hash, 'git_binary_sha256': git_hash}, indent=2)+'\n')
operations = []

execute('build_released_honk', ['make', 'GOOSE='+str(args.goose), 'build'], args.honk_source)
honk = args.honk_source/'.build/honk'
binary_hash = hashlib.sha256(honk.read_bytes()).hexdigest()
execute('release_identity', [str(honk), 'version'], work, output=b'honk 0.2.0\n')

def call(label, *argv, expected=0, output=None, error=None):
    return execute(label, [str(honk), *argv], workspace, expected, output, error)

def gate_output(value):
    return ('built '+str(workspace/'gate/target/debug/version_gate')+'\n').encode()+value

@contextmanager
def direct_git():
    previous = env['PATH'], env['HONK_DOGFOOD_WRAPPER_ACTIVE']
    env['PATH'] = original_path; env['HONK_DOGFOOD_WRAPPER_ACTIVE'] = '0'
    try:
        if shutil.which('git', path=env['PATH']) != real_git:
            raise RuntimeError('timed Git identity differs')
        yield
    finally:
        env['PATH'], env['HONK_DOGFOOD_WRAPPER_ACTIVE'] = previous

def network():
    rows = [json.loads(x) for x in gitlog.read_text().splitlines()] if gitlog.exists() else []
    return [x for x in rows if 'fetch' in x or 'ls-remote' in x]

cold_fetch = call('cold_unlocked_fetch', 'fetch', '--workspace')
with direct_git():
    cold_check = call('first_workspace_check', 'check', '--workspace', '--frozen')
    cold_build = call('first_gate_build', 'build', '-p', 'version_gate', '--frozen')
locks = {workspace/name: (workspace/name).read_bytes()
         for name in ['gate/Honk.lock', 'gate/vendor/rules/Honk.lock']}
if len(locks) != 2 or any(SEMVER.encode() not in data for data in locks.values()):
    raise RuntimeError('expected both locks to retain the exact SemVer commit')
if any(data != (fixture/p.relative_to(workspace)).read_bytes() for p, data in locks.items()):
    raise RuntimeError('shipped locks do not match the generated graph')
call('workspace_tests', 'test', '--workspace', '--frozen')
for label, request, version, status, out in [
    ('match', '^1.2.3', '1.8.0', 0, b'match\n'),
    ('no_match', '^1.2.3', '2.0.0', 1, b'no match\n'),
    ('invalid_requirement', '1.2', '1.2.3', 2, b'invalid requirement\n'),
    ('invalid_version', '*', 'v1.2.3', 2, b'invalid version\n')]:
    call('cli_'+label, 'run', '-p', 'version_gate', '--frozen', '--', request, version, expected=status, output=gate_output(out))
before = len(network())
call('offline_run', 'run', '-p', 'version_gate', '--offline', '--', '^1.2.3', '1.8.0', output=gate_output(b'match\n'))
cases = {'check': ['check', '--workspace', '--frozen'],
         'build': ['build', '-p', 'version_gate', '--frozen'],
         'run': ['run', '-p', 'version_gate', '--frozen', '--', '^1.2.3', '1.8.0'],
         'tree': ['tree', '--workspace', '--frozen']}
warm = []; rng = random.Random(20261105)
for name in cases:
    call('instrumented_'+name, *cases[name], output=gate_output(b'match\n') if name == 'run' else None)
if len(network()) != before or any(p.read_bytes() != data for p, data in locks.items()):
    raise RuntimeError('instrumented warm preflight changed network/lock state')
# Timed warm calls use original PATH/direct Git. The equivalent instrumented
# preflight above checks discovery/fetch absence before those frozen calls.
measurement_start = datetime.now(timezone.utc).isoformat()
with direct_git():
    for round_number in range(1 if args.smoke else args.rounds):
        order = list(cases); rng.shuffle(order)
        for name in order:
            sample = call('warm_'+str(round_number)+'_'+name, *cases[name], output=gate_output(b'match\n') if name == 'run' else None)
            warm.append({**sample, 'round': round_number, 'case': name})
measurement_end = datetime.now(timezone.utc).isoformat()
if len(network()) != before or any(p.read_bytes() != data for p, data in locks.items()):
    raise RuntimeError('warm/offline operation performed network work or changed a lock')
update = call('online_update', 'update', '--workspace')
if any(p.read_bytes() != data for p, data in locks.items()):
    raise RuntimeError('exact-revision update changed lock identity')
for folder in ['sources', 'git']:
    shutil.rmtree(cache/folder)
before = len(network())
for mode in ['--frozen', '--offline']:
    call('cold_cache_'+mode[2:], 'fetch', '--workspace', mode, expected=1,
         output=b'', error=b'dependency not cached: semver')
    if len(network()) != before or any(p.read_bytes() != data for p, data in locks.items()):
        raise RuntimeError('cold offline/frozen performed network work or changed a lock')
rehydrate = call('cold_locked_rehydrate', 'fetch', '--workspace', '--locked')
for argv in network()[before:]:
    if 'fetch' not in argv or argv[argv.index('--')+1:] != [ORIGIN, SEMVER]:
        raise RuntimeError('locked recovery did not fetch the exact locked OID')
if len(network()) == before:
    raise RuntimeError('cold online recovery did not fetch')
call('rehydrated_frozen_run', 'run', '-p', 'version_gate', '--frozen', '--', '^1.2.3', '1.8.0', output=gate_output(b'match\n'))
execute('track_workspace', [real_git, '-c', 'core.hooksPath=/dev/null', 'init', '-q'], workspace)
execute('track_sources_and_locks', [real_git, 'add', '.'], workspace)
call('workspace_package', 'package', '--workspace', '--frozen')
archives = {}
for path in workspace.rglob('target/package/*.tar.gz'):
    package_root = path.parents[2]
    with tarfile.open(path) as archive:
        exported = {}
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile():
                raise RuntimeError('unexpected package entry type')
            name = member.name.split('/', 1)[1]
            if name in exported:
                raise RuntimeError('duplicate package entry')
            exported[name] = archive.extractfile(member).read()
    tracked = {p.decode() for p in git(package_root, 'ls-files', '-z').split(b'\0') if p}
    if set(exported) != tracked:
        raise RuntimeError('exported package file set differs from tracked source')
    for name, data in exported.items():
        if data != (package_root/name).read_bytes() or any(x in {'.git', '.honk', 'target', '.build'} for x in Path(name).parts):
            raise RuntimeError('packaged source mismatch/generated state')
    archives[path.relative_to(workspace).as_posix()] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'files': len(exported)}
if len(archives) != 2 or any(p.read_bytes() != data for p, data in locks.items()):
    raise RuntimeError('package set/lock mismatch')
if hashlib.sha256(honk.read_bytes()).hexdigest() != binary_hash or hashlib.sha256(args.goose.read_bytes()).hexdigest() != compiler_hash:
    raise RuntimeError('measured executable changed')
if hashlib.sha256(Path(real_git).read_bytes()).hexdigest() != git_hash:
    raise RuntimeError('Git executable changed')
if git(args.honk_source, 'status', '--porcelain').strip() or git(args.goose_source, 'status', '--porcelain').strip():
    raise RuntimeError('build source changed')
if git(args.honk_source, 'rev-parse', 'HEAD').decode().strip() != RELEASE or git(args.goose_source, 'rev-parse', 'HEAD').decode().strip() != PIN:
    raise RuntimeError('build revision changed')
if git(ROOT, 'rev-parse', 'HEAD').decode().strip() != revision or git(ROOT, 'status', '--porcelain') != initial_status:
    raise RuntimeError('harness checkout changed')
for name, digest in inputs.items():
    if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
        raise RuntimeError('fixture/harness changed during execution')
summary = {}
for name in cases:
    rows = [x for x in warm if x['case'] == name]
    summary[name] = {unit: {'median': statistics.median(x[unit] for x in rows),
                            'min': min(x[unit] for x in rows), 'max': max(x[unit] for x in rows)}
                     for unit in ['wall_ms', 'cpu_ms']}
report = {'scope': 'functional smoke; timings not final' if args.smoke else 'one shared-host workspace series; cold dependency/target state, OS page cache uncontrolled; no superiority or regression claim',
          'harness_revision': revision, 'harness_dirty': dirty, 'inputs_sha256': inputs,
          'release': RELEASE, 'honk_binary_sha256': binary_hash, 'compiler_revision': PIN,
          'compiler_binary_sha256': compiler_hash, 'compiler_reported_version': subprocess.check_output([str(args.goose), 'version'], env=env).decode().strip(),
          'git_binary_sha256': git_hash, 'git_version': subprocess.check_output([real_git, '--version'], env=env).decode().strip(),
          'application_binary_sha256': hashlib.sha256((workspace/'gate/target/debug/version_gate').read_bytes()).hexdigest(),
          'platform': platform.platform(), 'cpu_affinity': sorted(os.sched_getaffinity(0)),
          'cpu_model': next((x.split(':', 1)[1].strip() for x in Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')), 'unknown'),
          'method': 'Readable .goose.in templates materialized as an isolated workspace. Honk rebuilt from clean release source before measurement; default make build. Applications use Honk default debug build. Functional/network phases use a record-only Git wrapper with real GitHub HTTPS. First check/build and timed warm calls use original PATH/direct Git. Cold network timings include wrapper startup and network variability. pidfd exit notification avoids controller wait polling. CPU is waited child/descendant user+system usage; RSS not measured.',
          'rounds': 1 if args.smoke else args.rounds, 'shuffle_seed': 20261105,
          'warm_started_utc': measurement_start, 'warm_completed_utc': measurement_end,
          'cold': [cold_fetch, cold_check, cold_build, update, rehydrate], 'warm': warm,
          'operations': operations, 'summary': summary,
          'git_network_commands': [[a.replace(str(work), '$WORK') for a in row] for row in network()],
          'locks': {p.relative_to(workspace).as_posix(): hashlib.sha256(data).hexdigest() for p, data in locks.items()},
          'packages': archives, 'lock_unchanged': True, 'warm_offline_git_discovery_fetch_absent': True,
          'cold_offline_frozen_git_discovery_fetch_absent': True, 'locked_recovery_exact_oid': True,
          'timed_warm_git_wrapper': False, 'warm_network_proof': 'equivalent instrumented frozen preflight; timed calls retain frozen/offline policy but are not network traced',
          'proxy_environment_present': any(k.lower() in ['http_proxy', 'https_proxy', 'all_proxy'] for k in env)}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2)+'\n')
print('PASS; report:', args.output, flush=True)

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Disposable pinned real-suite watch qualification with retained partial evidence."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import struct
import subprocess
import tarfile
import time
from process_observer import ProcessObserver, execute
from observer_calibration import calibrate

ROOT = Path(__file__).resolve().parents[1]
WORKLOADS = {
    'diff': ('129dc794b62ad987784db0a1d52ef618c85fccf4', 'diff.goose', 'tests/core.goose'),
    'json': ('fcee7b75658a5708756dc163127b70df656996a4', 'json_codec.goose', 'tests/codec.goose'),
}
EVENT = re.compile(rb'\[(INFO|ERROR)\] timestamp="[^"]+" (started|item_completed|returned|failed|child_failed) duration_ns=([0-9]+) outcome=([0-9]+)\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2)+'\n')
    tmp.replace(path)


def git(repo, *argv):
    return subprocess.check_output(['git', '-C', str(repo), *argv], timeout=30)


def canonical(data, project):
    # Strip only the single selected target's boundary presentation lines.
    built = b'built '+os.fsencode(project/'target/debug/.honk/tests/0')+b'\n'
    if data.startswith(built): data = data[len(built):]
    passed = b'Passed 1 test targets\n'
    if not data.endswith(passed):
        raise RuntimeError('missing exact successful-target summary')
    return data[:-len(passed)]


def terminals(data):
    """Classify complete serial command intervals; a partial append is not an event."""
    data = data[:data.rfind(b'\n')+1]
    matches = list(EVENT.finditer(data))
    if b''.join(m.group() for m in matches) != data:
        raise RuntimeError('unrecognized lifecycle bytes')
    rows, active = [], False
    for m in matches:
        kind, code = m[2].decode(), int(m[4])
        if kind == 'started':
            if active:
                raise RuntimeError('overlapping lifecycle intervals')
            active = True
        elif kind in ('returned', 'failed', 'child_failed'):
            if not active:
                raise RuntimeError('terminal without command start')
            rows.append(dict(kind=kind, code=code))
            active = False
        elif not active:
            raise RuntimeError('item outside command interval')
    return rows


class Session:
    def __init__(self, binary, project, env, folder, suite, sampled, extra_roots=(), trace_bytes=64*1024*1024):
        folder.mkdir()
        self.folder, self.project = folder, project
        self.proc = self.pidfd = self.observer = self.identity = None
        self.out = self.err = None
        self.closed = False
        self.next_sample = 0
        self.stdout_offset = 0
        self.observed_starts = 0
        self.deadline = time.monotonic()+1800
        self.record = dict(complete=False, sampled=sampled, actions=[], checkpoints=[], commands=[],
                           poll_interval_ms=10, started_ns=time.monotonic_ns())
        try:
            self.out = (folder/'stdout').open('wb'); self.err = (folder/'stderr').open('wb')
            argv = [str(binary), 'watch', 'test', '--offline', '--filter', suite, '--watch-recursive',
                    '--watch-debounce-ms', '50', '--watch-dir', str(project), '--log-file', str(folder/'events.log')]
            for extra in extra_roots: argv += ['--watch-dir', str(extra)]
            self.record['argv'] = argv
            self.proc = subprocess.Popen(argv, cwd=project, env=env, stdin=subprocess.DEVNULL,
                                         stdout=self.out, stderr=self.err, start_new_session=True)
            self.identity = ProcessObserver.identity(self.proc.pid)
            if self.identity is None:
                raise RuntimeError('supervisor disappeared at startup')
            self.pidfd = os.pidfd_open(self.proc.pid)
            self.record['identity'] = self.identity
            if sampled:
                self.observer = ProcessObserver(self.proc.pid, folder/'processes.jsonl.gz', [project/'target/debug/.honk/tests/0'], max_bytes=trace_bytes)
            self.persist()
        except BaseException:
            self.close()
            raise

    def persist(self):
        save(self.folder/'session.json', self.record)

    def action(self, kind, **fields):
        row = dict(kind=kind, at_ns=time.monotonic_ns(), **fields)
        self.record['actions'].append(row); self.persist()
        return row

    def outcomes(self):
        p = self.folder/'events.log'
        return terminals(p.read_bytes()) if p.exists() else []

    def pump(self):
        if time.monotonic() > self.deadline:
            raise RuntimeError('overall session deadline exceeded')
        starts=(self.folder/'stderr').read_bytes().count(b'running command')
        while self.observed_starts < starts:
            self.observed_starts += 1
            self.record['actions'].append(dict(kind='observed-command-start',index=self.observed_starts,at_ns=time.monotonic_ns()))
        for name in ('stdout', 'stderr', 'events.log'):
            p = self.folder/name
            if p.exists() and p.stat().st_size > 4*1024*1024:
                raise RuntimeError('log byte budget exceeded')
        now = time.monotonic_ns()
        if self.observer and now >= self.next_sample:
            self.observer.snapshot(); self.next_sample = now+20_000_000

    def wait(self, predicate, timeout=90):
        end = time.monotonic()+timeout
        while not predicate():
            self.pump()
            if self.exited():
                raise RuntimeError(f'early exit {self.proc.returncode}: {self.folder}')
            if time.monotonic() > end:
                raise RuntimeError('session handshake deadline exceeded')
            time.sleep(.01)
        self.pump()
        return time.monotonic_ns()

    def idle(self, count, expected, stdout):
        self.wait(lambda: len(self.outcomes()) >= count and
                  (self.folder/'stderr').read_bytes().count(b'command finished; waiting') >= count)
        rows = self.outcomes()
        if len(rows) != count or rows[-1]['code'] != expected:
            raise RuntimeError(f'unexpected completions: {rows}')
        data = (self.folder/'stdout').read_bytes()
        segment = data[self.stdout_offset:]; self.stdout_offset = len(data)
        if expected == 0 and canonical(segment,self.project) != stdout:
            raise RuntimeError('per-command canonical suite output mismatch')
        self.record['commands'].append(dict(index=count, observed_terminal_ns=time.monotonic_ns(),
                                            outcome=rows[-1], stdout_sha256=hashlib.sha256(segment).hexdigest()))
        self.persist()

    def checkpoint(self, label):
        before = ProcessObserver.identity(self.proc.pid)
        if before is None or before['start'] != self.identity['start']:
            raise RuntimeError('supervisor identity changed')
        text = Path(f'/proc/{self.proc.pid}/stat').read_text(); fields = text[text.rfind(')')+2:].split()
        status = Path(f'/proc/{self.proc.pid}/status').read_text()
        fds = {p.name: os.readlink(p) for p in Path(f'/proc/{self.proc.pid}/fd').iterdir()}
        anchors=[]
        for number,target in fds.items():
            stat=Path(f'/proc/{self.proc.pid}/fd/{number}').stat()
            watches=[]
            for line in Path(f'/proc/{self.proc.pid}/fdinfo/{number}').read_text().splitlines():
                if line.startswith('inotify '):
                    parts=dict(x.split(':',1) for x in line.split()[1:] if ':' in x)
                    watches.append([parts.get(x) for x in ('ino','sdev','mask')])
            anchors.append(dict(target=target,dev=stat.st_dev,inode=stat.st_ino,mode=stat.st_mode,watches=sorted(watches)))
        after = ProcessObserver.identity(self.proc.pid)
        if after is None or after['start'] != before['start']:
            raise RuntimeError('checkpoint identity changed')
        row = dict(label=label, at_ns=time.monotonic_ns(), cpu_ticks=int(fields[11])+int(fields[12]),
                   rss_kib=int(re.search(r'^VmRSS:\s+(\d+)', status, re.M)[1]), fds=fds, fd_anchors=anchors)
        self.record['checkpoints'].append(row); self.persist()
        return row

    def pause(self, seconds):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            self.pump()
            if self.exited():
                raise RuntimeError('supervisor died during idle interval')
            time.sleep(.02)

    def exited(self):
        # Keep the leader unreaped so its PID still anchors our private group.
        if self.proc.returncode is not None:
            return True
        return os.waitid(os.P_PID, self.proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None

    def group_members(self):
        anchor = ProcessObserver.identity(self.proc.pid)
        if not anchor or not self.identity or anchor['start'] != self.identity['start']:
            raise RuntimeError('private process group lost its identity anchor')
        members = []
        for path in Path('/proc').iterdir():
            if path.name.isdecimal() and int(path.name) != self.proc.pid:
                item = ProcessObserver.identity(int(path.name))
                if item and item['group'] == self.proc.pid and item['session'] == self.proc.pid:
                    members.append(item)
        return members

    def finish(self, expected=143, send=True):
        if send and not self.exited():
            self.action('signal', number=signal.SIGTERM)
            signal.pidfd_send_signal(self.pidfd, signal.SIGTERM)
        end = time.monotonic()+30
        while not self.exited() and time.monotonic() < end:
            self.pump(); time.sleep(.01)
        if not self.exited():
            raise RuntimeError('cooperative cleanup deadline exceeded')
        if self.group_members():
            raise RuntimeError('owned process group remains after supervisor exit')
        self.proc.wait(timeout=1)
        if self.proc.returncode != expected:
            raise RuntimeError(f'exit {self.proc.returncode}, wanted {expected}')
        self.record.update(complete=True, exit_code=self.proc.returncode, ended_ns=time.monotonic_ns())
        self.close()

    def close(self):
        if self.closed:
            return
        try:
            if self.proc and self.proc.returncode is None:
                if not self.exited():
                    if self.pidfd is not None:
                        signal.pidfd_send_signal(self.pidfd, signal.SIGCONT)
                        signal.pidfd_send_signal(self.pidfd, signal.SIGTERM)
                    else:
                        self.proc.terminate()
                    end = time.monotonic()+30
                    while not self.exited() and time.monotonic() < end:
                        time.sleep(.02)
                anchor = ProcessObserver.identity(self.proc.pid)
                if anchor and self.identity and anchor['start'] == self.identity['start']:
                    if not self.exited() or self.group_members():
                        os.killpg(self.proc.pid, signal.SIGKILL)
                        self.record['forced_cleanup'] = True
                else:
                    # start_new_session plus the unreaped Popen child reserves
                    # this group even if /proc identity acquisition failed.
                    if os.getpgid(self.proc.pid)!=self.proc.pid or os.getsid(self.proc.pid)!=self.proc.pid:
                        raise RuntimeError('startup private group identity mismatch')
                    os.killpg(self.proc.pid, signal.SIGKILL)
                    self.record['forced_cleanup'] = True
                self.proc.wait(timeout=10)
            if self.observer:
                self.record['observation'] = self.observer.close()
            if self.proc:
                self.record['exit_code'] = self.proc.returncode
            self.persist()
        finally:
            if self.out: self.out.close()
            if self.err: self.err.close()
            if self.pidfd is not None: os.close(self.pidfd)
            self.closed = True


def mutation(session, path, data, kind):
    tmp = path.with_name(path.name+'.watch-temporary'); tmp.write_bytes(data); tmp.chmod(path.stat().st_mode & 0o777); tmp.replace(path)
    completed=time.monotonic_ns()
    return session.action(kind, completed_ns=completed, path=str(path.relative_to(session.project)),
                          sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


def stop_case(binary, project, env, folder, suite, expected, kind, active=False):
    extra=folder.with_name(folder.name+'-empty')
    if kind=='delete':extra.mkdir()
    session=Session(binary,project,env,folder,suite,False,extra_roots=[extra] if kind=='delete' else ())
    moved=project.with_name(project.name+'-moved')
    try:
        session.idle(1,0,expected)
        if active:
            entry=next(project.glob('*.goose'))
            original=entry.read_bytes();mutation(session,entry,original+b'\n// active-stop\n','active-stop-edit')
            session.wait(lambda:len(session.record['actions'])>0 and
                         (session.folder/'stderr').read_bytes().count(b'running command')>=2 and
                         bool(Path(f'/proc/{session.proc.pid}/task/{session.proc.pid}/children').read_text().strip()))
            session.action('active-command-observed')
        if kind=='aba':project.rename(moved);moved.rename(project);session.action('root-aba')
        elif kind=='delete':extra.rmdir();session.action('root-delete')
        elif kind=='sigint':signal.pidfd_send_signal(session.pidfd,signal.SIGINT);session.action('sigint')
        session.finish(130 if kind=='sigint' else 125,send=False)
    finally:
        session.close()
        if moved.exists() and not project.exists():moved.rename(project)
        if active and 'original' in locals():entry.write_bytes(original)
        if extra.exists():extra.rmdir()


def overflow_case(binary, project, env, folder, suite, expected):
    queue=int(Path('/proc/sys/fs/inotify/max_queued_events').read_text())
    if queue>32768:return dict(result='inconclusive',reason='queue exceeds capped stimulus',queue_limit=queue)
    nested=project/'watch-overflow';nested.mkdir()
    for i in range(4):(nested/f'event{i}.o').write_bytes(b'0')
    record=folder.with_suffix('.overflow')
    session=Session(binary,project,{**env,'WATCH_OVERFLOW_RECORD':str(record)},folder,suite,False)
    try:
        session.idle(1,0,expected)
        if Path(f'/proc/{session.proc.pid}/task/{session.proc.pid}/children').read_text().strip():
            raise RuntimeError('overflow injection requires child-free idle supervisor')
        signal.pidfd_send_signal(session.pidfd,signal.SIGSTOP)
        try:
            session.wait(lambda: ProcessObserver.identity(session.proc.pid)['state'] in ('T','t'),timeout=5)
            began=time.monotonic();done=0
            for i in range(queue*2+32):
                if time.monotonic()-began>10:break
                (nested/f'event{i%4}.o').write_bytes(bytes([i%251]));done+=1
            session.action('real-kernel-overflow-attempt',operations=done,queue_limit=queue,files=4,bytes_per_file=1)
        finally:signal.pidfd_send_signal(session.pidfd,signal.SIGCONT)
        # Only the observer's actual IN_Q_OVERFLOW record establishes delivery.
        deadline=time.monotonic()+10
        while not record.exists() and time.monotonic()<deadline:
            session.pause(.05)
        if not record.exists():
            session.finish();return dict(result='inconclusive',reason='no direct overflow record',queue_limit=queue)
        data=record.read_bytes()
        if not data or len(data)%32:raise RuntimeError('incomplete native overflow record')
        records=list(struct.iter_unpack('=qqqq',data))
        if any(mask!=16384 or origin!=-1 for _,_,mask,origin in records):raise RuntimeError('invalid recorded overflow')
        session.idle(2,0,expected)
        mutation(session,nested/'event0.o',b'x','ignored-after-recovery')
        probe=nested/'changed.goose';probe.write_text('// coverage after loss\n')
        session.action('source-after-overflow');session.idle(3,0,expected)
        session.finish()
        return dict(result='observed-recovery',queue_limit=queue,native_records=records,record_sha256=sha(record))
    finally:
        session.close()
        for path in nested.iterdir():path.unlink()
        nested.rmdir()


def fd_roles(checkpoint):
    if 'fd_anchors' in checkpoint:
        return sorted(json.dumps(x,sort_keys=True) for x in checkpoint['fd_anchors'])
    return sorted(value for value in checkpoint['fds'].values())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('honk', 'goose', 'diff-repo', 'json-repo', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--cycles', type=int, default=30); p.add_argument('--idle-seconds', type=float, default=60)
    p.add_argument('--smoke', action='store_true')
    p.add_argument('--project',choices=tuple(WORKLOADS),action='append',help='selected projects; default both')
    p.add_argument('--mode',choices=('timing','resources'),action='append',help='selected measurement modes; default both')
    p.add_argument('--trace-mib',type=int,choices=(32,64,128),default=64,help='finite logical trace cap per sampled session')
    p.add_argument('--overflow-probe',type=Path)
    p.add_argument('--deadline-seconds',type=int,default=1800)
    a = p.parse_args()
    if not 1 <= a.cycles <= 100 or not 0 < a.idle_seconds <= 300 or not 60 <= a.deadline_seconds <= 7200:
        p.error('cycles1..100 and idle0..300seconds required')
    if a.smoke: a.cycles=min(a.cycles, 2); a.idle_seconds=min(a.idle_seconds, 1)
    a.honk=a.honk.resolve(strict=True); a.goose=a.goose.resolve(strict=True)
    if a.overflow_probe: a.overflow_probe=a.overflow_probe.resolve(strict=True)
    output=a.output.resolve(); output.mkdir(parents=True, exist_ok=False); (output/'tmp').mkdir()
    env={**os.environ, 'GOOSE':str(a.goose), 'HONK_HOME':str(output/'cache'), 'TMPDIR':str(output/'tmp')}
    report=dict(complete=False, mode='smoke' if a.smoke else 'long', cycles=a.cycles, idle_seconds=a.idle_seconds,
                source_commit=git(ROOT,'rev-parse','HEAD').decode().strip(), platform=platform.platform(),
                selected_projects=a.project or list(WORKLOADS),selected_modes=a.mode or ['timing','resources'],trace_mib=a.trace_mib,
                binary_sha256={'honk':sha(a.honk),'goose':sha(a.goose)}, harness_sha256=sha(__file__), projects={},
                compiler_pin=(ROOT/'GOOSE_REVISION').read_text().strip(),
                compiler_version=subprocess.check_output([str(a.goose),'--version'],text=True,timeout=10).strip(),
                source_status=git(ROOT,'status','--porcelain').decode(),
                helpers={x:sha(ROOT/x) for x in ['bench/process_observer.py','bench/observer_calibration.py','bench/watch_overflow.c','scripts/watch-overflow-build.py']},
                started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                limits='Sampled resource lower bounds; RSS sums double-count shared pages; log-poll times are observations, not kernel latency.')
    if a.overflow_probe: report['binary_sha256']['overflow_observer']=sha(a.overflow_probe)
    save(output/'report.json',report)
    if a.overflow_probe:
        provenance=a.overflow_probe.with_suffix('.json')
        report['overflow_build']=json.loads(provenance.read_text())
        report['overflow_build_manifest_sha256']=sha(provenance)
        build=report['overflow_build']
        if (build['binary_sha256']!=sha(a.overflow_probe) or build['goose_sha256']!=sha(a.goose) or
            build['observer_source_sha256']!=sha(ROOT/'bench/watch_overflow.c') or
            build['builder_sha256']!=sha(ROOT/'scripts/watch-overflow-build.py') or
            any(sha(ROOT/path)!=digest for path,digest in build['production_sources'].items())):
            raise RuntimeError('overflow observer build provenance mismatch')
    original_tools=dict(report['binary_sha256'])
    deadline=time.monotonic()+a.deadline_seconds
    source_commit=report['source_commit']
    try:
        if report['source_status']: raise RuntimeError('qualification requires a clean source checkout')
        (output/'calibration').mkdir();report['calibration']=calibrate(output/'calibration')
        for name,(rev,entry,suite) in WORKLOADS.items():
            if name not in report['selected_projects']: continue
            project=output/name;project.mkdir();repo=getattr(a,name+'_repo')
            archive=git(repo,'archive','--format=tar',rev);(output/(name+'-source.tar')).write_bytes(archive)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                members=tar.getmembers()
                if name == 'json':
                    # Preserve complete archive evidence while omitting unrelated
                    # examples/bench imports from Honk's sourced-import discovery.
                    selected={'json_codec.goose','json_codec.build','protocol.goose','CMakeLists.txt',
                              'LICENSE','NOTICE','GOOSE_REVISION','tests/codec.goose'}
                    members=[m for m in members if m.name in selected or m.name == 'native' or m.name.startswith('native/')]
                tar.extractall(project,members=members,filter='data')
            original=(project/entry).read_bytes()
            original_files={str(x.relative_to(project)):sha(x) for x in project.rglob('*') if x.is_file()}
            modes={str(x.relative_to(project)):x.stat().st_mode & 0o777 for x in project.rglob('*') if x.is_file()}
            manifest=f'[package]\nname="{name}"\nkind="lib"\nversion="0.1.0"\nentry="{entry}"\n'
            (project/'Honk.toml').write_text(manifest)
            info=dict(revision=rev,archive_sha256=hashlib.sha256(archive).hexdigest(),original_files=original_files,
                      adapter_manifest=manifest,original_file_modes=modes,sessions=[],projection=('selected production/native files and unmodified codec suite;full archive retained' if name=='json' else 'full upstream archive'));report['projects'][name]=info
            baseline=execute([str(a.honk),'test','--offline','--filter',suite,'--log-file',str(output/(name+'-baseline.log'))],
                             project,env,timeout=180,cap=4*1024*1024)
            save(output/(name+'-baseline.json'),baseline)
            baseline_stdout=baseline['stdout'].encode()
            (output/(name+'-baseline.stdout')).write_bytes(baseline_stdout)
            (output/(name+'-baseline.stderr')).write_text(baseline['stderr'])
            if not baseline['complete'] or baseline['exit_code'] or not canonical(baseline_stdout,project).strip():
                raise RuntimeError(f'{name} baseline failed')
            if (project/'GOOSE_REVISION').read_text().strip()!=report['compiler_pin']: raise RuntimeError('workload/compiler pin mismatch')
            expected=canonical(baseline_stdout,project);info['canonical_stdout']=expected.decode()
            for sampled in (False,True):
                if ('resources' if sampled else 'timing') not in report['selected_modes']: continue
                if time.monotonic()>deadline:raise RuntimeError('campaign deadline exceeded')
                session=Session(a.honk,project,env,output/(name+('-resources' if sampled else '-timing')),suite,sampled,trace_bytes=a.trace_mib*1024*1024)
                session.deadline=deadline
                info['sessions'].append(str(session.folder.relative_to(output)))
                try:
                    count=1;session.idle(count,0,expected)
                    before=session.checkpoint('idle-before');session.pause(a.idle_seconds);after=session.checkpoint('idle-after')
                    session.record['idle_cpu']=dict(ticks=after['cpu_ticks']-before['cpu_ticks'],hz=os.sysconf('SC_CLK_TCK'),elapsed_ns=after['at_ns']-before['at_ns'])
                    base_fds=fd_roles(after)
                    for i in range(a.cycles):
                        started=time.monotonic_ns();mutation(session,project/entry,original+f'\n// watch-save-{i}\n'.encode(),'atomic-save')
                        count+=1;session.idle(count,0,expected);session.action('save-complete',cycle=i,elapsed_ns=time.monotonic_ns()-started)
                        if fd_roles(session.checkpoint(f'save-{i}'))!=base_fds: raise RuntimeError('idle fd count did not converge')
                    for excluded in ('.git','.honk','target','.build','.toolchain'):
                        directory=project/excluded;created=not directory.exists()
                        directory.mkdir(exist_ok=True)
                        probe=directory/'watch-ignored-probe.goose'
                        if probe.exists(): raise RuntimeError('excluded probe collision')
                        probe.write_text('invalid excluded source');probe.unlink()
                        if created: directory.rmdir()
                        session.action('excluded-subtree-edit',name=excluded)
                    sibling=output/(name+'-sibling.goose');sibling.write_text('invalid sibling source');sibling.unlink()
                    session.action('sibling-edit');session.pause(.3)
                    if len(session.outcomes())!=count: raise RuntimeError('excluded/sibling edits scheduled a command')
                    # SIGSTOP makes the rapid-save burst deterministic: all edits
                    # precede consumption, and cleanup always resumes the owner.
                    signal.pidfd_send_signal(session.pidfd,signal.SIGSTOP)
                    try:
                        session.wait(lambda: ProcessObserver.identity(session.proc.pid)['state'] in ('T','t'),timeout=5)
                        for i in range(20):
                            mutation(session,project/entry,original+f'\n// burst-{i}\n'.encode(),'rapid-save')
                    finally: signal.pidfd_send_signal(session.pidfd,signal.SIGCONT)
                    count+=1;session.idle(count,0,expected)
                    session.pause(.2)
                    if len(session.outcomes())!=count: raise RuntimeError('rapid saves failed to coalesce')
                    for cycle in range(a.cycles):
                        incoming=output/f'{name}-incoming-{cycle}';incoming.mkdir();(incoming/'changed.goose').write_text('// populated\n')
                        nested=project/'watch-incoming';incoming.rename(nested);session.action('move-populated-subtree');count+=1;session.idle(count,0,expected)
                        mutation(session,nested/'changed.goose',b'// changed\n','nested-edit');count+=1;session.idle(count,0,expected)
                        (nested/'changed.goose').unlink();nested.rmdir();session.action('remove-subtree');count+=1;session.idle(count,0,expected)
                        session.pause(.2)
                        if fd_roles(session.checkpoint(f'topology-{cycle}'))!=base_fds or len(session.outcomes())!=count:
                            raise RuntimeError('topology did not return to the same idle descriptor roles/command count')
                    mutation(session,project/entry,original+b'\nfn deliberate_invalid(\n','invalid-source');count+=1;session.idle(count,1,expected)
                    mutation(session,project/entry,original,'restore-source');count+=1;session.idle(count,0,expected)
                    session.pause(.2)
                    if fd_roles(session.checkpoint('restored'))!=base_fds or len(session.outcomes())!=count:
                        raise RuntimeError('steady-state fd/command convergence failed')
                    points=session.record['checkpoints']
                    session.record['steady_rss_observations_kib']=dict(initial=after['rss_kib'],final=points[-1]['rss_kib'],minimum=min(x['rss_kib'] for x in points),maximum=max(x['rss_kib'] for x in points),delta=points[-1]['rss_kib']-after['rss_kib'])
                    session.finish()
                finally: session.close()
            info['stopping_cases']=[]
            for kind in ('aba','delete','sigint'):
                for active in (False,True):
                    if time.monotonic()>deadline:raise RuntimeError('campaign deadline exceeded')
                    stop_case(a.honk,project,env,output/f'{name}-{kind}-{active}',suite,expected,kind,active)
                    info['stopping_cases'].append(dict(kind=kind,active=active,folder=f'{name}-{kind}-{active}'))
            if a.overflow_probe:
                info['real_kernel_overflow']=overflow_case(a.overflow_probe.resolve(strict=True),project,env,output/f'{name}-overflow',suite,expected)
            info['restored_source_hashes']={path:sha(project/path) for path in original_files}
            for path,digest in original_files.items():
                if sha(project/path)!=digest or (project/path).stat().st_mode & 0o777 != modes[path]: raise RuntimeError('upstream source restoration mismatch: '+path)
            save(output/'report.json',report)
        final_tools={'honk':sha(a.honk),'goose':sha(a.goose)}
        if a.overflow_probe: final_tools['overflow_observer']=sha(a.overflow_probe)
        if a.overflow_probe and sha(provenance)!=report['overflow_build_manifest_sha256']: raise RuntimeError('observer build manifest changed')
        if original_tools != final_tools: raise RuntimeError('measured binaries changed')
        if any(sha(ROOT/path)!=digest for path,digest in report['helpers'].items()): raise RuntimeError('helper source changed')
        if git(ROOT,'status','--porcelain').decode(): raise RuntimeError('source checkout changed during qualification')
        if sha(__file__) != report['harness_sha256']: raise RuntimeError('harness changed during qualification')
        if git(ROOT,'rev-parse','HEAD').decode().strip()!=source_commit:raise RuntimeError('source commit changed during qualification')
        report['complete']=True
    except BaseException as error:
        report['failure']=f'{type(error).__name__}: {error}';raise
    finally: save(output/'report.json',report)


if __name__=='__main__':
    main()

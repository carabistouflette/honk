# SPDX-License-Identifier: Apache-2.0
"""Linux observations for owned benchmark processes; no performance timing claims."""
import gzip
import json
import os
from pathlib import Path
import time


class ProcessObserver:
    def __init__(self, root_pid, trace, test_executables=(), max_bytes=32*1024*1024):
        self.root_pid = root_pid
        self.root = self.identity(root_pid)
        if self.root is None:
            raise RuntimeError('owned root disappeared before observation')
        self.tests = {str(Path(x).resolve()) for x in test_executables}
        self.trace = gzip.open(trace, 'wt')
        self.max_bytes = max_bytes
        self.bytes = 0
        self.seen = {}
        self.samples = 0
        self.races = 0
        self.errors = []
        self.gaps = []
        self.last = None
        self.maxima = {}
        self.checkpoints = []

    @staticmethod
    def identity(pid):
        try:
            text = Path(f'/proc/{pid}/stat').read_text()
            fields = text[text.rfind(')')+2:].split()
            return dict(pid=int(pid), start=int(fields[19]), ppid=int(fields[1]),
                        group=int(fields[2]), session=int(fields[3]), state=fields[0])
        except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
            return None

    def read_node(self, identity, links=False):
        pid = identity['pid']
        before = self.identity(pid)
        if before is None or before['start'] != identity['start']:
            self.races += 1
            return None
        try:
            status = Path(f'/proc/{pid}/status').read_text()
            memory = {}
            for line in status.splitlines():
                key, _, value = line.partition(':')
                if key in ('VmRSS', 'VmHWM'):
                    memory[key] = int(value.split()[0])
            fds = list(Path(f'/proc/{pid}/fd').iterdir())
            descriptors = {}
            if links:
                for fd in fds:
                    descriptors[fd.name] = os.readlink(fd)
            executable = os.readlink(f'/proc/{pid}/exe').removesuffix(' (deleted)')
            child_ids = set()
            for task in Path(f'/proc/{pid}/task').iterdir():
                try:
                    child_ids.update(map(int, (task/'children').read_text().split()))
                except (FileNotFoundError, ProcessLookupError):
                    self.races += 1
            after = self.identity(pid)
            if after is None or after['start'] != before['start']:
                self.races += 1
                return None
            role = 'root' if pid == self.root_pid else 'test' if executable in self.tests else 'other'
            return dict(**after, rss_kib=memory.get('VmRSS', 0), hwm_kib=memory.get('VmHWM', 0),
                        fd_count=len(fds), role=role, children=sorted(child_ids), fd_links=descriptors)
        except (FileNotFoundError, ProcessLookupError):
            self.races += 1
            return None
        except PermissionError as error:
            self.errors.append(f'{pid}: {type(error).__name__}')
            return None

    def snapshot(self, checkpoint=None):
        began = time.monotonic_ns()
        if self.last is not None:
            self.gaps.append(began-self.last)
        self.last = began
        queue = [self.root]
        nodes = []
        visited = set()
        while queue:
            identity = queue.pop()
            key = (identity['pid'], identity['start'])
            if key in visited:
                continue
            visited.add(key)
            if len(visited) > 256:
                raise RuntimeError('owned process observation cap exceeded')
            node = self.read_node(identity, links=checkpoint is not None and identity['pid'] == self.root_pid)
            if node is None:
                continue
            nodes.append(node)
            self.seen[key] = identity
            for pid in node['children']:
                child = self.identity(pid)
                parent = self.identity(node['pid'])
                if parent is None or parent['start'] != node['start']:
                    self.races += 1
                    break
                if child is not None and child['ppid'] == node['pid']:
                    queue.append(child)
        root = next((n for n in nodes if n['pid'] == self.root_pid), None)
        if root is None:
            return None
        descendants = [n for n in nodes if n['pid'] != self.root_pid]
        phase = 'execution' if any(n['role'] == 'test' for n in descendants) else 'non_test_descendants' if descendants else 'idle'
        metrics = dict(root_rss_kib=root['rss_kib'], root_observed_hwm_kib=root['hwm_kib'],
                       descendant_rss_sum_kib=sum(n['rss_kib'] for n in descendants),
                       tree_rss_sum_kib=sum(n['rss_kib'] for n in nodes), root_fds=root['fd_count'],
                       descendant_fd_sum=sum(n['fd_count'] for n in descendants),
                       tree_fd_sum=sum(n['fd_count'] for n in nodes), descendants=len(descendants))
        record = dict(at_ns=began, observation_ns=time.monotonic_ns()-began, phase=phase,
                      checkpoint=checkpoint, metrics=metrics,
                      nodes=[{k: v for k, v in n.items() if k not in ('fd_links', 'children')} for n in nodes])
        line = json.dumps(record, separators=(',', ':'))+'\n'
        self.bytes += len(line.encode())
        if self.bytes > self.max_bytes or self.samples >= 50000:
            raise RuntimeError('observation storage/sample cap exceeded')
        self.trace.write(line)
        self.samples += 1
        maximum = self.maxima.setdefault(phase, {})
        for key, value in metrics.items():
            maximum[key] = max(value, maximum.get(key, 0))
        if checkpoint is not None:
            row = dict(label=checkpoint, metrics=metrics, fds=root['fd_links'],
                       children=root['children'], identity=[root['pid'], root['start']])
            self.checkpoints.append(row)
            self.trace.flush()
            return row
        return record

    def private_group_members(self):
        # An unreaped root reserves this private session/group identity.
        members = []
        for directory in Path('/proc').iterdir():
            if not directory.name.isdecimal() or int(directory.name) == self.root_pid:
                continue
            try:
                identity = self.identity(int(directory.name))
            except PermissionError as failure:
                raise RuntimeError('private group inspection incomplete') from failure
            if identity and identity['group'] == self.root_pid and identity['session'] == self.root_pid and identity['start'] >= self.root['start']:
                members.append(identity)
        return members

    def close(self):
        self.trace.close()
        return dict(samples=self.samples, logical_trace_bytes=self.bytes, read_races=self.races,
                    permission_errors=self.errors, maxima=self.maxima, checkpoints=self.checkpoints,
                    requested_semantics='sampled observed lower bounds; RSS sums double-count shared pages',
                    actual_gaps_ns=dict(min=min(self.gaps, default=0), max=max(self.gaps, default=0),
                                        mean=sum(self.gaps)//max(1, len(self.gaps))))


def execute(argv, cwd, env, *, trace=None, test_executables=(), interval=.005,
            checkpoint=None, trigger=None, timeout=180, cap=2*1024*1024):
    """Own an isolated group; checkpoint callback runs before stdin acknowledgment."""
    import selectors
    import signal
    import subprocess
    started = time.perf_counter_ns()
    process = None
    pidfd = None
    observer = None
    selector = selectors.DefaultSelector()
    buffers = {'out': bytearray(), 'err': bytearray()}
    pending = bytearray()
    record = dict(argv=list(map(str, argv)), sampled=trace is not None,
                  requested_interval_ms=interval*1000 if trace else None, checkpoints=[], complete=False)
    end = None
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE if checkpoint else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        pidfd = os.pidfd_open(process.pid)
        observer = ProcessObserver(process.pid, trace, test_executables) if trace else None
        selector.register(pidfd, selectors.EVENT_READ, 'exit')
        for stream, label in ((process.stdout, 'out'), (process.stderr, 'err')):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, label)
        deadline = time.monotonic()+timeout
        next_sample = time.monotonic()
        open_streams = 2
        exited = False
        while not exited or open_streams:
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError('qualification invocation exceeded finite deadline')
            if observer and not exited and now >= next_sample:
                row = observer.snapshot()
                if trigger and row:
                    trigger(process, row)
                next_sample = time.monotonic()+interval
            wait = min(deadline-time.monotonic(), max(0, next_sample-time.monotonic()) if observer and not exited else deadline-time.monotonic())
            for key, _ in selector.select(wait):
                label = key.data
                if label == 'exit':
                    if end is None:
                        end = time.perf_counter_ns()
                    exited = True
                    selector.unregister(pidfd)
                    # Do not reap until the private group has been checked;
                    # the terminal root still reserves this session/group ID.
                    members = observer.private_group_members() if observer else group_members(process.pid)
                    record['post_exit_group_members'] = members
                    if members:
                        raise RuntimeError('private group still contains descendants after leader exit')
                    continue
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    open_streams -= 1
                    continue
                buffers[label].extend(data)
                if len(buffers[label]) > cap:
                    raise RuntimeError('qualification output cap exceeded')
                if label == 'out' and checkpoint:
                    pending.extend(data)
                    while b'\n' in pending:
                        line, _, tail = pending.partition(b'\n')
                        pending = bytearray(tail)
                        if not line.startswith(b'@@QUAL '):
                            continue
                        if not observer:
                            raise RuntimeError('checkpoint observer is required')
                        text = line.decode('ascii')
                        row = observer.snapshot(text)
                        if row is None:
                            raise RuntimeError('checkpoint process was not observable')
                        row['group_members'] = observer.private_group_members()
                        record['checkpoints'].append(row)
                        checkpoint(process, text, row)
                        process.stdin.write(b'continue\n')
                        process.stdin.flush()
        record['exit_code'] = process.wait(timeout=5)
        record['complete'] = True
    except BaseException as failure:
        record['error'] = repr(failure)
    finally:
        if process is not None and process.returncode is None:
            try:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
            except BaseException as cleanup:
                record['cleanup_error'] = repr(cleanup)
                record['complete'] = False
        record.setdefault('exit_code', process.returncode if process is not None else None)
        record['elapsed_ns'] = (end or time.perf_counter_ns())-started
        record['stdout'] = bytes(buffers['out']).decode('utf-8', errors='backslashreplace')
        record['stderr'] = bytes(buffers['err']).decode('utf-8', errors='backslashreplace')
        def cleanup(operation):
            try:
                return operation()
            except BaseException as failure:
                record.setdefault('cleanup_errors', []).append(repr(failure))
                record['complete'] = False
                return None
        if observer:
            record['observation'] = cleanup(observer.close)
        cleanup(selector.close)
        if pidfd is not None:
            cleanup(lambda: os.close(pidfd))
        for stream in ((process.stdin, process.stdout, process.stderr) if process is not None else ()):
            if stream:
                cleanup(stream.close)
    # The caller saves this record, including failures, before deciding to stop.
    return record


def group_members(root_pid):
    members = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal() or int(directory.name) == root_pid:
            continue
        try:
            identity = ProcessObserver.identity(int(directory.name))
        except PermissionError as failure:
            raise RuntimeError('private group inspection incomplete') from failure
        if identity and identity['group'] == root_pid and identity['session'] == root_pid:
            members.append(identity)
    return members

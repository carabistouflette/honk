# Watch check and test commands

Build Honk from current development source (watch is not in v0.4.0), then
from a trusted project:

```sh
honk watch check --watch-dir "$PWD/src" --offline
honk watch test --watch-dir "$PWD/tests" --filter 'tests/**/*.goose' --frozen
honk watch check --watch-dir "$PWD/src" --watch-runs 2
```

An explicit normalized absolute directory is required. This first integration
watches exactly one directory, nonrecursively. It does not automatically watch
nested directories, other workspace members, dependency trees, manifests or
lockfiles. `check` or `test` still performs its ordinary full selected command;
`--filter` selects test targets, not watched filenames. Normal command options
and test arguments after `--` are forwarded literally, without a shell.

The watch is installed before the initial run. Close-write, moved-from/to and
delete events on immediate `.goose` names request another run; create alone is
ignored to avoid checking files still being written. Directory events and other
extensions are ignored. Changes observed during a command coalesce into one
pending rerun. There is no quiet-period debounce or exactly-once operation count:
changes arriving in a later batch may cause a later run. Each drain is capped at
256 records so a busy directory cannot starve child/signal handling.

The supervisor holds no cache/project lock. Each inner Honk command loads the
project normally and owns its normal locks. An ordinary command result in 1..127
is reported by that command and later edits can retry. Exit statuses of 128
or higher stop conservatively, including when reported as a normal exit code. `--watch-runs N` ends
after N runs (including the initial run), returning the last result; the default
0 waits indefinitely. Accepted range: 0..10000. Child signal termination,
supervision failure or terminal watch failure stops the session.

Overflow means events were lost. The watcher is closed/reopened and a full
selected command is scheduled; old watch removal may itself have been lost.
This is not a filesystem snapshot or an authorization check. An observed root
move/delete/unmount/ignored event stops instead of silently watching a stale
path. Diagnostics never print raw event names.

SIGINT/SIGTERM cancel the session. Direct cancellation is forwarded to an active
inner Honk; terminal-group SIGINT is not forwarded twice. The supervisor waits
for child cleanup before it exits or starts another run. There is no overall
command deadline or forced-kill escalation: a command ignoring cancellation can
keep cleanup waiting. This is not process-group supervision; external SIGKILL,
daemonizing tests and grandchildren escaping normal Honk cleanup remain outside
its guarantees. Test stdin is null; interactive tests are not supported.

Watch requires a compiled Linux Honk and `/proc/self/exe`. A bounded self-version
probe rejects running this command through `goose run honk.goose`. Re-execution
uses the running executable image rather than a PATH lookup. The probe alone has
a hard deadline; active commands do not, to avoid killing Honk before its nested
compiler/test process can clean up.

The consumer vendors unmodified goose-watch alpha.1 at
`7bbd7ef8c9a4d6323ef9d065d1461bae9ba9fe58`. Root owners cannot be dynamic array
values; recursive/multi-directory ownership belongs in a reusable watch-set
interface rather than a duplicate inotify implementation in Honk.

Validation: `make watch-test` runs real Honk/watcher subprocesses with controlled
compiler barriers. It covers initial/finite runs, failure recovery, coalescing,
ignored traffic, nonrecursion, atomic rename saves, literal args/filter/bin
forwarding, no idle cache lock, idle/active/group cancellation, directory moves,
child reaping and invalid options. The full normal and sanitizer suites remain
required. No comparative performance claim is made.

`make watch-fault-test` uses a separate linker adapter and compiler-cache key to
inject event loss and corruption into the real consumer. It checks reopening,
coalescing, deferred overflow diagnostics, a single termination request and
waiting for delayed compiler cleanup. The adapter is excluded from production
packages. `make watch-fault-sanitize` repeats it with ASan/UBSan.

# Warm command phase diagnosis

`phases.py` adds numeric stderr probes to a disposable copy of an exact Honk
Git snapshot. Production sources, binaries and CLI options are unchanged. Use
an already warmed copy of `bench/workspace` from the real workspace exercise;
this driver does not fetch or initialize dependencies. It rebuilds the
instrumented Honk with the selected compiler, checks the four commands against
a supplied plain binary's stdout, warms each command, then runs three shuffled
rounds by default.

```sh
taskset -c 0 python3 bench/phases.py \
  --revision 65d4e97d808e97cdcc2c6d1f783f440e89cb2786 \
  --baseline /path/to/frozen/honk \
  --goose /path/to/pinned/goose \
  --goose-home /path/to/warmed/goose-home \
  --honk-home /path/to/warmed/honk-cache \
  --workspace /path/to/warmed/workspace \
  --output .build/phases.json
```

The plain binary is an output oracle, not a timed performance comparator. Use a
binary built from the selected snapshot's application sources. The report
fingerprints the actual baseline and compiler executables; it does not prove
how someone built a supplied binary. Honk's version output alone is insufficient
build provenance. The checked-in observation identifies the specific previously
validated release binary and verifies runtime source equality separately.

Probes surround dependency resolution, compiler identity checks, source
staging/remapping, entry generation, compiler check/build, atomic executable
publication and application execution. Workspace `tree` and `check` contain two
member observations. The driver verifies this cardinality, exact stdout, known
numeric stderr only, unchanged workspace inputs/locks and unchanged source/tool
hashes. Each probe reports elapsed nanoseconds converted to milliseconds.
Diagnostic stderr writes occur between phases and are included in the overall
wall time. Residual time includes application dispatch, formatting, controller
launch/wait overhead and probe writes; it is not a measured module cost.

This is phase attribution from altered source/build paths with additional
clock reads and writes. Do not subtract it from the earlier plain-binary series
or report it as a matched speedup. CPU time covers waited children; memory and
network behavior are not traced. Frozen commands reuse an already checked
cache, but still perform normal cache validation and staging. The host is
shared, affinity is not isolation, and three samples establish no regression
bound. Every sample and the source transformation hashes are retained.

The driver writes bounded stdout/stderr to temporary regular files, uses pidfd
notification, normalizes waitable SIGCHLD, and terminates an owned process group
before reaping on exceptional exit. Its ignored work directory retains source
and completed per-command event records if a later operation fails. A success report is
created only after the input checks; choose a new output path each time.

For syscall attribution, run an additional **untimed** diagnostic against the
plain binary in that same warmed workspace:

```sh
strace -f -T -o /path/to/private/trace \
  -e trace=execve,fsync,fdatasync,rename,renameat,copy_file_range,read,write \
  /path/to/frozen/honk build -p version_gate --frozen
```

Keep this trace local: compiler arguments include private absolute paths. The
published syscall excerpt contains only the relevant sanitized numeric result.
The compiler, its subprocesses and syscall tracing add work; these observations
do not establish logger, Git transport or compiler throughput rankings.

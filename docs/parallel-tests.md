# Opt-in parallel tests

The default `honk test` path stays sequential with inherited streams. Explicit
`--jobs N` (1..8) selects bounded execution. `--test-timeout-ms N`
(1..86400000, default30000) requires explicit --jobs and applies to execution,
not compilation. Both apply only to ordinary test, including workspace members
processed sequentially; watch rejects them in this first version.

Discover/filter targets normally and compile all binaries sequentially before
executing any. This avoids compiler-cache/shared-staging races. Compiler failure
executes no tests. goose-task assigns IDs in discovery order; independent tests
need no dependency edges.

Execute cohorts of at most jobs tasks. Capture up to65536 bytes each of stdout
and stderr, with null stdin and literal forwarded arguments. Service every child
using incremental nonblocking steps, then one rotating short wait. Cohorts bound
retained captures to1MiB logically (8*2*65536), plus runtime overhead, independent
of target count. Slow tasks delay the next cohort; this keeps memory/reporting
simple. Replay discovery order, stdout then stderr per target. Cross-stream
interleaving is not retained. Program output is trusted and unescaped.
Compilation output precedes captured output.

Ordinary failures finish the admitted cohort and prevent later cohorts. Return
the lowest-ID failing task's exit/signal code. Infrastructure/output/cleanup
failure returns125 and closes all children before diagnostics/exit. Parent
SIGINT/SIGTERM stops admission, closes/kills all direct children without a graceful forwarding phase, restores the guard,
and returns128+signal. Cancellation outranks supervision errors, which outrank
ordinary child failure. No output occurs while children remain owned.

No threads, process groups, descendant supervision, interactive stdin, retries,
parallel compilation or workspace-wide concurrency. Direct-child deadlines are
not hard wall-time guarantees: start, kill/reap/recovery, filesystem operations
and blocked output writes may block. Recover each transferred PID exactly once,
after closing remaining owners. Replay and presentation occur after cleanup.

Review/test concurrency, deterministic binary output, exact output caps and
overflow, deadlines, launch/cleanup failure, signals, arguments/cwd/environment,
filters/workspaces/watch, early prevalidation and packaged imports. Preserve
default-path tests. Benchmark explicit jobs1 against jobs2/jobs4 and the legacy
default using real Goose targets, preserving raw source/toolchain/platform
identities. No performance claim before measurements.

Infrastructure diagnostics distinguish launch, deadline, output-limit, captured-
output-write and supervision/cleanup failures, with zero-based target IDs. An
ordinary test exit125 remains a child outcome and is not mislabeled as a
supervision failure. Exact stdout/stderr caps are accepted; excess terminates
the cohort and is reported as failure, never silent truncation.

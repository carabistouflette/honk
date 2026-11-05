# Honk UTC diagnostics: paired production-path measurements

This optional Linux development tool measures the real Honk diagnostics path
before and after UTC integration. It does not change Honk's implementation,
vendored libraries, file sink policy, or normal stdout. The baseline is immutable
public commit `65d4e97` (resolved to its full SHA in each record).

```sh
# Every run needs an absent or empty output directory.
python3 bench/utc/run.py --goose /absolute/path/to/goose --smoke --include-file \
  --output .build/utc/smoke-01
# Freeze/commit sources and stop competing local builds before timing.
python3 bench/utc/run.py --goose /absolute/path/to/goose --include-file \
  --iterations 100000 --rounds 7 --warmup 64 --file-iterations 1000 \
  --cpu 0 --build-cpu 3 --output .build/utc/full-01
```

The exact Goose checkout and executable-advertised revision must match
GOOSE_REVISION. This is an identity check, not cryptographic verification of
an executable. Default C compiler is GCC; `--cc` overrides it. All generated
Goose and native code is built with the recorded wrapper and `-O2`, without
native CPU tuning. Measurement/build CPUs must be available in the process
mask; defaults use its first/last available CPU. Python verification runs in
the parent with inherited affinity. Affinity does not reserve a CPU or control
frequency, turbo, thermal state, scheduling or activity on the shared host.

`--smoke` caps rounds at two, calls at 32 (file calls at 16), and warmups at eight.
It provides correctness evidence, not useful timings. A normal capture requires
clean sources unless `--allow-dirty` is explicitly used for exploratory work.
Dirty state and exact source hashes are recorded. No old evidence is overwritten.
Run only one measurement process per checkout; generated C and native caches
are not designed for unrelated concurrent mutation.

## Real paths and benchmark instrumentation

The runner exports the baseline through `git archive` under ignored `.build`,
without another checkout or modifications. Its `diagnostics::write` remains
byte-for-byte unchanged. Baseline and candidate use the same runtime fixture
and driver loop. Candidate calls the actual `diagnostics::write_with` shared
production path; fixed clocks return runtime fixture readings, and OS clocks
call production `diagnostics::wall_clock`. Guards, event severity, message
construction, lexical buffers, UTC adapter and sink-failure handling all remain
the real implementation. No fake reimplementation supplies either path.

The old implementation has no injectable sink. A benchmark-scoped linker
wrapper intercepts only `goose_cli_log_append` for both variants, retaining all
output and counting sink calls, bytes and a position-weighted checksum covering
every output byte. This counter/copy/checksum work is timed. Capture storage is
preallocated and touched before warmup. The optional `file` stage delegates to
the unchanged real native append function first, then captures its successful
output; all other stages substitute an in-memory sink and do no log-file I/O.
The wrapper rejects oversized workload output rather than bypassing its cap.

Candidate clock wrappers also count calls and store each i64 sample in a
preallocated trace. These callbacks and stores are timed, whereas serialization,
trace/file reads, independent validation, compilation and fixture setup are not.
Baseline has no clock callback or sample stores. Runtime stage dispatch, event
selection, counters, success checks and current-sample assignment are included.
These instrumentation/byte differences prevent an exact isolated UTC-cost claim.

| Stage | Baseline | Candidate |
| --- | --- | --- |
| `no_log` | Real write, initial unconfigured state | Real shared write, initial unconfigured state |
| `off` | Configured minimum Off | Configured minimum Off |
| `filtered` | Started event filtered at Warn | Started event filtered at Warn |
| `accepted_fixed` | Real write without timestamp | Real shared write with injected fixture clock |
| `accepted_os` | Same old write baseline | Real shared write with production OS clock |
| `file` (optional) | Real write and real native file sink | Real shared write, OS clock and real native file sink |

Each child is a fresh process configured once outside timing. Each phase starts
at fixture index zero. Eight runtime binary records vary event, full-u64 duration,
u32 outcome and signed-nanosecond samples, including endpoints, negative dates,
epoch and fractional values. Filtering forces Started so every event is filtered.
All variants return true in these successful/disabled workloads. No source-level
clock/sink work should occur when unconfigured, Off or filtered; counters and
captured bytes must remain empty. Invariant disabled states may be optimized by
the compiler; small loop costs do not establish general per-call latency.

## Independent verification and retained evidence

Python independently constructs every complete old and UTC-stamped record from
the runtime fixture and exact clock samples. It uses datetime plus integer
seconds/fractions, without float timestamps or local-time conversion. Every
captured byte, clock/sink count, successful return, measured byte count and
all-byte checksum is checked. Warmup output and traces are checked too but
excluded from measured counters. OS samples need not be equal across processes
or monotonic. The fixture holds only synthetic fixed events and numeric data.

For the real-file stage, each child receives its own pre-existing 0600 file with
a sentinel prefix. Complete delivered bytes must equal sentinel plus capture;
mode, owner, one-link count and inode identity must remain unchanged. Counts are
limited to at most 10000 file calls, keeping these workloads below the production
16 MiB file cap. This checks actual delivery but does not claim durability,
concurrent-writer atomicity, retries, rotation, or adversarial directory safety
beyond the existing native sink contract. Non-file stages must not create a log.

Rounds interleave seeded shuffled baseline/candidate stage processes. All raw
batch results and outliers remain in `rounds.jsonl`; summaries report median,
minimum and maximum **batch-average** nanoseconds per call. These are not tail
latencies, statistical-significance claims, complete Honk command timings, or
universal speed rankings. Old/new records contain different byte counts and
perform different work. Do not subtract component numbers as exact costs.

Records include full source/baseline identities, source/vendor/native/compiler
hashes, compiler/CC/platform/CPU versions, fixture bytes/hash, flags, wrapper/shim
and executable hashes, affinity, counts and dirty state. Relevant sources,
compiler and executable hashes are checked again after the run. Failure retains
evidence and marks validation failed.

Smoke retains compressed complete output and clock traces. Full measurements
verify them before discarding them to keep results small; hashes and all raw
batch counters remain. Use `--retain-traces` to preserve full compressed traces.
Without those full-run traces, OS output/checksums cannot be replayed solely
from the compact summary. The small smoke companion is fully replayable:

```sh
python3 bench/utc/test_runner.py bench/utc/results/smoke
python3 -O bench/utc/test_runner.py bench/utc/results/smoke
```

Verifier controls replay retained samples and require rejection of corrupted
counts, success values, checksums, complete output bytes and truncated clocks.
The controls use explicit failures and remain active under optimized Python.

## Clean capture sequence

Commit the reviewed harness and production feature before recording publication
samples. Once competing local builds have stopped, capture a fresh smoke corpus
at `bench/utc/results/smoke` and full paired rounds at `bench/utc/results/full`.
Each absent or empty destination is populated only by that run. Source commit,
clean/dirty state, complete relevant hashes, exact compiler/vendor identities,
all raw rounds and validation status live in each metadata record.

The smoke corpus retains compressed complete output and exact clock traces for
normal and optimized-Python replay. The full corpus keeps compact batch counters
and verified trace/output hashes unless `--retain-traces` is selected. Full OS
results without retained traces cannot be independently replayed from their
compact record alone. Companion smoke evidence exercises that verifier path.

Exploratory GCC/Clang smoke corpora are preserved under ignored
`.build/utc/precommit-proof` rather than published as clean-source measurements.
Those tests established byte/counter agreement, real native-file delivery and
rejection of 138 deliberate result corruptions per corpus; final release
evidence must come from the new committed-harness captures above.

# Measurements

Honk has no general latency ranking or Cargo comparison. The
[released v0.4.0 reuse record](results/announcement-v040/README.md) is one bounded
current build workload, with full cold, warm and fallback ranges. Read the
[performance currentness audit](../docs/PERFORMANCE.md) before quoting results.
Old tables and every raw sample remain available as historical observations;
changing a compiler, dependency, relevant implementation or build can invalidate
a comparison even when its date is recent.

## Developer commands

With a matching compiler already built:

```sh
make GOOSE=/absolute/path/to/goose build
make GOOSE=/absolute/path/to/goose bench
```

`tests/bench.py` writes 25 sequential CLI samples per case to `.build/bench.json`.
It builds the fixture once before measurement; version/metadata have no separate
per-case warmup. `tests/audit_perf.py` checks wide directories, dense dependency
graphs and 128 assets totaling 32 MiB, with one untimed check per binary/case.
It writes `.build/audit-perf.json`. Samples are milliseconds and include process
startup, validation, staging and any compiler invocation, not parser throughput.
The scripts identify the actual binary and advertised compiler version, but do
not independently attest a supplied binary's build history or complete compiler/
dependency inputs. Publication needs those identities checked separately.

For an alternating comparison of two identically built snapshots:

```sh
HONK=/absolute/after HONK_BASELINE=/absolute/before \
GOOSE=/absolute/pinned/goose HONK_BASELINE_REVISION=FULL_BEFORE_SHA \
AUDIT_SAMPLES=9 AUDIT_TEMP_ROOT=/filesystem/to/test \
AUDIT_REPORT=.build/comparison.json python3 tests/audit_perf.py
```

Build/flags, CPU/OS/toolchain, filesystem, fixture, warmup, sample count and
actual executable identities belong with the raw results. Report medians and
ranges and retain slower/noisy results. Filesystems and cold/warm states are
separate workloads. Affinity is not machine isolation. None of these numbers
is a CI timing threshold. On a shared machine, arrange a measurement window without competing heavy
workloads and disclose any overlap. Ordinary correctness smoke checks do not
create new published performance claims.

## Methods and retained records

| Workload | Method | Historical observations |
| --- | --- | --- |
| Whole CLI/filesystem | Scripts above | [audit log](../docs/history/RESULTS.md) and root `results/*.json` |
| Process launches | [caller method](../docs/PROCESS-CONSUMER-2026-11-04.md) | [raw](results/process-consumer.json) |
| Git/path workspace | [method](WORKSPACE.md), [example](workspace/README.md) | [v0.2.0 series](results/workspace-v020/README.md) |
| Warm phases | [instrumented method](PHASES.md) | [phase series](results/warm-phases/README.md) |
| UTC diagnostics | [method](utc/README.md) | [captures and replay limits](utc/results/README.md) |
| Build reuse | `bench/reuse.py --help` | [v0.4.0 current workload](results/announcement-v040/README.md), [older development series](results/build-reuse/README.md) |

The v0.4.0 [functional receipt](https://github.com/carabistouflette/honk/releases/download/v0.4.0/workspace-functional-v0.4.0.json)
checks actual workspace behavior. It contains no timing result and must not be
used as latency, throughput, uptime or memory evidence.

## Prepared glob consumer comparison

`glob_consumer.py` builds exact before/after Git snapshots with the same Goose compiler,
C compiler and `-O2`. It materializes the before revision as the fixed real Honk
project for both binaries, prepares its local lock outside timing, and checks
identical output for every command before measuring. No network is timed.

```sh
python3 bench/glob_consumer.py --goose /absolute/pinned/goose \
  --before 7583ebe4ccb19cca530ccd295359dd808d8de3c9 --after FULL_AFTER_SHA \
  --rounds 7 --cpu 2 --output .build/glob-comparison
```

Cases include `version` and `metadata` startup controls, literal and recursive
filters selecting the real core test, and a recursive filter selecting the real
process benchmark with its `tiny` argument. Every invocation includes startup;
test/bench also include staging, target compilation and execution. Both versions
compile the same fixture sources. This compares the consumer's filter machinery,
not a target rebuilt against the new library. Each binary/case receives one
untimed correctness/warmup run. Order is randomized per round and timings run
sequentially on one available CPU. There is no timing threshold.

GNU `/usr/bin/time` records maximum resident memory in KiB. For commands spawning
compilers/targets this is the largest reported process or descendant high-water
mark, not simultaneous aggregate memory. A kernel-reported zero is retained as
unavailable, not claimed as zero memory use. Wall time includes the same GNU time
wrapper for both versions. Linux pidfd readiness avoids the polling granularity
of Python `wait(timeout)` for short startup controls. Raw samples, compiler/tool/binary/source hashes,
platform/CPU details, full commands and expected outputs are retained; fixture
inputs, generated lock and binary/tool hashes are checked before each sample and
after measurement. Generated stage/output state is excluded from source hashes.
Use a new output directory for each experiment. Shared-host warm-cache results
cannot establish cold-start or general package-manager rankings.

# Clean Honk UTC diagnostics capture

Both captures started from clean source `e092d63c15e13958d26e3b2982d35a468f03ab7d`.
The immutable public baseline is `65d4e97d808e97cdcc2c6d1f783f440e89cb2786`.
Its real `diagnostics::write` is exported unchanged; the candidate invokes the
actual shared `diagnostics::write_with` production path. Logger core, native
append adapter and compiler pin match between variants. The vendored UTC adapter
comes from goose-log `e93a71c0ff2f852b2d68f0a2c70f25ded3e8893a`; time comes from
`343887caeee0a1f4e2e536ff322fcafb454e11bd`.

[Full metadata](full/metadata.json) retains source/vendor/native/compiler,
wrapper/object/executable and baseline archive identities. Exact runtime input
is in [fixture.bin](full/fixture.bin). Compiler: `goose eadca40 (runtime 3025e5810379)`.
GCC builds use `-O2 --standalone` and the benchmark-only sink linker wrapper.
Host: Intel(R) Core(TM) Ultra 7 258V, Linux-7.2.11-arch1-1-x86_64-with-glibc2.44. Measurement CPU:
0; compilation CPU: 7. Frequency, thermal
state and other host activity were uncontrolled. This integration's validation
and build jobs finished before capture; no core was exclusively reserved.

## Commands

`GOOSE` denotes the exact pinned compiler whose source/binary identity is
retained in metadata. Commands ran sequentially without source changes. Both
ignored output directories were new; both runs completed before their contents
were copied here, preserving a clean tree at each run's start.

```sh
python3 bench/utc/run.py --goose "$GOOSE" --smoke --include-file \
  --output .build/utc/final-smoke
python3 bench/utc/run.py --goose "$GOOSE" --include-file \
  --iterations 100000 --rounds 7 --warmup 64 --file-iterations 1000 \
  --output .build/utc/final-full
python3 bench/utc/test_runner.py bench/utc/results/smoke
python3 -O bench/utc/test_runner.py bench/utc/results/smoke
```

## Results

Seven seeded shuffled rounds retain **84 raw batch samples** covering both
variants and all six stages. Non-file stages use 100000 measured calls per
batch; file stages use 1000. Each batch follows 64 untimed warmups.
[All raw samples](full/rounds.jsonl) and [summary](full/summary.json) preserve all
stages and outliers, without removing samples. Below are median batch-average
nanoseconds per call including instrumentation, not individual-call latencies.

| Stage | Old diagnostics | UTC diagnostics |
| --- | ---: | ---: |
| no_log | 2.91 | 4.45 |
| off | 4.60 | 6.37 |
| filtered | 5.68 | 7.30 |
| accepted_fixed | 265.25 | 391.42 |
| accepted_os | 260.23 | 484.76 |
| file | 25778.59 | 26323.31 |

Both accepted baseline rows run the same old timestamp-free path; they are
separate paired samples rather than different baseline clock implementations.
Candidate records contain additional UTC bytes and clock callback/sample-store
work. Both variants include native capture copies and position-weighted checksums
of every byte. These measurements do not isolate clock/formatter cost, establish
statistical significance, or imply universal rankings. Do not subtract stages
as an exact decomposition. Disabled-state loops can be optimized by the compiler;
small numbers do not establish general per-call latency.

## Verification and limits

Every complete output byte, real clock sample, clock/sink count, success count,
measured byte count and all-byte checksum passed an independent Python datetime/
integer oracle. Warmup outputs/traces are checked too but excluded from measured
counters. Unconfigured, Off and filtered stages produced no clock callbacks,
no sink callbacks and no output. Accepted stages produced the expected callbacks.
Real-file stages preserved the prefix and all delivered bytes, 0600 mode, owner,
one-link status and inode identity. This exercises existing native policy;
it does not establish durability, retries or concurrent-writer atomicity.

[Smoke metadata](smoke/metadata.json) records two rounds, 32 ordinary calls or
16 file calls per batch, eight warmups and **24 raw samples**. Complete compressed
output and exact clock traces support independent replay. Normal and optimized
Python replay each passed and rejected **138 controlled corruptions** of callback/
success counts, byte counts, checksums, complete bytes and truncated clock traces.

Full-run captured output and traces were independently verified before being
discarded; their hashes remain in raw rows. OS-dependent values cannot be
recomputed from the compact full record alone. Companion smoke data is fully
replayable; new full runs can retain everything with `--retain-traces`. No dirty
exploratory record was relabeled as clean-source evidence.

The [method](../README.md) details the real shared paths, native sink
interposition, clock instrumentation, source checks and workload limits. This
is a diagnostics component benchmark, not startup time or end-to-end Honk command
throughput. Product stdout and production implementations were not modified to
add benchmark instrumentation.

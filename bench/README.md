# Reproducible measurements

Build an optimized native Honk with the pinned compiler:

```sh
make setup build
make bench
```

`tests/bench.py` records 25 warm sequential invocations of version, metadata,
check and build. `tests/audit_perf.py` records wide-directory and dense
production/dev dependency graphs plus 128 binary assets totaling 32 MiB.
Fixture creation and warmups are outside timed samples. Timings include process
startup, project/dependency validation, staging and the invoked compiler; these
are CLI workloads, not isolated parser/kernel throughput measurements.

Both scripts write all elapsed samples in milliseconds with source revision,
dirty state, compiler/runtime version and OS provenance under `.build/`.
Audit reports additionally record the filesystem. `.build/` is ignored; reviewed
publication samples are copied into [results/](results/).

## Paired comparison

Supply optimized before/after binaries built with the same pinned compiler and
C backend/flags. The harness alternates order on each sample to reduce drift:

```sh
HONK=/absolute/path/to/after HONK_BASELINE=/absolute/path/to/before \
GOOSE=/absolute/path/to/pinned/goose HONK_BASELINE_REVISION=FULL_BEFORE_COMMIT \
AUDIT_SAMPLES=9 AUDIT_TEMP_ROOT=/directory/on/filesystem/under/test \
AUDIT_REPORT=.build/comparison.json python3 tests/audit_perf.py
```

The default temporary directory may be tmpfs. A disk filesystem and tmpfs are
separate workloads; do not combine their samples or assume one predicts the
other. Large-file kernel assistance is filesystem-dependent. `make portable`
validates the portable implementation under native sanitizers.

[RESULTS.md](../RESULTS.md) identifies measured revisions, exact commands, flags,
hardware, raw files and limitations. Report every workload, including slowdowns
and noisy/no-change results. CI smoke-runs benchmarks without wall-clock gates;
local results are not universal rankings or a claim of Cargo parity.

[Follow-up audit measurements](../docs/AUDIT-2026-11-04.md) compare the hardened
implementation with the first public main and retain every measured workload.

[Source and signal audit measurements](../docs/SOURCE-SIGNAL-AUDIT-2026-11-04.md)
record the next reviewed source and complete paired samples against `f427cd1`.

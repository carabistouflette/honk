# Validation and measurement evidence

Honk is pre-release. This document records reproducible checks and measured
workloads rather than a production-stability or security certification.

## Reproduce validation

From a standalone clone, `make setup` builds the exact compiler revision in
GOOSE_REVISION. Then run:

```sh
make check test security
make sanitize portable
HONK_SANITIZER_CC=clang make sanitize portable
make bench
```

Use `make GOOSE=/absolute/path/to/matching/goose ...` to select an existing
compiler. `check` verifies vendored source/license hashes, Goose formatting and
types, plus whitespace. `test` runs Goose core contracts in-process and natively,
real CLI integration cases, and subprocess probes for closed descriptors,
output limits, signalled children and launch failure. `security` runs 213
seeded malformed-import probes and rejects FIFO manifests without blocking.

`sanitize` instruments Honk's native adapter and generated native code with GCC
(default) or Clang AddressSanitizer/UndefinedBehaviorSanitizer, leak detection, Goose debug checks
and bounds-check elimination disabled. It runs the integration/hostile suites
and process probes. `portable` forces large-file kernel assistance off and tests
binary source equality/independence, logical size limits and tracked-file staging
under the same native sanitizers. These are bounded tests, not exhaustive proofs.

CI uses an exact compiler pin, commit-pinned GitHub actions and read-only workflow
permissions. Its runs are linked from the repository's Actions tab. Publication
also checks a fresh clone, the README commands, public metadata/default branch,
license detection and private vulnerability reporting.

## Independent review

The original publication review covers filesystem/process boundaries, dependency and
package behavior, supported-platform/limit claims, third-party provenance and
tracked history. Reproductions identified archive modes affected by caller
umask, executable local Git fsmonitor configuration and invalid scaffolded
library namespaces. All three fixes and their regression tests passed independent
re-check. The review also corrected an overstatement about crash durability: metadata retains
file syncs, but there is no parent-directory sync guarantee after rename.

## Measured results

Measured on 2026-11-04 from clean application source
`16b75c1ad4e99e93ece718383d8ae2c7c76231c0`, compared with
`1738da1e821400b4dc84af3120610d5f30257bd8`. Both binaries used `make build`,
Goose `eadca40` / runtime `3025e5810379`, default optimized C backend (`-O2`),
and GCC 16.2.1 20260810. The native adapter uses C11, `-Wall -Wextra -Werror`.
Host: Intel Core Ultra 7 258V, Linux 7.2.11-arch1-1 x86-64, glibc 2.44.
Benchmark processes were pinned to logical CPU 1 on a shared machine. These are
warm local CLI measurements; other host activity and filesystem state can affect
them. No network, cold bootstrap, cross-machine ranking or Cargo comparison is
measured. This documentation/data commit changes no measured application code.

See [bench/README.md](bench/README.md) for the harness and fixture definitions.
The paired command used `HONK=.build/honk`,
`HONK_BASELINE=.build/honk-before-second-audit`,
`HONK_BASELINE_REVISION=1738da1e821400b4dc84af3120610d5f30257bd8`,
`AUDIT_SAMPLES=9` and the pinned `GOOSE` executable. `AUDIT_TEMP_ROOT` was unset
for tmpfs and set to `$PWD/.build` for btrfs; `AUDIT_REPORT` selected the raw file.
Each binary received nine samples per workload, alternating execution order.
Raw reports retain every sample, binary hashes and clean-source provenance:
[tmpfs](bench/results/paired-tmpfs.json), [btrfs](bench/results/paired-btrfs.json).

All times below are milliseconds, median with observed minimum–maximum.

| Filesystem | Workload | Baseline | Reviewed code |
| --- | --- | ---: | ---: |
| tmpfs | 1,200 directories | 38.91 (37.48–39.96) | 39.26 (38.17–40.57) |
| tmpfs | 120 production dependencies | 48.15 (46.70–50.08) | 48.57 (45.28–50.59) |
| tmpfs | 120 dev dependencies | 18.71 (18.18–21.67) | 19.00 (18.28–20.41) |
| tmpfs | 32 MiB binary assets | 40.69 (38.99–42.61) | 36.35 (34.62–38.12) |
| btrfs | 1,200 directories | 91.89 (89.02–94.39) | 92.68 (87.67–96.85) |
| btrfs | 120 production dependencies | 287.51 (271.05–298.79) | 80.92 (75.12–83.22) |
| btrfs | 120 dev dependencies | 26.03 (25.45–26.75) | 26.10 (25.14–27.24) |
| btrfs | 32 MiB binary assets | 30.99 (28.70–32.41) | 21.50 (20.07–23.66) |

The btrfs production-graph workload benefits from omitting syncs for disposable
staging files. That gain does not appear on tmpfs. The asset workload benefits
from kernel-assisted independent copying where supported. Other workloads show
small slowdowns within overlapping sample ranges; those results are retained
and do not establish an improvement or a general regression bound.

[Warm CLI samples](bench/results/cli.json) use `HONK=.build/honk` and the same
`GOOSE` with `python3 tests/bench.py`, 25 samples per command:

| Command | Median (ms) | p95 (ms) | Minimum–maximum (ms) |
| --- | ---: | ---: | ---: |
| version | 1.81 | 2.07 | 1.60–2.12 |
| metadata | 1.92 | 2.27 | 1.84–2.29 |
| warm check | 9.90 | 12.68 | 8.95–19.29 |
| warm build | 220.59 | 227.79 | 210.48–230.63 |

## Publication validation

The measured source passed 49 CLI integration cases, Goose core contracts in
both JIT and native execution, process probes, 213 malformed-import cases and
FIFO rejection. GCC ASan/UBSan with leak detection, Goose debug checks and no
bounds-check elimination passed the integration/security suites. The forced
portable-copy sanitizer suite passed, as did Clang static analysis. These
checks do not prove the absence of bugs or establish production stability.

A fresh remote standalone clone at that source revision completed a cold
`make setup`, `make check test security`, `make build`, then the README sibling
application `new`, `run` and `check --frozen` commands; the checkout stayed clean.
The exact-source [CI run passed](https://github.com/carabistouflette/honk/actions/runs/41805286576),
including sanitizer, portable-copy and benchmark jobs. Subsequent publication
commits contain documentation/results only; GitHub Actions records validation
of the final published revision separately.

## Follow-up deep audit

The [2026-11-04 follow-up audit](docs/AUDIT-2026-11-04.md) records subsequently
fixed bugs, independent rechecks, expanded GCC/Clang validation and complete
paired samples against published `9874ad5`. The original measurements above
remain tied to their stated source revisions.

The subsequent [source and signal audit](docs/SOURCE-SIGNAL-AUDIT-2026-11-04.md)
records six further reproduced fixes, the 62-case suite, independent rechecks
and paired samples against `f427cd1`, including all slower results and remaining
process-group cancellation limits.

The [generated source/cache recovery audit](docs/CACHE-RECOVERY-AUDIT-2026-11-04.md) records five additional fixes, the 66-case suite, cache migration rules and all paired CPU3 samples against `04f7ddf`.

The [process consumer checkpoint](docs/PROCESS-CONSUMER-2026-11-04.md) records the goose-process migration, signal/ownership fault tests, normal/GCC/Clang/portable validation, review state and paired caller measurements with full provenance.

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
make diagnostics-bench-smoke
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

## UTC diagnostics integration

The opt-in diagnostic file now receives canonical UTC timestamps through the
published goose-log v0.1.3 adapter (`e93a71c0ff2f852b2d68f0a2c70f25ded3e8893a`)
and goose-time v0.1.0 (`343887caeee0a1f4e2e536ff322fcafb454e11bd`). The selected
source/license bytes are vendored and checked; the logger core remains unchanged.
Native adapters, compiler pin, monotonic durations and terminal cleanup policy
are unchanged. The README documents the opt-in record format change.

Validation passed normal formatting/type/contract/CLI/HTTPS/security checks,
the full GCC and Clang sanitizer and portable-copy suites, standard benchmark
smokes, and the new paired diagnostics smoke with both compilers. The dedicated
probe also passes release/debug and standalone optimized/debug sanitizer builds;
it covers i64 timestamp endpoints, filtering, callback counts, configuration and
failure latching, borrowing and output ownership. A fresh standalone clone of
the committed implementation passes `make check build` and all five text/package
integration tests. Those tests compare the added vendored source/license bytes
inside the source archive and preserve the lockfile.

Independent implementation and test reviews found no blocking issues; a further
review checked the paired harness and replayed its verifier controls. The
[retained measurements](bench/utc/results/README.md) identify clean source
`e092d63c15e13958d26e3b2982d35a468f03ab7d`, the immutable pre-integration baseline,
all 84 measured batches and a replayable 24-batch smoke corpus. Instrumentation,
different record sizes, optimized disabled paths and shared-host noise prevent
an exact isolated UTC-cost or general speed-ranking claim. These bounded checks
do not establish cross-platform support or production stability. Existing release
tags remain unchanged.

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

The [HTTPS metadata consumer report](docs/HTTP-METADATA-2026-11-04.md) records fixed-origin request policy, dispatch/output/state-isolation tests, real loopback TLS and GCC/Clang sanitizer validation, the explicit live smoke and remaining transport limitations.

The [diagnostics integration report](docs/DIAGNOSTICS-2026-11-04.md) records the final combined checks, native import exclusion regression, fixed-record privacy and file-failure tests, exact library/component pins, and current CLI/workload samples.

## Controlled service stability checkpoint

An independent, isolated public clone of production source
`453aa53dc7b20622782423c64cc180097f653650` passed a bounded real compiled-Goose
service soak: natural exits and direct SIGINT/SIGTERM cancellation, with project
and cache locks checked during operation and after return. All 24 scenarios
passed; session-validated child identities were gone, controller descriptor
checks passed and no unwaited children remained. No runtime defect or patch
release was justified by this workload.

The immutable [report](https://github.com/carabistouflette/goose-process/blob/c609a65695444752c46a9fef82dbded1151d623a/bench/results/honk-soak-2026-11-04.json),
[method and limitations](https://github.com/carabistouflette/goose-process/blob/c609a65695444752c46a9fef82dbded1151d623a/bench/SOAK.md)
and [harness](https://github.com/carabistouflette/goose-process/blob/c609a65695444752c46a9fef82dbded1151d623a/bench/soak_honk.py)
retain exact consumer/compiler/executable/fixture/harness identities and each
outcome. The harness hash was independently compared with that immutable Git
object. Review findings in the initial harness's identity/timeout cleanup were
fixed before the recorded run; they were not Honk runtime findings.

This is short controlled functional validation, not hours or days of uptime, a
throughput or memory benchmark, or a guarantee about arbitrary descendants or
signal storms. The existing terminal/recovery regressions exercise separate
paths. The evidence does not claim Cargo parity or remove the documented
platform, trust and cleanup limits.


## Experimental 0.1.0 release checkpoint

The accepted editor integration is public merge
`1ce304fe9e672ab8452e34dd888f0f540653fc79`, whose tree matches reviewed head
`866e5853bfcbeef1ad2069126fcb8979a355c85e`. It pins TOML
`c1c703f8dd4ac4e0ebc95f35981e87becad76957` and goose-toml-edit
`cedb2c3c98affbeb45bd34bc7a6618f5a9b75ad0`. The integrated five-case CLI suite
checks byte preservation for LF/CRLF, inline/dotted/header dependency syntax,
comments, EOF, missing sections, resource bounds and atomic rejection. The
editor owner also completed 5,107 oracle calls, independent review and both
native sanitizer toolchains before merge.

The [reviewed-head matrix](https://github.com/carabistouflette/honk/actions/runs/41883903729)
and [merged-main matrix](https://github.com/carabistouflette/honk/actions/runs/41885151398)
passed with GCC and Clang. An independent fresh public clone passed vendor
verification, build, frozen self-check and self-package verification using the
exact pinned compiler and isolated cache directories.

The release preparation changes only CLI version text and documentation after
that merge. The local normal release checks (`make format check test security`),
Clang static analysis of both native application files, and optimized-Python
vendor verification passed. Final sanitizer and standalone release-candidate
checks are release gates; their completion is recorded in the release notes and
the exact candidate's hosted CI. No library, native adapter, compiler pin or
lockfile is changed by release preparation.

Unfinished Git-tag requirement selection and the pending SemVer
consumer-overload fix are excluded from this release tree. Existing package
version validation and workspace selection use the accepted parse/compare API;
this CLI does not expose requirement-based dependency selection.


## Unreleased Git version workflow

The concrete transport/lock behavior follows
[GIT-VERSION-DESIGN.md](docs/GIT-VERSION-DESIGN.md).
`tests/tag_catalog.goose` covers strict LF/object/ref parsing, sorted duplicate
conflicts, non-adjacent annotated peeling, 4,096 base tags, 8,192 raw rows and
exact/exceeded 1 MiB input. `tests/version_deps_cli.py` uses real Git behind one
explicit test-only HTTPS-to-local shim. Its seven cases cover highest numeric
selection, prereleases, aliases/build ties, moved commits, allowed same-commit
tag-object replacement, declaration/lock validation and failed-lock preservation.

The transport log proves both query and fetch absence for warm/cold frozen and
offline paths. Online locked rehydration asserts that every new fetch argument
names the old locked commit OID, despite a moved remote tag and retained bare
objects. These checks are stronger than observing the compiled answer alone.
A separate adapter deadline probe requires a child readiness marker before
asserting timeout cleanup, avoiding launch-failure false passes.

Full normal/typecheck/security, GCC/Clang ASan/UBSan/debug/no-BCE and portable-copy
suites passed. After the existing read-only review requested explicit fetch
proofs, the same seven cases passed with those assertions under normal, GCC and
Clang builds. The review also narrowed movement claims to commit identity and
qualified the general no-deadline documentation. No registry, graph solver, tag
signature verification or frozen-v0.1.0 feature is implied by this evidence.


## Canonical dependency editor adoption

The [isolated acceptance record](docs/results/canonical-editor-acceptance.json)
identifies public consumer base `1e0a117d5c4b11bfa1d9342314b2f04bb8e63a8b`,
the tested staged tree, compiler binary/source identities, all nine canonical
source/license hashes and wrapper source/license hashes. Fresh anonymous clones
verified canonical `de7dfe092f6d72811417355044e5d024d5600613`. Both normal and
frozen self-check/package passed with unchanged locks, identical archive bytes
and an inspected source-only export, alongside five editing and seven Git
workflow methods.

Companion candidate `b9b6ab1b8d9defb9c296891d57311a2162ebddb7` had both exact-head
validations green. Its runtime graph is unchanged from the earlier reviewed
source; merged/released `ae32f13d69b69c9604a44d7acd71d2f966daef35` has the exact
same Git tree `45100cfbaa13720fab07efb90c94b3490adf7462`. The full published merge
revision is used in Honk. The wrapper calls only the canonical legacy profile;
public behavior, aliases, limits and error bytes are retained. Honk's previous
private editor implementation is removed.

The upstream [parity/ownership record](https://github.com/carabistouflette/goose-toml-edit/blob/ae32f13d69b69c9604a44d7acd71d2f966daef35/docs/results/adapter-de7dfe0-validation.json)
and [both paired timing series](https://github.com/carabistouflette/goose-toml-edit/blob/ae32f13d69b69c9604a44d7acd71d2f966daef35/bench/results/canonical-adapter/README.md)
retain material regressions and shared-host sensitivity. They measure full
library calls, not end-to-end Honk commands. This adoption centralizes the
editing implementation; it does not claim a universal speedup.

The adoption also corrects a historical TOML revision in the notices table and
adds a revision-presence guard to vendor verification. An isolated negative
probe rejects stale notices even under optimized Python; matching pins pass.
Frozen Honk v0.1.0 remains unchanged.


## Recovery diagnostic SIGPIPE regression

A local real-transfer fault reproduction on the pre-fix adapter terminated with
SIGPIPE before recovery could kill/reap its silent child. A private subreaper
proved that the child remained alive and cleaned it through a reserved owned PID
and pidfd. Bypassing only the recovery warning made the same regression pass.
The full CLI fault path independently reproduced the orphan before the fix and
proved cleanup complete after it. Later ordinary CLI error output can still
receive SIGPIPE after cleanup; this change protects the ownership-critical
diagnostic without installing a global signal policy.

`tests/process_cli.py` exercises the real library transfer and application
recovery with readerless stderr under default, ignored, custom-handler, blocked
and already-pending SIGPIPE states. The native fixture checks the real lock and
normalized SIGCHLD through denied waits, then checks actual reaping and restored
disposition/mask/pending state. The controller uses a private subreaper and
pidfds to clean failed fixtures, including registration failures.

The readerless-stderr case routes sanitizer reports to a private file and
requires no report, with leak detection enabled. The fixture first asserts
Honk restored its intentionally ignored SIGCHLD, then restores the fixture's
original waitable policy before LeakSanitizer starts its own tracing child.
This avoids autoreaped sanitizer-helper status warnings; it does not weaken
the application's restoration checks or disable leak detection.


## Canonical alpha.3 successor adoption

The current graph pins canonical TOML `fe849141405009e36e1cce6eb479b395eae18f1a`
and released companion v0.1.1 `f8d1b1664a86b768a6f1375636d9b2c3a440aa31`.
Only `source/editor.goose` changes among the nine canonical vendor files; the
companion adapter and both licenses remain byte-identical. Each file is verified
against its public Git object and recorded SHA-256 in `vendor/manifest.json`.

One isolated fresh-public consumer acceptance tested candidate `44c99ad` on
Honk `f12d88a`: check/build, five dependency-editing and seven real Git-version
CLI cases, normal/frozen check and package all passed. The lock stayed unchanged;
normal and frozen archives matched (127 files, 15 required exports compared, no
generated state). The companion release has the identical tree
`a2a9534d317539ab801afd6ba1313abc70fe6e84`, bridging that acceptance to the
released pin. The acceptance excluded the separate SIGPIPE corrective commit.

Upstream's tested `debe1ab` to released `fe849` bridge changes only approved root
README/CHANGELOG files. The older `de7` to `fe849` range includes engine work.
The upstream successor parity/ownership evidence is
[recorded at the released companion pin](https://github.com/carabistouflette/goose-toml-edit/blob/f8d1b1664a86b768a6f1375636d9b2c3a440aa31/docs/results/adapter-fe849-validation.json).
Historical timing results remain qualified in their original reports; this
adoption introduces no new performance claim.

## Honk 0.2.0 workspace exercise

The released `855fb0552aefd5f0c033826af64f3bdd09ae6482` binary was exercised
through a useful version-policy CLI, two workspace members, and real public
HTTPS Git SemVer source. Workspace check/test, application exit codes, update,
warm and cold locked/offline behavior, exact-OID recovery, unchanged locks and
both exported source packages passed. No runtime defect was reproduced in this
bounded exercise; the new example/controller preflight findings were corrected
before the final series.

The [report and all raw samples](bench/results/workspace-v020/README.md) retain
36 direct-Git warm calls in nine shuffled rounds from clean driver `57ba12ea`,
CPU0 affinity with shared-host limits, plus first-use/network observations.
The earlier `1b104190` controller series remains as instrumentation evidence:
its Python Git wrapper also handled local cache checks, and timed polling added
latency. Both series used the same Honk binary. The final driver uses pidfd exit
notification and direct Git for first check/build and warm measurements, with
separate instrumented functional proofs. Controller exit/timeout, descriptor
and wait-status checks pass under normal and inherited-ignored SIGCHLD.

These measurements describe the stated small workload. They do not assign
build time to staging versus compiler work or establish universal performance.
The release source and immutable v0.2.0 tag are unchanged by this report.

## Warm command phase diagnosis

The [phase report](bench/results/warm-phases/README.md) retains two diagnostic
series against the same application source, including all raw samples, tool
hashes and an untimed syscall observation. The three-round shuffled series
attributes about 474 ms of a 537 ms median selected warm build to the compiler
invocation; staging is about 12 ms, while publication varies and retains its
file sync. This is instrumented phase attribution, not a matched speedup.
No runtime optimization, skipped validation or executable cache was adopted.

## Compiler path compatibility correction

A local two-project regression reproduced a source-selection defect in frozen
Honk v0.2.0 (`855fb055`): the pinned compiler's backslash package separator
normalization could select a sibling staged dependency when the project root
contained a literal backslash. The fixture expected one dependency value and
observed the sibling's value. No remote target or third-party data is involved.

Compiler-facing commands now reject that root before project state, graph
resolution or compiler work. Automatic source compiler bootstraps also reject
backslash cache paths; an explicit trusted `GOOSE` still works with that Honk
cache. Metadata and filesystem-only commands retain their existing behavior.
The native adapter, vendored libraries, compiler pin and lockfile are unchanged.

The two new public regressions in `tests/cli.py` verify all compiler command
rejections, preservation of the sibling source/executable, metadata handling,
and bootstrap refusal before a toolchain checkout. The project-root regression fails on
the frozen release; both new cases pass on the corrective source. Local `make check test security`
passed (71 CLI cases and the existing suites/213 malformed probes), as did both
new cases under GCC and Clang ASan/UBSan with debug checks and no bounds-check
elimination. Exact publication-head CI is recorded separately in the PR.


## Opt-in source-only build reuse

The bounded local `build/run --reuse-build` path keeps fresh dependency/Git
validation and independent staging, verifies copied artifacts using pinned
system-libsodium-backed SHA-256, and retains atomic output publication. It is
off by default. Native/embedded/unsupported inputs compile normally. The
indirect system compiler inputs must remain unchanged; see the explicit
[contract and limits](docs/INCREMENTAL-BUILDS.md).

[Retained development measurements](bench/results/build-reuse/README.md) include
all 144 observations, per-source/binary/tool/fixture provenance, substantial
standalone cold-population cost and conservative fallback. Those timings were
recorded before reconciliation with published UTC/v0.3.0 and the path guard;
they are not relabeled as publication-head measurements. The reconciled source
passed the full normal/security suites, all nine cache cases under GCC/Clang
ASan/UBSan, portable-copy/cache checks and normal/frozen self-check/package with
unchanged lock bytes and all tracked exports exact. Hosted publication-head
validation is a separate gate.

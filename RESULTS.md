# Validation and evidence

The preceding experimental release is [v0.4.0](https://github.com/carabistouflette/honk/releases/tag/v0.4.0)
at `f9f35e20e4407df56b2ad45310266c9238403144`. It passed the maintained
GCC/Clang CI suites, normal/security checks, fresh public clone/build/import
checks and normal/frozen self-check/package checks. Its tag archive has 242
files whose bytes and executable bits match Git.

- [Release verification](https://github.com/carabistouflette/honk/releases/download/v0.4.0/release-verification-v0.4.0.json): source, compiler, archive, CI and vendor identities.
- [Verification clarification](https://github.com/carabistouflette/honk/releases/download/v0.4.0/release-verification-clarification-v0.4.0.json): GitHub reported `immutable: false`. Matching hashes and preserved Git objects do not imply hosted immutability or permanent availability.
- [Functional workspace report](https://github.com/carabistouflette/honk/releases/download/v0.4.0/workspace-functional-v0.4.0.json) and [controller](https://github.com/carabistouflette/honk/releases/download/v0.4.0/workspace-functional-v0.4.0.py): one controlled two-application workspace, 18 checked commands, reuse/invalidation/fallback, multi-remove, explicit lock refresh and frozen packages. This is functional evidence, not timing or a broad stability claim. Exact-image replay needs the recorded binaries; rebuilds need not be bit-identical.

## Published 0.5.0-rc.1 candidate

[Publication evidence](docs/RELEASE-CANDIDATE.md) records passed candidate CI,
anonymous build and archive/download verification. The older local preparation
receipt remains separately scoped.
The [real-project watch receipt](bench/results/watch-stress-2026-11-07/README.md)
checks 514 intervals across two explicitly scoped frozen harness runs, including
real kernel loss, source failure/restoration, root changes and cancellation.
Its production source is development 8f2bb40; the candidate changes advertised
version strings and the compiled-watch version probe. Resource observations,
sampling errors and historical timing scope remain attached to that source.
[Native fallback/cache recovery](docs/NATIVE-REUSE-QUALIFICATION.md) separately
qualifies the unchanged conservative reuse policy.

## Watch integration qualification

Development source `34a25f46eb281f57746cc917c1fb67e6adcc50e7` adds the explicit,
nonrecursive check/test watcher. [Local qualification](docs/watch-validation.json)
records compiler/source identities and scope. Full format/check/test, security
and GCC ASan/UBSan suites pass; the targeted Clang sanitizer adapter passes all
17 watch cases. Controlled tests cover persistent corruption, exact ignored
batch limits, overflow recovery and delayed child cleanup. Three independent
reviews found no outstanding runtime blocker after fixes. A fresh local clone
and a manual two-run check using the real pinned compiler also pass.

The host's tmpfs quota interrupted one metadata compilation; rerunning with a
private disk-backed `TMPDIR` completed validation, including a final full normal
run. This is local evidence, not a hosted CI claim, performance ranking or
expanded platform qualification. [Watch scope and cleanup](docs/WATCH.md).

## Run the checks

With the matching compiler installed:

```sh
make GOOSE=/absolute/path/to/goose check test security
HONK_SANITIZER_CC=gcc make GOOSE=/absolute/path/to/goose sanitize portable
HONK_SANITIZER_CC=clang make GOOSE=/absolute/path/to/goose sanitize portable
```

`check` covers format/type checks and vendor consistency. `test` covers real CLI,
Git/path, cache, editing, process, metadata and logging behavior. `security` runs
malformed-import/FIFO probes. Sanitizers and portable-copy checks exercise the
native/generated code. These checks do not certify bug-free or secure software.

## Documentation examples

The [recorded checks](docs/results/docs-examples.json) cover the documented
matching-compiler build alternative, scaffold/run/frozen checks, local library
editing, and the materialized version-gate workspace: fetch/test/run/package
plus no-match/invalid-input exit codes. The application code and compiler pin
are unchanged from v0.4.0. A fresh compiler bootstrap is not repeated by that
check; unchanged bootstrap source/pin are covered by the release CI. No timings
are inferred from these correctness checks.

## Performance

The [v0.4.0 build-reuse measurement](bench/results/announcement-v040/README.md)
records one bounded workload with actual release binaries: 72 samples, cold
population, eligible hits and conservative fallback, with all medians/ranges.
No general command-latency ranking, throughput or Cargo comparison is claimed.
The [performance audit](docs/PERFORMANCE.md) identifies the measured code behind
each other retained series and why those older timings remain historical.
The [benchmark guide](bench/README.md) gives reproduction commands and limits.
All earlier samples, including slower outcomes, remain unchanged.

The [historical results log](docs/history/RESULTS.md) preserves earlier audits,
release checkpoints and tables. Use the source named in each record; a recent
date or matching compiler alone does not make an old whole-program result current.

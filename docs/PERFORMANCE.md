# Performance evidence and currentness

Audit baseline: released v0.4.0,
`f9f35e20e4407df56b2ad45310266c9238403144`. This documentation update changes
no runtime, dependency, compiler, build recipe or benchmark implementation.
The machine-readable [inventory](results/docs-currentness.json) records the
source comparisons and the original raw-artifact hashes.

## What the retained numbers mean

| Series | Measured implementation | How to use it |
| --- | --- | --- |
| [Released build reuse](../bench/results/announcement-v040/README.md) | v0.4.0 `f9f35e20` vs v0.2.0 `855fb055` | One current bounded workload; 72 samples, full cold/warm/fallback ranges, actual executable/compiler hashes and checked source bridge. |
| Initial CLI/filesystem audits | Individual revisions in each root `bench/results/*.json` | Historical CLI workloads, not v0.4.0 latency. Older reports identify the binary and advertised compiler but lack a full executable/compiler/dependency build attestation. |
| Process caller | `db81d8f` plus its recorded benchmark source; requested before `75d5d73` | Historical whole-implementation comparison. Later recovery changes prevent using it as current process latency. Recorded RSS is unusable for a memory comparison. |
| Git/path workspace | Honk v0.2.0 `855fb055`, harness identities in each report | A small earlier workflow, with all cold/network/warm samples and controller differences kept separate. |
| Warm phases | `65d4e97`, checked against v0.2.0 runtime | Instrumented diagnostic attribution, not a matched speedup or current phase cost. |
| UTC component | `e092d63`, older baseline `65d4e97` | The diagnostics/sink/logger/time component files match v0.4.0; root/build/driver inputs differ. An unchanged component does not make the old instrumented executable a new whole-Honk benchmark. |
| Build-reuse development | `1fdf5e5` prototype and `9e8c24a` second series | Preserve cold, warm and native-sidecar fallback costs. Later path/home guards, UTC/root and dependency changes mean old whole-CLI timings cannot be called current. |

The inventory checks full tracked implementation/build/vendor/compiler-pin
objects against the release, rather than trusting dates. A source label is not
proof of how a supplied executable was built. The stronger per-file metadata
and executable/compiler hashes in later records retain their actual scope;
missing older provenance is not invented. Dirty-source recipes and generated
instrumentation stay labelled as such.

## Current release

The v0.4.0 [functional workspace receipt](https://github.com/carabistouflette/honk/releases/download/v0.4.0/workspace-functional-v0.4.0.json)
shows actual compiler skipping on an eligible verified hit, content invalidation,
fallback, atomic edits and packages. It is not a latency or memory measurement.
It needs no timing rerun to support those functional claims.

The [v0.4.0 build-reuse record](../bench/results/announcement-v040/README.md)
uses frozen release binaries and the unchanged `bench/reuse.py`: nine shuffled
rounds per fixture/mode, 72 samples with full ranges. It retains slow population
and fallback as well as eligible hits. All listed runtime/build/vendor inputs
match the release and this documentation branch. This narrow current workload
does not update unrelated historical CLI, workspace or component numbers.

## Reproduction and limits

Use the [benchmark methods](../bench/README.md) and the exact source/driver named
by the report. Build the recorded flags and inputs, supply the recorded compiler
and actual executable identities, and use a fresh output location. Keep fixture
setup and warmups outside timed samples as specified by that method.

Retain the machine/OS/toolchain, filesystem, affinity, workload, units, warmup,
repeat count, raw samples and dispersion. Keep slower cases and outliers.
Cold Honk artifact state does not imply cold OS/compiler caches. A standalone
cache-populating build performs different work from an ordinary runtime-cache
build. Shared-host affinity is not isolation. Instrumented component batches,
network operations, process launches and whole CLI timings are different scopes.
No general speed, allocation-free, memory-leak, stability or Cargo-parity claim
follows from these small experiments.

For a retained report, compare the measured source with the release explicitly:

```sh
git diff MEASURED_FULL_SHA f9f35e20e4407df56b2ad45310266c9238403144 -- \
  honk.goose honk.build src native vendor GOOSE_REVISION Honk.toml Honk.lock
git show MEASURED_FULL_SHA:GOOSE_REVISION
sha256sum /path/to/measured/honk /path/to/measured/goose
```

The structured inventory records these object comparisons; an executable hash
alone does not attest a build, and matching source does not imply identical
executables. The new reuse record includes actual image hashes and the checked
release-to-docs source map.

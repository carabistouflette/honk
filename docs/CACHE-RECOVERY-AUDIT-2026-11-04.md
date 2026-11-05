# Generated source and cache recovery audit — 2026-11-04

> Historical report: results and test counts apply only to the source named
> below. They are not current v0.4.0/main performance claims. See the
> [currentness audit](PERFORMANCE.md). Raw records and slower results are unchanged.

Reviewed, clean measured source: `68b5d687badfa8c48296f7169e48c73d4d71059b`.
Baseline: `04f7ddf6e2591b8568ff21074565c7e912563f68`.
Two independent reviewers reproduced and rechecked five fixes and one limit
clarification. No implementation blocker remains in this reviewed scope.

## Findings and fixes

- A valid original source at exactly 1 MiB grew beyond that limit after import
  remapping, then failed a second read of Honk's own generated file. Only the
  post-validation staged reread now permits 8 MiB. A compile-time bound covers
  1 MiB original plus 256 worst-case JSON-escaped mapped paths. Original reads
  retain the strict 1 MiB regular-file/no-follow limit. Run/test/bench at exactly
  the original limit pass; adding one byte still fails. Lazy per-target prelude
  preparation remains unchanged, avoiding eager work before an early failure.
- A failed compiler build could leave a binary accepted on the next invocation.
  Managed caches now require successful completion, matching checkout and a
  validated advertised version. The marker is written only after successful
  build and verification. A failed builder advertising a plausible version is
  rejected offline; an online retry completes successfully. Explicit matching
  GOOSE paths, including symlinks, remain supported. The fault fixture uses real
  Git with a small custom pinned source and a compiler wrapper, so it does not
  require the selected compiler installation itself to be a Git checkout.
- Bare Git initialization could create a directory then fail before identity
  publication, permanently breaking retries. Initialization now publishes its
  identity and directory transactionally. Legacy incomplete initialization is
  recoverable only without registered worktrees; ambiguous corrupt identities
  and actual identity mismatches still fail closed.
- Source repair could retain an old ready marker after a failed worktree add,
  causing later retries to skip recovery. Readiness is invalidated before repair
  and restored only on success. Real local Git fault regressions cover failed
  initialization, legacy partial state, source eviction, failed repair and retry.
- Clean omitted failed package staging and its file list. Both are now removed
  through the existing safe removal boundary. A failed package verification
  followed by clean leaves neither behind.
- Discovery's existing 1 MiB per-directory filename-list limit was undocumented.
  README and diagnostics now explain it; the cap was not removed or raised.

## Validation and migration

All 66 integration cases, Goose JIT/native core contracts, process probes and
213 deterministic malformed-import probes plus FIFO rejection pass. GCC and
Clang ASan/UBSan with leak detection, debug checks and no bounds-check elimination
pass; forced portable-copy suites pass on both. Clang static analysis is clean.
The source [CI run](https://github.com/carabistouflette/honk/actions/runs/41827591894)
records both compiler jobs, including setup/check/test/security/sanitizers and
benchmarks. These bounded checks do not prove absence of bugs or Cargo parity.

**Migration:** compiler caches made before completion markers must undergo one
online rebuild/validation or use explicit matching GOOSE before offline reuse.
This is fail-closed provenance handling, not binary authentication: tools and
private cache ownership remain trusted as described in SECURITY.md. Git/cache
fault fixtures substitute local transport or CMake only within tests; production
HTTPS policy is unchanged. Compiler/library pins and bootstrap are unchanged.

## Paired measurements

Use [bench/README.md](../bench/README.md), optimized native Honk/default C backend
`-O2`, pinned Goose eadca40/runtime 3025e5810379, GCC 16.2.1, Intel Core Ultra 7 258V,
Linux 7.2.11-arch1-1/glibc2.44. Both binaries used identical flags. Nine samples
per binary/workload alternate order after warmup; all samples are retained.
Logical CPU 3 affinity on a shared host, with no exclusive-resource claim or
network in timed work. Fixture creation is untimed. Shared-host variability and
overlapping ranges limit interpretation; slower results are not omitted.

Reproduce with HONK and HONK_BASELINE pointing to the matching builds,
`HONK_BASELINE_REVISION=04f7ddf6e2591b8568ff21074565c7e912563f68`, `AUDIT_SAMPLES=9`,
matching GOOSE, and `taskset -c 3 python3 tests/audit_perf.py`. Leave
AUDIT_TEMP_ROOT unset for tmpfs or set it to a btrfs directory; AUDIT_REPORT names
the output. Reports retain every sample, both binary hashes and clean-source
provenance: [tmpfs](../bench/results/cache-audit-tmpfs.json),
[btrfs](../bench/results/cache-audit-btrfs.json).

Milliseconds: median (observed minimum–maximum). No broad speedup is claimed.

| Filesystem | Workload | Baseline | Reviewed source |
| --- | --- | ---: | ---: |
| tmpfs | 1,200 directories | 37.97 (36.04–39.18) | 37.96 (34.58–39.66) |
| tmpfs | 120 production dependencies | 45.89 (44.59–48.78) | 45.26 (42.49–48.72) |
| tmpfs | 120 dev dependencies | 18.48 (17.87–19.39) | 18.35 (17.95–19.99) |
| tmpfs | 32 MiB assets | 33.45 (31.32–80.20) | 35.08 (30.87–39.73) |
| btrfs | 1,200 directories | 89.05 (86.78–92.46) | 88.06 (84.92–96.25) |
| btrfs | 120 production dependencies | 75.12 (71.16–97.33) | 74.84 (72.85–79.58) |
| btrfs | 120 dev dependencies | 23.26 (22.19–25.89) | 23.38 (22.41–25.09) |
| btrfs | 32 MiB assets | 18.06 (17.63–19.54) | 18.33 (17.83–19.47) |

[Warm CLI samples](../bench/results/cache-audit-cli.json): 25 per command using
`taskset -c 3 python3 tests/bench.py` with HONK/GOOSE as above. Managed builds use
the default debug profile; the Honk manager is optimized.

| Command | Median (ms) | p95 (ms) | Minimum–maximum (ms) |
| --- | ---: | ---: | ---: |
| version | 1.67 | 1.94 | 1.54–2.26 |
| metadata | 1.83 | 2.00 | 1.68–2.09 |
| warm check | 8.74 | 9.40 | 8.49–9.58 |
| warm build | 210.28 | 218.20 | 196.58–221.92 |

The evidence commit changes no measured application code. Published-main checks
are recorded separately by GitHub Actions. Process-group cancellation limits,
trusted-project boundaries and lack of universal deadlines remain unchanged.

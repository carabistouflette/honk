# Source and signal audit — 2026-11-04

Reviewed and measured source: `4ac1a73d15de92eac2c7350dddc25d00756d4431`.
Baseline: published `f427cd1e39191b7ce6da06c6916f79487676a5ff`.

Two independent reviewers investigated remaining source/dependency boundaries
and native resource/cancellation behavior. Six new findings were reproduced,
fixed and independently rechecked. The review did not justify an unrelated
optimization or a general security/stability certification.

## Reproduced issues and fixes

1. **Ignored SIGCHLD:** an inherited ignored disposition automatically reaped
   children, losing exit status and invalidating zombie PID reservation during
   cancellation. Honk temporarily establishes waitable child handling, restores
   its original disposition afterward, and gives exec children the default
   disposition so compiler subprocess waits work too. The regression builds and
   runs a real program under inherited SIGCHLD ignore and checks its exit 7.
2. **Duplicate terminal Ctrl-C:** the terminal already signals every foreground
   group member. Honk could forward the same event again and interrupt graceful
   cleanup. Signal metadata now identifies kernel terminal SIGINT and avoids
   forwarding to a child still in the same group. A real PTY regression pauses
   Honk, starts child cleanup with Ctrl-C, resumes Honk, and verifies completion.
   Direct-PID SIGINT and existing SIGTERM cleanup are also checked.
3. **Entry suffix bypass:** a non-`.goose` entry escaped the normal source
   rewriting pass. An undeclared external import rejected in `main.goose` was
   accepted in `main.txt`; even package verification could accept that
   host-dependent archive. All manifest entries now require a safe relative
   `.goose` path before dispatch. Check/run/fetch/metadata/package regressions
   reject the bypass.
4. **Library adapter spelling:** a library entry such as `src/lib-entry.goose`
   worked alone but generated an invalid relative import in consumers. Library
   entries now require module-compatible path components; the adapter helper
   also guards binary self-import aliases. The exact 46 keywords were compared
   with the pinned compiler lexer. Uppercase, contextual names and builtin
   module names remain valid; actual `from`, `std` and `FN` consumers pass.
   Standalone binary filenames can retain other safe characters.
5. **Quoted roots:** an existing sourced import was correctly rewritten to an
   escaped generated path, then mistakenly rejected by the original-source
   scanner. Declaration discovery now recognizes generated mappings only after
   strict original-source validation/remapping. A quoted-root run succeeds;
   original escaped source declarations still fail. No escape decoder or new
   unvalidated original-source route was introduced.
6. **Entry-parent symlinks:** discovery could read through an internal entry
   parent symlink and commit a lock before staging rejected it. Existing
   descriptor-relative directory validation now rejects such parents before
   reading dependency entries; the previous lock remains unchanged.

## Validation

All 62 CLI integration cases, Goose JIT/native core contracts, subprocess probes,
213 seeded malformed-import cases and FIFO rejection pass. Full GCC 16.2.1 and
Clang 23.1.4 ASan/UBSan runs use leak detection, Goose debug checks and disabled
bounds-check elimination. Forced portable-copy suites pass on both compilers;
Clang static analysis has no diagnostics. Low-descriptor diagnostic probes fail
cleanly at limits 6/8/12 and succeed at 16/32 with a normal subsequent retry.
These diagnostics are bounded evidence, not exhaustive failure-injection proof.

The exact-source [CI run passes both compiler jobs](https://github.com/carabistouflette/honk/actions/runs/41815592189),
including setup/check/test/security/sanitizers/portable copies/benchmarks. A
fresh public HTTPS clone of that source passed check/test/security/build and
Honk self-check/package with `--frozen`, using an existing compiler built by the
previous recorded cold bootstrap at the unchanged exact pin. The checkout
remained clean. This audit did not change bootstrap or dependency-library pins.

## Paired local measurements

Methods: [bench/README.md](../bench/README.md). Nine alternating-order samples per
binary/workload after warmup, default optimized native Honk/C backend `-O2`,
Goose `eadca40` runtime `3025e5810379`, GCC 16.2.1, Intel Core Ultra 7 258V,
Linux 7.2.11-arch1-1/glibc2.44. Logical CPU 1 affinity; shared host, no exclusive
resource guarantee and no network in timed work. Fixture creation is untimed.

Reproduce with `HONK` and `HONK_BASELINE` pointing to matching optimized builds,
`HONK_BASELINE_REVISION=f427cd1e39191b7ce6da06c6916f79487676a5ff`,
`AUDIT_SAMPLES=9`, matching `GOOSE`, and `taskset -c 1 python3 tests/audit_perf.py`.
`AUDIT_TEMP_ROOT` was unset for tmpfs and `$PWD/.build` for btrfs; `AUDIT_REPORT`
selected each report. All samples, binary hashes and clean source provenance:
[tmpfs](../bench/results/source-signal-tmpfs.json),
[btrfs](../bench/results/source-signal-btrfs.json).

Milliseconds: median (observed minimum–maximum). Every workload is retained.
Mixed small differences and overlapping sample ranges do not establish a broad
speedup or a regression bound; notably the btrfs production-graph median is
higher and is reported as measured.

| Filesystem | Workload | Published baseline | Reviewed source |
| --- | --- | ---: | ---: |
| tmpfs | 1,200 directories | 37.33 (34.44–41.72) | 37.84 (35.40–38.74) |
| tmpfs | 120 production dependencies | 47.68 (45.96–52.30) | 48.01 (47.03–50.02) |
| tmpfs | 120 dev dependencies | 19.00 (18.28–39.46) | 19.20 (18.64–27.76) |
| tmpfs | 32 MiB assets | 38.96 (36.80–39.96) | 38.83 (34.32–40.67) |
| btrfs | 1,200 directories | 88.52 (85.76–93.18) | 86.94 (84.53–93.13) |
| btrfs | 120 production dependencies | 75.04 (74.43–80.39) | 78.70 (74.34–82.06) |
| btrfs | 120 dev dependencies | 23.33 (23.09–24.01) | 23.48 (23.11–24.38) |
| btrfs | 32 MiB assets | 17.94 (17.69–20.02) | 17.81 (17.42–19.58) |

The 25-sample [warm CLI report](../bench/results/source-signal-cli.json) uses
`HONK`, matching `GOOSE` and `taskset -c 1 python3 tests/bench.py`. Build uses the
ordinary default debug profile for the managed program; the Honk manager itself
is optimized as stated above.

| Command | Median (ms) | p95 (ms) | Minimum–maximum (ms) |
| --- | ---: | ---: | ---: |
| version | 1.69 | 2.07 | 1.51–2.21 |
| metadata | 1.78 | 1.96 | 1.69–2.01 |
| warm check | 8.85 | 9.76 | 8.49–10.39 |
| warm build | 216.02 | 224.68 | 211.08–234.59 |

## Cancellation limits

Scripted callers should signal Honk's PID. An external `killpg` user signal and
a direct `kill` have indistinguishable sender metadata, so a group-wide external
broadcast can still reach a same-group child twice through forwarding. This is
documented, not claimed fixed by the terminal-specific change. Honk does not
provide job-control/process-tree supervision or universal command deadlines.
See [SECURITY.md](../SECURITY.md). Trusted tools/projects and private cache
ownership remain required.

The audit report/raw samples do not change the measured application. Subsequent
validation of published main is available through GitHub Actions.

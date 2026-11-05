# Warm workspace phase observations

> Historical report: results and test counts apply only to the source named
> below. They are not current v0.4.0/main performance claims. See the
> [currentness audit](../../../docs/PERFORMANCE.md). Raw records and slower results are unchanged.

The largest observed warm build/run phase is the selected compiler invocation.
No application optimization was adopted: the small changes considered here do
not remove that work while preserving the existing checks and publication
semantics. This checkpoint adds a diagnostic tool and evidence only.

Measured application snapshot: `65d4e97d808e97cdcc2c6d1f783f440e89cb2786`.
Its 58 runtime/build/vendor/compiler/manifest/lock files are byte-identical to
release `855fb0552aefd5f0c033826af64f3bdd09ae6482`; the full file-hash proof is in
[verification.json](verification.json). The plain output oracle is the frozen
release binary SHA-256
`78701624fff932ff1aecdfeb9eefb6f793a8300116a9a05d5c1da6d7d356a511`.
The source transformation and actual diagnostic/compiler/tool binary hashes are
recorded with every report. Harness commit:
`bc2cece0b31a6409ef7d9294ae0aa41e4379f987`.

[shuffled.json](shuffled.json) records three shuffled rounds of the four commands
on the already warmed real Git/path workspace, using the reproducible
[phase driver](../../phases.py) and [method](../../PHASES.md). The instrumented
Honk itself is built normally; its selected application builds use Honk's
existing debug configuration (Goose checks, C backend `-O0 -g`). Compiler source
is pinned to `eadca409f68210893f366e60d0c2f0dc29a339be`; the actual compiler binary
SHA-256 is `7ffde13da95fbbdaa15b27419494fc9b71f2c91c0b4c4d732f51815e928a4b56`.
Linux x86-64, Intel Core Ultra 7 258V, btrfs, GCC 16.2.1 20260810; logical CPU0
on a shared machine. Affinity provides no exclusive isolation. Baseline stdout,
expected phase counts, workspace files/locks, instrumented source and actual
binary hashes were checked before/after as described in the method.

All times are milliseconds, median with observed minimum–maximum. Member
phases are summed **within each command sample** before taking the median.
Medians are separate statistics and need not add to the median overall wall.

| Phase | Workspace check (two members) | Selected build | Selected run |
| --- | ---: | ---: | ---: |
| Dependency resolution | 20.17 (19.14–21.18) | 9.92 (9.90–11.14) | 9.66 (9.46–12.56) |
| Compiler identity | 7.44 (6.97–7.50) | 4.41 (4.27–4.46) | 4.01 (3.86–4.23) |
| Source staging/remapping | 22.03 (21.65–26.19) | 11.74 (11.59–11.84) | 11.97 (11.60–12.05) |
| Root entry | 0.33 (0.31–0.60) | 0.16 (0.15–0.19) | 0.16 (0.15–0.16) |
| Compiler check/build | 58.53 (56.75–60.20) | 473.76 (463.25–476.04) | 469.29 (462.96–484.54) |
| Atomic publication | — | 36.53 (24.82–39.09) | 28.48 (27.94–34.00) |
| Application execution | — | — | 1.69 (1.58–1.74) |
| Overall instrumented wall | 120.45 (115.71–120.55) | 536.72 (534.11–550.21) | 539.45 (526.54–552.87) |

Workspace tree's two resolution phases sum to 19.09 ms (19.03–24.48), with
27.95 ms (27.71–33.59) overall wall. Remaining wall time includes ordinary CLI
work, formatting, probe writes, controller startup/wait and uninstrumented
boundaries; it is not assigned to a specific module. See the
[build phase chart](phases.html) for scale and observed ranges.

An initial sequential three-sample diagnostic is retained separately in
[exploratory.json](exploratory.json), with affinity CPU0/2 and its original
controller hash. Its two source transformation hashes match the published
probe transformation. Its build publication samples span 30.30–126.09 ms.
This earlier exploratory controller predates the reproducible driver; its
whole-command wall includes the same explicitly labelled diagnostic overhead.
No sample was removed or combined into the shuffled summary.

A separate **untimed** strace of the plain binary's warm build observed a
successful `fsync(6) = 0 <0.040322>` while publishing its 644,184-byte executable.
The trace also confirms the compiler launches the C compiler with `-O0 -g`.
The complete trace hash and sanitized excerpt are in verification.json; raw
exec/read/write arguments contain private absolute paths and remain local.
This is one traced observation, not an explanation of all publication variance
or a measurement of production syscall latency.

## Decisions from these observations

- Keeping the private compiler executable across staging cleanup was considered
  and rejected by source inspection: pinned `src/build.h` always calls
  `Builder::Link` in `BuildExecutable`, regardless of an existing final output.
  It would not enable executable reuse. The exact inspected source blob/hash is
  recorded in verification.json.
- Removing the publication sync would weaken the existing file-sync guarantee.
  The trace shows sync can be material here; it remains enabled. Replacing the
  independent copy with a rename/hard link would require a separate ownership
  design and is not justified by this small observation.
- Honk still validates cached Git identity/dirty state, stages independent
  source snapshots, compiles privately and publishes atomically. No checks or
  compiler debug options were disabled. No executable reuse/cache was added.
  A future incremental-build design must cover compiler/native inputs,
  environment, source snapshots, invalidation and failed builds explicitly.

This small diagnostic establishes where to investigate next, rather than a
speedup, Cargo comparison, production stability or regression bound. Altered
source/build paths and numeric probes prevent comparison against the earlier
plain CLI timings. The concurrent logging study used an independent binary,
workload and CPU6; no logger-cost attribution is made here. Existing release
source and tags remain unchanged.

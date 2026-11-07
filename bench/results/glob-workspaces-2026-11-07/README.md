# Honk workspace glob profile — 2026-11-07

Filtering is a negligible part of these complete commands. This profile supports keeping the matcher/API unchanged. It does not establish a ranking against other libraries or identify a new speedup.

Consumer source: `17f83c02103842f707f7d1e5a888d7e91e7047c4`, with the vendored alpha.4 prepared matcher. Generated workspaces contain 1, 4 or 8 complete snapshots of that real Honk project and its vendored dependencies. Each package runs the real `tests/core.goose` through `test --workspace --frozen --filter tests/**/core*.goose`. The layout is a scaling fixture, not a naturally occurring production workspace.

Five sequential shuffled rounds on CPU 2, warm caches and a shared host: 30 full command samples. Every binary/size first passes an untimed output-equivalence check. Inputs, locks, source snapshots, binaries, compiler, stdlib and tool hashes are guarded before each sample and after measurement. Own builds finished before timing; other host activity was uncontrolled.

A normal binary measures whole-command wall time using monotonic time and pidfd readiness. A separate private build times staging, candidate discovery and the filter loop. Filtering includes matcher calls, status checks, selected-path copies and timer overhead. Its timing bounds matcher work within that instrumented loop; source instrumentation can affect code generation, so it is not an exact cost decomposition of the normal binary. The remaining phase time includes compilation, target execution and other command work; those are not separately attributed.

## Complete command time

Seconds, median **[minimum, maximum]**. The two columns are normal and instrumented builds, not before/after optimization.

| Packages | Candidate paths | Selected tests | Normal command | Instrumented command |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 8 | 1 | 1.6230 [1.6105, 1.6624] | 1.6168 [1.6151, 1.7092] |
| 4 | 32 | 4 | 6.4219 [6.3844, 6.6857] | 6.4722 [6.2815, 6.5982] |
| 8 | 64 | 8 | 12.7752 [12.6022, 13.1805] | 13.0295 [12.7728, 13.2469] |

## Instrumented phases

Phase sums across all packages in one command, median **[minimum, maximum]**. Filter share is the median per-sample filter/whole-command ratio in the private build.

| Packages | Staging ms | Discovery ms | Filter µs | Filter share |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 36.3463 [34.7687, 55.8876] | 0.1158 [0.1090, 0.1383] | 4.0210 [3.5460, 4.6390] | 0.000249% |
| 4 | 174.7582 [146.1169, 203.3143] | 0.4682 [0.4577, 0.5081] | 16.3120 [15.3950, 17.6010] | 0.000253% |
| 8 | 304.1620 [296.3266, 312.3712] | 0.9097 [0.8764, 1.0496] | 32.9260 [31.3680, 34.6340] | 0.000249% |

## Scope and reproduction

The largest fixture has 64 candidate test paths and selects eight tests. It scales package/source staging but does not saturate the 4096-source-file cap per package or establish matcher behavior for thousands of targets. No consumer upgrade or library release follows from this evidence. Honk already shares one prepared filter across workspace members.

[Complete raw report](raw.json.gz) is losslessly gzip-compressed and includes all samples, phase records and input/tool/binary identities. [Context](context.json) records the host/tool environment. [Private instrumentation patch](instrumentation.patch) is not applied to Honk. [Executed driver](executed-driver.py) preserves the exact script/hash; adjust its root, output and Goose paths for another checkout, use a new output directory and the pinned compiler, and run it from the goose-libs workspace. It imports the guarded `bench/glob_consumer.py` helper. Its two builds and fixture fetches finish before any warmups or measurements.

Run `python3 render.py` in the retained result directory to regenerate the report, summary and chart. New timing runs should use the same snapshot and layout; full-command values and tiny phase timings depend on the host and do not establish statistical significance or causal speedups. Product sources, matcher API, traversal checks and limits are unchanged.

# Prepared glob consumer — 2026-11-07

Before: `7583ebe4ccb19cca530ccd295359dd808d8de3c9` (alpha.1 direct matching). After: `9b19a470c0beed420cdc1a085003769185bcaf32` (alpha.3, one compiled filter shared across workspace packages). Both binaries are built from exact Git archives with the same pinned Goose compiler and GCC `-O2`. The executing driver is hashed separately.

Seven randomized sequential rounds per version/case, CPU 2, shared Linux x86-64 host and warm OS/compiler caches. Every invocation includes process startup and the identical GNU time wrapper. Test/bench include staging, target compilation and execution against one real Honk source snapshot, frozen at the before revision. No network or fixture construction is timed. One untimed invocation checks identical output for every version/case before timing.

[Raw samples and input/tool/binary hashes](raw.json) · [Reproduction and scope](../../README.md#prepared-glob-consumer-comparison)

These samples show no clear whole-command speedup: all before/after ranges overlap, and the prepared test/bench medians are slightly higher. Compiler/target costs dominate this small real project. Maximum-RSS observations likewise provide no clear reduction.

The later merge of terminal-progress main `441d1bfc67f1` changes runtime/build/vendor inputs. This report predates that merge and identifies only the two exact measured snapshots above; it is not a measurement of the combined build.

## Complete command wall time

Milliseconds, median **[minimum, maximum]**. A ratio above 1 favors the prepared version; overlapping ranges do not establish a reliable speedup.

| Case | Before | Prepared | Before / prepared median |
| --- | ---: | ---: | ---: |
| version | 9.500 [8.783, 9.995] | 10.104 [9.217, 10.501] | 0.940× |
| metadata | 9.680 [9.180, 10.706] | 9.582 [9.325, 10.484] | 1.010× |
| test_literal | 1657.411 [1635.807, 1697.429] | 1658.994 [1631.125, 1718.280] | 0.999× |
| test_recursive | 1642.794 [1617.112, 1682.102] | 1655.374 [1625.362, 1683.082] | 0.992× |
| bench_recursive | 2933.600 [2888.360, 3110.046] | 2947.916 [2890.324, 2989.433] | 0.995× |

## Observed maximum resident memory

KiB reported by GNU time: largest process/descendant high-water mark, **not simultaneous aggregate memory**. Zero reports remain unavailable observations. Median **[minimum, maximum]**.

| Case | Before | Prepared |
| --- | ---: | ---: |
| version | 6752 [6664, 6900] | 6908 [6720, 7100] |
| metadata | 6924 [6760, 7020] | 6912 [6776, 7156] |
| test_literal | 66920 [66860, 67060] | 66964 [66748, 67044] |
| test_recursive | 67048 [66912, 67052] | 66924 [66860, 67036] |
| bench_recursive | 73176 [72992, 73272] | 73264 [72972, 73456] |

## Commands

```text
version: honk version
metadata: honk metadata
test_literal: honk test --frozen --filter tests/core.goose
test_recursive: honk test --frozen --filter tests/**/core*.goose
bench_recursive: honk bench --frozen --filter bench/**/process.goose -- tiny
```

The filter is compiled once by construction and reused for every discovered path, including subsequent workspace members. These complete real-project workflows include costs beyond matching; their timings must not be used to claim the matcher microbenchmark ratios carry over to Honk. Startup controls and all slower/noisy cases are retained. Other host activity was uncontrolled. This record establishes neither cold-start performance nor a general CLI/memory ranking.

# Combined Honk alpha.4 consumer — 2026-11-07

Before `bb36d57e7148413f62531354119a8b396924daf3` uses alpha.3 prepared matching with terminal progress. After `00442fb552e800889fc50858459bb8b8317fc383` vendors published alpha.4 (`2022a04e1847490c9c76af91e1e5c01a3c6e3cc0`). Both exact Git snapshots use the same pinned Goose compiler, GCC and `-O2`. The executing driver hash matches the checked-in driver.

Seven randomized sequential rounds, six cases and 84 guarded samples, CPU 2, shared Linux x86-64 host and warm caches. Every invocation includes startup and the same GNU time wrapper. Test/bench include staging, compilation and execution of a fixed real Honk project at the before revision; target sources/dependencies stay identical across CLI binaries. The forced-progress case exercises selected-target terminal output. Every version/case receives an untimed output-equivalence warmup; no network/setup is timed.

**Results are mixed.** These samples establish no consistent whole-command speedup or maximum-RSS reduction. Matching microbenchmark ratios must not be projected onto complete commands. All slower cases and ranges remain below. Own heavy correctness/build jobs finished before retained timing; lightweight publication work and uncontrolled host activity continued.

[Raw samples and complete input/tool/binary hashes](raw.json) · [Method](../../README.md#prepared-glob-consumer-comparison)

## Wall time

Milliseconds, median **[minimum, maximum]**; lower is better. Ratio = before median / after median. Above 1 favors alpha.4. These observations are not statistical-significance or causal-attribution claims.

| Case | Alpha.3 | Alpha.4 | Ratio |
| --- | ---: | ---: | ---: |
| version | 9.051 [8.874, 9.658] | 9.497 [9.269, 10.256] | 0.953× |
| metadata | 9.703 [9.253, 10.350] | 9.959 [9.318, 10.622] | 0.974× |
| test_literal | 1751.097 [1649.556, 1839.625] | 1643.876 [1634.149, 1706.587] | 1.065× |
| test_recursive | 1645.399 [1638.112, 1749.411] | 1640.998 [1638.460, 1871.992] | 1.003× |
| bench_recursive | 2917.744 [2887.231, 3168.482] | 3027.917 [2896.020, 3172.531] | 0.964× |
| test_progress | 1649.699 [1631.185, 1860.062] | 1686.208 [1645.498, 1806.271] | 0.978× |

## Maximum resident memory

KiB from GNU time: largest reported process/descendant high-water mark, **not simultaneous aggregate memory**. Compiler/target processes dominate the test/bench observations. Median **[minimum, maximum]**.

| Case | Alpha.3 | Alpha.4 |
| --- | ---: | ---: |
| version | 6880 [6664, 7092] | 6856 [6648, 7056] |
| metadata | 7000 [6888, 7280] | 7032 [6828, 7164] |
| test_literal | 69660 [69444, 69740] | 69668 [69436, 69832] |
| test_recursive | 69720 [69552, 70704] | 69620 [69512, 69784] |
| bench_recursive | 73240 [72996, 73424] | 73064 [72948, 73408] |
| test_progress | 69648 [69516, 69896] | 69692 [69516, 69796] |

## Commands

```text
version: honk version
metadata: honk metadata
test_literal: honk test --frozen --filter tests/core.goose
test_recursive: honk test --frozen --filter tests/**/core*.goose
bench_recursive: honk bench --frozen --filter bench/**/process.goose -- tiny
test_progress: honk test --frozen --filter tests/**/core*.goose --progress always
```

Reproduce with `bench/glob_consumer.py --before FULL_BEFORE --after FULL_AFTER --include-progress --rounds 7 --cpu 2 --goose /absolute/pinned/goose --output NEW_DIRECTORY`, using the recorded commits and exact driver. Source inputs, generated lock, compiler/stdlib/tool and binary hashes are checked before each sample and after measurement. Linux pidfd readiness avoids timeout polling granularity; comparison reads are bounded. Shared-host warm-cache results do not establish cold-start, general CLI or aggregate-memory rankings.

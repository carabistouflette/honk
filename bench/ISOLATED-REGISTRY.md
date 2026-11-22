# Isolated registry comparison with Cargo

The benchmark covers synthetic registry graphs on a local HTTP server. It
checks the resolved versions and directed dependency edges in both lockfiles.
The graphs have 24 or 96 registry packages, with two forward edges per package
where available and two direct edges from the application. Each archive
contains a manifest, a minimal library and the same 4 KiB of deterministic
payload for both managers. The update publishes a release for one transitive
package and a release for an unrelated package. The benchmark checks that
only the selected package changes.

| Workload | Honk | Cargo |
| --- | --- | --- |
| Cold resolution | `update --isolated --dry-run` | `generate-lockfile` |
| Cold fetch | `fetch --isolated` | `fetch` |
| Frozen fetch | `fetch --isolated --frozen` | `fetch --frozen` |
| Targeted preview | `update --isolated --dependency NAME --dry-run` | `update -p NAME --dry-run` |
| Targeted update and fetch | `update --isolated --dependency NAME` | `update -p NAME`, then `fetch --locked` |

Cold cases start with empty manager caches. Frozen fetch uses the preceding
cold fetch's lock and cache. Preview and actual update start with identical
copies of that cache and lock. Each size has one excluded warmup round and
seven measured rounds, alternating which manager runs first. Archive
creation, index changes and cache copying are outside timing. The operating
system page cache remains in its normal state. Rust compiler information
probes and Honk's Goose version probe are included. Project compilation is
outside this benchmark.

Cold resolution measures the index-only workflow. Cargo also writes its lock.
Cold fetch includes index lookup, download, archive verification, extraction
and lock writing. The two cold measurements are independent, so their
difference is not an isolated extraction time. The JSON records the two
Cargo update steps separately. The workflow's wall time is their sum and
its peak RSS is the maximum reported by GNU time. Request counts include
index configuration and conditional requests that return 304. The comparison
covers loopback HTTP and small packages. Results can change with network,
archive size, graph structure, machine or filesystem.

## Reproduce

Build Honk with its pinned compiler using `goose build honk.goose -O2`.
Run the harness on Linux with GNU time, Python 3.11 or later, a qualified
Goose graph compiler and matching Cargo and Rust compiler binaries.

```sh
python3 bench/isolated_registry.py \
  --honk /absolute/path/to/honk \
  --honk-revision FULL_SHA_USED_TO_BUILD_HONK \
  --goose /absolute/path/to/qualified/goose \
  --cargo "$(rustup which --toolchain stable cargo)" \
  --rustc "$(rustup which --toolchain stable rustc)" \
  --sizes 24 96 --rounds 7 --output .build/isolated-registry-results.json
```

Set `--temp-root` to compare a specific filesystem. The default is the
system temporary directory. The harness validates lock contents, rejects
registry traffic during frozen fetch and checks download counts. It uses the
documented Cargo sparse-index format and conservative update behavior.
[Cargo registry index](https://doc.rust-lang.org/cargo/reference/registry-index.html) · [Cargo update](https://doc.rust-lang.org/cargo/commands/cargo-update.html)

## Recorded run

Run on 2026-11-21 on an Intel(R) Core(TM) Ultra 7 258V, Linux x86_64,
and tmpfs. Honk revision `1260f4f` was built with
`-O2`. The graph compiler advertised revision
`eeab7ee`. Cargo and rustc were the
installed stable 1.99.0 toolchain. The raw report records full identifiers,
the Honk executable hash, and every measured sample.
[Raw results](results/isolated-registry-cargo.json)

Wall time is median milliseconds with the observed range in brackets.
RSS is median MiB. Requests are median index/archive counts.

| Packages | Workflow | Honk ms [range] | Cargo ms [range] | RSS Honk / Cargo | Requests Honk | Requests Cargo |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 24 | Cold resolution | 78.0 [69.1–81.4] | 84.6 [71.7–89.9] | 17.7 / 38.5 | 24/0 | 25/0 |
| 24 | Cold fetch | 132.4 [127.7–139.6] | 153.7 [145.5–160.8] | 19.6 / 46.0 | 24/24 | 25/24 |
| 24 | Frozen fetch | 35.9 [30.5–36.4] | 66.0 [63.0–78.3] | 16.0 / 45.9 | 0/0 | 0/0 |
| 24 | Targeted preview | 36.7 [35.7–40.0] | 80.8 [72.8–89.3] | 18.2 / 38.5 | 1/0 | 25/0 |
| 24 | Targeted update and fetch | 43.9 [42.6–46.2] | 147.4 [145.9–156.3] | 19.7 / 46.0 | 1/1 | 25/1 |
| 96 | Cold resolution | 348.3 [309.3–356.4] | 232.7 [187.7–276.3] | 18.1 / 38.5 | 96/0 | 97/0 |
| 96 | Cold fetch | 511.0 [489.0–599.6] | 387.9 [364.0–417.7] | 19.5 / 46.0 | 96/96 | 97/96 |
| 96 | Frozen fetch | 162.1 [156.9–166.6] | 81.8 [76.2–88.3] | 16.6 / 45.9 | 0/0 | 0/0 |
| 96 | Targeted preview | 161.0 [157.0–178.3] | 235.7 [203.0–238.0] | 18.6 / 38.5 | 1/0 | 97/0 |
| 96 | Targeted update and fetch | 182.3 [171.6–186.3] | 314.0 [297.7–320.9] | 20.2 / 46.0 | 1/1 | 97/1 |

Honk had lower median wall time in every 24-package case and lower median
peak RSS in both sizes. At 96 packages, Cargo led cold resolution, cold
fetch and frozen fetch. Honk still led the targeted update workflows, with
one index request for the target instead of the registry configuration and
96 package-index requests. The two-command Cargo update-and-fetch workflow
includes a second process startup.

The 96-package frozen fetch is a priority for profiling. It sends no HTTP
requests yet takes roughly twice as long in Honk, so making HTTP faster
would have no effect there. The benchmark does not establish how much of
that time belongs to dependency solving, source validation or writing the
compiler graph.

## Frozen replay follow-up

On 2026-11-22, temporary monotonic timers split five frozen replays of the
96-package workload. Median phase times were 4.2 ms to read and validate
pins, 116.5 ms to solve the registry graph, 12.2 ms to verify cached sources
and manifests, and 4.2 ms to construct bindings. Compiler graph rendering
took 0.7 ms, checking the lock took 0.3 ms, and writing the graph took
0.2 ms. The timers omit startup, compiler probing, local source discovery
and lock text generation.

Cycle validation now computes each selected package key once and uses
catalog positions to find the target node. It retains the same cycle
check and cached source verification. Nine alternating frozen replays
with both `-O2` binaries against one warm cache took a median of 167.0 ms
before the change (153.4–170.5 ms) and 73.4 ms after it (70.3–80.0 ms).
All runs made zero registry requests and produced byte-identical lock and
compiler graph files.

A fresh seven-round run of the existing harness on the same 96-package
workload measured 75.7 ms for Honk (72.4–90.4 ms) and 74.5 ms for Cargo
(67.5–80.4 ms) in frozen fetch. The ranges overlap. Cold fetch was still
slower for Honk at 403.6 ms versus 345.9 ms. The Honk binary hashes and
per-round values are retained in the report.
[Follow-up raw results](results/isolated-registry-cargo-cycle-keys.json)

## Cold archive prefetch

On 2026-11-22, a five-run profile split the cold fetch on the 96-package
workload. The median catalog phase took 167.5 ms, including 130.2 ms in HTTP
transfers. Resolution including the catalog took 193.7 ms. Materialization
and package validation took 191.1 ms, including 132.9 ms in archive HTTP
transfers and 22.6 ms in extraction and tree hashing. The remaining time in
these phases includes cache and manifest work. Phase medians are independent.

After solving, the isolated client stages verified archive blobs with up to
four concurrent requests. The existing materialization path verifies each
blob or cached tree and checks the package manifest. In nine alternating
runs with new project directories and empty caches, the 96-package median
fell from 391.1 ms (362.7–438.6 ms) to 333.6 ms (315.4–391.8 ms). Each run
made 96 index and 96 archive requests. The lockfiles were byte-identical
and their versions and dependency edges matched the fixture.

Seven measured rounds of the full Honk/Cargo harness gave these cold-fetch
medians and ranges. RSS is the median process peak, in MiB.

| Packages | Honk ms | Cargo ms | Honk / Cargo RSS |
| ---: | ---: | ---: | ---: |
| 24 | 101.6 [97.4–110.9] | 141.4 [134.9–155.0] | 19.2 / 45.8 |
| 96 | 340.1 [324.7–349.8] | 346.9 [315.0–367.8] | 19.6 / 45.9 |

At 96 packages the cold-fetch ranges overlap. Cold resolution still took
217.8 ms in Honk and 192.4 ms in Cargo. The comparison uses loopback HTTP
and small archives. [Raw samples](results/isolated-registry-cargo-prefetch.json)

## Cold index prefetch

The isolated resolver batches up to four distinct known catalog requests and
parses the responses in solver order. The benchmark can add a fixed server
delay with `--index-delay-ms 5`. This applies equally to Honk and Cargo
index responses, including conditional responses and Cargo's registry
configuration request. Archives receive no artificial delay.

In nine alternating cold resolution runs with empty caches, 96 packages and
5 ms of delay per index response, prefetch reduced the Honk median from
779.7 ms (752.7–914.9 ms) to 425.0 ms (406.0–471.1 ms). The dry-run output
was identical and each run made 96 index requests and zero archive requests.
Without injected delay, the same paired test was more variable, with medians
of 250.0 ms before and 246.6 ms after. A separate three-round dry-run check
at 250 packages also preserved the output and request counts.

Seven measured rounds of the full comparison with stable Cargo 1.99.0 gave
the following medians and ranges on 96 packages. RSS is the median peak
process memory in MiB.

| Index delay | Workflow | Honk ms | Cargo ms | Honk / Cargo RSS |
| ---: | --- | ---: | ---: | ---: |
| 0 ms | Cold resolution | 165.2 [142.1–259.6] | 184.2 [174.6–201.3] | 22.3 / 38.5 |
| 0 ms | Cold fetch | 265.2 [241.6–342.1] | 383.6 [301.9–527.7] | 25.1 / 46.0 |
| 5 ms | Cold resolution | 445.8 [421.8–516.2] | 738.8 [719.3–769.1] | 22.2 / 36.5 |
| 5 ms | Cold fetch | 551.3 [537.2–573.5] | 896.5 [863.5–1060.7] | 23.2 / 45.9 |

The no-delay ranges overlap. Honk's batch buffer adds up to 4 MiB of scratch
space during online resolution. Frozen fetch bypasses it. The frozen runs
made zero registry requests and retained the existing lock.
[No-delay samples](results/isolated-registry-cargo-index-batch.json)
[5 ms delay samples](results/isolated-registry-cargo-index-batch-delay-5ms.json)

## Backtracking across many releases

Run the harness with `--backtracking --sizes 48 512` to vary the number of
compatible adapter releases while keeping the same three registry packages.
The root requests `adapter` and `pinning`. Each depends on `shared`.
`pinning` and the oldest adapter require exactly `shared 1.0.0`. All newer
adapters require exactly `shared 1.1.0`. Only the oldest adapter can produce
a graph with one release in each compatibility family. The cold fetch
checks both lockfiles against that graph and downloads exactly three archives.
The frozen replay checks for a byte-identical lock and zero network requests.

Seven measured rounds with Cargo 1.99.0, empty caches for cold commands and
no artificial delay gave these medians and ranges in milliseconds. Honk's
cold-resolution command previews its plan, while Cargo writes its lock.

| Candidates | Workflow | Honk ms | Cargo ms |
| ---: | --- | ---: | ---: |
| 48 | Cold resolution | 40.3 [37.2–49.4] | 46.6 [41.3–51.4] |
| 48 | Cold fetch | 47.0 [38.6–51.3] | 86.7 [82.4–93.8] |
| 48 | Frozen fetch | 28.0 [25.3–30.1] | 58.9 [53.8–69.8] |
| 512 | Cold resolution | 1175.6 [1123.3–1366.6] | 51.9 [47.9–59.0] |
| 512 | Cold fetch | 1170.5 [1137.5–1266.5] | 95.2 [83.1–103.5] |
| 512 | Frozen fetch | 28.3 [23.9–30.2] | 63.5 [50.7–70.1] |

At 512 candidates, median peak RSS during cold resolution was 23.8 MiB for
Honk and 38.5 MiB for Cargo. The cold-resolution request totals remained
three for Honk and four for Cargo at both sizes. The results include HTTP
transfer and parsing but do not measure each manager's resolver decisions
or isolate their individual phase costs.
[Raw samples](results/isolated-registry-cargo-backtracking.json)

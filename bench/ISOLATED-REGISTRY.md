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

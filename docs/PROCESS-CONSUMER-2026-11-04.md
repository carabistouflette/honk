# Process consumer validation — 2026-11-04

Production checkpoint: `db81d8fe552b233231ff8ff29af9e75761484cd6` on `feat/process-consumer`, based on `75d5d73647467040e7c3634cd9473aeff3859c18`. This report describes a feature checkpoint and does not by itself claim integration into main.

Honk now uses unmodified goose-process `191a9423197e850e699eff500620a5c7d111aa54`. Application handlers only latch pending signals; normal forwarding uses pidfds and immediate identity observations. Explicit Child timeout 0 preserves server lifetimes; 20 ms steps keep the application loop responsive. Git/tar environment filtering, inherited stdin/live stderr, 1 MiB stdout capture and shell-style status precedence remain application policy. Exceptional transferred-child recovery retains locks and waitable SIGCHLD until terminal wait/ECHILD, including denied cancellation and recovery waits. Launch-window terminal classification remains best effort; descendants are unsupervised.

## Validation

Normal `make format check test security`, GCC/Clang `make sanitize portable`, and Clang static analysis of `native/platform.c` passed. Existing 69 CLI, 5 text and 5 SemVer methods passed; the new 4-method process suite checks independent stderr bytes, inherited stdin, exact/exceeded capture/argv bounds, pre-start cancellation without launching, post-start direct TERM via one pidfd signal, and real native ownership transfer/recovery. The fault route injects a monotonic-clock error and denies both cancellation routes, then denies two recovery waits while asserting lock contention and default SIGCHLD. Child cleanup reaches terminal/ECHILD before returning. It never substitutes a mocked Goose Status.

The cancellation fixture cleanup bug is fixed: it now signals an identity-anchored child pidfd before killing the parent and draining pipes with a finite timeout. Native fault compiler paths fingerprint fixture/wrapper/compiler/instrumentation bytes, separating normal and sanitizer caches. The stale-fingerprint guard rejects with both ordinary Python and `python -O`. GCC and Clang have separate honest compiler identities; corrected fault builds instrument the generated program/runtime and both native packages.

Read-only consumer standards/specification reviews found no production blocker; test-review findings on the unconditional fingerprint guard and quoted compiler path were fixed. Vendored source/build/header/license bytes independently match the immutable upstream pin. Passing checks do not prove absence of bugs.

## Paired caller measurements

[Raw samples and exact source/compiler/binary hashes](../bench/results/process-consumer.json). [Frozen harness](https://github.com/carabistouflette/honk/blob/a36ca656da0467783c89a6f491e0b1206a60c05d/bench/process.goose), [measured driver](https://github.com/carabistouflette/honk/blob/a36ca656da0467783c89a6f491e0b1206a60c05d/bench/process_profile.py). Nine shuffled rounds, seed 491, three cases, 200 real child launches per batch. Both binaries use the pinned Goose compiler and default optimized C backend (`-O2`); both keep inherited stdin/stderr, the same capture cap and no command deadline. Before uses the prior fork adapter; after uses the reviewed library/guard, so this compares complete implementations rather than isolating one optimization or ranking languages.

Measurements used logical CPU 3 on a shared host, without exclusive isolation. A separate consumer validation on CPU 0 was announced during this period; other host activity was uncontrolled. Every sample and range is retained. Wall includes batch startup; CPU is wait4 accounting for the benchmark process and waited children. The raw wait4 RSS high-water values are identical and can inherit the Python spawner high-water: they are **not usable memory-comparison evidence**, allocation counts or combined simultaneous RSS.

| Workload (200 launches) | Before wall median [range], ms | After wall median [range], ms | Before CPU median, ms | After CPU median, ms |
| --- | --- | --- | --- | --- |
| inherit | 143.510 [138.934, 156.449] | 114.753 [112.416, 121.240] | 139.829 | 111.394 |
| tiny | 201.841 [199.340, 205.608] | 189.349 [185.948, 192.587] | 195.610 | 183.742 |
| 64k | 228.441 [225.613, 236.521] | 209.442 [204.131, 219.472] | 221.670 | 203.662 |

All three measured wall medians are lower in this run. This small local workload set provides no universal throughput, latency, memory or stability guarantee; long-running applications, transport/network and compiler workloads are not ranked here.

## Reproduce

Use two separate checkouts and the compiler in `GOOSE_REVISION`. The current harness declares later dependency mappings, so use the immutable harness linked above when reproducing this historical comparison. For the before checkout at `75d5d73`, copy the unmodified vendor/goose-process snapshot and frozen harness from `a36ca656da0467783c89a6f491e0b1206a60c05d` into `bench/process.goose`; its process import mapping is unused by the old adapter but must resolve. Build each harness in its own checkout with `goose build bench/process.goose -o /absolute/output/path`. Baseline source is the historical checkout plus this identical harness/unused mapping, not a claim that its whole build tree was clean. The recorded source manifest describes the measured after tree (production checkpoint plus staged benchmark files); requested baseline revision is a label, while the executable SHA-256 is verified before and after measurement.

```sh
taskset -c 3 python3 bench/process_profile.py \
  --before /absolute/before-bench --after /absolute/after-bench \
  --goose /absolute/pinned/goose \
  --before-revision 75d5d73647467040e7c3634cd9473aeff3859c18 \
  --output .build/process-profile.json
```

The driver fails instead of publishing results if captured source/compiler/binary identities change during measurement. Timing is evidence, not a CI threshold. The raw report SHA-256 is `bd646d90abf0f33b4cf38db5ca235c6de292cef8c483a8a37d34c77f4ee4cda4`.

# Real-project watch qualification — 2026-11-07

This qualifies development Honk production source `8f2bb40833bf76a87a01894c986de34bc9f6553d`
against one unchanged suite each from public goose-diff v0.1.0 and goose-json
v0.2.0. The development executable still prints 0.4.0; this is not evidence for
the published v0.4.0 source. No production code changed in this qualification.
The normal-build receipt associates the recorded executable/build command with
all 92 matching production files. Exact binary/Goose/compiler/source identities
remain in the raw receipts; rebuild bit-reproducibility is not claimed.

Qualification combines completed phases from two frozen harness commits:
`a225c79` (diff timing/resources and JSON timing) and `7f83eb5` (JSON resources).
The first run was deliberately interrupted after JSON timing completed because
its 32 MiB trace cap was projected to be too small for JSON resources. No trace-cap
failure occurred. A clean handoff audit verified HEAD, source status, harness,
helpers, binaries, observer manifest and restored original file hashes/modes
before changing the harness. The focused remaining run records its JSON/resource
scope and 128 MiB cap explicitly. The observer also retains its 50,000-sample cap.

## Workloads and acceptance

- Exact Git archives and original hashes/modes, plus recorded adapter manifests.
  Diff executes `tests/core.goose`; JSON executes `tests/codec.goose` using a
  documented production/native/test projection. Its full archive is retained,
  but unrelated examples and benchmarks are not the executed project tree.
- An ordinary Honk invocation establishes each suite's expected bytes. Every
  checked successful watch interval preserves them after removing only the
  exact selected-target build prefix and final one-target summary. This is not
  a separate direct-Goose oracle.
- Each timing/resource phase performs 60 seconds idle, 30 atomic saves, 20 saves queued
  while its owned idle supervisor is stopped, 30 populated-subtree move/edit/remove
  cycles, ignored-path/sibling edits, an expected invalid-source failure and
  restoration. Lifecycle logs enforce serial intervals and exact rerun counts.
- Separate root movement/deletion and SIGINT sessions exercise idle/active
  commands. Cleanup retains the supervisor unreaped until private-group checks.
- Real overflow uses a separately built observation-only wrapper around the real
  watcher. Four existing nested files generate a bounded stimulus while only
  the owned idle supervisor is stopped. Actual delivered IN_Q_OVERFLOW records,
  passing recovery output and a subsequent included-source edit establish loss
  recovery. Synthetic adapter tests are not the kernel-overflow oracle.

All four phases passed 124 checked intervals each, including one expected invalid-source
failure per phase. With 12 stopping sessions and two overflow sessions, the receipt
checks 514 intervals: 510 successful suite outputs and four expected compile failures.
All 18 accepted sessions completed without forced cleanup. Every quiescent checkpoint
retained 24 descriptors for diff and 15 for JSON, with matching anchored roles.

Local validation: make check; 58 watch tests (20 fault-only skips); five observer
controls; nine evidence controls under normal/optimized Python; and GCC/Clang
ASan/UBSan observer controls passed. The additional explicit-excluded-root regression
covers all five excluded basenames. Full required GCC/Clang CI is recorded separately
on the pull request before merge.

## Interpretation

Timing phases omit periodic process sampling; resource phases request 20 ms
sampling and retain actual gaps/read races. Start/terminal times are log-poll
observations, with scheduling, polling and persistence uncertainty. Atomic-save
latencies in summary.json subtract completed-edit timestamps; historical
save-complete.elapsed_ns also includes the edit operation itself. These are
shared-host observations, not kernel delivery latency, hard deadlines or general
speedup claims. Idle CPU percentages in summary.json are fractions of one CPU
core over approximately 60 seconds. JSON resources recorded three observer
permission errors and 332 read races, with gaps up to 101.742 ms; diff resources
recorded 70 read races and gaps up to 133.413 ms. These gaps/errors limit coverage;
no cause for the permission errors is inferred. Full error lists remain retained.

Quiescent fd anchors retain filesystem identities and watched inode/device/mask
sets while ignoring allocation numbers. Their convergence applies to these
sessions. RSS changes reflect observed root checkpoints; sampled maxima are
lower bounds and descendant RSS sums double-count shared pages. The observer's
`idle` bucket means no sampled descendants, which can include reconciliation;
quiescent checkpoints are the steady-state evidence. Short test execution can
fall entirely between samples. No universal memory bound or absence-of-leaks
claim is made.

## Retained artifacts

`qualified-phases.tar.gz` includes raw lifecycle/stdout/stderr/session records,
compressed process traces, calibration, both reports, the controlled handoff and
normal/observer build receipts. The first report intentionally remains incomplete;
only its three completed audited phases are accepted. Its interrupted JSON
resource session is excluded. `source-archives.tar.gz` preserves exact upstream
Git archive bytes. `exploratory-and-interrupted.tar.gz` preserves earlier smoke
runs and interruptions separately, including the original full-JSON discovery
failure that motivated the explicit projection. Those runs are not qualification
evidence. `artifacts.json` records file hashes.

To reproduce, build the pinned compiler and ordinary Honk, then build the observer
with `python3 scripts/watch-overflow-build.py /absolute/path/to/goose`. Supply
local repositories containing the exact public revisions:

```sh
python3 bench/watch_stress.py --honk .build/honk --goose /absolute/path/to/goose \
  --diff-repo /path/to/goose-diff --json-repo /path/to/goose-json \
  --overflow-probe .build/honk-overflow-observer --cycles 30 --idle-seconds 60 \
  --trace-mib 128 --deadline-seconds 7200 --output .build/fresh-watch-qualification
```

The trace budget and phase selectors are explicit; `--smoke` cannot establish
long-session coverage. To regenerate this receipt's derived numbers, extract
qualified-phases.tar.gz under .build, copy its receipts/watch-phase-handoff.json
to .build/watch-phase-handoff.json and run the retained derive-summary.py from
the repository root. Compare .build/watch-result-summary.json with summary.json.

# Honk 0.2.0 real workspace observations

> Historical report: results and test counts apply only to the source named
> below. They are not current v0.4.0/main performance claims. See the
> [currentness audit](../../../docs/PERFORMANCE.md). Raw records and slower results are unchanged.

Measured Honk release `855fb0552aefd5f0c033826af64f3bdd09ae6482` with clean driver
`57ba12ea906536010f68ec21ac24c692aa0bf13d`. The workspace builds a useful
version-policy CLI from two members plus public Git SemVer source.
All functional checks passed; no Honk runtime defect was reproduced in this
bounded exercise. The example/controller findings fixed during preflight were
the explicit self-root import, Honk's built-path output, staging-copy lock counts
and isolation of embedded source templates.

## Warm commands

One nine-round shuffled series, CPU0 affinity, shared host. Timed commands use
the original PATH/direct Git and pidfd exit notification. Every process sample,
wall/CPU value, source input and binary hash is in [direct-git.json](direct-git.json).
All 36 samples, four-by-nine coverage, every summary and input Git blob were
separately recomputed by the publication step.

| Workflow | Median wall ms | Wall range ms | Median CPU ms |
| --- | ---: | ---: | ---: |
| Workspace check | 113.60 | 111.23–115.08 | 106.95 |
| Selected build | 568.33 | 529.69–595.93 | 464.61 |
| Selected run | 565.02 | 495.37–641.10 | 463.87 |
| Workspace tree | 26.59 | 25.92–27.74 | 25.62 |

[Interactive warm chart](warm.html) shows every sample, range and median.
Check/tree cover both members; build/run select the binary. The commands do
different work. CPU includes waited children/descendants; RSS is not measured.
Warm window: `2026-11-05T00:54:06.512538+00:00`–`2026-11-05T00:54:17.884533+00:00`.

## First-use and network observations

Single observations, with private dependency/target state. The compiler was
already built and Honk's own build populated some compiler/runtime caches. OS
page cache is uncontrolled. Fetch/update/recovery observations include the
record-only Python Git wrapper and live network variation.

| Operation | Wall ms | CPU ms | Git mode |
| --- | ---: | ---: | --- |
| `cold_unlocked_fetch` | 2408.56 | 618.62 | record-only Git wrapper |
| `first_workspace_check` | 115.34 | 105.22 | direct Git |
| `first_gate_build` | 1560.97 | 1522.16 | direct Git |
| `online_update` | 1468.59 | 394.32 | record-only Git wrapper |
| `cold_locked_rehydrate` | 1107.82 | 390.15 | record-only Git wrapper |

The [functional Git trace](direct-git-git.jsonl) retains actual public HTTPS
arguments with private paths replaced by anchors. Exact-revision resolution,
update and rehydration made 6 fetch calls total, all for the pinned commit.
The instrumented frozen/offline equivalents made no discovery/fetch calls;
timed direct commands retain frozen policy but are not network traced.
Both lockfiles remained byte-identical. Recovery after removing Git/source
caches fetched the old locked OID. Both source packages matched their complete
tracked source sets (10 and 5 files); hashes also match the retained control.

## Retained instrumentation control

[instrumented-control.json](instrumented-control.json) retains all 36 original
samples from clean source `1b1041905e4d99312630043dcb93b3c4e745cd87`.
It used the same Honk binary, but its Python Git wrapper also handled local Git
cache checks, and Python's timed wait added polling latency. The accompanying
[Git trace](instrumented-control-git.jsonl) records 180 calls. These numbers are
instrumentation evidence and are excluded from the headline latency table.
The controller changed between series and run times differ; Honk's implementation
and measured binary stayed identical. No Honk speedup is attributed to this work.

## Scope and next useful profiling

This is one small workspace on one shared host, with no exclusive-core or
universal performance claim. Min/max ranges preserve all observations; there
is no outlier removal. Network timings establish no throughput ranking.
The remaining warm build/run cost warrants splitting staging/cache validation
from the Goose compiler invocation before choosing an optimization. These totals
alone do not assign that cost to a library or justify removing safety checks.

[Protocol and reproduction](../../WORKSPACE.md), [source/executable verification](verification.json).
Honk v0.2.0 and its tag stay unchanged.

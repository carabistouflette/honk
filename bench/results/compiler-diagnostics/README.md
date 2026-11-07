# Single-package compiler diagnostics evidence

`report.json` records measured source `486f27b` and the immutable baseline
`a39216aba524dc4bffe2e0d038f86ccecf4d013d`. Runtime/interface sources match the
reviewed feature commit; later documentation changes do not alter those sources.
The runner built both revisions and recorded exact commands and executable hashes.
The working source was clean. All 56 end-to-end samples and eight raw allocation
logs are retained; log SHA-256 values are in the report. No slower sample is
removed. Measurements ran after the local normal/security suite had finished.

The success/error fixtures each check a tiny project. Four cases cover baseline,
current default, explicit text and JSON, alternating order over seven rounds.
Timings include project staging, compiler-version validation, compiler execution,
child cleanup and pipe reads. Scheduling/startup/shared-host noise matters; these
fixtures establish neither a universal regression bound nor a general speed claim.

Allocation profiling runs separately under Valgrind, with child tracing disabled.
It counts parent-process malloc-family heap activity, including loaded libraries,
not the child compiler's allocations or Goose's mmap-backed data regions. Totals
are cumulative requested bytes, not peak memory or RSS. Profiling executables use
16 MiB stack reservations because the initial default-reservation profiling attempt
failed to map the runtime's sparse stacks. Timings use default reservations.
The incomplete attempt's log is retained under `failed-default-reserve/`; it is
excluded from the final report. Production runtime settings are unchanged.

No speed threshold is enforced. See `docs/COMPILER_DIAGNOSTICS.md` for the exact
reproduction command and semantic limitations.

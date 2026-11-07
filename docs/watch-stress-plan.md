# Real-project watch stress qualification

This campaign qualifies the complete watch workflow before preparing the next
Honk release candidate. It does not add a feature or promise a speedup.

Use full Git archives of public goose-diff v0.1.0 (129dc794) and goose-json
v0.2.0 (fcee7b7). Run one unmodified real test suite from each, with a recorded
adapter Honk.toml. Preserve archives, source hashes, canonical direct-test output,
the compiler/Honk/harness identities and every mutation. Only disposable copies
are changed. No sibling working checkout is modified.

Timing sessions omit periodic process sampling. Resource sessions sample the
identity-anchored supervisor and descendant tree, using the existing observer
and calibration controls. Retain actual sampling gaps, errors and missed-process
limits. RSS sums double-count shared pages; fd/RSS samples are lower bounds.
Idle CPU uses kernel supervisor CPU ticks over a separately recorded interval.
Rerun timestamps are observer measurements at log-poll resolution, not exact
kernel-event delivery or hard latency deadlines. Record command-start and final
successful-command observations separately. Raw logs and structured child
outcomes verify that completion was successful, rather than merely becoming idle.

Each project covers initial execution, idle intervals, repeated atomic comment
saves, rapid saves, populated subtree movement and subsequent edits, nested
removal, invalid-source failure followed by restoration, and cancellation.
Returned test output must preserve the canonical suite output. Topology cycles
check convergence to the same root fd identities/count after retired generations
are closed. Report RSS growth honestly; allocator high-water retention is not
itself proof of a leak. Default long campaign: at least60 seconds idle and30
cycles per project; smoke shortens both and cannot establish long-session claims.

Root movement/deletion are separate sessions that must stop with125. Signals
must preserve130/143 and reap the owned process group. Session/time/output/trace
budgets bound the harness; partial failures and forced-cleanup actions remain
retained. Sampling helpers never silently signal unrelated PID-reused processes.

Real overflow is an explicit bounded experiment: pause only an idle owned
supervisor, generate more events than the observed queue capacity inside an
already watched nested directory, and always resume in cleanup. Do not change
sysctls. Preflight event/file/byte budgets; inability to observe loss is
inconclusive, not a successful recovery claim. Synthetic overflow may separately
qualify the consumer through the existing test-only adapter, with a separate
binary/source identity and label. It cannot substitute for real-kernel evidence.

Independent reviewers first check workload validity/safety, then harness controls,
then retained results. Fix demonstrated defects and preserve failed evidence.
Only after final qualification prepare a release candidate, with full CI/reviews
and exact public-source verification before publication or catalog registration.

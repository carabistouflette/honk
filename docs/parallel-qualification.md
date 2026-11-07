# Real-project parallel-test qualification

Use goose-diff v0.1.0 at129dc794b62ad987784db0a1d52ef618c85fccf4: the four
maintained core/sparse/unified/context suites, with their exact upstream source
bytes and three library modules. Exclude argument-driven protocol tools and
examples. A temporary Honk manifest is the only adapter. The source subset,
archive/tag identity, file hashes, staging transformations, output and binaries
must be recorded; no suite wrappers, inserted work or delays.

Freeze Honk and the compiler. Separate uninstrumented end-to-end timing from
resource sampling. Compare default/jobs1/jobs2/jobs4 after equal warmups, with
fixed-seed randomized measured order and all slower samples retained. Include
serial compilation. Run actual compiled suites directly to characterize the
execution/compilation split without pretending that isolated controller timings
are exact internal phases.

On separate invocations, sample the owned private process tree through Linux
/proc using PID+starttime identity. Record root/descendant RSS and descriptor
counts and sums from the same observation, roles (compiler/test/idle), monotonic
timestamps, actual sampling gaps and missing reads. Sampled maxima are lower
bounds, not guaranteed peaks. Sum-of-RSS double-counts shared pages; FD sums
count entries, not distinct resources. Observed parent VmHWM includes earlier
compilation. Observer CPU work perturbs these runs: do not use their elapsed
times for performance conclusions.

For endurance, a bench-only caller imports the production scheduler/supervisor
unchanged and repeatedly dispatches actual compiled suite binaries. It pauses
on a private stdin checkpoint after each run. The observer records exact live
parent FD identities and verifies no children while paused; root RSS/high-water
trajectories describe allocator behavior, not proof of leak freedom. This is
supervisor stress, not a claim that the real project contains hundreds of tests.
Failure, timeout, cancellation and output-pressure controls are separately
classified and must close/reap admitted children and return FD identities to the
baseline. Every record, including partial failures, is retained.

Calibrate the observer with deliberately retained FDs, touched memory pages and
an intentionally unsampled short burst. These controls must demonstrate both
sensitivity and limitations before trusting cleanup/resource conclusions.
Measurements justify a decision, not an automatic scheduler rewrite. Four
natural suites at jobs4 form one cohort, so rolling admission cannot improve
that cohort; any execution-only opportunity must be weighed against full
command cost and lifecycle complexity.

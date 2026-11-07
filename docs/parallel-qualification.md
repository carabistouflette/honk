# Real-project parallel-test qualification

Use goose-diff v0.1.0 at 129dc794b62ad987784db0a1d52ef618c85fccf4: the four
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
counts and sums from the same observation, roles (test/non-test/idle), monotonic
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

## Reproduce

On Linux with Python 3.12+, `/proc`, pidfds and the pinned Goose toolchain:

```sh
mkdir -p .build/task-tmp
# Fetch the public tag into a trusted local source repository first.
git -C /path/to/goose-diff fetch origin tag v0.1.0
TMPDIR="$PWD/.build/task-tmp" make parallel-qualify \
  GOOSE=/path/to/goose DIFF_SOURCE_REPO=/path/to/goose-diff \
  PARALLEL_QUALIFY_OUTPUT=.build/parallel-qualification
```

Create the temporary directory first. Use a clean committed Honk checkout and a
new output directory. The target builds all tools and runs synthetic harness
checks before measurement. Do not run other builds during the campaign. Three
measured rounds follow one warmup for each mode; the seed fixes the shuffled
order. Default, jobs1, jobs2 and jobs4 all compile the same four release targets.
Resource runs and amplified supervisor stress follow timing separately.

`report.json` retains full outputs, samples, errors, tool/source hashes, load,
affinity and compiler identities. Gzipped JSONL files retain process samples;
`source.tar` and `staged-source/` preserve upstream and staged source bytes.
A failed campaign remains `complete: false`; keep that evidence and fix its
cause before starting a new output directory. `make qualification-test` exercises
observer positive/negative controls and all driver modes with synthetic binaries;
it makes no real-project performance claim. External harness group cleanup can
observe an orphan zombie; it proves no live descendant remains, not that the
harness reaped a process whose parent exited.

## Qualification result (2026-11-07)

Clean source `86be5a70143e3349bc0c53fc497574f048d0bf30`, public goose-diff revision
`129dc794b62ad987784db0a1d52ef618c85fccf4`: all 43 invocations passed. Three
measured end-to-end medians were 6284 ms default, 6243 ms jobs1, 6172 ms jobs2
and 6242 ms jobs4. Individual samples overlap; this shared-host experiment
establishes no meaningful general speed benefit. Isolated suite medians were
about 3/13/116/3 ms (context/core/sparse/unified). Serial compilation dominates
the full command; isolated timings do not subtract exactly into internal phases.

Separate sampled invocations observed tree RSS sums of 131.6–132.0 MiB and
44 total descriptor entries at their maxima, including compilation. These are
observed lower bounds with shared pages counted repeatedly. Endurance dispatched
512 unchanged suite executions across 128 cohorts. All nine paused checkpoints
had the same three descriptor identities and no children/group members. Paused
root RSS rose from 2460 to 3176 KiB after the first run and remained there; its
observed HWM later reached 3264 KiB. This trajectory does not prove leak freedom.
Failure, timeout, cancellation, full-buffer output and overflow controls all
returned to baseline descriptors with no children at their cleanup pauses.

Retain fixed cohorts. Four natural suites already fit a single jobs4 cohort,
so rolling admission cannot help within that cohort. Investigate repeated build
cost before adding scheduler complexity. No production code changed. The
`docs/results/parallel-qualification.json` receipt retains the derived samples,
resource/checkpoint summary and full raw-evidence hash. Full raw outputs, process
traces, source archive, staged sources, calibration and validation logs are
retained in the goose-libs publication evidence directory.

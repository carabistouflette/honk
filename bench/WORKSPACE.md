# Real Git/path workspace exercise

The template in `bench/workspace/` builds a useful release-policy CLI from two
Honk workspace members and the reviewed public SemVer library. It checks match,
no-match and invalid-input exit codes, runs the library's own contracts, updates
the exact Git dependency, rejects cold offline/frozen recovery without discovery
or fetch, rehydrates by the locked OID, and verifies both exported packages.
The Git wrapper records arguments and forwards them unchanged to real GitHub
HTTPS for functional proofs. First check/build and warm measurements use direct
Git on the original PATH. An equivalent instrumented warm preflight checks
discovery/fetch absence; the direct timed commands are not network traced.

Reproduce from a clean checkout of the harness commit, with a separate clean
Honk release checkout and the matching compiler source/binary:

```sh
taskset -c 0 python3 bench/dogfood.py \
  --honk-source /path/to/honk-at-855fb055 \
  --goose /path/to/goose/build/goose \
  --goose-source /path/to/goose \
  --output .build/workspace-profile.json
```

`python3 bench/dogfood.py --self-test` checks real child exit status, timeout
cleanup, descriptor counts and absence of unwaited children without network.
`make check` runs it automatically.

The output path must be new. `--smoke` performs one functional round and allows
an unfinished harness checkout; its timings are labelled as preflight data.
For normal measurements, the driver rejects a dirty harness, builds Honk from
the fixed v0.2.0 source, and fingerprints source inputs and compiler/Git/Honk
executables. It checks them again before publishing the success report. Inputs
and every completed process sample also remain under the ignored work directory
named in `.build/dogfood-last-path`, including on a later failure.

Cold observations are single first-use operations with private dependency and
application output state. The compiler is already built, and building Honk
populates some compiler/runtime caches before the application is built. OS page
cache is uncontrolled. Network observations include the record-only Git wrapper
and live network variability. They are not network throughput measurements.

Warm measurement is nine shuffled rounds of workspace check, selected binary
build/run, and workspace tree; seed 20261105 and every raw sample are retained.
CPU time includes the waited command and its waited descendants. Controller
record-writing happens after the timed process completes; RSS is not measured.
The controller uses pidfd exit notification, private groups, regular-file logs
and bounded waits. A timeout terminates the owned group before logs are read.
It does not exercise daemon or arbitrary-descendant supervision.

This is one small functional workspace on a shared host. The four commands do
different amounts of work; their timings should be interpreted per workflow.
Larger graphs and other hardware may behave differently. No universal speedup,
regression or isolated-core claim is made. Release tags remain immutable while
the example and measurements develop in later commits.

[Published v0.2.0 observations](results/workspace-v020/README.md) retain both
the plain-CLI series and the earlier instrumented controller control.

# Bounded opt-in build reuse: retained development records

These reports measure the source-only implementation before reconciliation with
UTC diagnostics/v0.3.0 and the later compiler-path guard. They identify their
actual source and binaries; they are not measurements of a later publication
head. All observations, including cold costs and conservative fallback, remain.

`prototype.json` contains 72 samples at the prototype runtime/harness identities
recorded there. `final.json` contains a second 72-sample series at clean source
`9e8c24a4f4cd3fdc41875be5cd95643b28e41bb2`. Its candidate binary was built
from working-tree runtime/build/vendor bytes subsequently committed at that
revision; its actual SHA-256 identifies the executed image. This is not a
claim that the build itself started from a clean commit. `verification.json`
records independent summary recomputation, tool/runtime/vendor identities and
that build provenance. `selfhost.json` describes normal/frozen check/package
at that same source, independently of timing.

The existing `bench/reuse.py` recorder runs nine shuffled rounds of four modes
on each of two fixtures: exact pinned semver source plus license, and the same
fixture with an unused native sidecar requiring conservative fallback. Each
build is followed by an actual application run/status/output check. A real
backend-log sentinel and independent Python artifact digest establish an
eligible hit; warm output publication still copies, verifies and atomically
installs an independent executable. It does not skip source staging or Git
validation. All operation details, fixture hashes and tool hashes are retained.

The source-only second-series wall medians are about 486 ms for frozen v0.2.0
ordinary builds, 480 ms for candidate ordinary builds, 1501 ms for candidate
cold slots and 99 ms for candidate warm hits. Ordinary/fallback ranges overlap.
The warm result is specific to this small supported fixture; cold population
is substantially slower because it explicitly builds standalone rather than
consuming a mutable runtime object. Equal generated binary bytes/equal work
are not asserted. The fallback fixture remains near ordinary build latency;
prototype fallback overhead and all outliers are retained in the first series.

All series use a shared Linux host on CPU0, with controller and application
checks included. OS/tool runtime caches are warm; cold means only the Honk
artifact slot is cleared. No exclusive-core, isolated-host, universal speedup,
RSS or allocation claim follows. Differences between prototype and second
series cannot be causally attributed to one optimization: source fixes, code
layout, run time and host activity also differ. Indirect system compiler inputs
must remain unchanged as documented in `docs/INCREMENTAL-BUILDS.md`.

Later source validation or measurements must be recorded separately and must
not relabel these retained samples as a different source revision.

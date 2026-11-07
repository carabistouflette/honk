# Native fallback and test-cache controls

The qualification uses public goose-crypto alpha.1 at
`a4643f62bd5e76b371054c6537a95169a7930101`: unchanged `tests/api.goose`, the
library, native sources/headers, CMake and sidecar build inputs, compiler pin,
license and notices. A temporary Honk manifest is the only adapter. This API
suite is an explicit profile; stdin protocol runners, examples and native fuzz
programs are excluded. Passing it does not qualify the whole upstream suite.

Native builds remain ineligible for Honk executable reuse. Ordinary and repeated
explicit-reuse invocations must pass the API regressions, perform Goose backend
work, and leave no successful Honk test-cache record. Goose/CMake's own native
object caches may still be warm; this is fallback recompilation, not proof of
Honk cache invalidation or native cache support.

An intentionally invalid native C fixture also changes the sidecar fingerprint
so a pre-existing native package cannot mask the error. It must fail in the
native compiler and preserve the previously published executable. Both files
are restored exactly before the next successful fallback. Source edits and
other mutations are derivative controls, not canonical upstream results.

The unchanged four-suite goose-diff v0.1.0 profile separately proves actual
cache hits before checking same-size source edits, filtered output reindexing,
same-size artifact corruption with ELF magic preserved, symlink safety and
compiler changes. Moving a copied supported ELF compiler changes both location
and the `GOOSE` environment input; appending a byte at the same copied path
isolates compiler-content invalidation. All selected tests still execute.

Backend evidence records identities, hashes and nanosecond timestamps. Before
commands, existing compiler diagnostic logs in each isolated Goose home receive
a marker, as in maintained cache regressions. Those logs are not build inputs;
this distinguishes real backend writes even when timestamp resolution is coarse.
It does not wrap the compiler or alter test source. Raw results are saved before
metadata/assertions, including expected failures. `/proc` group checks, private
process ownership, finite deadlines and bounded capture come from the maintained
observer. No performance comparison is inferred from control durations.

Reproduce on the supported Linux platform, from a clean committed Honk checkout,
with the pinned compiler, CMake, pkg-config and libsodium development files:

```sh
mkdir -p .build/task-tmp
make build GOOSE=/path/to/pinned/goose
python3 bench/native_reuse.py --crypto-repo /path/to/goose-crypto \
  --diff-repo /path/to/goose-diff --honk .build/honk \
  --goose /path/to/pinned/goose --output .build/native-reuse-qualification
```

Use local trusted repositories containing the exact public tags and a new output
directory. No checkout changes are made in them. The report retains source
archives/member modes/hashes, tool/environment/harness fingerprints, resolved
runtime libraries, actual CMake compiler selections, invocation output, backend
and cache-record snapshots, mutation hashes and restoration checks against the extracted fixture baseline. Binary
mutation files are temporary controls and must not be committed as build output.
A failed campaign remains `complete: false`; preserve it and choose another
output directory after fixing its cause. Indirect system-toolchain assumptions
from [the reuse guide](INCREMENTAL-BUILDS.md) still apply.

# Opt-in local build reuse

Build/run reuse is available in experimental v0.4.0. Test reuse is prepared
for v0.5.0-rc.1 and is not part of published v0.4.0. Reuse is off by default.

`build --reuse-build` and `run --reuse-build` may reuse one verified executable
per project and profile. `test --reuse-build` opts into bounded per-test reuse;
watch and bench commands do not support test reuse. Ordinary builds still invoke the compiler, and clear
the reusable marker for that profile. `clean` removes all reuse state. This is
an opt-in local cache for trusted projects and tools, not a hermetic build or
an authenticity boundary against the account that owns the project.

## Eligibility and build inputs

The first version supports binary targets whose freshly staged source graph
uses only downward relative imports, validated staged self-import aliases,
declared dependencies and the single
`std` module.
Every staged file is fingerprinted, not just the entry or reachable declarations.
Native sidecars (`*.build`), explicit externs, embedded files/shaders, other
standard/blessed modules, and unsupported toolchain configurations fall back to
normal compilation. A conservative lexical scan may reject additional safe
programs; it never authorizes a native build. Existing source validation,
independent staging and cached Git identity/dirty checks always run first.

The selected `std.goose` is copied into the private stage, hashed, and passed
through an explicit compiler `--stdlib` option. Its own imports or embed
operations make the target ineligible. Eligible cache-populating builds use
`--standalone` so they do not consume a mutable cached Goose runtime object.
The actual Goose and selected C compiler must be regular ELF executables on
the validated Linux platform;
script wrappers, a configured C compiler and a compiler home containing a
literal backslash fall back in this first version.

A versioned SHA-256 key includes compiler bytes and canonical location, selected
C compiler bytes/location, complete inherited environment (hashed only, never
persisted as plaintext), entry/cwd/profile, and every staged file's relative
name and bytes. Names/values are length framed. Cache hashing has independent
bounds: 4,096 files/directories each, 32 MiB aggregate staged data, 8 MiB per
staged read, 256 MiB per compiler/artifact, and 1 MiB/4,096 entries of environment
records (64 KiB each). Compiler/artifact hashing streams through a 32 KiB
buffer; staged file reads reuse the existing bounded loader. Unsupported or
excessive inputs disable reuse rather than relaxing ordinary build validation.

**System toolchain assumption:** the rest of the C toolchain and its indirect
inputs must remain unchanged for reuse: support programs, headers, specifications,
linker scripts, loaded libraries/plugins and sysroot, including files selected
through environment paths. Their complete transitive filesystem inputs are not
tracked by this first version. After changing them, use `clean` before
requesting test reuse. An ordinary binary build refreshes only the build/run
slot; an ordinary test refreshes only the selected test buckets. Changing the selected compiler executable, source, std file,
profile or environment invalidates automatically. This limitation is why reuse
is explicit and off by default; the feature makes no complete-toolchain or
cross-machine reproducibility claim.

## Artifact lifecycle

Each profile has one bounded slot containing a program and a small versioned
key/digest record, under the project's private `.honk` directory. Selecting a
different binary replaces that slot; it does not accumulate entries. Files are
not executable just because a record exists. A matching record first copies
the cached program into a fresh private stage using no-follow independent file
copying. The copy's SHA-256 must match the recorded artifact before the existing
checked, synced, atomic executable publication is called. Output symlinks and
special files remain errors. Missing, malformed, excessive or corrupt entries
cause compilation. Cache files/directories must have private owner permissions.

On a miss, invalidate the marker before starting the compiler. A failed compiler
cannot certify or publish a new artifact and leaves the previous public binary
intact. After successful compilation, recheck the key before publishing cache
metadata. Cache population is best effort: a cache write failure does not turn a
successful ordinary executable publication into a partial failure. Records are
written atomically after program publication. No secrets, compiler diagnostics
or original environment records are written to cache metadata.

## Maintained checks

`tests/build_cache_cli.py` covers actual compiler work, source/dependency/std/
environment/profile/compiler invalidation, same-size changes, corrupted/missing
artifacts and records, failed compilation preserving the old executable,
symlink/private-mode refusal, native/embedded-file fallback, ordinary build
refresh, and clean behavior. Output and lock semantics must match the ordinary
path. The [measurement guide](../bench/README.md) keeps cold, warm and fallback
workloads separate. The [v0.4.0 record](../bench/results/announcement-v040/README.md)
checks the released implementation; older development samples retain their
original source labels and are not current release latency.

## Test compilation reuse

Every selected test still executes on every invocation; only compilation can be
reused. Sequential execution and opt-in `--jobs` retain their existing behavior.
All discovered test roots receive their dependency import declarations before
key construction. Filtering changes which tests run, without changing that
staged snapshot. Complete staged content, including unselected tests, remains
in each key, so any source change conservatively invalidates all test keys.
Only self-import aliases rewritten by validated staging to the exact app stage
are eligible; arbitrary external imports, native inputs and embedded files
still fall back to ordinary compilation.

Each profile has sixteen fixed test buckets under `.honk/reuse/PROFILE/tests`,
selected by SHA-256 of the complete relative test path modulo sixteen. The full
entry path remains in the key: collisions replace the bucket and cause misses,
never substitution of another test. Renames and deletes cannot grow the table.
With the existing 256 MiB artifact bound this permits up to 4 GiB of test cache
per profile (plus the ordinary build/run slot and small records); `clean`
removes all slots. Reuse remains explicit and subject to the system-toolchain
assumption above. Selected ordinary tests invalidate their buckets and preserve
the existing invalidation of the ordinary build/run profile marker. Opt-in tests
do not invalidate the build/run marker. Changing debug/release selects separate
slots. Compiler failure keeps the previously published executable intact.

Measure the maintained real-project case from a clean commit after validation
builds finish (trusted goose-diff repository containing public v0.1.0):

```sh
python3 bench/test_reuse.py --source-repo /path/to/goose-diff \
  --honk .build/honk --goose /path/to/pinned/goose \
  --output .build/test-reuse-measurement
```

The finite recorder separates ordinary compilation, cache population and hits;
it retains every sample and fails a hit claim if backend logs changed. It uses
an isolated Goose home and clears the compiler override to exercise supported
ELF tools, recording the resulting environment hash. These are trusted-project,
shared-host measurements, not an authenticity or performance guarantee.

## Native fallback qualification

The [second real-project qualification](../bench/results/native-reuse-2026-11-07/README.md)
uses goose-crypto's frozen public API suite to verify native fallback and the
source-only goose-diff profile to verify actual hits and invalidation. Native
reuse requests compile normally and leave no Honk cache marker; CMake may still
reuse native objects. Requesting reuse does not make a native project eligible.

For eligible source-only snapshots, unchanged tests and changed filters can hit
stable path-derived slots. Source or selected compiler changes recompile;
corrupt artifacts and symlinked cache programs fall back safely. Subsequent hits
verify recovery. Cache population still costs compilation, so repeated unchanged
eligible runs are the intended use. Full profile and correctness limits are in
the retained evidence; no native cache support or broader speed guarantee follows.

# Opt-in local build reuse (first version)

`build --reuse-build` and `run --reuse-build` may reuse one verified executable
per project and profile. The recipe/key epoch must change when build flags or
key interpretation change. Ordinary builds still invoke the compiler, and clear
the reusable marker for that profile. `clean` removes all reuse state. This is
an opt-in local cache for trusted projects and tools, not a hermetic build or
an authenticity boundary against the account that owns the project.

## Eligibility and build inputs

The first version supports binary targets whose freshly staged source graph
uses only downward relative imports, declared dependencies and the single
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
tracked by this first version. After changing them, perform an ordinary build or `clean` before
requesting reuse. Changing the selected compiler executable, source, std file,
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

## Required verification

Public regressions must exercise actual compiler work, source/dependency/std/
environment/profile/compiler invalidation, same-size changes, corrupted/missing
artifacts and records, failed compilation preserving the old executable,
symlink/private-mode refusal, native/embedded-file fallback, ordinary build
refresh, and clean behavior. Output and lock semantics must match the ordinary
path. Matched measurements must retain all cold/warm samples and source/tool/
fixture identities, and report the standalone cold-build cost separately.

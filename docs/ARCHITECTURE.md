# Implementation boundaries

Honk's application behavior is Goose. The CLI parses arguments, loads strict
TOML manifests, resolves a bounded flat package graph, maintains lockfiles,
selects targets/workspace members and invokes the compiler. The vendored TOML
and argument parsers are pure Goose.

`src/platform.goose` is the internal synchronous boundary to the native adapter.
The adapter supplies missing filesystem operations and application signal guards: descriptor-based
no-follow walks and copies, locks, bounded reads,
atomic replacement/installation and signal latching/recovery. Pinned goose-process owns normal child launching, captures, pumping, pidfd signalling and reaping. Its functions
are internal, single-threaded application implementation details, not a stable
reusable library API.

## Build sequence

1. Discover a manifest and validate its schema and resource limits.
2. Acquire nonblocking cache/project locks. Resolve Git refs using the existing
   lockfile unless update was explicit; validate local/cache source identities.
3. Select production/dev graph nodes. Copy source trees into private staging,
   reject unsupported entries and remap root source declarations to resolved
   local packages. User source files remain unchanged.
4. Normally invoke the selected Goose compiler with offline dependency fetching.
   An explicit eligible `--reuse-build` hit verifies and copies a cached program
   instead. Both paths keep graph validation, fresh staging and atomic output.
   Libraries are source-checked; native programs compile privately on a miss.
5. Atomically publish successful executables. Test/benchmark outputs have a
   reserved directory and cannot collide with the application's executable.

Temporary source rewrites skip crash-durability syncs, while metadata writes
retain their durability syncs. Kernel-assisted large-file copies have the same type, byte,
length and snapshot-independence contract as the portable path. Optional content-keyed build reuse is a separate step described in
[the reuse contract](INCREMENTAL-BUILDS.md). Its indirect toolchain inputs must
remain unchanged; ordinary build/clean refreshes that state.

## Package sequence

The Git index selects paths, while current working-tree bytes and executable
flags supply their contents. Only tracked regular files enter staging. Tar
receives an explicit NUL-delimited list with filename option parsing disabled,
fixed timestamps/owners/format and normalized 0644/0755 modes. Honk extracts its
own generated archive and checks the exact exported sources offline before
atomically publishing it. A package is a source archive, not a signed release,
registry publication, or promise of bit-identical executables across toolchains.

The supported user interface is the CLI and manifest/lock format described in the
[reference](REFERENCE.md). Internal module fields/functions can change before 1.0. Registry version
solving, Windows support and process-tree supervision are outside this version.

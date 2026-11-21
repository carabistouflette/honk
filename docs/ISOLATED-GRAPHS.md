# Experimental isolated packages

`honk check --isolated`, `honk run --isolated`, `honk build --isolated` and
`honk test --isolated`
produce the compiler's resolved graph directly, retaining dependency aliases
inside their owning packages. Two dependencies can both import `dep` with
different bindings, and incompatible nominal types and globals stay isolated.
Aliases pointing to one materialized package share its instance.

This opt-in path requires an explicit `GOOSE` executable and `[toolchain]`
revision matching the qualified compiler fork commit
`0ce3a5edb5679e10a490e9f66d5db5f6a30b9f63` or its merge commit
`6471713c6c18f64e172c4c778ac5987a5a177358`. It checks the compiler's full revision
and graph capability using `version --json`. The normal compiler bootstrap and
default flat package workflow remain unchanged.

```toml
[toolchain]
revision = "0ce3a5edb5679e10a490e9f66d5db5f6a30b9f63"

[dependencies]
old = { path = "../old-version" }
newer = { path = "../new-version" }
```

Each directory needs its own Honk.toml. Use ordinary imports (`import old;`)
and aliases (`old::make()`) without sourced imports. Entry namespaces are read
from source and independently validated by the compiler. Graph metadata goes
to `target/isolated/graph.json`; native executables go to
`target/isolated/<package-name>`.

Local snapshots hash a domain tag and bytewise-sorted relative file names and
contents: all Goose sources, Honk.toml and the entry's optional .build sidecar.
Fields use decimal byte length plus colon then exact bytes. Generated/cache
directories use the existing source-walk exclusions. Symlinks and special files
are rejected, with the existing source/file limits and a 32 MiB total snapshot
limit. Physical paths do not enter the snapshot digest. Source edits refresh
the graph each invocation; there is no persistent graph reuse yet.

Production and development dependencies can come from paths, Git, or registries.
Build and run produce executables from binary packages. Check supports binary
and library packages. Bench targets, embedded resources and build reuse
remain unfinished. The compiler
rejects non-toolchain native sidecars, foreign externs/exports and unsupported
tooling. Source digest assertions are producer-owned; concurrent source edits
are not an atomic filesystem snapshot. This is not full Cargo parity.

## Shared workspace resolution

Run from the workspace root, or point `--manifest-path` at its Honk.toml.
Place the qualified compiler revision in the workspace root's `[toolchain]`
table. Members inherit it by omitting their pin or can specify the same revision.

```sh
honk fetch --isolated --workspace
honk check --isolated --workspace --frozen
honk run --isolated -p app --frozen
honk build --isolated --workspace --frozen
```

Resolution includes the root package, if present, and every declared member.
Even when `-p` selects a single target, all members contribute production
constraints to one solve and share the root's version-2 Honk.lock. The lock
records sorted member paths. Each compiler invocation receives only the
selected target's reachable dependencies. From a member directory, use the
workspace's manifest path to select this shared mode.

A virtual workspace defaults to all members. A workspace with a root package
defaults to that package for compilation. `--workspace` checks all packages or
builds all binary packages. Run requires one binary target. Member outputs live
under `target/isolated/members/<graph-id>/` in the workspace, with IDs assigned in
member path order. The root package uses `target/isolated/root/`. Member
selection does not limit fetch or update.

## Features and optional dependencies

Isolated path and Git packages can define named groups of optional production
dependencies. A group can also include other groups in the same package.

```toml
[dependencies]
json_codec = { path = "../json-codec", optional = true }

[features]
default = []
export-data = ["dep:json_codec"]
full = ["export-data"]
```

Run `honk fetch --isolated --features full` to resolve this configuration.
Use the same effective feature set when replaying the lock, for example
`honk build --isolated --features full --frozen`. Feature selection accepts
comma-separated names. The `default` group is activated for each package
unless `--no-default-features` disables it for the selected package.
On workspaces, use `-p` to override a member's selection while the other
members keep their defaults. Repeated and cyclic feature references terminate
once each reached feature has been activated.

The version-2 lock records active feature names and bindings. A feature
selection that changes the effective graph or enabled feature names requires
an unlocked update. A disabled dependency is excluded from resolution and
materialization, including registry requests. The compiler sees the resulting
bindings. Source code that unconditionally imports an optional dependency must
be built with that dependency enabled.

A production dependency from a path, Git repository, or registry can request features
on its target:

```toml
[dependencies]
codec = { path = "../codec", features = ["json", "pretty-print"] }
```

Honk activates the union of requests for the same resolved instance across
the workspace. Late requests can enable additional dependencies before
registry resolution and lock writing. Different Git revisions keep independent
selections. A requested name must exist in the target manifest. Requests on
optional dependencies take effect when the dependency is activated.

A production dependency from any of the three sources can use
`default-features = false` to opt out of requesting the target's default
group. Any active edge that requests defaults enables them for the shared
instance, including edges discovered after that instance was first visited.
Explicitly requesting `"default"` also enables it.

A feature can forward a request to a dependency by its manifest alias.
For example, `"codec/json"` requests `json` and activates `codec` if it
is optional. With `"codec?/json"`, the request takes effect only if that
optional edge is otherwise active. Honk applies pending requests when
the edge is activated later. Registry version selection can backtrack if
the chosen release lacks a forwarded feature. A local or Git package can
gate a registry dependency behind its own groups.

### Conditional declarations

Set the workspace or root project's compiler revision to
`eeab7eebcae92d9a04b6caf43c321da560b8d269` and use a Goose binary built from that revision.
Honk sends each instance's active feature names to the compiler along with
its dependency bindings. Make optional imports conditional with top-level blocks:

```goose
if feature("export-data") {
    import json_codec;
    fn export_format() -> i64 { json_codec::format_id() }
} else {
    fn export_format() -> i64 { 0 }
}
```

Use an unconditional namespace directive if the file has one. Previous supported
compiler pins still work for dependency selection alone. Graph-aware formatting
and editing tools are future work.

## Platform dependencies

Isolated package manifests can add dependencies and development dependencies
under `target.<os>`. Supported selectors are `linux`, `macos`, `windows`,
and `freebsd`.

```toml
[target.linux.dependencies]
files = { path = "../linux-files" }

[target.windows.dependencies]
files = { path = "../windows-files" }
```

Unqualified commands resolve for the host OS. An explicit `--target-os`
stores its own production and test graphs in the shared `[platforms]`
section of `Honk.lock`. Use the same explicit target when replaying a
platform lock, for example `honk fetch --isolated --target-os windows
--frozen`. Foreign targets support fetching, including `--tests`.
Compilation and execution use the host compiler. Platform-specific
declarations are supported in path and Git packages and in published
registry packages using a schema-2 index. Honk selects the active registry
edges before downloading archives and checks every published production
edge against the archive manifest, including inactive edges.

Aliases can name different dependencies on disjoint OSes. On the active
OS, ordinary and development edges follow the same alias rules as
unconditional dependencies. Features forwarded to an alias unavailable
on the selected OS have no effect there.

## Isolated tests

`honk test --isolated` discovers standalone executables under `tests/`,
builds them with their package's isolated bindings, and runs them serially.
Build outputs are separate from normal executables. Test arguments follow
`--`. The workspace selectors also apply to test execution.

Only the test graph includes workspace package development dependencies.
Dependencies acquired through path, Git or a registry contribute their
production edges. Within the test graph, `features` and
`default-features` on development edges participate in feature unification.
A production edge and a development edge can share an alias when their
source and version requirement match. Tests use the union of both requests.

The first unlocked `honk test --isolated` or `honk fetch --isolated --tests`
writes a `[test]` section to the same `Honk.lock`, alongside the production
graph. Fetching with `--tests` resolves and materializes both graphs without
compiling or running test targets. In CI, use `honk fetch --isolated --tests
--locked` to populate an empty cache from the committed lock, then run
`honk test --isolated --frozen`. Plain `honk fetch --isolated` prepares the
production graph. `honk build --isolated --frozen`
checks the production rows and preserves the test section. `honk test
--isolated --frozen` checks both graphs using cached sources. If dependencies
change, rerun the affected command without `--locked` to refresh its rows.
The isolated graph still rejects package dependency cycles.

## Multi-instance locks

Isolated mode writes version 2 of `Honk.lock`: `mode = "isolated"`, the exact
compiler revision, package coordinates/name/version/entry, and owner-local
alias-to-package edges. Different versions with the same package name remain
separate records. Rows are sorted independently of graph discovery order.
Coordinates are relative to the root project, so relocating the whole project
closure and reordering dependency declarations do not invalidate the lock.

`--locked` requires the current package graph to match the existing lock and
never rewrites it. `--frozen` implies locked plus offline operation; `--offline`
alone permits lock creation/update for these already local path dependencies.
Local source edits refresh compilation snapshots without changing dependency
locks. Dependency bindings, package versions/entries and compiler changes do
require a lock update. Path dependencies perform no package network access. Git offline behavior is
described below.

A legacy version-1 lockfile is never silently converted or overwritten. Preserve
it separately before deliberately opting a project into the new mode; automatic
migration is unfinished. Malformed lockfiles and cycle/resolution failures leave
the original bytes intact. A per-project `.honk/isolated.lock` serializes Honk's
isolated operations, while the existing Honk cache lock excludes concurrent
legacy writers using the same HONK_HOME. Persistent locks use the existing atomic
write helper.

Canonical lock bytes are regenerated from local manifests. Arbitrary manual
formatting changes require an unlocked canonical rewrite. As in Cargo,
a successful dependency resolution may update the lock even if a subsequent
compiler/typecheck fails.

## Scoped Git dependencies

Git dependencies use the existing Honk acquisition/cache verification code, with
an independent alias context for each owner. Each Git dependency needs a library
Honk.toml and the same compiler compatibility required by isolated local packages.
Exact refs and Honk's bounded Git tag-version requirements are supported:

```toml
[dependencies]
old = { git = "https://example.org/mathx.git", rev = "v1.0.0" }
newer = { git = "https://example.org/mathx.git", version = "^2.0.0" }
```

The lock stores the Git URL, original ref or range, selected ref and full commit
per owner/alias. Package and edge coordinates use `git:<url>@<commit>` plus an
optional checkout-relative subdirectory, never a host-specific cache path.
Compiler identities use the Git source URL, full commit and subdirectory.
Two incompatible commits coexist; aliases reaching one instance share its state.
A new unlocked source request is resolved once per invocation even if a tag moves
between consumers. Existing owner-specific lock pins retain precedence.

`honk fetch --isolated` resolves/materializes without compiling; it still requires
the explicit graph-capable compiler probe. Ordinary builds prefer existing pins.
`honk update --isolated` deliberately refreshes requested refs/ranges and updates
the lock without running the application. Update rejects --locked/--frozen.
Honk's Git version-tag policy is unchanged; it differs from Cargo's Git `version`
semantics and is not general cross-source solving.

Warm --frozen runs perform no Git fetch/tag lookup. Missing/incomplete sources
fail without fetching. --locked may repopulate a cold cache using the locked
commit, provided the server still serves that commit; it does not resolve the
current tag again. Git refs cannot be resolved offline without a usable lock.
Changed locked source requests fail before fetching a replacement. Dirty cached
checkouts and mismatched commit/completion identities are rejected by the existing
cache verifier. Locks are preserved on acquisition/resolution failures.

Path dependencies inside a Git checkout retain its URL/commit and their relative
subdirectory. They cannot escape the checkout into arbitrary host directories.
Existing transport restrictions remain: HTTPS-only Git sources, disabled hooks/filters, no submodule acquisition, and verified source/commit
cache identities. Tests
use real local Git repositories behind an explicit test-only HTTPS transport shim.

## Scoped registry dependencies

Registry dependencies use the existing Nest v1 index and verified archive cache.
No server or protocol migration is needed. The default flat workflow still uses
Nest's original single-version resolver; the isolated producer uses a separate
bounded owner-scoped resolver. Both reuse the same native transport, checksum,
extraction and cached-content verification.

```toml
[dependencies]
old = { package = "example", version = "^1.0.0" }
newer = { package = "example", version = "^2.0.0" }
```

Versions compatible under caret SemVer rules must unify; conflicting exact
compatible versions fail, while incompatible major versions (or zero-major
compatibility groups) may coexist. This follows Cargo's
[version-unification rule](https://doc.rust-lang.org/cargo/reference/resolver.html#semver-compatibility),
not its entire resolver/feature policy. All registry constraints from path/Git
packages are collected before solving. Selected archive dependencies are solved
from index metadata before any registry archive is materialized. Only selected
releases are downloaded. Cycles can trigger backtracking to older releases.

Isolated mode accepts schema-1 and schema-2 indexes. Schema 2 allows releases
to declare feature groups, optional dependencies, and feature requests on
dependency edges, including per-edge default opt-out. Requested features
constrain eligible versions. Honk merges late requests per selected release, then validates the
downloaded manifest against the index before writing the lock. Only activated
optional dependencies enter the graph. Active registry features require a Goose
compiler that advertises package graph feature support. The flat workflow
continues to use schema 1.

The resolver first tries the complete owner-specific lock without reading any
index. If an unlocked graph change requires catalog lookup, eligible existing
pins and already selected instances are preferred before highest releases.
Existing pins may retain yanked releases; update ignores old candidates and
excludes yanked releases. Reusing a published version with changed immutable
metadata is rejected (the mutable yanked flag is excluded from that comparison).

Each registry binding stores the registry, package, requirement and full release
record. Stable coordinates use `registry:<url>/<package>@<version>#<sha256>`.
Compiler provenance uses that registry/package source plus the full archive
SHA-256. Different registries remain different sources, even for identical
archive bytes. Archive manifest name/version/entry, compiler compatibility and
same-registry dependency metadata are independently checked before use. Cached
source corruption fails closed. --locked refuses changed bindings before index
or replacement-archive fetches; warm --frozen replay requires no index cache.

Initial limits are 256 combined instances, 65,536 edges/active requests, 8,192
catalog releases, 512 candidates per request, 4,096 alternative frames, 100,000
candidate decisions and 8,000,000 charged scan iterations per resolution. Limit
exhaustion is an explicit failure, never a partial lock. The solver is bounded
chronological backtracking, not PubGrub, and has no optimal-complexity or universal
Cargo performance claim. Graph and lock encodings are each bounded to 1 MiB.

The graph compiler is derived from the qualified Goose baseline
`eadca409f68210893f366e60d0c2f0dc29a339be`; dependency manifests may retain that
specific development compiler pin. Root manifests must still select an exact
qualified graph compiler. Other mismatched pins remain rejected. This narrow
compatibility allowance does not relax native/library-ABI gates or introduce
an inferred minimum-compiler policy.

Registry names/requirements retain the alpha protocol's current grammar. Native
packages, sourced imports, and registry authentication/publishing
remain unfinished. The test suite includes an independent
exhaustive oracle over 64 seeded small acyclic graphs, plus real JIT/native,
cycle/backtracking, yanked-lock, archive-integrity and mixed Git/registry cases.

Qualification with a separately built graph compiler:

```sh
GRAPH_GOOSE=/path/to/qualified/goose python3 tests/isolated_cli.py -v
```

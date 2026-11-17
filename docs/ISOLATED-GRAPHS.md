# Experimental isolated local packages

`honk check --isolated`, `honk run --isolated` and `honk build --isolated`
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

Only production path dependencies and binary root targets are supported.
Git/registry sources, workspaces, dev/test/bench
targets, embedded resources and build reuse are unfinished and rejected when
requested. The compiler
rejects non-toolchain native sidecars, foreign externs/exports and unsupported
tooling. Source digest assertions are producer-owned; concurrent source edits
are not an atomic filesystem snapshot. This is not full Cargo parity.

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
require a lock update. The mode performs no package network access.

A legacy version-1 lockfile is never silently converted or overwritten. Preserve
it separately before deliberately opting a project into the new mode; automatic
migration is unfinished. Malformed lockfiles and cycle/resolution failures leave
the original bytes intact. A per-project `.honk/isolated.lock` serializes Honk's
isolated operations, while the existing Honk cache lock excludes concurrent
legacy writers using the same HONK_HOME. Persistent locks use the existing atomic
write helper.

This is a local graph lock, not yet Git/registry pinning or a workspace-wide
shared lock. Canonical lock bytes are regenerated from local manifests; arbitrary
manual formatting changes require an unlocked canonical rewrite. As in Cargo,
a successful dependency resolution may update the lock even if a subsequent
compiler/typecheck fails.

Qualification with a separately built graph compiler:

```sh
GRAPH_GOOSE=/path/to/qualified/goose python3 tests/isolated_cli.py -v
```

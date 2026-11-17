# Experimental isolated packages

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

Production path and Git dependencies and binary root targets are supported.
Registry sources, workspaces, dev/test/bench
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
require a lock update. Path dependencies perform no package network access. Git offline behavior is
described below.

A legacy version-1 lockfile is never silently converted or overwritten. Preserve
it separately before deliberately opting a project into the new mode; automatic
migration is unfinished. Malformed lockfiles and cycle/resolution failures leave
the original bytes intact. A per-project `.honk/isolated.lock` serializes Honk's
isolated operations, while the existing Honk cache lock excludes concurrent
legacy writers using the same HONK_HOME. Persistent locks use the existing atomic
write helper.

This is a path/Git graph lock, not yet registry pinning or a workspace-wide
shared lock. Canonical lock bytes are regenerated from local manifests; arbitrary
manual formatting changes require an unlocked canonical rewrite. As in Cargo,
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

Qualification with a separately built graph compiler:

```sh
GRAPH_GOOSE=/path/to/qualified/goose python3 tests/isolated_cli.py -v
```

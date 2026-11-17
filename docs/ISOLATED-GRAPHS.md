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
Git/registry sources, lock/frozen/offline semantics, workspaces, dev/test/bench
targets, embedded resources and build reuse are unfinished and rejected when
requested. Honk.lock is neither read nor written by this mode. The compiler
rejects non-toolchain native sidecars, foreign externs/exports and unsupported
tooling. Source digest assertions are producer-owned; concurrent source edits
are not an atomic filesystem snapshot. This is not full Cargo parity.

Qualification with a separately built graph compiler:

```sh
GRAPH_GOOSE=/path/to/qualified/goose python3 tests/isolated_cli.py -v
```

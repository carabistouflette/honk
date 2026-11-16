# Goose Nest registries (experimental)

Honk supports static Goose Nest v1 registries alongside existing Git/path dependencies.
Public default: https://carabistouflette.github.io/goose-nest/index.

```sh
honk search semver
honk info goose-semver
honk add goose-semver --as semver
honk fetch
honk run --frozen
```

An omitted version selects the latest compatible stable release and stores a caret
requirement. Use `--version '^0.1.1'` to specify it explicitly. Use `--registry URL`
with add/search/info to select another registry. Without `--as`, package hyphens
become underscores in the import alias. Existing Git/path add syntax is unchanged.

```toml
[dependencies]
semver = { package = "goose-semver", version = "^0.1.1" }
```

Import it with `import semver;`. A dependency table with no path/git uses the
registry. `package` defaults to the alias and `registry` defaults to Nest's index.
A locked registry dependency records package, registry, exact version, checksum,
archive URL, entry and transitive metadata. Commit Honk.lock. A valid lock needs
no index, even if its version is subsequently yanked. `update` re-resolves current
non-yanked releases. `--locked` forbids lock changes; `--offline` forbids network;
`--frozen` combines both. A missing archive can be downloaded from a valid lock
online without querying the index. An intact cached blob can be extracted offline.
Older Honk clients reject lock entries containing registry fields; use the new
client or regenerate a Git/path-only lock after reverting the manifest.

New native build requirements: libarchive 3+ and OpenSSL 3+ development headers,
in addition to existing libcurl/libsodium requirements. Ubuntu packages are
`libarchive-dev libssl-dev`. No Python or shell starts during registry resolution.

The registry solver selects one version per package and rejects cycles, with
bounded backtracking. Honk currently uses global import aliases; conflicting
aliases remain errors. Registry roots must be declared in the application
manifest. A registry dependency discovered only in a Git/path dependency must
also be declared at the application root in this alpha. Published registry
packages use same-registry manifest dependencies, without sourced import strings.
Their declared package, version, entry, compiler pin and dependencies are checked
against registry metadata before use. Full protocol, transport/cache trust and
limits: https://github.com/carabistouflette/goose-nest/blob/main/docs/PROTOCOL.md.

The cache hashes all extracted file contents on each invocation, not just mtimes.
Corrupt/incomplete source entries fail closed; remove their digest directory and
`.ready` file under `HONK_HOME/nest/packages/`, then fetch again. The SHA-256-pinned
blob is retained. Do not edit cached dependency sources; use a path dependency.

Publication is currently a reviewed index PR plus a GitHub release asset, with
`honk package` or Nest's deterministic offline authoring tool. There is no hosted
publish API or `honk publish` command yet. No compile-time or universal Cargo
performance guarantee is made; the Nest repository contains reproducible scoped
fetch benchmarks.

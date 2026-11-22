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

The default flat compiler workflow selects one version per package and rejects cycles, with
bounded backtracking. Honk currently uses global import aliases; conflicting
aliases remain errors. Honk discovers registry dependencies inside Git/path manifests and legacy
sourced-import chains automatically. It discovers the non-registry graph first,
aggregates all registry requirements, then solves and downloads the registry
graph. A later narrow constraint can change a direct registry choice before any
archive is fetched; resolution failure leaves the old lock unchanged. Published registry
packages use same-registry manifest dependencies, without sourced import strings.
Their declared package, version, entry, compiler pin and dependencies are checked
against registry metadata before use. Full protocol, transport/cache trust and
limits: https://github.com/carabistouflette/goose-nest/blob/main/docs/PROTOCOL.md.

The cache hashes all extracted file contents on each invocation, not just mtimes.
Corrupt/incomplete source entries fail closed; remove their digest directory and
`.ready` file under `HONK_HOME/nest/packages/`, then fetch again. The SHA-256-pinned
blob is retained. Do not edit cached dependency sources; use a path dependency.

## Prepare a registry release

```sh
honk publish --dry-run \
  --url https://github.com/OWNER/REPO/releases/download/v1.0.0/example-1.0.0.tar.gz \
  > release.toml
```

Run this from a Git-tracked library with a current `Honk.lock`, tracked
`Honk.toml` and `LICENSE`, and a local compiler and dependency cache. Use
`-p NAME` to select a workspace member. The manifest needs explicit
`package.version` and `package.entry`. Production dependencies must use the
selected index. `--registry HTTPS_INDEX_URL` selects an index other than Nest.

Honk builds a deterministic archive, checks it with Nest's archive reader,
and typechecks the extracted library with the pinned compiler in offline
mode. It writes the verified archive to `target/package/<name>-<version>.tar.gz`
and prints a schema-1 index document with one release and the archive SHA-256.
The archive path and compiler messages go to stderr.

## Publish through GitHub

```sh
honk publish --repo OWNER/LIBRARY --index-repo carabistouflette/goose-nest \
  --index-fork OWNER/goose-nest
```

This uses the same offline preparation, then uses Python 3.11+ and authenticated
GitHub CLI to upload the archive and open a reviewed index PR. The library
repository must be public and have the tag `v<package.version>` on GitHub.
Set the release repository to its canonical GitHub spelling. Use a synced
direct fork with write access, or omit `--index-fork` when you can write branches
in the index repository.

Publication appends the release and updates the search catalog in one commit.
On retry, Honk checks the existing asset SHA-256 and reuses a matching branch
and open PR. It refuses a conflicting version or asset. The release can already
exist if a later index operation fails.

The [manual Nest publication workflow](https://github.com/carabistouflette/goose-nest#publish-a-package)
also accepts the archive produced by `--dry-run`.

## Isolated multi-version graphs

`honk build/run/check/fetch/update --isolated` uses the scoped compiler graph and
version-2 lock instead of the flat workflow above. It can compile incompatible
registry versions together, unifies SemVer-compatible releases with bounded
backtracking, and records each owner's alias binding and complete immutable
release metadata. See [the isolated graph contract and limits](ISOLATED-GRAPHS.md).
Honk's scoped graph producer selects versions. It uses the vendored Nest client
to prefetch missing archives in groups of up to four on online runs.

# Honk

A Goose project manager, written in Goose. Apache-2.0. Pre-release; Linux/POSIX is the initial target. Uses the Goose compiler for compilation and goose-toml/goose-argparse for parsing. A small C adapter supplies missing process/filesystem primitives.

```sh
make setup
make format check test
make build
export GOOSE=/absolute/path/to/pinned/goose # optional; must match GOOSE_REVISION
.build/honk new hello
cd hello
/path/to/honk run
```

Without `GOOSE`, Honk builds and caches the exact pinned compiler using Git, CMake 3.27+, C/C++20 compilers, and Make/Ninja. Linux also needs libc development headers. `HONK_HOME` selects Honk's cache; default is `$XDG_CACHE_HOME/honk` or `$HOME/.cache/honk`. Projects may override the compiler with `[toolchain] revision = "<full commit>"`. `GOOSE` explicitly selects a compiler and checks its advertised short revision against the pin. You must trust that binary; this is not cryptographic verification. Source bootstraps additionally verify the full Git commit.

## Projects

```toml
[package]
name = "hello"
version = "0.1.0"
kind = "bin" # or lib
entry = "src/main.goose"

[dependencies]
mathx = { path = "../mathx" }
# remote = { git = "https://github.com/owner/repo.git", rev = "v0.1.0" }

[dev-dependencies]
# test support; excluded when this project is consumed as a dependency
```

Use `import mathx;` in application source. Library names and namespaces are separate; declare the namespace in library source. The dependency key is the Goose import name: identifiers with underscores, not hyphens. Existing libraries need `<import-name>.goose` at their root. Honk libraries may use a manifest entry elsewhere; Honk creates an adapter in its staging directory. Existing sourced imports are remapped to the explicit manifest graph. Honk discovers transitive manifests and sourced imports in legacy dependency entry files, rejects conflicting identities/refs and cycles, and checks cached Git checkouts for local changes before use. Declare other package requirements in Honk.toml; no untracked compiler fetch is allowed.

## Commands

- `new PATH [--lib] [--name NAME]`, `init [PATH]`: scaffold without overwriting existing files.
- `build [--release] [--bin NAME]`, `run [--release] -- ARGS`: native executable in `target/debug` or `target/release`. `--bin NAME` selects `src/bin/NAME.goose`. Executables are compiled privately and published atomically after success; a failed compiler leaves the previous binary intact, and output symlinks/special files are rejected. Debug builds enable Goose runtime checks. Libraries are source packages and `build` checks them.
- `check`: type/lifetime checking. `test`, `bench`: build and run `.goose` programs under `tests/` or `bench/`, failing on the first nonzero exit. Test/benchmark executables have a separate reserved output directory so target names cannot overwrite application binaries. Program arguments follow `--`.
- `fmt [--check]`: Goose formatting.
- `add NAME --path PATH` or `add NAME --git HTTPS_URL --rev REF [--dev]`; `remove NAME`: normalize the manifest; run `fetch` to refresh the lock. Normalization removes comments.
- `fetch`, `update`: resolve dependencies; ordinary commands preserve locked Git commits, `update` deliberately refreshes refs.
- `tree`: list resolved dependencies. `metadata`: machine-readable JSON project metadata.
- `package`: typecheck and produce a deterministic source `.tar.gz` under `target/package/`. Requires tracked Honk.toml/Honk.lock in a Git repository; copies only tracked regular files into private staging, excludes local untracked files, and typechecks the exact exported contents offline before publishing the archive. External path dependencies and tracked submodules are rejected. Vendored dependencies inside the project are supported.
- `install [--root PREFIX] [--force]`: build release and atomically install `PREFIX/bin/NAME`; default prefix is `HONK_HOME/installed`. Existing executables require `--force`. Add that bin directory to PATH yourself. `uninstall NAME [--root PREFIX]` works outside a project.
- `doc`: save the compiler's API declaration/documentation dump under `target/doc/NAME.goose`.
- `clean`: remove project build/staging directories without following symlinks.
- `toolchain`: obtain/report the pinned compiler; `version`, `help`.

All project commands discover Honk.toml upward from cwd. Program arguments retain their exact boundaries, including empty arguments; child exit codes propagate. SIGINT/SIGTERM are forwarded to the direct child; Honk retains its locks while waiting for that child to finish cleanup. This does not supervise arbitrary grandchildren created by an application. `--manifest-path PATH` explicitly selects a file named Honk.toml and rejects a final symlink. `[workspace] members = ["one", "two"]` supports explicit members; `--workspace` executes each, `-p NAME` selects one. Virtual workspaces execute all members by default. Each member keeps its own lockfile and output directory. Nested workspaces and symlinks in workspace-member paths are rejected, including for clean.

## Reproducibility and safety

Commit Honk.lock. It records the compiler revision and dependencies. Git refs resolve to full commits. `--locked` forbids lockfile changes; `--offline` forbids network/bootstrap but may write a lockfile for local dependencies; `--frozen` combines both. Local dependencies remain live source trees, not immutable releases. HTTPS is the only network Git transport. Credentials in manifests, shell commands, automatic lifecycle scripts, and Git hooks are unsupported. Credentials may be supplied by Git transport environment/agents under your control; Git repository-context environment overrides (such as GIT_INDEX_FILE) are cleared and global Git configuration is deliberately disabled, so credential helpers and URL rewrites from it are not loaded. Native dependencies and the selected compiler can execute code; build only trusted projects.

Honk stages source trees under `.honk/` and leaves original sources intact. Source trees reject symlinks and special files and are bounded to 100,000 entries, 256 MiB, and depth 64 per tree; Goose sources and manifests are limited to 1 MiB each. Resolution is bounded to 256 packages; source discovery is bounded to 4096 Goose files and directories. Captured subprocess stdout is bounded to 1 MiB. Honk uses nonblocking project/cache locks: concurrent operations fail clearly; retry after the other process exits. Private per-user caches and project directories must not be writable by untrusted users.

This is an evolving Git/path package workflow. Registry publishing, semver solving, cross compilation, and Windows support are not implemented. Do not treat this pre-release as Cargo feature or stability parity.

## Validation

`make check test` runs formatting, typechecking, and black-box process tests. `make security` runs 213 deterministic malformed-import probes and FIFO rejection. `make sanitize` runs integration and hostile-input suites with AddressSanitizer, UndefinedBehaviorSanitizer, debug checks, and bounds-check elimination disabled in Honk. `make bench` records all raw samples, compiler, platform and source revision in `.build/bench.json`, plus wide-directory and dense production/dev dependency-graph workloads in `.build/audit-perf.json`. `tests/audit_perf.py` can interleave a comparison binary from `HONK_BASELINE` against `HONK`; no timing threshold or universal performance claim.

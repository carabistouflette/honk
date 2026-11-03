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

Without `GOOSE`, Honk builds and caches the exact pinned compiler using Git, CMake 3.27+, C/C++20 compilers, and Make/Ninja. Linux also needs libc development headers. `HONK_HOME` selects Honk's cache; default is `$XDG_CACHE_HOME/honk` or `$HOME/.cache/honk`. Projects may override the compiler with `[toolchain] revision = "<full commit>"`. `GOOSE` explicitly selects an existing matching compiler; it is not silently accepted at a different revision.

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

Use `import mathx;` in application source. The dependency key is the Goose import name: identifiers with underscores, not hyphens. Existing libraries need `<import-name>.goose` at their root. Honk libraries may use a manifest entry elsewhere; Honk creates an adapter in its staging directory. Existing sourced imports are remapped to the explicit manifest graph. Honk discovers transitive manifests and sourced imports in legacy dependency entry files. Declare other package requirements in Honk.toml; no untracked compiler fetch is allowed.

## Commands

- `new PATH [--lib] [--name NAME]`, `init [PATH]`: scaffold without overwriting existing files.
- `build [--release] [--bin NAME]`, `run [--release] -- ARGS`: native executable in `target/debug` or `target/release`. `--bin NAME` selects `src/bin/NAME.goose`. Debug builds enable Goose runtime checks. Libraries are source packages and `build` checks them.
- `check`: type/lifetime checking. `test`, `bench`: build and run `.goose` programs under `tests/` or `bench/`, failing on the first nonzero exit. Program arguments follow `--`.
- `fmt [--check]`: Goose formatting.
- `add NAME --path PATH` or `add NAME --git HTTPS_URL --rev REF [--dev]`; `remove NAME`: normalize the manifest; run `fetch` to refresh the lock. Normalization removes comments.
- `fetch`, `update`: resolve dependencies; ordinary commands preserve locked Git commits, `update` deliberately refreshes refs.
- `tree`: list resolved dependencies. `metadata`: machine-readable JSON project metadata.
- `clean`: remove project build/staging directories without following symlinks.
- `toolchain`: obtain/report the pinned compiler; `version`, `help`.

All project commands discover Honk.toml upward from cwd. `--manifest-path PATH` selects a manifest. `[workspace] members = ["one", "two"]` supports explicit members; `--workspace` executes each, `-p NAME` selects one. Virtual workspaces execute all members by default. Each member keeps its own lockfile and output directory. Nested workspaces are rejected.

## Reproducibility and safety

Commit Honk.lock. Git refs resolve to full commits. `--locked` forbids lockfile changes; `--offline` forbids network/bootstrap but may write a lockfile for local dependencies; `--frozen` combines both. Local dependencies remain live source trees, not immutable releases. HTTPS is the only network Git transport. Credentials in manifests, shell commands, automatic lifecycle scripts, and Git hooks are unsupported. Native dependencies and the selected compiler can execute code; build only trusted projects.

Honk stages source trees under `.honk/` and leaves original sources intact. Source trees reject symlinks and special files and are bounded to 100,000 entries, 256 MiB, and depth 64 per tree; Goose sources and manifests are limited to 1 MiB each. Resolution is bounded to 256 packages. Captured subprocess stdout is bounded to 1 MiB. Honk uses nonblocking project/cache locks: concurrent operations fail clearly; retry after the other process exits. Private per-user caches and project directories must not be writable by untrusted users.

This is an evolving Git/path package workflow. Registry publishing, semver solving, cross compilation, and Windows support are not implemented. Do not treat this pre-release as Cargo feature or stability parity.

## Validation

`make check test` runs formatting, typechecking, and black-box process tests. `make sanitize` runs the same integration suite with AddressSanitizer, UndefinedBehaviorSanitizer, debug checks, and bounds-check elimination disabled in Honk. `make bench` reports local CLI timings; no timing threshold or universal performance claim.

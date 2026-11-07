# Honk

Honk builds and manages Goose projects. It creates applications and libraries,
resolves Git/path dependencies, records them in a lockfile, runs tests, and
packages tracked source files. Honk is written in Goose with a small POSIX adapter.
It is Apache-2.0 licensed.

The latest experimental release is [v0.4.0](https://github.com/carabistouflette/honk/releases/tag/v0.4.0),
source `f9f35e20e4407df56b2ad45310266c9238403144`. Current development source also contains
unreleased features, including watch and `check --diagnostics`; v0.4.0 includes neither feature. CLI, manifest and lockfile compatibility are not
yet guaranteed. Registry publishing, general dependency solving, cross
compilation and Cargo feature/stability parity are outside this release.

This branch prepares **v0.5.0-rc.1**; the candidate has not been published.
It collects watch, parallel tests, test reuse, diagnostics, filtering and optional
progress. [Candidate scope and publication gates](docs/RELEASE-CANDIDATE.md)
separate prepared source from verified published artifacts.

## Quickstart

Build on Linux x86-64 with kernel 5.3+ and glibc 2.34+. Install Git 2.31+,
CMake 3.27+, Make, C/C++20 tools, pkg-config, libcurl development files
(7.85+ with TLS, asynchronous DNS and thread-safe initialization), and libsodium
development files (1.0.18+). Tests also need Python 3.11+, OpenSSL and GNU tar/gzip;
packaging needs GNU tar/gzip. Other platforms are not validated.

```sh
git clone --branch v0.4.0 --depth 1 https://github.com/carabistouflette/honk.git
cd honk
make setup build
export GOOSE="$PWD/.toolchain/goose/build/goose"
honk_bin="$PWD/.build/honk"
"$honk_bin" new ../hello-honk
cd ../hello-honk
"$honk_bin" run
"$honk_bin" check --frozen
```

This prints `Hello, Goose!`. Choose fresh `honk` and `hello-honk` directories.
`make setup` builds the exact compiler in `GOOSE_REVISION`. If you already have
that trusted compiler, replace setup/build with
`make GOOSE=/absolute/path/to/goose build` and export that same path as `GOOSE`.

## Everyday commands

| Command | Purpose |
| --- | --- |
| `new PATH [--lib]`, `init [PATH]` | Create a project without overwriting files. |
| `check --diagnostics text\|json` | Single-package compiler diagnostics; [format and limits](docs/COMPILER_DIAGNOSTICS.md). |
| `build`, `run -- ARGS`, `check` | Compile, run, or type/lifetime-check. Use `build/run --release` for release builds. |
| `watch check/test --watch-dir ABS_DIR [--watch-dir ABS_DIR ...]` | Rerun on `.goose` changes; optional `--watch-recursive` discovers bounded subtrees; see [watch scope and cleanup](docs/WATCH.md). |
| `test`, `bench`, `fmt [--check]` | Run test/benchmark programs or format sources. |
| `add NAME --path PATH`, `add NAME --git URL --rev REF` | Declare a local or exact Git dependency. |
| `add NAME --git URL --version REQUIREMENT` | Select a matching Git tag. See the [version rules](docs/GIT-VERSION-DESIGN.md). |
| `remove NAME [NAME ...]` | Remove up to 64 dependencies in one atomic manifest update. |
| `fetch`, `update`, `tree` | Refresh the lock, deliberately update Git selections, or inspect dependencies. |
| `metadata`, `toolchain` | Print project metadata or obtain/report the compiler. |
| `package`, `install`, `uninstall NAME`, `doc`, `clean` | Package tracked sources, manage executables, generate API declarations, or remove build state. |

Commit `Honk.lock`. `--locked` forbids changes to it; `--offline` forbids network
and compiler bootstrap; `--frozen` combines both. Source/package checks still run.
Workspaces support `--workspace` and `-p NAME[@FULL_VERSION]`. Each member has its
own lock/output; updates are atomic per manifest, not across a whole workspace.

`build/run/test --reuse-build` is optional and off by default. A verified hit can
skip compilation while retaining dependency validation, staging and atomic
publication. Unsupported inputs compile normally. Indirect system toolchain
files must stay unchanged; use `clean` after changing them.
[Eligibility and limits](docs/INCREMENTAL-BUILDS.md) explain the tradeoffs.

## Documentation

- [CLI, manifests, workspaces, limits and diagnostics](docs/REFERENCE.md)
- [Architecture](docs/ARCHITECTURE.md), [security and trust](SECURITY.md)
- [Validation and release evidence](RESULTS.md), [performance methods and history](bench/README.md)
- [Changelog](CHANGELOG.md), [contributing](CONTRIBUTING.md), [third-party notices](THIRD_PARTY_NOTICES.md)

Build only projects and tools you trust: Honk is not a sandbox. Private caches
must not be writable by untrusted users. Builds preserve the last-good executable
on compilation failure; source packaging requires tracked regular files and
in-package dependencies. See the reference for resource, signal and HTTP limits.

## Optional command progress

`honk build|run|check|test|bench|install --progress auto|always|never` adds
bounded, escaped status snapshots to stderr. The default is `never`, preserving
existing command output. `auto` displays only on a terminal; `always` also emits
plain text when redirected. Terminal facts are re-probed for each snapshot;
nonempty `NO_COLOR` disables styling, and absent/empty/dumb `TERM` disables ANSI.
Existing stdout and child diagnostics remain unchanged. Test/bench progress is
reported after each completed target, with complete newline-terminated frames;
snapshots begin with a newline to preserve unterminated child diagnostics, and
there is no live animation or cursor state spanning child execution. Successful
styled writes include the reset sequence; partial writes can leave terminal
formatting altered, and no rollback is promised. Narrow
terminals receive a simple completion line. A status-write failure suppresses
later presentation without changing the command's result. A native signal-guard
cleanup failure instead exits with status 1, without further application
diagnostics or child launches (the runtime may flush existing stdio buffers). Blocking stderr may still block; the borrowed descriptor's flags are never changed. The rendering
and optional POSIX adapter come from the pinned goose-terminal snapshot.

### Select test and benchmark targets

`honk test --filter 'tests/unit/**/*.goose'` and
`honk bench --filter 'bench/*_bench.goose'` select standalone `.goose` programs.
Quote the pattern to prevent shell expansion. Matching is case-sensitive on the
whole project-relative byte path (including `tests/` or `bench/`), with hidden
components included. Without `--filter`, all targets run as before. Arguments
after `--` still go to each selected program. Imported helpers are not filtered.

Patterns support `*` (within one component), `?` (one byte), `**` as an entire
component (zero or more components), classes `[abc]`, `[a-z]`, `[!abc]`/`[^abc]`,
and backslash escapes outside classes. Braces, tilde and extglobs have no special
meaning. Empty/absolute patterns, empty or `.`/`..` components, malformed classes,
embedded `**` and trailing escapes fail. Patterns are capped at 1024 bytes and
128 components; matched paths at 4095 bytes and 128 components. Each match uses
goose-glob's default 1048576 work budget. Invalid paths or exhausted limits fail
the command before any selected program runs; a filter matching no targets also
fails (including when the target directory is absent).

Filtering compiles the pattern once with `glob::compile` and reuses the owned
pattern through the public `glob::matches` API across all workspace packages from
[goose-glob v0.1.0-alpha.4](https://github.com/carabistouflette/goose-glob/releases/tag/v0.1.0-alpha.4).
The [combined alpha.4 consumer measurement](bench/results/glob-alpha4-2026-11-07/README.md)
retains 84 startup, test/bench, default/forced-progress and maximum-RSS samples.
Its whole-command observations are mixed, with no consistent speed or memory gain.
The [earlier pre-terminal comparison](bench/results/glob-2026-11-07/README.md)
remains a separate historical record.
Honk retains its own traversal and staging: symlinks and special files are
rejected, `.git`, `target`, `.honk`, `.toolchain`, `.build` remain excluded, and
the existing 4096 source/directory caps apply before filtering. This option is
available only for `test` and `bench`; it does not prune the source tree or change
manifest selection. The library and this CLI remain experimental.

## Opt-in parallel test execution

`honk test --jobs 1..8` compiles all selected targets sequentially, then executes
independent tests in bounded cohorts. The default without --jobs retains the
existing sequential inherited-stream behavior. Explicit --jobs captures up to
64 KiB per stream per child, uses null stdin, and applies a 30-second direct-child
deadline; override with `--test-timeout-ms 1..86400000`. Output is replayed in
target discovery order after each cohort closes. Workspace members stay
sequential; watch and bench do not accept these options. See
[contracts and limits](docs/parallel-tests.md), including failure, cancellation
and the absence of hard wall-time or descendant-cleanup guarantees.

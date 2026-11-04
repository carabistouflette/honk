# Honk

A Goose project manager, written in Goose. Apache-2.0. Pre-release; Linux x86-64/glibc is the initial target. Uses the pinned Goose compiler and vendored parsing, text, version and process libraries. A small C adapter supplies filesystem operations and application signal guards.

```sh
git clone https://github.com/carabistouflette/honk.git
cd honk
make setup
make check test security
make build
export GOOSE="$PWD/.toolchain/goose/build/goose"
honk_bin="$PWD/.build/honk"
cd ..
"$honk_bin" new hello-honk
cd hello-honk
"$honk_bin" run
"$honk_bin" check --frozen
```

The example creates a sibling application and leaves the Honk checkout clean.
Build/test prerequisites: Linux, Git 2.31+, CMake 3.27+, C/C++20 compilers, Make,
libc and libcurl development headers (libcurl >=7.85 with TLS, asynchronous DNS and thread-safe initialization), pkg-config, Python 3.11+, GNU tar, gzip and OpenSSL (TLS tests). The tests exercise
packaging as well as builds. The sanitizer and portable-copy scripts default to GCC; set
`HONK_SANITIZER_CC=clang` to validate with Clang instead.
The release workflow is initially validated on Linux x86-64/glibc; Windows,
macOS, other architectures and libc implementations are not validated.

[Changelog](CHANGELOG.md), [validation results](RESULTS.md), [benchmark methods and raw samples](bench/README.md),
[security policy](SECURITY.md), and [third-party notices](THIRD_PARTY_NOTICES.md).

Without `GOOSE`, Honk builds and caches the exact pinned compiler using Git, CMake 3.27+, C/C++20 compilers, and Make/Ninja. Linux also needs libc development headers. `HONK_HOME` selects Honk's cache; default is `$XDG_CACHE_HOME/honk` or `$HOME/.cache/honk`. Projects may override the compiler with `[toolchain] revision = "<full commit>"`. `GOOSE` explicitly selects a compiler and checks its advertised short revision against the pin. You must trust that binary; this is not cryptographic verification. Source bootstraps additionally verify the full Git commit. Honk-managed compiler caches require a successful-build completion marker and matching checkout/version; older caches without that marker need one online rebuild/validation or an explicit matching `GOOSE` before offline use. Incomplete Git initialization and failed source repairs are retryable online; completed cache identity mismatches still fail closed.

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

Entries must be safe relative paths ending in `.goose`. Library entry path components (without the extension) must be ASCII Goose identifiers: letters/underscore first, then letters/digits/underscore, excluding language keywords. Uppercase, contextual names such as `from`, and builtin module names remain valid path components. Binary filenames may use other safe characters for standalone compilation; using the entry through a root import adapter requires identifier path components too.

Use `import mathx;` in application source. Library names and namespaces are separate; declare the namespace in library source. Scaffolding replaces hyphens with underscores for library namespaces and rejects reserved names before creating files. The dependency key is the Goose import name: identifiers with underscores, not hyphens. Existing libraries need `<import-name>.goose` at their root. Honk libraries may use a manifest entry elsewhere; Honk creates an adapter in its staging directory. Existing sourced imports are remapped to the explicit manifest graph. Honk discovers transitive manifests and sourced imports in legacy dependency entry files, rejects conflicting identities/refs and cycles, and checks cached Git checkouts for local changes before use. Declare other package requirements in Honk.toml; no untracked compiler fetch is allowed.

## Commands

- `new PATH [--lib] [--name NAME]`, `init [PATH]`: scaffold without overwriting existing files.
- `build [--release] [--bin NAME]`, `run [--release] -- ARGS`: native executable in `target/debug` or `target/release`. `--bin NAME` selects `src/bin/NAME.goose`. Executables are compiled privately and published atomically after success; a failed compiler leaves the previous binary intact, and output symlinks/special files are rejected. Debug builds enable Goose runtime checks. Libraries are source packages and `build` checks them.
- `check`: type/lifetime checking. `test`, `bench`: build and run `.goose` programs under `tests/` or `bench/`, failing on the first nonzero exit. Test/benchmark executables have a separate reserved output directory so target names cannot overwrite application binaries. Program arguments follow `--`.
- `fmt [--check]`: Goose formatting.
- `add NAME --path PATH`, `add NAME --git HTTPS_URL --rev REF [--dev]`, or `add NAME --git HTTPS_URL --version REQUIREMENT [--dev]`; `remove NAME`: edit dependency syntax while preserving surrounding comments and formatting; run `fetch` to refresh the lock. Unsupported inline parent-table edits and changes exceeding dependency or metadata-size limits fail before replacing the original manifest.
- `fetch`, `update`: resolve dependencies; ordinary commands preserve locked Git commits, `update` deliberately refreshes refs.
- `tree`: list resolved dependencies. `metadata`: machine-readable JSON project metadata. `metadata -p NAME` or `metadata -p NAME@FULL_VERSION` selects one workspace member; `metadata --workspace` streams an array of members (check the exit status before consuming output). Metadata does not create caches or obtain a compiler, and rejects non-UTF-8 project paths before emitting a project object.
- `package`: requires GNU tar/gzip; typecheck and produce a deterministic source `.tar.gz` under `target/package/`. Requires tracked Honk.toml/Honk.lock in a Git repository; copies only tracked regular files from the current working tree into private staging, excludes local untracked files, and typechecks the exact exported contents offline before publishing the archive. External path dependencies and tracked submodules are rejected. Vendored dependencies inside the project are supported. Archive modes normalize to 0644/0755 independently of caller umask. Archive creation uses an explicit GNU format and ignores inherited TAR_OPTIONS/GZIP options.
- `install [--root PREFIX] [--force]`: build release and atomically install `PREFIX/bin/NAME`; default prefix is `HONK_HOME/installed`. Existing executables require `--force`. Add that bin directory to PATH yourself. `uninstall NAME [--root PREFIX]` works outside a project; empty roots, unsupported project flags and symlinks in every prefix component are rejected.
- `doc`: save the compiler's API declaration/documentation dump under `target/doc/NAME.goose`.
- `clean`: remove project build/staging directories without following symlinks.
- `toolchain`: obtain/report the pinned compiler. Opt-in `toolchain --metadata [--manifest-path PATH]` reads anonymous GitHub source metadata for the project pin or built-in default outside a project. It performs no compiler/Git/cache/bootstrap work; `--offline`, `--frozen`, `--locked` and package/workspace flags are rejected. `version`, `help` remain local.

All project commands discover Honk.toml upward from cwd. Program arguments retain their exact boundaries, including empty arguments; child exit codes propagate. SIGINT/SIGTERM sent to Honk are forwarded to the direct child; a terminal Ctrl-C already delivered to their shared foreground group is not sent twice. Honk retains its locks while waiting for child cleanup. For scripted cancellation, signal Honk's PID: external group-wide signals cannot be distinguished from direct signals and can reach the child twice. This does not supervise arbitrary grandchildren created by an application. `--manifest-path PATH` explicitly selects a file named Honk.toml and rejects a final symlink. `[workspace] members = ["one", "two"]` supports explicit members; `--workspace` executes each, `-p NAME` selects one unambiguous member, and `-p NAME@FULL_VERSION` compares strict SemVer precedence to disambiguate versions before any package command runs. Multiple matching members are rejected, including with `--workspace`. Virtual workspaces execute all members by default. Each member keeps its own lockfile and output directory. Nested workspaces and symlinks in workspace-member paths are rejected, including for clean.

## Reproducibility and safety

Commit Honk.lock. It records the compiler revision and dependencies. An oversized resolved lockfile is rejected before replacing the original. Git refs resolve to full commits. `--locked` forbids lockfile changes; `--offline` forbids network/bootstrap but may write a lockfile for local dependencies; `--frozen` combines both. Local dependencies remain live source trees, not immutable releases. HTTPS is the only network Git transport. Both CLI and `make setup` Git calls ignore ambient hooks and repository-context overrides. Certificate and hostname verification are forced, including over inherited `GIT_SSL_NO_VERIFY` and URL-specific cache configuration; system trust roots and Git CA environment settings remain available. Credentials in manifests, shell commands, automatic lifecycle scripts, and Git hooks and fsmonitor commands are disabled for CLI Git invocations. Credentials may be supplied by Git transport environment/agents under your control; Git repository-context environment overrides (such as GIT_INDEX_FILE) are cleared and global Git configuration is deliberately disabled, so credential helpers and URL rewrites from it are not loaded. Native dependencies and the selected compiler can execute code; build only trusted projects.

Honk stages source trees under `.honk/` and leaves original sources intact. Source trees reject symlinks and special files and are bounded to 100,000 entries, 256 MiB, and depth 64 per tree; Goose sources and manifests are limited to 1 MiB each. Resolution is bounded to 256 packages; source discovery is bounded to 4096 Goose files and directories. Each directory listing is limited to 1 MiB of names including separators; filenames containing CR/LF are rejected. Original source limits remain 1 MiB even when generated import mappings enlarge staged files; only validated staged rereads have a separate bounded 8 MiB allowance. Captured subprocess stdout is bounded to 1 MiB. Honk uses nonblocking project/cache locks: concurrent operations fail clearly; retry after the other process exits. Atomic text updates preserve existing ordinary permission bits; newly created text metadata is owner-only. Private per-user caches and project directories must not be writable by untrusted users.

This is an evolving Git/path package workflow. Registry publishing, general dependency solving/backtracking, cross compilation, and Windows support are not implemented. Do not treat this pre-release as Cargo feature or stability parity.

## Validation

`make check test` runs formatting, typechecking, and black-box process tests. `make portable` exercises source-copy independence, byte limits, and tracked-file staging with kernel-assisted copying disabled and native sanitizers enabled. `make security` runs 213 deterministic malformed-import probes and FIFO rejection. `make sanitize` runs integration and hostile-input suites with AddressSanitizer, UndefinedBehaviorSanitizer, debug checks, and bounds-check elimination disabled in Honk. `make bench` records all raw samples, compiler, platform and source revision in `.build/bench.json`, plus wide-directory and dense production/dev dependency-graph workloads in `.build/audit-perf.json`. `tests/audit_perf.py` can interleave a comparison binary from `HONK_BASELINE` against `HONK`; no timing threshold or universal performance claim.

Large staged files use Linux kernel-assisted copying where supported, with a bounded portable fallback. Temporary staging rewrites are atomic without requesting crash durability; manifest, lockfile, and cache metadata writes retain their durability syncs. Snapshot tests verify byte equality, executable assets, source/copy independence, and rejection above the logical byte limit. Benchmarks record their filesystem and include a 32 MiB asset workload; `AUDIT_TEMP_ROOT` selects the fixture location.

Dependency `add`/`remove` preserves comments and formatting outside edited TOML
syntax using goose-toml-edit. Removal keeps attached comments as standalone
comments. Inline dependency assignments, dotted dependency fields and declared
dependency tables are supported; editing a dependency inside an inline parent
`dependencies = { ... }` is rejected before saving. Result validation and the
existing atomic manifest write remain in effect.

Successful CLI completion checks Honk’s own stdout writes, including metadata and toolchain reporting and buffered failures. Output errors in delegated programs remain their responsibility. A broken/full destination for Honk output returns nonzero; this does not roll back a completed build or installation.

Package versions use strict SemVer 2.0 with a Honk limit of 64 bytes, preserving safe package filename lengths. Prerelease and build metadata are supported; leading zero numeric components, partial versions and `v` prefixes are rejected. Workspace selectors ignore build metadata when comparing versions, so equal-precedence members remain ambiguous. Exact Git refs and paths retain their behavior; a separate bounded Git-tag requirement workflow is described below. The tested tag policy accepts only enumerated full `refs/tags/` names and strips at most one lowercase `v`; arbitrary branch/ref strings never enter that policy. The [bounded tag-selection policy](docs/GIT-TAG-SELECTION.md) and [transport/lock contract](docs/GIT-VERSION-DESIGN.md) describe the tested development workflow.

Honk delegates child ownership to pinned goose-process. This requires Linux kernel 5.3+ and glibc 2.34+. Commands use Child with no overall deadline by default, preserving long-running `run` servers. Git tag metadata discovery explicitly uses a 60-second deadline. The parent pumps bounded 20 ms steps, forwards pending cancellation through pidfds, and retains locks through direct-child cleanup or exceptional transferred-child recovery. Recovery may wait indefinitely if OS permissions prevent proving cleanup. Captured stdout is capped at 1 MiB; stderr and stdin remain inherited. Argument limits include argv[0]: 4,096 arguments, 1 MiB total, 131,071 bytes per argument. PATH lookup uses the child's effective environment/cwd; it does not invoke a shell fallback for executable text without a shebang. Descendants and capture pipes they keep open remain outside direct-child supervision. Terminal Ctrl-C suppression is best effort during launch, when the application cannot distinguish a signal predating the child from one already delivered to its foreground group.

The metadata command requests only the fixed Goose-upstream commit endpoint with HTTPS certificate/hostname verification, anonymous headers and identity content encoding. It makes one request with no proxy, credentials, redirect or retry, caps body/header callback bytes at 256 KiB/32 KiB, requires HTTP 200 and full returned SHA equality, and emits escaped JSON. The 5000 ms transfer timeout is **not** a hard wall deadline: threaded DNS cleanup can take longer. Metadata does not authenticate compiler binaries, authorize installation or prove upstream trust. Returned URL/subject strings remain untrusted data. libcurl callback normalization/trailer limitations mean security-critical headers/digests must never be inferred from transfer success; this consumer validates the required JSON SHA directly. `make metadata-test` and `make metadata-sanitize` use only local TLS fixtures with a test-only shim; ordinary builds contain no shim.


## Optional diagnostic file

Add `--log-file PATH` after an ordinary command, for example
`honk metadata --log-file /private/directory/honk.log`. Help/version retain
existing early-return behavior. Without the option no diagnostics are emitted
and no log path is opened. Machine-readable stdout remains separate.

Records contain only fixed lifecycle event names, elapsed nanoseconds, and
numeric outcome codes. Arguments, environment values, project text, paths and
Git URLs are not copied into them. `returned` is emitted only after Honk's own
stdout flush succeeds. Errors and child failures after logging is configured
use fixed error events; signal handlers never log. Abrupt termination cannot guarantee an event.

The application-owned Linux adapter rejects symlinks in every supplied path
component and accepts only euid-owned, single-link regular files of exact mode
0600. New files are created privately; parents are never created. Each append
uses a nonblocking advisory exclusive lock, checks a 16417-byte line cap and
16MiB total cap, completes short/EINTR writes, and checks close. Existing prefix
bytes remain. Writers ignoring the lock and same-user pathname changes are
outside this coordination contract. This is not a path sandbox or durability
promise. A busy/invalid/full/failed destination returns nonzero; partial output
or already-completed application work is not rolled back. There is no automatic
retry, rotation or fsync. Use a fresh private file when the cap is reached.

The opt-in toolchain metadata command also accepts explicit `--log-file`; those records contain only fixed lifecycle events and numeric duration/outcome fields, never response URLs, subjects, pins or bodies. Logging is the only explicit file output added to that otherwise cache/compiler-free path.

Explicit diagnostics may record `started`/`failed` even when a metadata flag combination is rejected before transport. Log delivery can fail after stdout or command side effects; no rollback is promised, and callers must check the exit status.


### Git version requirements (unreleased)

A Git dependency may use `version = "^1.2.3"` instead of `rev`, including through
`add NAME --git HTTPS_URL --version REQUIREMENT`. Field presence is exclusive: both
keys together, empty requirements and any version field on a path dependency
are rejected. Requirements are at most 4,096 bytes and use ASCII spaces, not TAB.
Bare full versions are exact; explicit `= > >= < <= ^ ~`, comma AND and standalone
`*` are supported. There are no partial versions, implicit caret, OR or hyphen
ranges. Prereleases require a comparator with the same core and a prerelease.

Unlocked resolution enumerates at most 1 MiB / 8,192 raw Git tag records and
4,096 base tags, handles annotated peeling, then chooses the highest matching
precedence. Equal highest aliases/build-only distinctions fail as ambiguous. A
60-second transfer deadline applies to the metadata child; cleanup and kernel
scheduling are not hard real-time guarantees. Fetch verifies the selected peeled
commit and requires a Honk library manifest with a matching package version.
Changing only a tag annotation/object while retaining the same commit is allowed;
annotations and signatures are not trusted or verified by this workflow.

The lock records the requirement, selected full tag ref and verified commit.
Ordinary commands reuse that commit until `update`, including after remote tag
movement. An online cold cache fetches the locked commit directly. `--locked`
rejects changed/missing entries before enumeration; offline/frozen never enumerate
or fetch. Failed resolution preserves lock bytes. Distinct requirements for one
import identity fail as a conflict; there is no graph backtracking or registry.
The optional new lock `requirement` key is rejected by older Honk versions.
This workflow is absent from the frozen v0.1.0 release.

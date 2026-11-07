# CLI and manifest reference

Applies to v0.4.0 and current main. The supported interface is the CLI, not Honk's
internal Goose modules. See [the quickstart](../README.md) first.

## Compiler selection

`GOOSE` selects a trusted existing compiler. Honk checks its advertised short
revision against the project pin; this does not authenticate the executable.
Without it, Honk builds the full pinned compiler source with Git/CMake/C++20
and verifies its full Git commit. `[toolchain] revision = "<full commit>"` can
select a project compiler.

`HONK_HOME` selects the cache; the default is `$XDG_CACHE_HOME/honk` or
`$HOME/.cache/honk`. Completed compiler caches need a successful-build marker,
matching checkout and matching version. Older/incomplete caches may need an
online rebuild or explicit matching `GOOSE` for offline use. Initialization
and failed repairs can be retried online; completed identity mismatches fail.

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

Starting with a fresh application scaffold, these commands create and declare a
sibling library. Use the matching compiler and `honk_bin` from the quickstart,
inside the application:

```sh
"$honk_bin" new ../mathx --lib
"$honk_bin" add mathx --path ../mathx
"$honk_bin" fetch
"$honk_bin" check --frozen
```

Entries must be safe relative paths ending in `.goose`. Library entry path components
(without the extension) must be ASCII Goose identifiers: letters/underscore first, then
letters/digits/underscore, excluding language keywords. Uppercase, contextual names such
as `from`, and builtin module names remain valid path components. Binary filenames may
use other safe characters for standalone compilation; using the entry through a root
import adapter requires identifier path components too.

Use `import mathx;` in application source; the scaffold exports `mathx::answer()`.
Library names and namespaces are separate;
declare the namespace in library source. Scaffolding replaces hyphens with underscores
for library namespaces and rejects reserved names before creating files. The dependency
key is the Goose import name: identifiers with underscores, not hyphens. Existing
libraries need `<import-name>.goose` at their root. Honk libraries may use a manifest
entry elsewhere; Honk creates an adapter in its staging directory. Existing sourced
imports are remapped to the explicit manifest graph. Honk discovers transitive manifests
and sourced imports in legacy dependency entry files, rejects conflicting
identities/refs and cycles, and checks cached Git checkouts for local changes before
use. Declare other package requirements in Honk.toml; no untracked compiler fetch is
allowed.

## Commands

- `new PATH [--lib] [--name NAME]`, `init [PATH]`: scaffold without overwriting existing files.
- `build [--release] [--bin NAME]`, `run [--release] -- ARGS`: native executable in `target/debug` or `target/release`. `--bin NAME` selects `src/bin/NAME.goose`. Executables are compiled privately and published atomically after success; a failed compiler leaves the previous binary intact, and output symlinks/special files are rejected. Debug builds enable Goose runtime checks. Libraries are source packages and `build` checks them.
- `check`: type/lifetime checking. `test`, `bench`: build and run `.goose` programs under `tests/` or `bench/`, failing on the first nonzero exit. Test/benchmark executables have a separate reserved output directory so target names cannot overwrite application binaries. Program arguments follow `--`.
- `fmt [--check]`: Goose formatting.
- `add NAME --path PATH`, `add NAME --git HTTPS_URL --rev REF [--dev]`, or `add NAME --git HTTPS_URL --version REQUIREMENT [--dev]`; `remove NAME [NAME ...]`: edit dependency syntax while preserving surrounding comments and formatting; run `fetch` to refresh the lock. Unsupported inline parent-table edits and changes exceeding dependency or metadata-size limits fail before replacing the original manifest.
- `fetch`, `update`: resolve dependencies; ordinary commands preserve locked Git commits, `update` deliberately refreshes refs.
- `tree`: list resolved dependencies. `metadata`: machine-readable JSON project metadata. `metadata -p NAME` or `metadata -p NAME@FULL_VERSION` selects one workspace member; `metadata --workspace` streams an array of members (check the exit status before consuming output). Metadata does not create caches or obtain a compiler, and rejects non-UTF-8 project paths before emitting a project object.
- `package`: requires GNU tar/gzip; typecheck and produce a deterministic source `.tar.gz` under `target/package/`. Requires tracked Honk.toml/Honk.lock in a Git repository; copies only tracked regular files from the current working tree into private staging, excludes local untracked files, and typechecks the exact exported contents offline before publishing the archive. External path dependencies and tracked submodules are rejected. Vendored dependencies inside the project are supported. Archive modes normalize to 0644/0755 independently of caller umask. Archive creation uses an explicit GNU format and ignores inherited TAR_OPTIONS/GZIP options.
- `install [--root PREFIX] [--force]`: build release and atomically install `PREFIX/bin/NAME`; default prefix is `HONK_HOME/installed`. Existing executables require `--force`. Add that bin directory to PATH yourself. `uninstall NAME [--root PREFIX]` works outside a project; empty roots, unsupported project flags and symlinks in every prefix component are rejected.
- `doc`: save the compiler's API declaration/documentation dump under `target/doc/NAME.goose`.
- `clean`: remove project build/staging directories without following symlinks.
- `toolchain`: obtain/report the pinned compiler. Opt-in `toolchain --metadata [--manifest-path PATH]` reads anonymous GitHub source metadata for the project pin or built-in default outside a project. It performs no compiler/Git/cache/bootstrap work; `--offline`, `--frozen`, `--locked` and package/workspace flags are rejected. `version`, `help` remain local.

All project commands discover Honk.toml upward from cwd. Program arguments retain their
exact boundaries, including empty arguments; child exit codes propagate.

SIGINT/SIGTERM sent to Honk are forwarded to the direct child. A terminal Ctrl-C
already delivered to a registered child in the same foreground group is suppressed;
classification during child launch is best effort. Honk retains its locks
while waiting for child cleanup. For scripted cancellation, signal Honk's PID: external
group-wide signals cannot be distinguished from direct signals and can reach the child
twice. This does not supervise arbitrary grandchildren created by an application.

`--manifest-path PATH` explicitly selects a file named Honk.toml and rejects a final
symlink.

`[workspace] members = ["one", "two"]` supports explicit members; `--workspace` executes
each, `-p NAME` selects one unambiguous member, and `-p NAME@FULL_VERSION` compares
strict SemVer precedence to disambiguate versions before any package command runs.
Multiple matching members are rejected, including with `--workspace`. Virtual workspaces
execute all members by default. Each member keeps its own lockfile and output directory.
Nested workspaces and symlinks in workspace-member paths are rejected, including for
clean.

## Reproducibility and safety

Commit Honk.lock. It records the compiler revision and dependencies. An oversized
resolved lockfile is rejected before replacing the original. Git refs resolve to full
commits. `--locked` forbids lockfile changes; `--offline` forbids network/bootstrap but
may write a lockfile for local dependencies; `--frozen` combines both. Local
dependencies remain live source trees, not immutable releases. HTTPS is the only network
Git transport. Both CLI and `make setup` Git calls ignore ambient hooks and repository-
context overrides. Certificate and hostname verification are forced, including over
inherited `GIT_SSL_NO_VERIFY` and URL-specific cache configuration; system trust roots
and Git CA environment settings remain available. Manifest credentials and automatic
lifecycle scripts are rejected. CLI Git calls disable hooks and fsmonitor. Credentials
may be supplied by Git transport environment/agents under your control; Git repository-
context environment overrides (such as GIT_INDEX_FILE) are cleared and global Git
configuration is deliberately disabled, so credential helpers and URL rewrites from it
are not loaded. Native dependencies and the selected compiler can execute code; build
only trusted projects.

Honk stages source trees under `.honk/` and leaves original sources intact. Source trees
reject symlinks and special files and are bounded to 100,000 entries, 256 MiB, and depth
64 per tree; Goose sources and manifests are limited to 1 MiB each. Resolution is
bounded to 256 packages; source discovery is bounded to 4096 Goose files and
directories. Each directory listing is limited to 1 MiB of names including separators;
filenames containing CR/LF are rejected. Original source limits remain 1 MiB even when
generated import mappings enlarge staged files; only validated staged rereads have a
separate bounded 8 MiB allowance. Captured subprocess stdout is bounded to 1 MiB. Honk
uses nonblocking project/cache locks: concurrent operations fail clearly; retry after
the other process exits. Atomic text updates preserve existing ordinary permission bits;
newly created text metadata is owner-only. Private per-user caches and project
directories must not be writable by untrusted users.

This is an evolving Git/path package workflow. Registry publishing, general dependency
solving/backtracking, cross compilation, and Windows support are not implemented. Do not
treat this pre-release as Cargo feature or stability parity.

## Dependency editing

Dependency `add`/`remove` preserves comments and formatting outside edited TOML syntax. Single edits retain the existing output and error behavior. Removal keeps attached comments as standalone comments. Inline
dependency assignments, dotted dependency fields and declared dependency tables are
supported; editing a dependency inside an inline parent `dependencies = { ... }` is
rejected before saving. Result validation and the existing atomic manifest write remain
in effect. `remove alpha beta` accepts 1–64 distinct, present dependency names (each a
valid import identifier of at most 64 bytes). All names are checked first; multiple
removals use the same fresh manifest snapshot and one atomic save under the project lock.
Missing, duplicate, invalid or unsupported requests leave the manifest untouched.
Selector metadata is at most 5,120 bytes; manifest input/output stay capped at 1 MiB.
Single-name removal retains its legacy bytes and output. Honk.lock is unchanged until an
explicit `fetch`. Atomicity is per manifest; workspace members still execute
sequentially. Multiple-name removal is available from v0.4.0; frozen v0.3.0 supports
single-name removal only.

Successful CLI completion checks Honk’s own stdout writes, including metadata and
toolchain reporting and buffered failures. Output errors in delegated programs remain
their responsibility. A broken/full destination for Honk output returns nonzero; this
does not roll back a completed manifest edit, build or installation.

## Package versions

Package versions use strict SemVer 2.0 with a Honk limit of 64 bytes, preserving safe
package filename lengths. Prerelease and build metadata are supported; leading zero
numeric components, partial versions and `v` prefixes are rejected. Workspace selectors
ignore build metadata when comparing versions, so equal-precedence members remain
ambiguous. Exact Git refs and paths retain their behavior; a separate bounded Git-tag
requirement workflow is described below. The tested tag policy accepts only enumerated
full `refs/tags/` names and strips at most one lowercase `v`; arbitrary branch/ref
strings never enter that policy. The [bounded tag-selection policy](GIT-TAG-SELECTION.md) and [transport/lock contract](GIT-VERSION-DESIGN.md) describe the
supported bounded Git version workflow.

## Child processes

Honk uses goose-process for child ownership. This requires Linux kernel 5.3+ and glibc
2.34+. Commands use Child with no overall deadline by default, preserving long-running
`run` servers. Git tag metadata discovery explicitly uses a 60-second deadline. The
parent pumps bounded 20 ms steps, forwards pending cancellation through pidfds, and
retains locks through direct-child cleanup or exceptional transferred-child recovery.
Recovery may wait indefinitely if OS permissions prevent proving cleanup. Captured
stdout is capped at 1 MiB; stderr and stdin remain inherited. Argument limits include
argv[0]: 4,096 arguments, 1 MiB total, 131,071 bytes per argument. PATH lookup uses the
child's effective environment/cwd; it does not invoke a shell fallback for executable
text without a shebang. Descendants and capture pipes they keep open remain outside
direct-child supervision. Terminal Ctrl-C suppression is best effort during launch, when
the application cannot distinguish a signal predating the child from one already
delivered to its foreground group.

## HTTPS source metadata

`toolchain --metadata` requests only the fixed Goose-upstream commit endpoint with HTTPS
certificate/hostname verification, anonymous headers and identity content encoding. It
makes one request with no proxy, credentials, redirect or retry, caps body/header
callback bytes at 256 KiB/32 KiB, requires HTTP 200 and full returned SHA equality, and
emits escaped JSON. The 5000 ms transfer timeout is **not** a hard wall deadline:
threaded DNS cleanup can take longer. Metadata does not authenticate compiler binaries,
authorize installation or prove upstream trust. Returned URL/subject strings remain
untrusted data. libcurl callback normalization/trailer limitations mean security-
critical headers/digests must never be inferred from transfer success; this consumer
validates the required JSON SHA directly. `make metadata-test` and `make metadata-
sanitize` use only local TLS fixtures with a test-only shim; ordinary builds contain no
shim.

## Optional diagnostic file

Add `--log-file PATH` after an ordinary command, for example `honk metadata --log-file
/private/directory/honk.log`. Help/version retain existing early-return behavior.
Without the option no diagnostics are emitted and no log path is opened. Machine-
readable stdout remains separate.

Records contain a canonical UTC timestamp, fixed lifecycle event names, elapsed
nanoseconds, and numeric outcome codes. Arguments, environment values, project text,
paths and Git URLs are not copied into them. `returned` is emitted only after Honk's own
stdout flush succeeds. Errors and child failures after logging is configured use fixed
error events; signal handlers never log. Abrupt termination cannot guarantee an event.

Enabled records include `timestamp="YYYY-MM-DDTHH:MM:SS[.fraction]Z"` before the event,
using up to nine fractional digits with trailing zeroes removed. The timestamp is
sampled once per enabled event from the OS wall clock; it may step backwards and is not
used for deadlines or elapsed durations. Durations continue to use the existing
monotonic clock. Unconfigured, Off, filtered, or failed logging returns before any wall-
clock read. Signal handlers still never log. This changes the opt-in record bytes;
consumers of these logs must accept the quoted timestamp field. For example:

```text
[INFO] timestamp="1970-01-01T00:00:00Z" started duration_ns=0 outcome=0
```

UTC formatting reuses pinned goose-log v0.1.3 and goose-time v0.1.0 sources, vendored
for standalone/offline operation. Event messages remain fixed/numeric; lexical caller-
owned timestamp/line buffers preserve the compiler's borrowing contract during terminal
cleanup. The maximum emitted fixed record is 117 bytes, below the unchanged native line
cap. There is no shared growable scratch buffer. The [paired diagnostics
measurements](../bench/utc/results/README.md) retain the before/after workloads, exact
source identities and instrumentation limits.

The application-owned Linux adapter rejects symlinks in every supplied path component
and accepts only euid-owned, single-link regular files of exact mode 0600. New files are
created privately; parents are never created. Each append uses a nonblocking advisory
exclusive lock, checks a 16417-byte line cap and 16MiB total cap, completes short/EINTR
writes, and checks close. Existing prefix bytes remain. Writers ignoring the lock and
same-user pathname changes are outside the advisory-lock contract. This is not a path
sandbox or durability promise. A busy/invalid/full/failed destination returns nonzero;
partial output or already-completed application work is not rolled back. There is no
automatic retry, rotation or fsync. Use a fresh private file when the cap is reached.

The opt-in toolchain metadata command also accepts explicit `--log-file`; those records
add only the UTC timestamp to fixed lifecycle events and numeric duration/outcome
fields, never response URLs, subjects, pins or bodies. Logging is the only explicit file
output added to that otherwise cache/compiler-free path.

Explicit diagnostics may record `started`/`failed` even when a metadata flag combination
is rejected before transport. Log delivery can fail after stdout or command side
effects; no rollback is promised, and callers must check the exit status.

## Git version requirements

Since v0.2.0, Git dependencies can specify `version` instead of `rev`. Only one may be
present. Requirements use full versions, explicit operators and ASCII spaces. Honk
selects the highest matching tag and rejects ties; ordinary commands retain its locked
commit. See the [complete Git version rules](GIT-VERSION-DESIGN.md) and [tag selection
policy](GIT-TAG-SELECTION.md) for syntax, prereleases, annotations, bounded enumeration
and failure behavior.

## Build reuse and compiler paths

`build/run/test --reuse-build` is off by default and supports bounded source-only targets.
See [eligibility, fingerprints and limits](INCREMENTAL-BUILDS.md). Native, embedded or
unsupported inputs compile normally. Indirect compiler support files must remain
unchanged; `clean` removes all reuse state. Ordinary builds refresh the binary
slot; ordinary tests refresh the selected test buckets.

Compiler-facing commands reject project paths with literal backslashes because the
pinned compiler treats them as separators on POSIX. Source compiler bootstrap also
rejects backslash cache paths. An explicit matching `GOOSE` avoids that bootstrap
restriction. Metadata and filesystem-only commands keep POSIX paths.

# Changelog

## Unreleased

## 0.4.0 — 2026-11-05 (experimental prerelease)

Source-only Linux x86-64/glibc release. CLI, manifest and lockfile formats
remain experimental. Build reuse is explicit and off by default: indirect
system-toolchain inputs must remain unchanged. Cache population builds
standalone and may cost substantially more than an ordinary build. Native,
embedded and unsupported inputs compile normally. Multi-remove is atomic per
manifest; workspace members still execute sequentially and lock refresh is
explicit. Existing release tags remain immutable.

- Add atomic per-manifest `remove NAME [NAME ...]` for up to 64 unique present
  dependency names using approved canonical TOML alpha.4. Validate all names
  before one snapshot apply and one atomic save; preserve single-edit legacy
  bytes, locks and explicit lockfile refresh.

- Add explicit `build/run --reuse-build` for bounded source-only targets, using
  verified independent artifacts and SHA-256 from pinned goose-crypto. Reuse
  keeps dependency validation/staging and atomic output publication; it is off
  by default and requires unchanged indirect system-toolchain inputs.
- Reject compiler-incompatible backslash project/cache paths before compiler
  work, preventing a normalized path from selecting a sibling staged tree.

## 0.3.0 — 2026-11-05 (experimental prerelease)

Source-only Linux x86-64/glibc release. CLI, manifest and lockfile formats
remain experimental. Explicit diagnostic records now include a canonical quoted
UTC timestamp; log consumers must accept the additional field. Existing exact
Git/path syntax and monotonic duration measurement remain supported.

- Add canonical UTC timestamps to the existing opt-in diagnostic file using
  pinned, vendored goose-log v0.1.3 and goose-time v0.1.0. Sample the wall clock
  only for enabled events; preserve monotonic durations, stdout, native file
  policies, error/child cleanup and sink-failure latching. Opt-in record bytes
  now contain a quoted timestamp field; existing release tags remain unchanged.

- Add an opt-in functional Git/path workspace example and a reproducible driver
  for cold operations, warm CLI samples, locked/offline recovery and packaging.

## 0.2.0 — 2026-11-05 (experimental prerelease)

Adds bounded Git version requirements and the recovery SIGPIPE correction.
Source-only Linux x86-64/glibc release; manifests, lockfiles and CLI remain
experimental. Lockfiles with the optional requirement field need Honk 0.2.0.

- Adopt the released TOML companion v0.1.1 and canonical alpha.3 source profile,
  preserving legacy dependency editing behavior and exact vendored provenance.

- Protect transferred-child recovery from diagnostic-generated SIGPIPE when
  inherited stderr has no reader. Keep ownership/locks until actual cleanup;
  preserve the caller's SIGPIPE disposition, mask and pre-existing pending signal.

- Consolidate dependency editing through the canonical TOML legacy profile and
  its reviewed thin companion adapter, retaining the existing public behavior,
  byte/error contract and limits. Exact provenance is recorded in vendor metadata.
  Correct stale TOML notice provenance and check that all recorded library
  revisions appear in the third-party notices.

- Advance goose-semver to the reviewed 0.1.1 source, fixing consumer `copy`, `str`
  and `min` overload interference while preserving API, grammar and limits.
- Add bounded internal selection from sorted enumerated Git tags, with strict
  requirements, highest-precedence matching, ambiguity rejection and owned
  outputs. Contract tests include hostile consumer overloads. This does not
  itself change exact Git/path workflows.

- Add an opt-in Git `version` requirement alongside exclusive exact `rev`:
  bounded annotated-tag enumeration, highest-match selection, package-version
  verification and requirement/tag/commit locking. Matching locks rehydrate by
  commit without tag queries; offline/frozen forbid discovery, and resolution
  failures retain the old lock. Distinct import requirements conflict instead
  of invoking a graph solver. This is included from v0.2.0 and is excluded from v0.1.0.

## 0.1.0 — 2026-11-04 (experimental prerelease)

Source-only release for Linux x86-64/glibc. APIs, manifests and lockfile formats
may change; this release makes no stable compatibility promise.

### Project workflows

- Scaffold binary/library projects; build, run, check, test, benchmark and format
  through an exact Goose compiler revision.
- Preserve comments and formatting outside edited dependency TOML syntax;
  validate edited manifests under the project lock before atomic replacement.
  Inline parent-table edits fail safely without normalizing the source.
- Resolve explicit Git/path dependency graphs, retain Git commits in a lockfile,
  and support locked/offline/frozen workflows and explicit workspace members.
- Stage validated sources without modifying originals, check exported source
  packages, and publish executables through atomic replacement.
- Support strict SemVer package versions within a 64-byte consumer limit and
  `NAME@FULL_VERSION` workspace selection. Equal-precedence matches remain
  ambiguous, including build-only differences.

### Process, metadata and diagnostics

- Use pinned goose-process for direct-child ownership, bounded stdout capture,
  inherited stdin/stderr and pidfd cancellation. Explicit no-deadline Child
  operation preserves long-running applications; locks remain held through
  cleanup and exceptional transferred-child recovery.
- Provide opt-in `toolchain --metadata` against the fixed anonymous GitHub
  compiler-source endpoint, with TLS validation, bounded input/parser work,
  full SHA equality and checked escaped JSON output. Ordinary commands do not
  request this metadata.
- Provide explicit `--log-file` diagnostics containing fixed lifecycle events
  and numeric durations/outcomes. Checked private-file appends reject unsafe
  file identities and enforce line/file quotas without copying user text.

### Correctness and validation

- Reject ambiguous workspace selections before package actions and reject
  unsupported options and empty installation roots.
- Check Honk-owned stdout completion, preserve child outcomes after cleanup,
  harden cache recovery/source publication, and retain source-copy bounds and
  no-follow filesystem boundaries.
- Keep vendor/fault verification active under optimized Python. Exclude VCS,
  generated, toolchain, test, benchmark and vendor directories from Honk's
  native package symbol discovery; exercise ignored-source isolation through
  an in-process import regression.
- Record independent reviews, normal/security checks, GCC/Clang sanitizers,
  standalone clone/source-package verification and measured workload evidence
  in [RESULTS.md](RESULTS.md). Measurements remain tied to their stated source
  revisions and do not establish universal performance or security guarantees.

### Scope and limits

Registry publishing/version solving, cross compilation, Windows/macOS and
process-tree supervision remain outside this release. Git-tag requirement
selection remains separate unfinished work and is not included.

The HTTP transfer timeout is not a hard wall-clock DNS cancellation bound, and
source metadata is not compiler-binary authentication or install authorization.
Build only trusted projects/tools. See [README.md](README.md) for supported
platforms and limits, [SECURITY.md](SECURITY.md) for trust boundaries, and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for pinned source provenance.

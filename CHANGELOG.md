# Changelog

## Unreleased

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
  of invoking a graph solver. This is unreleased and is excluded from v0.1.0.

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

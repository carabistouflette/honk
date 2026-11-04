# Changelog

## Unreleased — experimental 0.1.0 candidate

The intended candidate is a source-only release for Linux x86-64. No `v0.1.0` Honk tag or
stable compatibility promise is implied by this section.

### Project workflows

- Scaffold binary/library projects; build, run, check, test, benchmark and format
  through an exact Goose compiler revision.
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
process-tree supervision remain outside this candidate. Dependency editing
currently normalizes manifests and removes comments; comment-preserving editing
is not claimed until its separate integration is validated.

The HTTP transfer timeout is not a hard wall-clock DNS cancellation bound, and
source metadata is not compiler-binary authentication or install authorization.
Build only trusted projects/tools. See [README.md](README.md) for supported
platforms and limits, [SECURITY.md](SECURITY.md) for trust boundaries, and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for pinned source provenance.

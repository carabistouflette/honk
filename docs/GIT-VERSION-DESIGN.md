# Git version requirements

Status: implemented contract for the bounded Git-version workflow released
in experimental Honk v0.2.0. The frozen Honk v0.1.0 release is
unaffected. This adds Git-tag requirements, not a registry or a general solver.

## Manifest and command contract

A Git dependency specifies exactly one of `rev` or `version` by field presence,
not by nonempty values. Both keys together, empty values, and any `version` key
on a path dependency are rejected before modification:

```toml
[dependencies]
helper = { git = "https://example.org/helper.git", version = "^1.2.3" }
```

`add helper --git URL --version REQUIREMENT` preserves that requirement in the
source manifest through the existing editor. Existing `--rev`, sourced imports
and path dependencies retain their behavior. Path dependencies reject versions.
A version requirement follows the explicit full-version grammar documented in
[GIT-TAG-SELECTION.md](GIT-TAG-SELECTION.md); no implicit caret or partial forms.
The existing 4,096-byte manifest string bound also bounds this consumer input.
Honk retains its UTF-8/control-byte policy: requirement whitespace is ASCII
space only. TAB is rejected consistently by CLI, manifest and lock validation.
`honk --version` keeps its early version-display behavior.

## Discovery and commit identity

Only unlocked resolution or explicit `update` enumerates the selected HTTPS
remote's tags. Use the existing hardened argv/environment Git policy, bounded
stdout capture and an explicit 60-second metadata-query deadline. Retain signal forwarding,
cleanup and locks. No shell, new transport, proxy policy, registry or TLS code.

Parse `git ls-remote --tags --sort=refname` output with a 1 MiB raw cap and at most
8,192 raw rows / 4,096 base tags. Preserve raw stdout for this query rather than
using the helper's trailing-newline trimming. Require full lowercase 40-byte
object IDs, one tab, bounded full `refs/tags/` names and LF record termination. Distinguish base tag records
from synthetic `^{}` peeled records. Validate all rows and reject conflicting,
missing-base or malformed peel records. Never assume peeled records are adjacent
to their base after sorting; use bounded lookup against the sorted base names.
A real local Git probe orders `v1.2.3+build` and `v1.2.3-alpha` between an
annotated `v1.2.3` base record and its `v1.2.3^{}` record.
SHA-256 Git repositories remain unsupported by the existing 40-byte contract.

Produce a sorted unique tag catalog with peeled commit IDs for annotated tags;
lightweight tag IDs are checked as commits during fetch. Apply the implemented
selector without weakening its alias/build tie rejection or prerelease rules.
Fetch the selected full tag ref and require `FETCH_HEAD^{commit}` to equal the
advertised selected commit before publishing sources or a lockfile. Missing
selected-tag peel capability or a changed selected commit fails closed; do not silently
retry or substitute a different tag. Replacing an annotated tag object while
retaining the same peeled commit is allowed: this workflow trusts the commit
identity, not tag annotations or signatures. These checks establish consistency with the queried remote,
not publisher authenticity or a cryptographic signature policy.

Version-selected sources must contain a valid Honk library manifest whose
validated effective package version compares equal to the selected tag version.
Existing exact-ref/path workflows continue to support legacy source libraries.
No project code, hooks or build scripts run during discovery or validation.

## Lock and cache behavior

Keep lock schema 1 with an optional `requirement` on version-selected entries.
Their existing `rev` field stores the selected full tag ref, and `commit` stores
the verified immutable commit. Omit the new field for exact-ref/path entries so
those lock bytes remain unchanged. Older Honk versions reject the new key; the
requirement field therefore needs Honk v0.2.0 or later.

A present-but-empty lock `requirement` is invalid, not legacy exact mode.
Match reusable lock entries by import name, HTTPS origin and exact requirement
text. Validate the locked tag against that requirement. Ordinary commands reuse
the locked commit even if the remote tag moves or a newer version appears.
Online cold-cache rehydration, including `--locked`, fetches and verifies the
locked commit OID directly, never the mutable selected tag or a fresh catalog.
`--locked` rejects a missing/changed requirement entry before enumeration;
`--offline`/`--frozen` do not enumerate or fetch, and require matching lock data
and verified cached sources. Preserve existing cache identity, dirty-tree,
completion-marker and no-follow checks. Commit a replacement lock only after
the complete graph validates. Failed resolution preserves the old lock bytes.

The first implementation retains one source identity per import name and
rejects distinct requirement identities instead of attempting backtracking,
multiple versions of one import or registry unification. A later solver needs a
separate design and validation; do not approximate it silently.

## Maintained tests

The tests use isolated real Git repositories behind a test-only HTTPS-to-local
transport shim. They cover annotated/lightweight tags, highest numeric matches,
prereleases, v/build ties, non-adjacent peel records, malformed/conflicting and
oversized advertisements, selected-commit movement and same-commit tag-object replacement between
query/fetch, manifest-version
mismatch, changed constraints, shared-import conflicts and unchanged exact refs.
They check that frozen/offline paths perform no enumeration/fetch, preserve old locks on
all failures, and retain comment-preserving add/remove and self-package exports.
The normal/security and GCC/Clang sanitizer suites include these cases.

The wire record/peel format follows the official
[git-ls-remote manual](https://git-scm.com/docs/git-ls-remote); ref validation
follows [git-check-ref-format](https://git-scm.com/docs/git-check-ref-format).
Honk's byte, row, object-format and version limits are additional consumer rules.

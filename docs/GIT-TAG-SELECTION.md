# Git tag selection policy

This is an internal, tested selection function. Honk commands still accept exact
Git refs/commits and paths; no requirement-based dependency command, registry or
graph solver is exposed by this checkpoint.

`tag_select::select(requirement, tags)` takes a complete, lexically sorted
catalog of enumerated full `refs/tags/` names and lowercase 40-byte commit IDs.
It validates the whole catalog before selecting, so an early match cannot hide
malformed, conflicting or oversized later records. The transport must supply
actual commit identities for annotated tags rather than tag-object IDs; this
pure function does not query or authenticate Git objects.

Versions follow the strict SemVer library grammar. Strip at most one lowercase
`v` from an enumerated tag name. Branch names and arbitrary refs never enter this
policy. Ignore non-version tag names and versions longer than Honk's 64-byte
package-version limit. Requirement syntax is explicit full versions with `=`,
`>`, `>=`, `<`, `<=`, `^`, `~`, comma AND, or standalone `*`; a bare full version
means exact equality. Partial versions, OR, implicit caret and hyphen ranges are
unsupported. Prereleases require an eligible same-core prerelease comparator.

Choose the greatest matching precedence, ignoring build metadata. Distinct
winning refs or commits with equal precedence are ambiguous, including `v`/bare
aliases and build-only differences. Repeated identical ref/commit records are
harmless; one ref associated with different commits invalidates the catalog.
Ambiguity among lower versions does not prevent an unambiguous higher winner.

Limits: 4,096 catalog records, 4,096 bytes per full ref and 1 MiB total ref/commit
bytes, plus the library's bounded requirement grammar. No catalog sorting or
quadratic duplicate scan is performed. Selection validates linearly over the
bounded input and retains at most one owned candidate version. Returned ref,
commit and normalized version are owned; all outputs are empty on failure.

`tests/tag_select.goose` exercises numeric precedence, prereleases, aliases,
conflicts, ordering, malformed later rows, every catalog/filename boundary,
arbitrary-magnitude numeric cores and output ownership after input destruction.
Hostile consumer `copy(Version)` and `copy(Comparator[:])` overloads ensure
requirement targets remain owned and unchanged. The reviewed SemVer fix is
pinned in `vendor/manifest.json`; it leaves API, grammar and limits unchanged.
The suite runs through JIT, optimized native and GCC/Clang debug ASan/UBSan via
`make check test sanitize`.

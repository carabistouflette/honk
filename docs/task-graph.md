# Dependency graph validation

Honk vendors goose-task v0.1.0-alpha.1 at
`166b684ca96403fea94072cc8e0c630321fb832d` for cycle validation only.
Source/license hashes and notices are in vendor/manifest.json and
THIRD_PARTY_NOTICES.md. Honk's manifest, lockfile and standalone import roots
include the task package.

The adapter keeps Honk's existing parent (dependent) to child (dependency)
edge direction. That direction is appropriate for detecting cycles; it is the
reverse of execution prerequisites, so the returned task plan is discarded.
Node discovery, serialized lockfile order and build behavior are preserved.
No scheduling, parallel execution or task failure policy is adopted here.

Validation allows 256 nodes and 131,072 edges: each expanded node can add up to
256 manifest dependencies and 256 sourced imports. Duplicate declarations are
retained; 65,536 edges would incorrectly narrow existing resolver capacity.
Oversized internal graphs are rejected before conversion. Cycles retain the
`dependency cycle detected` diagnostic; other malformed graphs report
`invalid dependency graph`. Rejection occurs before writing a lockfile.

The adapter and library validate in O(V+E) time/storage. This is an algorithmic
claim, not a measured Honk command speedup. Tests cover boundaries, duplicate
edges, input errors, ordering preservation, missing/existing lockfiles and
frozen operation. `tests/graph.goose` runs through JIT, compiled and sanitizer
paths; CLI regressions exercise actual resolution and packaged self-projects.

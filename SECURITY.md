# Security policy

Honk is pre-release. Security fixes target the latest `main`; older commits have
no separate maintenance guarantee. There are no signed binary releases yet.

Report vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/carabistouflette/honk/security/advisories/new).
Include the commit, OS/compiler versions, minimal reproduction, expected behavior,
and actual impact. Redact credentials and personal data. Please do not publish
exploit details in a public issue before a fix is available.

## Trust boundaries

Honk is a build/project manager, not a sandbox. Run it on trusted projects and
with trusted compiler, CMake, Git, tar/gzip and PATH configuration. Native
sidecars, compiler bootstrap sources, installed tools, and application programs
can execute code. Git TLS/object checks do not constitute signed release or
publisher verification. An explicitly supplied GOOSE binary is trusted; its
advertised short version is checked, not authenticated cryptographically.

The CLI uses argv arrays, never implicit shell interpolation. Git transports
are restricted to HTTPS, repository-context environment overrides are cleared,
and hooks/fsmonitor are disabled. Tar option and gzip environment overrides are
ignored. Arbitrary runtime program arguments and output are forwarded as data;
Honk does not sanitize a trusted program's terminal output.

Source staging, workspace selection and installation/removal reject symlinks at
their managed boundaries. Private caches and project directories must not be
writable by untrusted users. The filesystem adapter is not a sandbox against
malicious concurrent writers with the same directory access. Ordinary text
permission bits are preserved on replacement; ownership, ACLs and extended
attributes are not part of that promise. New text metadata is owner-only.

Manifests, lockfiles, source inputs, dependency graphs, filesystem walks and
captured stdout have fixed limits documented in README. Failed metadata updates
are checked before replacing the original. Executables are published atomically
only after successful compilation. Temporary staged-source writes are not crash
persistent; manifests, lockfiles and cache metadata retain durability syncs.

SIGINT/SIGTERM are forwarded to a running direct child, and locks remain held
until that child finishes. This is not process-tree supervision: applications
that fork grandchildren, ignore cancellation, or keep captured streams open can
require operator intervention. There is no universal command deadline in this
version. Directory locks are cooperative and local filesystem semantics apply.

See [RESULTS.md](RESULTS.md) for the concrete test/review evidence and its scope.
Passing tests, sanitizers and fuzz probes is not a proof of security or absence
of bugs.

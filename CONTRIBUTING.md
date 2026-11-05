# Contributing

Use focused branches and Conventional Commits with imperative subjects. Each commit is
one coherent, working change. Before committing behavior changes, add public integration
regressions, run `make format check test`, and inspect `git diff --check` and the diff.
Run `make sanitize` for native adapter or ownership changes, and `make bench` for
performance changes. Request independent review and fix actionable findings before
release. Keep main passing CI.

Keep the implementation small and explicit. Goose owns application logic; native code
only supplies missing POSIX operations. Never interpolate shell commands. Reject
malformed inputs, ambiguous dependency identities, symlinks in managed source trees, and
unbounded manifests or captured subprocess output. Build scripts and native dependencies
are executable code: only build projects you trust. Do not run repository hooks or
lifecycle scripts automatically.

Pin the exact compiler in GOOSE_REVISION and vendored libraries in vendor/README.md.
Update pins deliberately with full validation. Never commit build output, credentials,
or private planning. No stability promise before 1.0; tag releases only after review.
Report vulnerabilities privately via GitHub security advisories when available.

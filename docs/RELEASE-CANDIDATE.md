# Honk 0.5.0-rc.1 preparation

Status: [v0.5.0-rc.1 published](https://github.com/carabistouflette/honk/releases/tag/v0.5.0-rc.1).
Source `26f8a7454d27dc81e2c24d918293f286a494d9ee` is the CI-tested candidate
head; merged source `2957a78` has the identical Git tree. Candidate CLI,
manifest and lockfile formats remain experimental, with no compatibility promise
before 1.0. The platform remains Linux x86-64, kernel 5.3+, glibc 2.34+ and the
pinned Goose compiler. Build prerequisites and trust limits remain in README.md
and SECURITY.md. Honk executes trusted projects/tools and is not a sandbox.

## Scope

The candidate collects opt-in recursive/explicit watch and debounce, bounded
parallel tests, per-test build reuse, target filtering, single-package diagnostic
output and optional command progress. Watch is cooperative: a child that does not
finish cleanup can delay shutdown; resource bounds exclude compiler/test children.
Recursive discovery is bounded and stops on unsupported root identity or guard
loss. Reuse is off by default, retains indirect-system-toolchain assumptions and
falls back for native/unsupported inputs. Existing defaults stay unchanged.

The real-project watch receipt preserves 514 checked intervals and actual kernel
loss recovery on one unchanged suite from each of two pinned projects. JSON uses
a documented codec projection. Measurements retain their original development
source/binary identities, permission errors, read races and sampling gaps.
Candidate version-string changes do not turn old observations into measurements
of the candidate executable. See RESULTS.md and the linked raw receipts.

## Gates before publication

1. Independent implementation/release reviews and required GCC/Clang CI must pass
   for the exact candidate source. Check manifest, version/help output and compiled
   watch together; exercise candidate watch with the pinned compiler.
2. Merge reviewed candidate source, verify its exact Git tree and CI state, then
   prepare source-only prerelease notes. Do not replace any existing release tag.
3. Verify anonymous clone and tag archive bytes/executable modes, build the exact
   candidate using the explicitly supplied matching compiler, and exercise version,
   normal/frozen project commands and source packages. A fresh compiler bootstrap
   is a separate claim and is not implied by supplying an existing compiler.
4. Record source/compiler/archive/asset digests and public download checks. Observe
   GitHub release immutability directly; hashes do not imply hosted immutability,
   authenticity or permanent availability. Only then describe it as published.

[Public verification](https://github.com/carabistouflette/honk/releases/download/v0.5.0-rc.1/verification.json)
and [publication receipt](https://github.com/carabistouflette/honk/releases/download/v0.5.0-rc.1/publication.json)
record the passed candidate CI, anonymous source build, normal/frozen/package and
real watch checks, all 419 tag-archive file bytes/modes and public asset digests.
GitHub reported `immutable: false`; no hosted immutability is claimed.

## Local preparation evidence

[Local receipt](results/release-candidate-0.5.0-rc.1-local.json) and its hashed
log archive retain full format/check/test/security results, exact producer source
and binary/compiler hashes, two independent release reviews and a two-run real
recursive-watch test with the pinned compiler. Production differences from the
qualified base are restricted to the three advertised-version locations.
The local receipt predates publication; the public receipts above record completed
hosted CI and artifact verification.

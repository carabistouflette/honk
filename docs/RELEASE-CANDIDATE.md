# Honk 0.5.0-rc.1 preparation

Status: prepared source; no candidate tag or release has been published.
The latest published experimental release remains v0.4.0. Candidate CLI,
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

Publication receipts and candidate CI links follow these gates. The prepared
branch deliberately does not advertise a release URL that does not yet exist.

## Local preparation evidence

[Local receipt](results/release-candidate-0.5.0-rc.1-local.json) and its hashed
log archive retain full format/check/test/security results, exact producer source
and binary/compiler hashes, two independent release reviews and a two-run real
recursive-watch test with the pinned compiler. Production differences from the
qualified base are restricted to the three advertised-version locations.
Required hosted CI and public artifact verification remain pending gates.

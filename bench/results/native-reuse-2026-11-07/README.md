# Native fallback and cache recovery qualification

Clean source `98934b54e07cb4c4b886695fb32d6f4a79489949` completed all 26 expected
outcomes: eight native cases (including one intentional compiler failure) and
eighteen source-only cases, including nine verified hits. No production code
changed. This is correctness evidence, not a timing comparison or native caching
support announcement. Durations are retained only as raw invocation metadata.

The frozen native profile is public goose-crypto alpha.1 at
`a4643f62bd5e76b371054c6537a95169a7930101`: unchanged public API suite, module,
sidecar, CMake, native sources/headers, pin, license and notices. Protocol runners,
examples and fuzz programs are excluded. The temporary Honk manifest labels the
fixture; it does not claim a new crypto release. The positive profile contains
the four maintained goose-diff v0.1.0 suites at
`129dc794b62ad987784db0a1d52ef618c85fccf4`. Neither profile claims full-upstream
suite coverage. Source archives and extracted member hashes/modes are retained. Archive file
modes (0664) normalize to0644 during safe extraction; restoration checks that
extracted baseline, while raw archives retain original archive metadata.

Native ordinary/reuse/filter/edited-source commands passed the API suite and
invoked the Goose backend without retaining a Honk cache record. The deliberate
native C error also changed the sidecar fingerprint to force a native package
refresh. Its compiler diagnostic is retained, the published executable's exact
hash remained unchanged, and restored sources passed again. Goose/CMake native
object caches may stay warm; these cases prove fallback, not invalidation.

The source-only profile first proved real hits, then safely recompiled after a
same-size whitespace edit, restored source, artifact corruption, compiler
location/environment changes and same-path compiler-byte changes. Filters
reindexed published outputs without confusing target identity. Artifact
corruption kept ELF magic and size intact while disagreeing with the unchanged
cache certificate, exercising digest rejection. A symlinked cache program did
not alter an external sentinel. The copied compiler's version remains unchanged
after the byte mutation; actual test compilation/execution still succeeds.
Subsequent verified hits demonstrate recovery. Every extracted source byte and
baseline mode is restored; system tools, stdlib and resolved runtime libraries are
fingerprinted before/after. Actual CMake compiler selections are recorded.

`raw.json` is the final report. `summary.json` is derived only from it. Its
postconditions retain published-output hashes, certificate/artifact hashes,
ELF magic, sentinel hashes and source restoration. Existing compiler diagnostic
logs receive markers outside commands, so backend-write detection does not rely
only on timestamps. These are isolated compiler homes, not users' build caches.

`pilot.json` is the earlier complete campaign at cad9cfd. It predates explicit
postcondition/certificate fields and is excluded from the final summary.
`source-controls/` retains only derivative source bytes. Copied compiler and
cached executable mutation binaries are deliberately not committed; their
hashes, sizes and reproducible mutations remain in the report/harness. The
native compiler failure is expected and retained, not a successful test exit.

Two independent design/code reviewers corrected evidence gaps before final
qualification. Observer tests cover same-size/same-timestamp log changes,
certificate extraction and symlinked metadata. The new tests join `make test`;
static checks and the complete real-project campaign pass. Hosted CI repeats
the maintained suite; it does not rerun this local-repository qualification.

Recompute:

```sh
python3 summarize.py raw.json summary.json
```

See [the qualification guide](../../../docs/NATIVE-REUSE-QUALIFICATION.md) for
reproduction and [reuse eligibility](../../../docs/INCREMENTAL-BUILDS.md) for
system-toolchain assumptions. These controls establish no general speed,
hermeticity, authenticity or leak-freedom guarantee.

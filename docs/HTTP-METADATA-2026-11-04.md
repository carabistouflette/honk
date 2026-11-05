# Opt-in HTTPS metadata consumer — 2026-11-04

> Historical report: results and test counts apply only to the source named
> below. They are not current v0.4.0/main performance claims. See the
> [currentness audit](PERFORMANCE.md). Raw records and slower results are unchanged.

Honk integrates the unmodified goose-http source and independent metadata example at `c879c6fec88eaf7229f890a5dd6e3fc313261eab`. The example SHA-256 is `6ffbbaabe73db968c0f8286d0f3cf035986c4ad562ceec850c7b134c0f759150`; all Goose/build/CMake/native/license hashes are recorded in `vendor/manifest.json`. The local-only HTTPS fixtures are separate test files with their own immutable upstream provenance.

`honk toolchain --metadata` validates flags, selects the nearest project/default full compiler pin (or explicit manifest), and requests the fixed anonymous GitHub commit endpoint before cache, compiler, dependency, Git or bootstrap actions. Only `--manifest-path` is accepted alongside the explicit metadata flag; offline/frozen/locked and package/workspace flags fail before transport. The command requires HTTP 200 and full returned SHA equality. It emits escaped JSON with requested revision, SHA, untrusted URL and subject. This is metadata, not artifact authentication, installation or trust authorization.

The request uses HTTPS certificate/hostname validation, identity encoding, no proxy/credentials/redirect/retry, 256 KiB body and 32 KiB callback-header caps, and a 5000 ms transfer timeout. Threaded DNS cleanup can exceed that timeout; it is not a wall-clock cancellation bound. The application temporarily ignores SIGPIPE for synchronous fetch and restores its prior disposition before reporting errors or writing output. Existing checked stdout flush handles `/dev/full` failures. Backend callback normalization and HTTP/2 trailer limitations remain documented upstream; the consumer does not infer critical metadata from successful transport.

Validation completed:

- Normal `make format check test security` with the existing CLI/text/SemVer/process and malformed-input suites.
- `make sanitize portable` with GCC and Clang, including generated Goose/runtime C, Honk's adapter, the HTTP kernel and test transport shim. CMake's HTTP target uses the content-keyed test compiler for these builds.
- Five caller test methods reuse the upstream response matrix and add real Honk dispatch checks: fixed request headers/origin, certificate/hostname failures, timeout without retry, UTF-8/duplicate/type/depth/number/size/encoding errors, default/override/nested manifest selection, invalid pins/flags, ordinary metadata without transport, poisoned compiler/PATH, preserved lock/cache/target sentinels, checked stdout and missing-fixture fail-closed behavior.
- Clang static analysis of `native/platform.c`.
- An explicit **unshimmed live** request succeeded for `eadca409f68210893f366e60d0c2f0dc29a339be`, with complete SHA equality and no cache creation, while GOOSE pointed to an unusable compiler path. Ordinary tests use loopback TLS only.
- Independent read-only standards/specification/security consumer review found no outstanding implementation issue. The generated-bytecode staging finding was removed and Python caches are ignored. Vendor/example/fixture bytes independently match the immutable upstream Git objects.

Reproduce with the pinned compiler:

```sh
make GOOSE=/absolute/pinned/goose format check test security
make GOOSE=/absolute/pinned/goose sanitize portable
HONK_SANITIZER_CC=clang make GOOSE=/absolute/pinned/goose sanitize portable
```

`make metadata-test` and `make metadata-sanitize` provide the focused caller checks. The GNU routing/CA shim exists only in explicitly built test executables; `make build` links the unchanged production transport. Local compiler-wrapper identities separate instrumentation modes and fixture revisions. System libcurl/TLS itself is outside sanitizer instrumentation. No whole-Honk network-throughput ranking is claimed; the upstream component report at the same immutable pin records its parser/render/request measurements and limitations. Passing checks are not proof of zero bugs or universal stability.

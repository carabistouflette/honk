# Explicit diagnostics integration — 2026-11-04

> Historical report: results and test counts apply only to the source named
> below. They are not current v0.4.0/main performance claims. See the
> [currentness audit](PERFORMANCE.md). Raw records and slower results are unchanged.

Production source: `00be9b04d40d46c16e5de4f7c2c8a98b7c43d0b6`. The implementation vendors unmodified goose-log core `a3919c5e9135b9812db422d5052bb1ea5d1d202b`, including LICENSE/NOTICE. Application diagnostics and native checked append match the reviewed consumer component `0c3794066cb3d5c5c1e06cace92b953437baea46` (only its import declaration is adapted). The sink SHA-256 is `51dabc2881c3032e2dd3e12e535d2d6c2d634cc16506a57ccd783522a4033c5e`; the module SHA-256 is `0047149ebc9ab0e1c07483485b132d73d12f3c2fd35566c65dff0c05a00fdbea`.

Logging requires explicit `--log-file PATH`. Without it, no path is opened and no diagnostics are emitted. Records contain fixed event enums and numeric durations/outcomes only; argv, environment, project text and HTTP response fields are not copied. Machine-readable stdout remains separate. Returned is recorded after checked stdout; child failure events run after process cleanup and preserve exit status. Help/version retain their previous early returns. Abrupt termination cannot guarantee a record.

The application-owned sink walks path components without following symlinks, requires an euid-owned single-link regular file of exact mode 0600, uses a nonblocking advisory lock and checked short/EINTR writes/close, and enforces a 16,417-byte line cap and 16 MiB total cap. It does not create parents, rotate, retry delivery, fsync, roll back completed work, or protect against writers ignoring its lock. Failures may follow partial output. Explicit logging can emit started/failed before an incompatible metadata combination is rejected; it introduces no implicit network, cache or compiler action.

## Validation and fixes

Normal `make format check test security`, GCC and Clang `make sanitize portable` passed on the combined process/HTTP/logging implementation. This includes 69 CLI, 5 text, 5 SemVer, 4 process, 9 logging and 6 HTTPS caller test methods, plus core runner/native contracts, process probes, 213 malformed-import probes and FIFO rejection.

Logging cases cover metadata stdout/privacy, workspace progress, child output and exit 7 preservation, fixed business-error events, invalid sinks, failed stdout, 100 sustained invocations/200 validated records, hardlink/mode/FIFO/full-file rejection, and quota failure after started (valid JSON may already be delivered, but exit status is nonzero). The HTTPS integration additionally proves that explicit diagnostics contain neither source pins nor response URLs/subjects. Native component fault validation and separate construction/render/I/O measurements remain in the [immutable upstream component report](https://github.com/carabistouflette/goose-log/blob/bc3e7523e2f0dcc1a9015f297b055f73b4684819/bench/cli/RESULTS.md); these are not whole-Honk latency claims.

Combined testing exposed a latent package-boundary defect: the pinned compiler's native symbol discovery scans all `.goose` files below an imported native package root. Honk's sidecar had no exclusions. Logging made the native package reachable in core runner tests, exposing ignored compiler negative fixtures and unrelated test-only externs. A deterministic runner reproduction failed with invalid C identifiers; excluding `.build` narrowed it to undefined test externs, and excluding tests fixed it. The final sidecar excludes VCS/build/toolchain/staging/test/benchmark/vendor directories. This changes application package configuration, not the compiler or library core.

`tests/native_import.py` now forces Honk's native JIT library with a checked stdout operation while an invalid extern is present under ignored `.build`. It failed on the prior sidecar and passes with the fix, including under `python -O`. Existing explicit vendor/fault identity checks also reject tampered inputs under optimized Python. Read-only standards/specification reviews found no remaining blocker; component hashes were independently compared. No new test transport is present in production builds.

## Measurements at the historical source

The existing benchmark drivers ran against clean production source `00be9b0` with CPU 3 affinity on a shared host, without exclusive isolation. [CLI raw samples](../bench/results/integration-cli.json) cover 25 sequential warm invocations per case, including process startup. [Workload raw samples](../bench/results/integration-workloads.json) cover wide directories, dense production/dev dependency graphs and 32 MiB assets, three runs each. Each report records compiler/platform/revision, binary SHA-256, all samples and its scope. These are observations at that historical source, not a comparison against an older feature set or a universal performance claim.

Reproduce with `make bench` and the pinned compiler. Historical process before/after measurements use their immutable harness and retain every paired sample separately. No allocation-count or combined memory claim is made. Tests and measurements are evidence, not proof of zero bugs or Cargo feature/stability parity.

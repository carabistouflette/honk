# Opt-in test compilation reuse

Measured clean source `10c45728b3fe6280104b6fe9b520ab5c9a136824`, containing
production implementation `fd72487` plus documentation and recorder fixes.
The four maintained source-only goose-diff suites use unchanged public v0.1.0
source at `129dc794b62ad987784db0a1d52ef618c85fccf4`. This is the explicit
core/sparse/unified/context suite profile, not the full upstream checkout:
argument-driven tools, examples and benchmark sources are excluded. Complete
archived file names/bytes/hashes and the manifest adapter are recoverable from
`source.tar`, the recorder, and `raw.json`. No test work or delays were inserted.

`raw.json` retains all twelve invocations: three warmups and three measured
rounds of ordinary compilation, population and hits. Full command release/jobs4
wall times include staging, hashing, compilation when applicable, publication
and actual suite execution. Fixed-seed shuffled ordinary/reuse pairs retain
population immediately before each hit; ordinary builds invalidate selected
slots. Compiler backend-log identities/mtimes must remain unchanged for a hit
claim. All outputs match; all measured hit checks passed. Cold runtime setup is
retained in the first warmup, outside measured summaries.

The medians are 6174 ms ordinary, 7590 ms population and 412 ms hits. Every
individual sample, including slower population/hit samples, is retained. This
shared-host, three-round, single-profile experiment demonstrates skipped
compilation here; it establishes no general speed guarantee. No other builds
from this agent ran during the final campaign. Unsupported/native inputs and
fixed-bucket collisions may compile normally. System toolchain assumptions
still apply; reuse remains off by default.

`checks.json` hashes the retained validation logs. Full final `make test` passed
all sixteen cache regressions plus existing integration/fault checks. Static and
format checks, 213 malformed-import/security probes, existing benchmarks,
ASan/UBSan and portability passed. Sanitizer cache coverage is fifteen tests
plus the separately run new 256-dependency case. Three independent code reviews
found no remaining production blockers; the final evidence was independently
checked before publication.

`development/` is excluded from all timing conclusions. The first pilots exposed
safe misses (bucket collisions and a leftover shared private output). The
corrected pilot overlapped validation work. The negative control deliberately
runs `/bin/false` and preserves an error. The cold-notice attempt ran a successful
warmup but its initial recorder rejected Goose's runtime-setup stderr notice;
that partial report is preserved. The final recorder accepts only that specific
notice during the cold ordinary warmup, with other unexpected diagnostics still
failing the campaign.

Recompute derived data:

```sh
python3 render.py raw.json summary.json report.html
```

See [the reuse guide](../../../docs/INCREMENTAL-BUILDS.md) for reproduction,
eligibility, bounded storage, invalidation, and the indirect-toolchain limitation.

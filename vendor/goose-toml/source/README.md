# Source-preserving TOML edits

This opt-in module adds and removes named TOML values while copying all bytes
outside the edited token spans. It is separate from the semantic document editor
and canonical writer. It does not change those APIs or enable itself implicitly.

```goose
import toml from "../goose-toml"; // adjust your checkout path
import toml.source.editor;
import std;

fn main() {
    let original = "# project notes\n[dependencies]\nold = {path='../old'} # keep\n";
    let updated, error = toml_source::put(original,
        ["dependencies", "helper"], "{path='../helper'}");
    if error.len > 0 { print(error); return; }
    print(updated);
}
```

The supported entry points are `toml_source::put`, `toml_source::remove`,
`toml_source::legacy_set` and `toml_source::legacy_remove`.
Other declarations are implementation details. All return `(owned_output,
owned_error)`, with an empty error on success and empty output on every error.
The application owns reading files and atomic publication after success.
Inputs are borrowed for the duration of the call; no references or source ranges
escape into the returned text. Each operation privately indexes the original
source and reparses changed output before returning it.

## Operations

`put(source, path, raw_value, version = toml::Version.V1_0)` replaces a directly
assigned value or inserts a new member. `raw_value` is exactly one TOML value;
it is independently parsed under the selected version, preventing extra
assignments or headers from being injected. Raw spelling is retained. Insertion
uses the deepest existing table body, with quoted relative dotted names as
needed to create missing tables. New lines use the first source newline style,
or LF when the source has none. Existing line endings are copied verbatim.

`remove(source, path, version = toml::Version.V1_0)` removes the assignment or
header token spans belonging to a named subtree, including descendants declared
through dotted assignments or separate table headers. A missing path succeeds
with an owned copy of the original source. Removing a table header also removes
its associated values; unrelated sections remain. Arrays of tables can be
removed as a whole, but paths do not select individual array elements.

Paths contain **decoded table-key segments**, not dotted strings or array
indices. `["a.b", "c"]` selects literal key `a.b`, then `c`. Empty keys, Unicode
and escaped controls are supported; keys must contain valid UTF-8. Inserting
DEL uses `\u007f`, since a literal DEL is prohibited in a TOML quoted key.

The scanner reuses the existing parser's `Reader`, `header`, `assignment_target`
and `value` routines. Its private offsets refer to the original bytes, never
the parsed document's decoded key/text arena. Parser declaration rules and work
budgets apply unchanged. Fixture tests compare the source index's complete
semantic node layout and arena with the ordinary parser.

## Companion compatibility profile

`legacy_set(source, decoded_path, raw_value)` and
`legacy_remove(source, decoded_path)` expose the compatibility profile for
[goose-toml-edit](https://github.com/carabistouflette/goose-toml-edit).
They return the same owned `(output, error)` pair and are fixed to strict
TOML 1.0. They share the scanner, lookup, subtree selection and splice engine
with `put`/`remove`; the default operations retain their existing policies.

The compatibility reference is companion commit
[`cedb2c3c98affbeb45bd34bc7a6618f5a9b75ad0`](https://github.com/carabistouflette/goose-toml-edit/commit/cedb2c3c98affbeb45bd34bc7a6618f5a9b75ad0).
The profile preserves its output and diagnostic bytes, including these rules:

- Validate the path first, replacement fragment second, original source third.
  Parse only the first fragment value using the literal four-byte `x = `
  wrapper, after validating UTF-8 across the whole fragment. Only spaces/tabs
  may follow the value. Trailing comments/newlines or statements return the strict-suffix diagnostic without parsing that suffix.
  Comments/newlines inside a value remain allowed by the TOML grammar.
- Paths permit 1..64 decoded components and up to 1 MiB combined key bytes.
  Traversing through a scalar, array or inline table fails before checking for
  a child. A genuinely missing prefix short-circuits to missing. Removing an
  entire array of tables remains supported.
- Insert at root byte zero or immediately after the closest explicit ancestor
  header's complete line. Use the first source newline style, or LF. New keys
  use TOML quoting with uppercase control escapes, including `\u007F` for DEL.
- Before encoding each inserted key, reserve two quote bytes plus six bytes
  per decoded byte within the 1 MiB insertion cap, including prior separators.
  This conservative guard can reject a new key whose actual encoding would
  fit; it does not apply when replacing/removing an existing assignment.
- Source/output are capped at 1 MiB each and the replacement at 1 MiB minus
  four wrapper bytes; an empty replacement is rejected. Existing parser limits
  also apply. Even a missing-key removal reparses its independent owned copy.
  Every failure returns empty output and an owned nonempty diagnostic.

The companion obtains the complete result before replacing or clearing its
caller's output, preserving input/output aliasing. This module performs no I/O.
The compatibility profile is follow-on work and is **not** included in the
frozen `v0.1.0-alpha.1` release. Use an immutable reviewed commit that contains
these entry points; do not assume their presence in that alpha tag.

## Preservation and current limits

Existing comments, indentation, blank lines, quote styles and numeric spellings
outside changed token spans remain byte-for-byte intact. A replaced or removed
multiline value includes its own internal comments. Leading/trailing comments
outside the span remain, including orphaned comments and whitespace-only lines;
the editor does not guess comment ownership or normalize the file.

Removing the last dotted or header-created child can also make its now-empty
**implicit ancestors** disappear semantically: removing `["a", "b"]` from
`a.b=1` leaves a blank line, not an explicit empty `[a]` table. Existing explicit
headers outside the selected subtree remain unchanged.

Edits to an individual child inside an inline table are deliberately unsupported
in this version. They return an error and empty output. Replacing or removing the
entire directly assigned inline table is supported. Replacing a header-declared
table or AoT with a raw value is also unsupported. A source-preserving caller
should report unsupported layouts without falling back to whole-file
normalization. Array ordinals, formatting cleanup and multi-edit plans are not
part of this API.

Each call is bounded independently:

- Original and completed source: at most 1 MiB each.
- Replacement fragment: at most 1 MiB minus four wrapper bytes.
- Path: 1..64 segments and at most 4,096 total decoded key bytes.
- Index: at most 65,536 statements, plus existing parser node/depth/key-work limits.
- At most three bounded parsing passes for insertion/replacement, two for removal.

Outside existing metered parser/index work, scans, path walks and copying are
linear in bounded input plus output size. Storage is O(input bytes + parser
nodes + statements), not a strict allocation-byte budget. Runtime allocation
failure follows Goose's normal policy. Applications must bound repeated calls
and input I/O themselves. No native kernel or runtime dependency is introduced.

## Validation

From a standalone checkout, bootstrap the compiler and official fixtures through
the root project's documented setup/conformance commands, then:

```sh
make -C source format check test property conformance
make -C source sanitize SANITIZER_CC=gcc
make -C source sanitize SANITIZER_CC=clang
make -C source fuzz
```

The opt-in target has its own Makefile and tests. Tests include exact source
comparisons, all ASCII key bytes, source-context cases, 2,405 generated
semantic/preservation checks against Python `tomllib`, 21 frozen legacy
output/diagnostic fixtures plus 512 independent insertion byte checks, and source-index equality
on all pinned TOML 1.0 and 1.1 fixtures. Python comparisons use their shared
TOML 1.0 subset; explicit tests cover version-specific behavior. Sanitizers
instrument both editor tests and the independent model adapter. Fuzzing reuses
all pinned TOML 1.0 fixture inputs and verifies exact Goose assertion crash
capture before its bounded campaign. Its maximum generated input is 1,048,577
bytes, covering the first size beyond the API cap. Linux GCC/Clang are required
for these sanitizer/fuzzer targets. Build output and crash artifacts remain in
`source/.build/`, outside version control.

## Compatibility-profile validation and timing

The new profile has 21 exact legacy output/diagnostic fixtures from clean
companion `cedb2c3`, plus 512 independent root/header insertion byte checks.
`tests/legacy-contract.json` retains the original fixture bytes and reference
revision. The oracle also transports arbitrary path bytes as hex, including
NUL and paths above the operating system's argument-size limit. JIT, optimized
native and debug tests cover exact 1 MiB output, sixfold reservation, path and
combined parser limits, UTF-8/suffix precedence and hostile consumer overloads.
The existing 2,405 default model checks and 717/720 source-index fixtures remain
separate acceptance checks. Wrapper output clearing and aliasing must also be
validated by the companion's own public-API tests before adoption.

Engine `04c8bef` passed two independent code reviews, GCC/Clang ASan/UBSan,
and 35,688 Clang/libFuzzer executions in a 31-second bounded campaign, including
the assertion-artifact self-test. An independent
[5,134-call differential](tests/results/legacy-parity-04c8bef.json) against clean
`cedb2c3` compared exact status, output, diagnostic bytes and failure emptiness,
with Python `tomllib` independently checking successful outputs. Its frozen
candidate checkout, executable and source hashes were verified before and after
the campaign. This is canonical-engine evidence; companion/consumer adoption
has separate gates. The earlier `5cca023` evidence does not cover optimization
`04c8bef`; the reported final differential does.

[Paired default-operation raw samples and provenance](tests/results/default-profile-04c8bef.json)
compare alpha `b59b25a` with engine `04c8bef`, using the unchanged four-case
benchmark, pinned Goose `eadca409`, GCC 16.2.1 and `-O2`, on Linux x86-64 CPU 0.
One warmup per build precedes nine alternating pairs of 1,000 operations.
All calls create fresh parser state and owned output, including validation.
The ratios of candidate/baseline medians were **1.005** (put small), **1.085**
(remove small), **0.983** (put large) and **0.953** (remove large). The small
removal regression remains; these samples do not establish a universal speedup.
This was a shared host, with local GCC tests overlapping on CPU 2 during part
of the series. Source/binary identities and all samples are retained; readable
compiler identity and fixture-length consistency were verified after timing,
as disclosed in the report. The earlier pre-optimization series is also
[retained without dropping regressions](tests/results/default-profile-initial.json).

To repeat from two clean standalone clones at the desired immutable revisions:

```sh
python3 source/tests/compare_profiles.py /path/to/baseline /path/to/candidate \
  --goose /path/to/pinned/goose --cpu 0 --rounds 9 --iterations 1000 \
  --output /tmp/default-profile.json
```

The current driver additionally checks its own fingerprint, compiler identity
and fixture lengths during the run. Its earlier measured revision is recorded
in the report; the subsequent changes tighten provenance only. Performance of
the actual thin wrapper must be measured independently against its frozen
legacy implementation before publishing companion performance claims.

## Recorded complete-operation timings

[Raw samples and provenance](results/2026-11-04-linux-x86_64.json) were measured
from clean source commit `c9359f380f420ac7c055d9caad1ef20a20c9dccd` after the
parser consumer-overload hardening in parent
`c32c7dab44883f8fb5a5a984bf6f3c4c49119d79`. The checkout used an external
matching compiler through `GOOSE`; no toolchain symlink or tracked edits were
present. The driver fingerprints sources before compilation and verifies them
again before and after timing. The report includes compiler/hardware/flags,
source and binary hashes, every fixture and seven raw samples after one warmup.

Command: `make -C source bench CC=gcc BENCH_ITERATIONS=100`, on Linux x86-64,
Intel Core Ultra 7 258V, GCC 16.2.1, `-O2`, CPU affinity 0. These are complete
fresh operations, including all parsing, copying, allocation and validation;
input construction occurs outside the measured loops. Other processes may run
on the development machine; no exclusive-host or cross-library claim is made.

| Operation | Input bytes | Median ns/operation |
| --- | ---: | ---: |
| put_small | 68 | 2617.6 |
| remove_small | 68 | 1174.1 |
| put_large | 289072 | 1773086.4 |
| remove_large | 289072 | 1595069.2 |

The large fixture contains 256 KiB of commentary and 1,000 dependency entries.
These cases characterize specific workloads; they do not prove worst-case
latency or a universal performance ranking. CI runs benchmark smoke execution
without timing thresholds.

The recorded pre-profile local source validation also passed the consumer-overload regression
in-process and optimized native, all model/fixture checks under the hardened
parser, GCC/Clang ASan/UBSan, and 84,695 Clang/libFuzzer executions in 31 seconds
(seed 20261104, bounded by the 30-second budget). The assertion-bridge self-test
verified exact crash-artifact capture. That execution count is a recorded
campaign, not an exhaustive input claim. No source I/O or manifest publication
was performed by the module.

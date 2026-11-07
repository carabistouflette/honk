# Compiler diagnostics

Development-source feature; the published v0.4.0 release does not include this
option. Build the reviewed current source to use it.

Use `honk check --diagnostics json` for a single package to forward the pinned
Goose compiler's structured diagnostic array directly to stdout. A successful
check normally emits `[]`. Compiler errors retain the compiler's exit status.
The default is `text`; explicitly selecting `--diagnostics text` has the same
behavior as omitting the option.

```sh
honk check --diagnostics json > diagnostics.json
honk check -p member --diagnostics json > member-diagnostics.json
```

Objects can include severity, message, file, line, byte column (`col`), end span
(`endLine`, `endCol`), related locations, and original diagnostic `text`. Unknown
locations are omitted. Text is data inside JSON; JSON mode suppresses the usual
compiler text on stderr. Honk forwards the pinned compiler format without
reinterpreting it or promising a schema independent of the compiler revision.
Paths remain compiler-named staging paths, not remapped original-source paths.
Terminal escapes and untrusted messages must be handled safely by the consumer.

The option is supported only by `check`, including a binary or library package
and explicit `-p` member selection. Workspace-wide checks and `watch` are rejected
in JSON mode to avoid concatenating arrays from multiple compiler invocations.
A workspace root must select one member with `-p`. Explicit `-p` takes precedence
when `--workspace` is also supplied, matching Honk's existing selection rules.
Other execution commands reject the option; help/version retain their existing
shortcuts. Text mode retains existing workspace behavior.

Honk preflight failures (manifest, dependency, compiler selection), launch errors
and unexpected compiler-driver failures can still report stderr without any JSON.
This is compiler-output passthrough, not a universal JSON response protocol.
Optional progress goes to stderr; the existing log-file option writes its normal
application events separately. Honk neither captures nor buffers these compiler
streams: there is no new output cap, line limit or deadline. Existing process
signal forwarding, cleanup and exit handling remain in use.

## Why native compiler output

The pinned compiler already provides source spans, related messages and original
text. Parsing text headers using goose-regex would lose structure, and bounded
capture could stop a compiler and change its result. This integration therefore
adds no regex dependency or regex API change. The released goose-regex alpha
remains unchanged; a separate real consumer must justify future changes there.

## Reproduce the consumer measurement

```sh
python3 bench/compiler_diagnostics.py --goose /absolute/path/to/pinned/goose \
  --allocations --output .build/compiler-diagnostics-evidence/report.json
```

The runner builds both the recorded baseline revision and current candidate with
`--standalone -O2 --cc cc`, validates success/error outcomes, alternates four modes,
and retains seven raw end-to-end samples per case. Compiler work and staging are
included. Separate Valgrind runs use profiling executables with 16 MiB stack reservations
because Valgrind cannot map the default sparse reservations. They count parent
Honk allocations; they exclude the
exec'd compiler. The counters describe malloc-family heap events, not Goose's mmap-backed data
regions. Requested bytes are cumulative, not peak memory or RSS. Raw logs,
binary/source hashes, build commands, tool versions and limitations accompany the
results. The two tiny fixtures on a shared host do not establish a general speed
claim. Omit `--allocations` if Valgrind is unavailable.

The retained report is a pre-recursive-watch checkpoint at `486f27b`; check out
that source to replay its recipe. For a comparison of this integrated source,
pass `--baseline-ref 601b4bc` (the recursive-watch main snapshot). Comparing against
the runner's older historical default also includes the recursive-watch changes
and must not be attributed solely to diagnostic output mode.

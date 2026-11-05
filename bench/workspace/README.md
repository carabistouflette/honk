# Version gate workspace

A small CLI for release-policy checks, built with Honk 0.2.0. `version_gate`
uses a local `version_rules` library and the published Goose SemVer library at a
full immutable Git revision. Git transport uses the real public HTTPS origin.

From the Honk repository root, create a new directory from the readable source
templates. The command writes files only; then use Honk with the pinned compiler
available through `GOOSE`:

```sh
python3 bench/dogfood.py --materialize /tmp/version-workspace
cd /tmp/version-workspace
honk fetch --workspace
honk test --workspace --frozen
honk run -p version_gate --frozen -- '^1.2.3' '1.8.0'
```

The CLI prints `match` and exits 0, `no match` and exits 1, or an invalid-input
message and exits 2. Honk propagates those application exit codes. Its `run`
command also prints a built-path progress line before CLI output. Requirements
use the SemVer library's explicit full-version grammar; this tool is a policy
predicate, not a dependency solver.

The rules library lives inside the binary package so both members can be source
packaged independently. Honk deliberately rejects external path dependencies in
source packages. After tracking both manifests, sources and generated locks in
Git, `honk package --workspace --frozen` checks the exported contents offline.

`bench/dogfood.py` at the Honk repository root exercises the copied workspace,
records exact inputs and cold/warm timings, and preserves raw samples. It uses
a record-only Git wrapper that forwards unchanged arguments to real Git; it
does not replace or rewrite the HTTPS transport.

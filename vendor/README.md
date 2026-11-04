# Vendored libraries

Honk includes unmodified Apache-2.0 snapshots of goose-toml, goose-toml-edit,
goose-argparse, goose-text, goose-semver, goose-process, goose-http and goose-log,
plus the pinned HTTP metadata consumer example.
Exact upstream URLs, full commits, source/license SHA-256 values and included
files are recorded in [manifest.json](manifest.json). Attribution and license
links are in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

`python3 scripts/check-vendor.py` checks source and license hashes without a
network connection or another checkout. This is a consistency check against
reviewed repository metadata, not an upstream signature verification service.

Vendoring makes Honk's own libraries available in a standalone clone. Compiler
bootstrap still fetches the pinned Goose compiler unless an existing matching
GOOSE executable is supplied. Library updates are explicit reviewed commits.

Optional explicit diagnostics use the pinned goose-log snapshot, including its upstream NOTICE. Full source/license/notice identity remains in manifest.json.

The companion dependency editor is a thin adapter over the canonical TOML
source module's `legacy_set`/`legacy_remove` profile. Its source and the complete
canonical graph are pinned separately in manifest.json; the former private
editing engine is no longer duplicated here. Adoption retains the legacy
source/error/bounds contract and requires parity plus Honk consumer validation.

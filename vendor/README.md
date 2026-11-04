# Vendored libraries

Honk includes unmodified Apache-2.0 snapshots of goose-toml, goose-argparse
and goose-text.
Exact upstream URLs, full commits, source/license SHA-256 values and included
files are recorded in [manifest.json](manifest.json). Attribution and license
links are in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

`python3 scripts/check-vendor.py` checks source and license hashes without a
network connection or another checkout. This is a consistency check against
reviewed repository metadata, not an upstream signature verification service.

Vendoring makes Honk's own libraries available in a standalone clone. Compiler
bootstrap still fetches the pinned Goose compiler unless an existing matching
GOOSE executable is supplied. Library updates are explicit reviewed commits.

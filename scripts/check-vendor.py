#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify the exact checked-in source/license snapshots; no network or sibling checkout."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'vendor'
manifest = json.loads((root / 'manifest.json').read_text())
if manifest['schema'] != 1:
    raise SystemExit('unsupported vendor manifest schema')
for library in manifest['libraries']:
    directory = Path(library['directory'])
    if directory.is_absolute() or len(directory.parts) != 1 or directory.name in {'.', '..'}:
        raise SystemExit('unsafe vendor directory')
    for name, expected in library['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts:
            raise SystemExit('unsafe vendored file path')
        actual = hashlib.sha256((root / directory / path).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f'vendored {directory}/{name} differs from its recorded snapshot')
print('Vendored source and license hashes match the recorded pins')

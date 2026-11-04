#!/usr/bin/env python3
"""Verify the exact checked-in source/license snapshots; no network or sibling checkout."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'vendor'
manifest = json.loads((root / 'manifest.json').read_text())
assert manifest['schema'] == 1
for library in manifest['libraries']:
    directory = Path(library['directory'])
    assert not directory.is_absolute() and len(directory.parts) == 1 and directory.name not in {'.', '..'}
    for name, expected in library['files'].items():
        path = Path(name)
        assert not path.is_absolute() and '..' not in path.parts
        actual = hashlib.sha256((root / directory / path).read_bytes()).hexdigest()
        assert actual == expected, f'vendored {directory}/{name} differs from its recorded snapshot'
print('Vendored source and license hashes match the recorded pins')

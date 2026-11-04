#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Ignored fixtures must never enter Honk's native package symbol discovery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

root = Path(__file__).resolve().parents[1]
(root / '.build').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='native-import-', dir=root / '.build') as raw:
    directory = Path(raw)
    # The pinned scanner only lexes symbol declarations; importing this source
    # would correctly fail. A library import must never scan ignored build data.
    (directory / 'poison.goose').write_text('extern fn poison() = "not.a.C.symbol";\n')
    deps = tomllib.loads((root / 'Honk.toml').read_text())['dependencies']
    imports = ''.join('import ' + name + ' from ' + json.dumps(str(root / spec['path'])) + ';\n'
                      for name, spec in deps.items())
    probe = directory / 'probe.goose'
    probe.write_text(imports + 'import honk from ' + json.dumps(str(root)) + ';\nimport std;\n'
                     + 'fn main() { assert(platform::flush_stdout()); print("native import boundaries passed"); }\n')
    result = subprocess.run([os.environ['GOOSE'], 'run', str(probe)], cwd=root,
                            capture_output=True, timeout=60)
    if result.returncode or b'native import boundaries passed\n' not in result.stdout:
        sys.stderr.buffer.write(result.stdout + result.stderr)
        raise SystemExit('Honk native package scanned ignored/test sources or failed to load')
print('Honk native import ignores poisoned build fixtures')

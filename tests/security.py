#!/usr/bin/env python3
"""Deterministic malformed-import probes through the real process boundary."""
import os
from pathlib import Path
import random
import subprocess
import tempfile

honk = os.environ['HONK']
goose = os.environ['GOOSE']
rng = random.Random(0x484F4E4B)
with tempfile.TemporaryDirectory(prefix='honk hostile ') as directory:
    root = Path(directory)
    env = {**os.environ, 'GOOSE': goose, 'HONK_HOME': str(root/'cache')}
    subprocess.run([honk, 'new', 'app'], cwd=root, env=env, check=True, stdout=subprocess.DEVNULL)
    app = root/'app'
    victim = root/'victim.goose'; victim.write_bytes(b'private marker\x00unchanged')
    (app/'"x').mkdir()
    nested_victim = app/'src/owned".goose'; nested_victim.write_text('fn untouched() {}')
    names = ['"x/../../../../src/owned"', '"../../victim"', '..', '/', '""', '"\\u002e\\u002e/victim"',
             'a/b', 'a..b', '"a\\x00b"', '"a\\n../../victim"', '"a\\x1bb"', 'std', 'fn']
    cases = [f'import {name} from ".."; fn main() {{}}' for name in names]
    alphabet = 'abcdefghijklmnopqrstuvwxyz./"\\;@_0123456789\t'
    for _ in range(200):
        name = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(0, 70)))
        cases.append(f'import {name} from ".."; fn main() {{}}')
    for i, source in enumerate(cases):
        (app/'src/main.goose').write_text(source)
        proc = subprocess.run([honk, 'check', '--offline'], cwd=app, env=env, capture_output=True, timeout=10)
        assert proc.returncode >= 0, (i, proc.returncode, proc.stderr)
        assert b'AddressSanitizer' not in proc.stderr and b'runtime error:' not in proc.stderr, (i, proc.stderr)
        assert victim.read_bytes() == b'private marker\x00unchanged', i
        assert nested_victim.read_text() == 'fn untouched() {}', i
    # Opening a FIFO/device as a manifest must fail promptly, without attempting an unbounded read.
    (app/'Honk.toml').unlink(); os.mkfifo(app/'Honk.toml')
    proc = subprocess.run([honk, 'metadata'], cwd=app, env=env, capture_output=True, timeout=5)
    assert proc.returncode != 0
print(f'Passed {len(cases)} malformed-import probes and FIFO rejection')

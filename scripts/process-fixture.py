#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bind fault source, instrumentation and compiler bytes to a unique CC path."""
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
root = Path(__file__).resolve().parents[1]
wrapper = root / 'scripts/process-fault-cc.sh'
source = wrapper.read_text()
fixture = (root / 'tests/process_fault.c').read_bytes()
line = '# Fixture SHA256: ' + hashlib.sha256(fixture).hexdigest()
if '--update' in sys.argv:
    source = re.sub(r'\n# Fixture SHA256: [0-9a-f]+\n?', '\n', source)
    wrapper.write_text(source.rstrip() + '\n' + line + '\n')
else:
    if line not in source:
        raise SystemExit('run make format to refresh native fault fixture identity')
    if '--path' in sys.argv:
        sanitize = '--sanitize' in sys.argv
        selected = os.environ.get('HONK_SANITIZER_CC', 'gcc') if sanitize else 'cc'
        compiler = shutil.which(selected)
        if not compiler:
            raise SystemExit('fault fixture C compiler unavailable')
        compiler = str(Path(compiler).resolve())
        sink = root / 'scripts/sanitizer-cc.sh'
        inner = str(sink) if sanitize else compiler
        header = '#!/bin/sh\nexport HONK_PROCESS_CC=' + shlex.quote(inner) + '\n'
        header += 'export HONK_SANITIZER_CC=' + shlex.quote(compiler) + '\n'
        contents = header + source.split('\n', 1)[1]
        digest = hashlib.sha256(fixture + contents.encode() + Path(compiler).read_bytes()
                                + (sink.read_bytes() if sanitize else b'')).hexdigest()
        target = root / '.build' / ('process-fault-' + digest + '-cc.sh')
        target.parent.mkdir(exist_ok=True)
        if not target.exists() or target.read_text() != contents:
            target.write_text(contents)
            target.chmod(0o755)
        print(target)

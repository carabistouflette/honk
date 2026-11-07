#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Link-only write faults prove the actual consumer's offsets/retry policy."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', required=True, type=Path)
    parser.add_argument('--sanitize', action='store_true')
    args = parser.parse_args()
    cc_name = os.environ.get('HONK_SANITIZER_CC', 'gcc') if args.sanitize else 'gcc'
    cc = shutil.which(cc_name)
    if cc is None:
        parser.error(f'compiler not found: {cc_name}')
    flags = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
             '-fno-omit-frame-pointer', '-fno-pie'] if args.sanitize else ['-O2']
    fixture = ROOT/'tests/terminal_fixture/write.c'
    identity = hashlib.sha256(Path(__file__).read_bytes()+fixture.read_bytes()+
                              repr((cc, flags)).encode()).hexdigest()[:16]
    build = ROOT/'.build'/f'presentation-write-{identity}'
    build.mkdir(parents=True, exist_ok=True)
    obj = build/'write.o'
    subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror',*flags,'-c',str(fixture),'-o',str(obj)],
                   cwd=ROOT, check=True, timeout=60)
    wrapper = build/'cc'
    wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\n'+f'cc={cc!r}\nflags={flags!r}\n'+
                       'args=sys.argv[1:]\n'+
                       'probe=any(a in args for a in ("--version","-v","-dumpversion","-dumpmachine"))\n'+
                       'link=not probe and not any(a in args for a in ("-c","-E","-S"))\n'+
                       f'extra=[{str(obj)!r},"-Wl,--wrap=write"] if link else []\n'+
                       ('if link: extra.append("-no-pie")\n' if args.sanitize else '')+
                       'os.execv(cc,[cc,*args,*([] if probe else flags),*extra])\n')
    wrapper.chmod(0o755)
    executable = build/'probe'
    options = ['--debug','--no-bce'] if args.sanitize else ['-O2']
    subprocess.run([str(args.goose.resolve()),'build','tests/presentation_write.goose','--standalone',
                    '--cc',str(wrapper),*options,'-o',str(executable)],cwd=ROOT,check=True,timeout=180)
    expected = (b'\nfirst\n\nsecond\n', b'\nfirst\n\nsecond\n', b'\nfi', b'')
    for mode, stderr in enumerate(expected):
        result = subprocess.run([str(executable),str(mode)],cwd=ROOT,
                                env={**os.environ,'NO_COLOR':'1','TERM':'dumb'},
                                capture_output=True,timeout=10)
        if result.returncode or result.stdout != b'application success\n' or result.stderr != stderr:
            raise SystemExit(f'mode {mode}: exit={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}')
    print('consumer writes: exact partial offsets, EINTR retry, EAGAIN suppression, and 64-attempt cap pass')


if __name__ == '__main__':
    main()

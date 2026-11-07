#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build/replay isolated fault probes; never link fixtures into production."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--goose', required=True)
p.add_argument('--sanitize', action='store_true')
a = p.parse_args()
compiler = Path(shutil.which(os.environ.get('HONK_SANITIZER_CC', 'gcc'))).resolve()
flags = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie'] if a.sanitize else ['-O2']
inputs = [Path(__file__), ROOT/'tests/parallel_fault.c', ROOT/'tests/parallel_probe.goose', ROOT/'vendor/goose-process/native/process.h']
digest = hashlib.sha256(b''.join(x.read_bytes() for x in inputs) + compiler.read_bytes() + repr(flags).encode()).hexdigest()
folder = ROOT/'.build'/('parallel-fault-'+digest)
folder.mkdir(parents=True, exist_ok=True)
obj = folder/'fixture.o'
subprocess.run([str(compiler), '-std=c11', '-Wall', '-Wextra', '-Werror', *flags, '-c', str(ROOT/'tests/parallel_fault.c'), '-o', str(obj)], check=True, timeout=60)
wrapper = folder/'cc'
wrap = '-Wl,--wrap=clock_gettime,--wrap=syscall,--wrap=kill,--wrap=gp_start,--wrap=gp_close,--wrap=honk_process_recover'
wrapper.write_text('#!'+sys.executable+'\nimport os,sys\n'+f'compiler={str(compiler)!r}\nflags={flags!r}\n'+
                  'args=sys.argv[1:]\nprobe=any(a in args for a in ("--version","-v","-dumpmachine","-dumpversion"))\n'+
                  'link=not probe and not any(a in args for a in ("-c","-E","-S"))\n'+
                  f'extra={[str(obj),wrap]+(["-no-pie"] if a.sanitize else [])!r} if link else []\n'+
                  'os.execv(compiler,[compiler,*args,*([] if probe else flags),*extra])\n')
wrapper.chmod(0o755)
output = folder/'probe'
subprocess.run([a.goose, 'build', 'tests/parallel_probe.goose', '--standalone', '--debug', '--no-bce', '--cc', str(wrapper), '-o', str(output)], cwd=ROOT, check=True, timeout=180)
for mode in ('success', 'launch', 'close', 'transfer'):
    env = {**os.environ, 'HONK_PARALLEL_FAULT': mode, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1', 'UBSAN_OPTIONS': 'halt_on_error=1'}
    result = subprocess.run([str(output)], cwd=ROOT, env=env, capture_output=True, timeout=15)
    if result.returncode or result.stdout != b'parallel fault probe passed\n':
        sys.stderr.buffer.write(result.stdout + result.stderr)
        raise SystemExit(f'parallel fault probe failed: {mode} ({result.returncode})')
    print(f'parallel fault {mode}: PASS')

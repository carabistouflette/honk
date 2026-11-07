#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build a test-only watch-event fault adapter with its own native cache key."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parent.parent
compiler = shutil.which(os.environ.get('HONK_SANITIZER_CC', 'gcc'))
assert compiler
sanitize = '--sanitize' in sys.argv
flags = ['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie'] if sanitize else ['-O2']
source = ROOT/'tests/watch_fault.c'
identity = hashlib.sha256(Path(__file__).read_bytes()+source.read_bytes()+repr((compiler,flags)).encode()).hexdigest()[:16]
folder = ROOT/'.build'/('watch-fault-'+identity);folder.mkdir(parents=True,exist_ok=True)
obj = folder/'fault.o'
subprocess.run([compiler,'-std=c11','-Wall','-Wextra','-Werror',*flags,'-c',str(source),'-o',str(obj)],check=True,timeout=60)
wrapper = folder/'cc'
wrapper.write_text('#!'+sys.executable+'\nimport os,sys\n'+f'compiler={compiler!r}\nflags={flags!r}\n'+
    'args=sys.argv[1:]\nprobe=any(a in args for a in ("--version","-v","-dumpmachine","-dumpversion"))\n'+
    'link=not probe and not any(a in args for a in ("-c","-E","-S"))\n'+
    f'extra=([{str(obj)!r},"-Wl,--wrap=gw_set_next"]+({["-no-pie"] if sanitize else []!r})) if link else []\n'+
    'os.execv(compiler,[compiler,*args,*([] if probe else flags),*extra])\n')
wrapper.chmod(0o755)
output=ROOT/'.build'/('honk-watch-fault-sanitize' if sanitize else 'honk-watch-fault')
subprocess.run([sys.argv[1],'build','honk.goose','--standalone','--debug','--no-bce','--cc',str(wrapper),'-o',str(output)],cwd=ROOT,check=True,timeout=180)
print(output)

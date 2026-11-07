#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Separate observer-only binary for real inotify overflow evidence."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
cc=shutil.which('gcc')
source=ROOT/'bench/watch_overflow.c'
identity=hashlib.sha256(source.read_bytes()+Path(__file__).read_bytes()+cc.encode()).hexdigest()[:16]
folder=ROOT/'.build'/('watch-overflow-'+identity);folder.mkdir(parents=True,exist_ok=True)
obj=folder/'probe.o'
subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-O2','-c',str(source),'-o',str(obj)],check=True,timeout=60)
wrapper=folder/'cc'
wrapper.write_text('#!'+sys.executable+'\nimport os,sys\n'+f'cc={cc!r}\nobj={str(obj)!r}\n'+
                  'args=sys.argv[1:]\nprobe=any(a in args for a in ("--version","-v","-dumpmachine","-dumpversion"))\n'+
                  'link=not probe and not any(a in args for a in ("-c","-E","-S"))\n'+
                  'os.execv(cc,[cc,*args,*([obj,"-Wl,--wrap=gw_set_next"] if link else [])])\n')
wrapper.chmod(0o755)
subprocess.run([sys.argv[1],'build','honk.goose','--standalone','--cc',str(wrapper),'-O2','-o','.build/honk-overflow-observer'],cwd=ROOT,check=True,timeout=240)

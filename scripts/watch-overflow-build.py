#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Separate observer-only binary for real inotify overflow evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
cc=shutil.which('gcc')
if not cc: raise SystemExit('gcc is required')
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

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
tracked=subprocess.check_output(['git','ls-files','-z','honk.goose','honk.build','src','native','vendor'],cwd=ROOT).decode().split('\0')
manifest=dict(binary_sha256=digest(ROOT/'.build/honk-overflow-observer'),
              source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              observer_source_sha256=digest(source),builder_sha256=digest(__file__),
              goose_sha256=digest(Path(sys.argv[1]).resolve()),
              compiler=dict(path=cc,sha256=digest(Path(cc).resolve()),version=subprocess.check_output([cc,'--version'],text=True)),
              production_sources={name:digest(ROOT/name) for name in tracked if name},
              flags=['--standalone','-O2','-Wl,--wrap=gw_set_next'])
(ROOT/'.build/honk-overflow-observer.json').write_text(json.dumps(manifest,indent=2)+'\n')

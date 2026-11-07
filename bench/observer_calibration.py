# SPDX-License-Identifier: Apache-2.0
"""Positive controls for /proc observation, deliberately separate from real suites."""
import json
import os
from pathlib import Path
import sys
from process_observer import execute

CONTROL = r'''
import mmap, os, sys
mode=sys.argv[1]
def point(label):
    print('@@QUAL '+label, flush=True)
    assert sys.stdin.readline()=='continue\n'
point('baseline')
if mode=='fd':
    fds=[]
    for i in range(4):
        fds.append(os.open('/dev/null',os.O_RDONLY))
        point('fd'+str(i))
    for fd in fds: os.close(fd)
    point('restored')
else:
    pages=mmap.mmap(-1,8*1024*1024)
    for i in range(0,len(pages),4096): pages[i]=1
    if mode=='memory': point('touched')
    pages.close()
    point('released')
'''


def calibrate(folder):
    folder=Path(folder)
    results={}
    for mode in ('fd','memory','burst'):
        result=execute([sys.executable,'-S','-c',CONTROL,mode], folder, os.environ.copy(),
                       trace=folder/f'{mode}.jsonl.gz', interval=5 if mode=='burst' else .002,
                       checkpoint=lambda process,line,row: None, timeout=10)
        (folder/f'{mode}.json').write_text(json.dumps(result, indent=2)+'\n')
        assert result['complete'] and result['exit_code']==0, result
        rows=result['checkpoints'];baseline=rows[0]
        assert all(not row['children'] and not row['group_members'] for row in rows)
        if mode=='fd':
            deltas=[len(row['fds'])-len(baseline['fds']) for row in rows]
            assert deltas==[0,1,2,3,4,0],deltas
            assert rows[-1]['fds']==baseline['fds']
            result['calibration']='four deliberately retained FDs detected; exact identities restored'
        else:
            assert rows[-1]['fds']==baseline['fds']
            if mode=='memory':
                assert rows[1]['metrics']['root_rss_kib']-baseline['metrics']['root_rss_kib']>=4096
                result['calibration']='retained touched 8MiB mapping observed'
            else:
                peak=rows[-1]['metrics']['root_observed_hwm_kib']
                observed=max(phase['root_rss_kib'] for phase in result['observation']['maxima'].values())
                assert peak-observed>=4096,(peak,observed)
                result['calibration']='short touched burst missed by periodic RSS observations but visible in kernel VmHWM'
        results[mode]=result
    return results


#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verifier controls; no compiler builds. Run under normal Python and python -O."""
import gzip
import importlib.util
import json
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('honk_utc_measure', HERE/'run.py')
measure=importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


def reject(function, reason):
    try:
        function()
    except (ValueError, RuntimeError):
        return
    raise SystemExit('verifier accepted '+reason)


def main():
    root=Path(sys.argv[1]) if len(sys.argv)>1 else HERE/'results/smoke'
    metadata=json.loads((root/'metadata.json').read_text())
    raw=(root/'fixture.bin').read_bytes()
    items=list(struct.iter_unpack('<B Q I q',raw))
    rows=[json.loads(line) for line in (root/'rounds.jsonl').read_text().splitlines()]
    if not rows or metadata['validation']!='passed':
        raise SystemExit('missing successful replay evidence')
    tested=0
    for original in rows:
        row={key:original[key] for key in ('elapsed_ns','iterations','successful','clocks','sinks','bytes','checksum')}
        capture=gzip.decompress((root/original['capture_file']).read_bytes())
        trace=gzip.decompress((root/original['clock_file']).read_bytes())
        variant=original['variant'];stage=measure.STAGES.index(original['stage'])
        count=row['iterations'];warmup=metadata['warmup']
        measure.verify(row,variant,stage,items,count,warmup,capture,trace)
        for key in ('sinks','clocks','checksum','bytes','successful'):
            mutated=dict(row);mutated[key]+=1
            reject(lambda:measure.verify(mutated,variant,stage,items,count,warmup,capture,trace),'corrupted '+key)
            tested+=1
        if capture:
            mutated=bytes([capture[0]^1])+capture[1:]
            reject(lambda:measure.verify(row,variant,stage,items,count,warmup,mutated,trace),'corrupted complete bytes')
            tested+=1
        if trace:
            reject(lambda:measure.verify(row,variant,stage,items,count,warmup,capture,trace[:-1]),'truncated clock trace')
            tested+=1
    print(f'replayed {len(rows)} retained samples; rejected {tested} controlled corruptions')


if __name__=='__main__':
    main()

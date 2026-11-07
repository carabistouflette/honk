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


def manifest_controls():
    baseline = (b'c_sources = ["native/platform.c", "native/log_sink.c"];\n'
                b'c_flags_cc = ["-std=c11", "-Werror"];\n'
                b'exclude = ["tests", "bench"];\n')
    candidate = baseline.replace(b'"native/log_sink.c"]',
                                 b'"native/log_sink.c", "native/watch_tree.c"]')
    if measure.match_native_manifest(baseline, baseline) != 'identical':
        raise SystemExit('identical manifest rejected')
    if measure.match_native_manifest(baseline, candidate) != 'additive-watch-tree':
        raise SystemExit('reviewed scanner addition rejected')
    for bad in (candidate.replace(b'-Werror', b'-O3'),
                candidate.replace(b'"bench"', b'"vendor"'),
                candidate.replace(b'watch_tree.c', b'unreviewed.c'),
                candidate.replace(b'"native/platform.c", ', b''),
                candidate + b'c_sources = ["native/extra.c"];\n'):
        reject(lambda: measure.match_native_manifest(baseline, bad), 'unmatched native manifest')
    print('native manifest: identical/reviewed addition accepted; five mismatches rejected')


def main():
    manifest_controls()
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

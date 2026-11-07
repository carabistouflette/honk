# SPDX-License-Identifier: Apache-2.0
import hashlib
import html
import json
from pathlib import Path
import statistics
import sys
raw_path,summary_path,page_path=map(Path,sys.argv[1:])
r=json.loads(raw_path.read_text());assert r['complete'] and not r.get('error')
summary={'source':r['head'],'workload':r['source_revision'],'raw_sha256':hashlib.sha256(raw_path.read_bytes()).hexdigest(),'samples':{},'scope':r['scope']}
for mode in ('ordinary','population','hit'):
 rows=[x for x in r['records'] if x['label'].startswith(mode+'_')]
 assert len(rows)==3 and all(x['complete'] and x['exit_code']==0 for x in rows)
 if mode=='hit':assert all(x['backend_logs_before']==x['backend_logs_after'] for x in rows)
 values=[x['elapsed_ns']/1e6 for x in rows]
 summary['samples'][mode]={'all_ms':values,'median_ms':statistics.median(values)}
summary['interpretation']='Explicit verified hits avoid compilation; population includes standalone compilation and can cost more. Default behavior unchanged. Shared-host single-workload evidence; no general speed guarantee.'
summary_path.write_text(json.dumps(summary,indent=2)+'\n')
scale=max(max(x['all_ms']) for x in summary['samples'].values())
rows=[]
for i,(mode,v) in enumerate(summary['samples'].items()):
 samples=', '.join(f'{x:,.0f}' for x in v['all_ms'])
 color=f'var(--chart-{i+1},currentColor)'
 rows.append(f'<div class="row"><span>{mode}</span><div class="track"><div style="width:{v["median_ms"]/scale*100:.2f}%;background:{color}"></div></div><b>{v["median_ms"]:,.0f} ms</b></div><p class="samples">All samples: {samples} ms</p>')
page_path.write_text('''<!doctype html><html><head><meta charset="utf-8"><style>:root{font-family:var(--font-sans,system-ui);color:var(--foreground,CanvasText);color-scheme:light dark}body{margin:0}h2{font-size:18px}p{font-size:13px;line-height:1.5}.row{display:flex;align-items:center;gap:10px;font-size:13px}.row span{width:85px}.row b{width:85px;text-align:right}.track{flex:1;background:var(--muted,ButtonFace);height:20px}.track div{height:20px;min-width:2px}.samples{font-size:11px;color:var(--muted-foreground,GrayText);margin:5px 0 20px}</style></head><body><h2>Opt-in test compilation reuse</h2><p>Four unchanged public goose-diff suites · Honk release tests, jobs4.<br>Median of three full-command measurements; lower is better.</p>'''+''.join(rows)+'''<p>Every suite still executes. Hit runs were checked against unchanged compiler backend logs. Population pays for standalone compilation; ordinary tests continue to compile by default.</p><p class="samples">Shared host, warm compiler caches, one source-only workload. All measured samples retained. Native/unsupported inputs fall back to compilation; fixed cache bucket collisions can also cause misses. System toolchain assumptions still apply.</p></body></html>''')

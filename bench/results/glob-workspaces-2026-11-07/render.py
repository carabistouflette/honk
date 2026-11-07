import gzip,html,json,statistics
from pathlib import Path
out=Path(__file__).resolve().parent
path=out/'raw.json'
d=json.loads(path.read_text() if path.exists() else gzip.decompress((out/'raw.json.gz').read_bytes()))
def values(scale,engine,phase=None):
 rows=[s for s in d['samples'] if (s['packages'],s['engine'])==(scale,engine)];assert len(rows)==5
 return [sum(p['ns'] for p in s['phases'] if p['phase']==phase) if phase else s['wall_ns'] for s in rows]
def cell(v,scale):return f'{statistics.median(v)/scale:.4f} [{min(v)/scale:.4f}, {max(v)/scale:.4f}]'
summary=[]
lines=['# Honk workspace glob profile — 2026-11-07','',
'Filtering is a negligible part of these complete commands. This profile supports keeping the matcher/API unchanged. It does not establish a ranking against other libraries or identify a new speedup.','',
f'Consumer source: `{d["revision"]}`, with the vendored alpha.4 prepared matcher. Generated workspaces contain 1, 4 or 8 complete snapshots of that real Honk project and its vendored dependencies. Each package runs the real `tests/core.goose` through `test --workspace --frozen --filter tests/**/core*.goose`. The layout is a scaling fixture, not a naturally occurring production workspace.','',
'Five sequential shuffled rounds on CPU 2, warm caches and a shared host: 30 full command samples. Every binary/size first passes an untimed output-equivalence check. Inputs, locks, source snapshots, binaries, compiler, stdlib and tool hashes are guarded before each sample and after measurement. Own builds finished before timing; other host activity was uncontrolled.','',
'A normal binary measures whole-command wall time using monotonic time and pidfd readiness. A separate private build times staging, candidate discovery and the filter loop. Filtering includes matcher calls, status checks, selected-path copies and timer overhead. Its timing bounds matcher work within that instrumented loop; source instrumentation can affect code generation, so it is not an exact cost decomposition of the normal binary. The remaining phase time includes compilation, target execution and other command work; those are not separately attributed.','',
'## Complete command time','',
'Seconds, median **[minimum, maximum]**. The two columns are normal and instrumented builds, not before/after optimization.','',
'| Packages | Candidate paths | Selected tests | Normal command | Instrumented command |','| ---: | ---: | ---: | ---: | ---: |']
for scale in (1,4,8):
 native=values(scale,'native');profile=values(scale,'profile');prep=values(scale,'profile','prepare');disc=values(scale,'profile','discover');filt=values(scale,'profile','filter');shares=[]
 for s in [s for s in d['samples'] if s['engine']=='profile' and s['packages']==scale]:
  rows=[p for p in s['phases'] if p['phase']=='filter'];assert len(rows)==scale and sum(p['candidates'] for p in rows)==8*scale and sum(p['selected'] for p in rows)==scale;shares.append(100*sum(p['ns'] for p in rows)/s['wall_ns'])
 summary.append({'packages':scale,'candidates':8*scale,'selected':scale,'normal_wall_ns':{'median':statistics.median(native),'min':min(native),'max':max(native)},'profile_wall_ns':{'median':statistics.median(profile),'min':min(profile),'max':max(profile)},'prepare_ns':statistics.median(prep),'discover_ns':statistics.median(disc),'filter_ns':statistics.median(filt),'filter_share_percent':statistics.median(shares)})
 lines.append(f'| {scale} | {8*scale} | {scale} | {cell(native,1e9)} | {cell(profile,1e9)} |')
lines+=['','## Instrumented phases','','Phase sums across all packages in one command, median **[minimum, maximum]**. Filter share is the median per-sample filter/whole-command ratio in the private build.','','| Packages | Staging ms | Discovery ms | Filter µs | Filter share |','| ---: | ---: | ---: | ---: | ---: |']
for scale in (1,4,8):
 s=next(s for s in summary if s['packages']==scale);lines.append(f'| {scale} | {cell(values(scale,"profile","prepare"),1e6)} | {cell(values(scale,"profile","discover"),1e6)} | {cell(values(scale,"profile","filter"),1e3)} | {s["filter_share_percent"]:.6f}% |')
lines+=['','## Scope and reproduction','',
'The largest fixture has 64 candidate test paths and selects eight tests. It scales package/source staging but does not saturate the 4096-source-file cap per package or establish matcher behavior for thousands of targets. No consumer upgrade or library release follows from this evidence. Honk already shares one prepared filter across workspace members.','',
'[Complete raw report](raw.json.gz) is losslessly gzip-compressed and includes all samples, phase records and input/tool/binary identities. [Context](context.json) records the host/tool environment. [Private instrumentation patch](instrumentation.patch) is not applied to Honk. [Executed driver](executed-driver.py) preserves the exact script/hash; adjust its root, output and Goose paths for another checkout, use a new output directory and the pinned compiler, and run it from the goose-libs workspace. It imports the guarded `bench/glob_consumer.py` helper. Its two builds and fixture fetches finish before any warmups or measurements.','',
'Run `python3 render.py` in the retained result directory to regenerate the report, summary and chart. New timing runs should use the same snapshot and layout; full-command values and tiny phase timings depend on the host and do not establish statistical significance or causal speedups. Product sources, matcher API, traversal checks and limits are unchanged.','']
(out/'README.md').write_text('\n'.join(lines));(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
chart=['<!doctype html><html><head><style>body{margin:0;color:var(--foreground);font-family:var(--font-sans)}h3{font-size:17px;margin:0 0 8px}p{font-size:13px;color:var(--muted-foreground)}.row{display:grid;grid-template-columns:85px 1fr 85px;align-items:center;gap:12px;font-size:13px;margin:10px 0}.track{height:22px;background:var(--secondary);border-radius:4px}.bar{height:100%;border-radius:4px}.number{text-align:right}.label{font-size:14px;font-weight:600;margin-top:20px}</style></head><body><h3>Honk workspace scaling</h3><p>Five rounds · generated workspaces containing real Honk snapshots</p><div class="label">Normal full command · seconds</div>']
maximum=max(s['normal_wall_ns']['median'] for s in summary)*1.05
for s in summary:
 v=s['normal_wall_ns']['median'];chart.append(f'<div class="row"><span>{s["packages"]} packages</span><div class="track"><div class="bar" style="width:{v/maximum*100:.2f}%;background:var(--chart-1)"></div></div><span class="number">{v/1e9:.3f} s</span></div>')
chart.append('<div class="label">Private filter loop · microseconds (separate scale)</div>');maximum=max(s['filter_ns'] for s in summary)*1.05
for s in summary:
 v=s['filter_ns'];chart.append(f'<div class="row"><span>{s["candidates"]} paths</span><div class="track"><div class="bar" style="width:{v/maximum*100:.2f}%;background:var(--chart-2)"></div></div><span class="number">{v/1e3:.2f} µs</span></div>')
chart.append('<p>Filtering includes status checks and selected-path copies. Largest fixture: 64 candidate paths, eight selected tests. This does not test the 4,096-target limit. Shared-host observations; all ranges are retained.</p></body></html>');(out/'comparison.html').write_text(''.join(chart));print(json.dumps(summary,indent=2))

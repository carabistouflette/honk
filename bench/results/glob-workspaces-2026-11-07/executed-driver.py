import hashlib,json,os,random,shutil,statistics,subprocess,sys,tarfile,time
from pathlib import Path
root=Path('/home/arobin/Work/Projects/goose-libs/honk');out=Path('/home/arobin/Work/Projects/goose-libs/.build/consumer-scale');goose=Path('/home/arobin/Work/Projects/goose-libs/.build/goose-time-public/.toolchain/goose/build/goose');rev='17f83c02103842f707f7d1e5a888d7e91e7047c4'
sys.path.insert(0,str(root/'bench'));from glob_consumer import call,digest,fixture_inputs
os.sched_setaffinity(0,{2});env={**os.environ,'GOOSE':str(goose),'HONK_HOME':str(out/'home'),'TMPDIR':str(out/'tmp')};(out/'tmp').mkdir(exist_ok=True)
source=out/'native-source';source.mkdir();archive=out/'source.tar';subprocess.run(['git','-C',str(root),'archive','--output',str(archive),rev],check=True)
with tarfile.open(archive) as t:t.extractall(source,filter='data')
profile=out/'profile-source';shutil.copytree(source,profile)
p=profile/'src/build.goose';s=p.read_text().replace('    var selected: u8[][>..] = [];','    let profile_start = clock_ns(); let profile_count = paths.len;\n    var selected: u8[][>..] = [];',1).replace('    paths = copy(selected);','    paths = copy(selected);\n    let profile_elapsed = clock_ns() - profile_start;\n    print("HONK_PROFILE\\tfilter\\t", profile_count, "\\t", paths.len, "\\t", profile_elapsed);',1);s=s.replace('    let stage = prepare(p, g); let profile =','    let profile_prepare_start = clock_ns();\n    let stage = prepare(p, g);\n    print("HONK_PROFILE\\tprepare\\t0\\t0\\t", clock_ns() - profile_prepare_start);\n    let profile =',1);s=s.replace('        var paths: u8[][>..] = []; files(stage, dir, paths);','        let profile_discover_start = clock_ns();\n        var paths: u8[][>..] = []; files(stage, dir, paths);\n        print("HONK_PROFILE\\tdiscover\\t", paths.len, "\\t0\\t", clock_ns() - profile_discover_start);',1);p.write_text(s)
binaries={}
for name,path in [('native',source),('profile',profile)]:
 binary=out/f'honk-{name}';r=call([goose,'build',path/'honk.goose','--cc','gcc','-O2','-o',binary],env=env);(out/f'{name}-build.log').write_text(r.stdout+r.stderr);binaries[name]=binary;print('built',name,flush=True)
fixtures={};inputs={str(goose):digest(goose),str(root/'bench/glob_consumer.py'):digest(root/'bench/glob_consumer.py'),str(Path(__file__)):digest(__file__)}
for scale in (1,4,8):
 fixture=out/f'workspace-{scale}';fixture.mkdir();members=[]
 for i in range(scale):
  name=f'member{i}';members.append(name);shutil.copytree(source,fixture/name);call([binaries['native'],'fetch'],cwd=fixture/name,env=env)
 (fixture/'Honk.toml').write_text('[workspace]\nmembers='+json.dumps(members)+'\n');fixtures[scale]=fixture;inputs.update(fixture_inputs(fixture));print('prepared',scale,flush=True)
for tree in (source,profile):inputs.update({str(p):digest(p) for p in tree.rglob('*') if p.is_file()})
for p in binaries.values():inputs[str(p)]=digest(p)
stdlib=goose.parent.parent/'stdlib'
if not stdlib.is_dir():stdlib=goose.parent.parent.parent/'stdlib'
inputs.update({str(p):digest(p) for p in stdlib.rglob('*') if p.is_file()})
for name in ('gcc','as','ld'):
 p=Path(shutil.which(name)).resolve();inputs[str(p)]=digest(p)
command=['test','--workspace','--frozen','--filter','tests/**/core*.goose']
def run(engine,scale):
 start=time.monotonic_ns();r=call([binaries[engine],*command],cwd=fixtures[scale],env=env);wall=time.monotonic_ns()-start;rows=[];plain=[]
 for line in r.stdout.splitlines():
  if line.startswith('HONK_PROFILE\t'):
   _,phase,candidates,selected,ns=line.split('\t');rows.append({'phase':phase,'candidates':int(candidates),'selected':int(selected),'ns':int(ns)})
  else:plain.append(line)
 assert sum('Passed 1 test targets'==line for line in plain)==scale,(scale,r.stdout[-500:])
 if engine=='profile':assert len(rows)==scale*3
 return {'engine':engine,'packages':scale,'wall_ns':wall,'phases':rows},('\n'.join(plain),r.stderr)
expected={}
for scale in fixtures:
 for engine in binaries:
  _,text=run(engine,scale)
  if engine=='native':expected[scale]=text
  else:assert text==expected[scale],scale
 print('warmed',scale,flush=True)
def verify():
 assert all(digest(p)==h for p,h in inputs.items()),'input changed'
 for fixture in fixtures.values():assert fixture_inputs(fixture)=={p:h for p,h in inputs.items() if p.startswith(str(fixture)+'/')},'fixture changed'
verify();report={'revision':rev,'compiler':call([goose,'version']).stdout,'command':command,'inputs_sha256':inputs,'environment':{'cpu':2,'TMPDIR':env['TMPDIR']},'scope':'Generated 1/4/8-package workspaces containing exact real Honk source snapshots. Warm local commands; selected real core test runs per package. Private phase instrumentation; native complete-command samples. Shared host, uncontrolled activity. Phase timing includes bookkeeping, filtering includes selected-path copies. No alternative-library or causal speedup claim.','samples':[]};rng=random.Random(20261107)
for round in range(5):
 tasks=[(e,s) for e in binaries for s in fixtures];rng.shuffle(tasks)
 for engine,scale in tasks:
  verify();sample,text=run(engine,scale);assert text==expected[scale];sample['round']=round;report['samples'].append(sample)
 (out/'raw.partial.json').write_text(json.dumps(report,indent=2)+'\n');print('round',round+1,'complete',flush=True)
verify();(out/'raw.json').write_text(json.dumps(report,indent=2)+'\n');print('done',flush=True)

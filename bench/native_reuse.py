#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Qualify native fallback separately from real source-only cache controls."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import tarfile

from process_observer import execute
from qualify_parallel import FILES as DIFF_FILES, REV as DIFF_REV, clean, digest, git, save

ROOT=Path(__file__).resolve().parents[1]
CRYPTO_REV='a4643f62bd5e76b371054c6537a95169a7930101'
CRYPTO_FILES=('crypto.goose','crypto.build','CMakeLists.txt','native','tests/api.goose',
              'GOOSE_REVISION','LICENSE','THIRD_PARTY_NOTICES.md')


def backend(home):
    result={}
    for path in sorted((home/'build/prog').rglob('cc.log')):
        info=path.stat()
        result[str(path.relative_to(home))]=dict(device=info.st_dev,inode=info.st_ino,
                                               mtime_ns=info.st_mtime_ns,size=info.st_size,sha256=digest(path))
    return result


def cache_records(project):
    result={}
    for path in sorted((project/'.honk/reuse').rglob('record')):
        if not path.is_file() or path.is_symlink():continue
        record=dict(sha256=digest(path))
        if path.stat().st_size==130:
            text=path.read_text()
            record.update(key=text[:64],artifact_sha256=text[65:129])
        result[str(path.relative_to(project))]=record
    return result


def native_tools(home):
    result={}
    for path in sorted((home/'build/pkg').rglob('CMakeCache.txt')):
        compiler=next((line.partition('=')[2] for line in path.read_text().splitlines() if line.startswith('CMAKE_C_COMPILER:')),None)
        record=dict(cache_sha256=digest(path),compiler=compiler)
        if compiler and Path(compiler).is_file():
            record['compiler_sha256']=digest(compiler)
        result[str(path.relative_to(home))]=record
    return result


def dependencies(ldd,program):
    output=version([str(ldd),str(program)])
    paths={}
    for word in output.split():
        if word.startswith('/') and Path(word).is_file():
            resolved=Path(word).resolve()
            paths[str(resolved)]=digest(resolved)
    return dict(ldd=output,sha256=paths)


def version(argv):
    return subprocess.check_output(argv,text=True,timeout=15).strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('crypto-repo','diff-repo','honk','goose','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    for name in ('crypto_repo','diff_repo','honk','goose'):
        setattr(args,name,getattr(args,name).resolve(strict=True))
    if git(ROOT,'status','--porcelain').strip():parser.error('requires clean committed Honk source')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'tmp').mkdir()
    report=dict(complete=False,head=git(ROOT,'rev-parse','HEAD').decode().strip(),platform=platform.platform(),
                records=[],mutations=[],profiles={},postconditions={},scope='Correctness qualification, not a performance comparison. Native CMake caches may remain warm.')
    target=out/'raw.json';save(target,report)
    tools={'honk':args.honk,'goose':args.goose}
    harness=[Path(__file__),ROOT/'bench/process_observer.py',ROOT/'bench/qualify_parallel.py',ROOT/'bench/observer_calibration.py']
    environments={}
    projects={}

    def stage(name,repo,tag,revision,files,entry):
        if git(repo,'rev-parse',tag+'^{commit}').decode().strip()!=revision:raise RuntimeError('public tag mismatch')
        archive=git(repo,'archive','--format=tar',revision,'--',*files)
        (out/(name+'.tar')).write_bytes(archive)
        project=out/name;project.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:bundle.extractall(project,filter='data')
        originals={str(p.relative_to(project)):dict(sha256=digest(p),mode=stat.S_IMODE(p.stat().st_mode)) for p in sorted(project.rglob('*')) if p.is_file()}
        if (project/'GOOSE_REVISION').read_text().strip()!=(ROOT/'GOOSE_REVISION').read_text().strip():raise RuntimeError('compiler pins differ')
        manifest=f'[package]\nname="{name}"\nkind="lib"\nversion="0.1.0"\nentry="{entry}"\n'
        (project/'Honk.toml').write_text(manifest)
        env={**os.environ,'GOOSE':str(args.goose),'HONK_HOME':str(out/(name+'-cache')),
             'GOOSE_HOME':str(out/(name+'-goose')),'TMPDIR':str(out/'tmp'),'GOOSE_STDLIB':str(stdlib)}
        env.pop('GOOSE_CC',None)
        report['profiles'][name]=dict(revision=revision,tag=tag,files=originals,archive_sha256=hashlib.sha256(archive).hexdigest(),manifest=manifest,
                                      environment_sha256=hashlib.sha256(json.dumps(sorted(env.items())).encode()).hexdigest())
        projects[name]=project;environments[name]=env
        return project

    def run(name,label,flags=(),work='compile',code=0,expected=None):
        project=projects[name];env=environments[name];home=Path(env['GOOSE_HOME'])
        original_logs=backend(home)
        # Owned diagnostic logs are not compiler inputs or Honk cache inputs.
        # A marker distinguishes backend writes even on coarse timestamp filesystems.
        for relative in original_logs:
            path=home/relative
            if path.is_symlink():raise RuntimeError('backend log unexpectedly symlinked')
            path.write_bytes(b'qualification: awaiting backend invocation\n')
        before=backend(home)
        row=execute([str(args.honk),'test','--release','--jobs','4',*flags],project,env,timeout=180)
        row.update(profile=name,label=label,expected_work=work,expected_code=code,backend_before_marker=original_logs)
        report['records'].append(row);save(target,report)
        row.update(profile=name,label=label,expected_work=work,expected_code=code,
                   compiler={'path':env['GOOSE'],'sha256':digest(env['GOOSE'])},
                   environment_sha256=hashlib.sha256(json.dumps(sorted(env.items())).encode()).hexdigest(),
                   source_snapshot={path:digest(project/path) for path in report['profiles'][name]['files']},backend_before=before,backend_after=backend(home),cache_records=cache_records(project))
        save(target,report)
        row['native_cmake_tools']=native_tools(home);save(target,report)
        if not row['complete'] or row['exit_code']!=code:raise RuntimeError('unexpected invocation result: '+label)
        changed=before!=row['backend_after']
        if work=='hit' and changed:raise RuntimeError('expected backend avoidance: '+label)
        if work=='compile' and not changed:raise RuntimeError('expected recompilation: '+label)
        if expected is not None and clean(row['stdout'])!=expected:raise RuntimeError('suite output mismatch: '+label)
        if name=='crypto' and row['cache_records']:raise RuntimeError('native fallback retained a cache record')
        print(name,label,'passed',flush=True)
        return row

    def mutate(path,data,label):
        before=path.read_bytes()
        record=dict(label=label,path=str(path.relative_to(out)),before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(data).hexdigest(),before_size=len(before),after_size=len(data))
        mutation_dir=out/'mutations';mutation_dir.mkdir(exist_ok=True)
        (mutation_dir/(label+'.before')).write_bytes(before);(mutation_dir/(label+'.after')).write_bytes(data)
        report['mutations'].append(record);save(target,report);path.write_bytes(data)
        return before

    try:
        stdlib=next(p for p in [args.goose.parent/'stdlib',args.goose.parent.parent/'stdlib'] if (p/'std.goose').is_file()).resolve()
        for name in ('cc','cmake','pkg-config','ldd'):
            tools[name]=Path(shutil.which(name)).resolve(strict=True)
        report['tools']={name:dict(path=str(path),sha256=digest(path),version=version([str(path),'version' if name=='goose' else '--version'])) for name,path in tools.items() if name!='honk'}
        report['honk_sha256']=digest(args.honk);report['harness_sha256']={str(p.relative_to(ROOT)):digest(p) for p in harness}
        report['honk_runtime_dependencies']=dependencies(tools['ldd'],args.honk)
        report['libsodium']=version([str(tools['pkg-config']),'--modversion','libsodium'])
        libdir=Path(version([str(tools['pkg-config']),'--variable=libdir','libsodium']))
        sodium=(libdir/'libsodium.so').resolve(strict=True)
        report['libsodium_library']={'path':str(sodium),'sha256':digest(sodium)}
        report['libsodium_flags']=version([str(tools['pkg-config']),'--cflags','--libs','libsodium'])
        report['stdlib_sha256']=digest(stdlib/'std.goose')
        crypto=stage('crypto',args.crypto_repo,'v0.1.0-alpha.1',CRYPTO_REV,CRYPTO_FILES,'crypto.goose')
        diff=stage('diff',args.diff_repo,'v0.1.0',DIFF_REV,DIFF_FILES,'diff.goose')
        native_expected='crypto public interface regressions passed\n'
        run('crypto','ordinary',expected=native_expected)
        report['native_runtime_dependencies']=dependencies(tools['ldd'],crypto/'target/release/.honk/tests/0')
        save(target,report)
        for i in range(3):run('crypto','fallback_'+str(i),['--reuse-build'],expected=native_expected)
        run('crypto','filtered_fallback',['--reuse-build','--filter','tests/api.goose'],expected=native_expected)
        api=crypto/'tests/api.goose';before=mutate(api,api.read_bytes()+b'\n// derivative qualification fixture\n','native-source-edit')
        run('crypto','edited_source_fallback',['--reuse-build'],expected=native_expected);mutate(api,before,'native-source-restore')
        published=crypto/'target/release/.honk/tests/0';published_hash=digest(published)
        report['postconditions']['native_publication_before']=published_hash;save(target,report)
        native=crypto/'native/crypto.c';sidecar=crypto/'crypto.build'
        c_before=mutate(native,native.read_bytes()+b'\n#error intentional_qualification_failure\n','native-compile-failure')
        b_before=mutate(sidecar,sidecar.read_bytes()+b'\n// derivative: force native package fingerprint refresh\n','native-build-refresh')
        failed=run('crypto','failed_native_build',['--reuse-build'],work='any',code=1)
        report['postconditions']['native_publication_after_failure']=digest(published);save(target,report)
        if digest(published)!=published_hash:raise RuntimeError('failed native build replaced published executable')
        if 'intentional_qualification_failure' not in failed['stdout']+failed['stderr']:raise RuntimeError('native compiler failure was not exercised')
        mutate(native,c_before,'native-compile-restore');mutate(sidecar,b_before,'native-build-restore')
        run('crypto','restored_fallback',['--reuse-build'],expected=native_expected)

        first=run('diff','population',['--reuse-build']);expected=clean(first['stdout'])
        if not all(line.startswith(name+': ') for line,name in zip(expected.splitlines(),['context','core','sparse','unified'])) or len(expected.splitlines())!=4:raise RuntimeError('unexpected pure suite identities')
        if len(first['cache_records'])!=4:raise RuntimeError('pure profile did not populate four slots')
        run('diff','verified_hit',['--reuse-build'],work='hit',expected=expected)
        source=diff/'diff.goose';data=source.read_bytes();altered=data.replace(b'const MAX_BYTES',b'const\tMAX_BYTES',1)
        if altered==data or len(altered)!=len(data):raise RuntimeError('same-size mutation not prepared')
        mutate(source,altered,'pure-source-edit');run('diff','source_invalidates',['--reuse-build'],expected=expected)
        run('diff','edited_hit',['--reuse-build'],work='hit',expected=expected)
        mutate(source,data,'pure-source-restore');run('diff','restore_repopulates',['--reuse-build'],expected=expected)
        lines=expected.splitlines(keepends=True)
        for suite,index in [('unified',3),('core',1)]:
            run('diff','filtered_'+suite,['--reuse-build','--filter','tests/'+suite+'.goose'],work='hit',expected=lines[index])
        bucket=int.from_bytes(hashlib.sha256(b'tests/core.goose').digest(),'big')%16
        program=diff/f'.honk/reuse/release/tests/{bucket}/program'
        report['postconditions']['corruption_record_before']=cache_records(diff)[str((program.parent/'record').relative_to(diff))]
        data=program.read_bytes();damaged=data[:-1]+bytes([data[-1]^1])
        if damaged[:4]!=b'\x7fELF':raise RuntimeError('corruption must preserve ELF magic')
        report['postconditions']['corrupt_elf_magic']={'before':data[:4].hex(),'after':damaged[:4].hex()}
        mutate(program,damaged,'corrupt-cached-executable')
        report['postconditions']['corruption_record_after_edit']=cache_records(diff)[str((program.parent/'record').relative_to(diff))];save(target,report)
        run('diff','corruption_recompiles',['--reuse-build'],expected=expected)
        run('diff','corruption_recovered_hit',['--reuse-build'],work='hit',expected=expected)
        sentinel=out/'external-sentinel';sentinel.write_bytes(b'unchanged external data')
        report['postconditions']['sentinel_before']=digest(sentinel);save(target,report)
        program.unlink();program.symlink_to(sentinel)
        run('diff','symlink_not_followed',['--reuse-build'],expected=expected)
        report['postconditions']['sentinel_after']=digest(sentinel);save(target,report)
        if sentinel.read_bytes()!=b'unchanged external data':raise RuntimeError('symlink modified external sentinel')
        program.unlink();run('diff','symlink_repopulate',['--reuse-build'],expected=expected)
        run('diff','symlink_recovered_hit',['--reuse-build'],work='hit',expected=expected)
        alternate=out/'alternate-goose';shutil.copyfile(args.goose,alternate);alternate.chmod(0o755)
        report['postconditions']['alternate_compiler_version_before']=version([str(alternate),'version'])
        environments['diff']['GOOSE']=str(alternate)
        run('diff','compiler_location_environment_change',['--reuse-build'],expected=expected)
        run('diff','alternate_compiler_hit',['--reuse-build'],work='hit',expected=expected)
        mutate(alternate,alternate.read_bytes()+b'\0','compiler-bytes-change')
        report['postconditions']['alternate_compiler_version_after']=version([str(alternate),'version']);save(target,report)
        run('diff','compiler_bytes_invalidate',['--reuse-build'],expected=expected)
        run('diff','changed_compiler_hit',['--reuse-build'],work='hit',expected=expected)
        environments['diff']['GOOSE']=str(args.goose)
        run('diff','original_compiler_restore',['--reuse-build'],expected=expected)
        run('diff','final_hit',['--reuse-build'],work='hit',expected=expected)
        report['restored_files']={name:{path:{'sha256':digest(project/path),'mode':stat.S_IMODE((project/path).stat().st_mode)} for path in report['profiles'][name]['files']} for name,project in projects.items()}
        save(target,report)
        for name,project in projects.items():
            for path,record in report['profiles'][name]['files'].items():
                if digest(project/path)!=record['sha256'] or stat.S_IMODE((project/path).stat().st_mode)!=record['mode']:raise RuntimeError('upstream input not restored: '+path)
        for group in ('honk_runtime_dependencies','native_runtime_dependencies'):
            if any(digest(path)!=value for path,value in report[group]['sha256'].items()):raise RuntimeError('resolved runtime dependency changed')
        if digest(stdlib/'std.goose')!=report['stdlib_sha256'] or digest(sodium)!=report['libsodium_library']['sha256']:raise RuntimeError('standard library or libsodium changed')
        if digest(args.honk)!=report['honk_sha256'] or any(digest(path)!=report['tools'][name]['sha256'] for name,path in tools.items() if name!='honk'):raise RuntimeError('tool changed')
        if any(digest(ROOT/name)!=value for name,value in report['harness_sha256'].items()):raise RuntimeError('harness changed')
        if git(ROOT,'status','--porcelain').strip() or git(ROOT,'rev-parse','HEAD').decode().strip()!=report['head']:raise RuntimeError('Honk source changed')
        report['complete']=True
    except BaseException as error:
        report['error']=repr(error);raise
    finally:save(target,report)


if __name__=='__main__':main()

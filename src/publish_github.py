# SPDX-License-Identifier: Apache-2.0
"""GitHub transport for an archive and index entry verified by Honk."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import quote, urlencode


def require(condition, message):
    if not condition:
        raise ValueError(message)


def gh(*args, payload=None, missing=False, cwd=None):
    env = dict(os.environ, GH_HOST='github.com', GH_PROMPT_DISABLED='1')
    process = subprocess.run(['gh', *args], input=payload, capture_output=True,
                             text=True, cwd=cwd, env=env, timeout=120)
    if missing and process.returncode == 1 and '(HTTP 404)' in process.stderr:
        return None
    if process.returncode:
        raise ValueError(process.stderr.strip() or f'gh exited with status {process.returncode}')
    return process.stdout


def api(path, data=None, *, missing=False):
    options = ['--method', 'POST', '--input', '-'] if data is not None else []
    result = gh('api', '--hostname', 'github.com', *options, path,
                payload=json.dumps(data) if data is not None else None, missing=missing)
    return None if result is None else json.loads(result)


def file_at(repo, path, commit):
    result = api(f'repos/{repo}/contents/{path}?ref={commit}', missing=True)
    if result is None:
        return None
    require(result['type'] == 'file' and result['encoding'] == 'base64', f'invalid index file {path}')
    require(result['size'] <= 1024 * 1024, f'index file exceeds 1 MiB: {path}')
    return base64.b64decode(result['content']).decode()


def release_in(text, name, version, schema):
    doc = tomllib.loads(text)
    require(doc['schema'] == schema and doc['package'] == name, f'expected a schema-{schema} package index')
    matches = [row for row in doc['releases'] if row['version'] == version]
    require(len(matches) <= 1, 'duplicate version in package index')
    return matches[0] if matches else None


def index_files(repo, commit, path, name, entry, row, schema):
    # Search catalogs use schema 1 even when package indexes use schema 2.
    marker = file_at(repo, 'index/_schema', commit)
    declared = '1' if marker is None else marker.strip()
    require(declared == str(schema),
            f'index schema mismatch: expected {schema}; schema-2 indexes must declare 2 in index/_schema')
    existing = file_at(repo, path, commit)
    if existing:
        previous = release_in(existing, name, row['version'], schema)
        require(previous is None or previous == row, 'version already exists with different index metadata')
        if previous:
            return {}
        prefix = entry.index('[[releases]]')
        package_text = existing.rstrip() + '\n\n' + entry[prefix:]
    else:
        package_text = entry
    return catalog_files(repo, commit, path, name, package_text)


def catalog_files(repo, commit, path, name, package_text):
    releases = tomllib.loads(package_text)['releases']
    require(len(releases) <= 512 and len(package_text.encode()) <= 1024 * 1024, 'package index limit exceeded')
    catalog_path = 'index/_catalog.toml'
    catalog_text = file_at(repo, catalog_path, commit)
    require(catalog_text is not None, 'index repository is missing index/_catalog.toml')
    catalog = tomllib.loads(catalog_text)
    require(catalog['schema'] == 1, 'expected a schema-1 search catalog')
    packages = {item['name']: item['version'] for item in catalog['packages']}
    stable = [r['version'] for r in releases if not r['yanked'] and '-' not in r['version']]
    if stable:
        packages[name] = max(stable, key=lambda v: tuple(map(int, v.split('.'))))
    else:
        packages.pop(name, None)
    catalog_text = 'schema = 1\n'
    if packages:
        catalog_text += ''.join(f'\n[[packages]]\nname = {json.dumps(n)}\nversion = {json.dumps(v)}\n'
                                for n, v in sorted(packages.items()))
    else:
        catalog_text += 'packages = []\n'
    require(len(packages) <= 4096 and len(catalog_text.encode()) <= 1024 * 1024, 'search catalog limit exceeded')
    return {path: package_text, catalog_path: catalog_text}


def ensure_release(repo, tag, archive, row):
    endpoint = f'repos/{repo}/releases/tags/{quote(tag, safe="")}'
    release = api(endpoint, missing=True)
    assets = [] if release is None else [asset for asset in release['assets'] if asset['name'] == archive.name]
    require(release is None or not release['draft'], 'existing release is a draft')
    if not assets:
        # Upload the bytes checked against the index row, from a private copy.
        with tempfile.TemporaryDirectory() as directory:
            with archive.open("rb") as source:
                data = source.read(16 * 1024 * 1024 + 1)
            require(len(data) <= 16 * 1024 * 1024, "local archive exceeds 16 MiB")
            require(hashlib.sha256(data).hexdigest() == row['sha256'], 'local archive SHA-256 mismatch')
            (Path(directory) / archive.name).write_bytes(data)
            if release is None:
                prerelease = ('--prerelease',) if '-' in tag else ()
                gh('release', 'create', tag, archive.name, '--repo', f'github.com/{repo}',
                   '--verify-tag', '--title', tag, '--notes', '', *prerelease, cwd=directory)
            else:
                gh('release', 'upload', tag, archive.name, '--repo', f'github.com/{repo}', cwd=directory)
        release = api(endpoint)
        assets = [asset for asset in release['assets'] if asset['name'] == archive.name]
    require(not release['draft'] and len(assets) == 1 and assets[0]['state'] == 'uploaded',
            'release archive is unavailable on a public release')
    asset = assets[0]
    require(asset['browser_download_url'] == row['url'], 'release archive URL differs from the index entry')
    digest = asset.get('digest')
    if not digest:
        require(asset['size'] <= 16 * 1024 * 1024, 'release archive exceeds 16 MiB')
        with tempfile.TemporaryDirectory() as directory:
            gh('release', 'download', tag, '--repo', f'github.com/{repo}',
               '--pattern', archive.name, '--dir', directory)
            downloaded = Path(directory) / archive.name
            require(downloaded.stat().st_size <= 16 * 1024 * 1024, 'release archive exceeds 16 MiB')
            digest = 'sha256:' + hashlib.sha256(downloaded.read_bytes()).hexdigest()
    require(digest == 'sha256:' + row['sha256'], 'release archive SHA-256 mismatch')


def index_target(index, fork):
    upstream = api(f'repos/{index}')
    target = api(f'repos/{fork}') if fork else upstream
    fork = target['full_name']
    index = upstream['full_name']
    require(target['permissions']['push'], 'index branch repository requires write access')
    require(fork == index or target.get('parent', {}).get('full_name') == index,
            'index fork must be a direct fork of the index repository')
    base = upstream['default_branch']
    upstream_head = api(f'repos/{index}/git/ref/heads/{quote(base)}')['object']['sha']
    require(fork == index or api(f'repos/{fork}/git/commits/{upstream_head}', missing=True),
            'sync the index fork with upstream before publishing')
    return index, fork, base, upstream_head


def publish(repo, index, fork, archive, entry):
    doc = tomllib.loads(entry)
    schema = doc['schema']
    require(schema in (1, 2), 'unsupported release schema')
    name = doc['package']
    row, = doc['releases']
    version = row['version']
    tag = 'v' + version
    index, fork, base, upstream_head = index_target(index, fork)
    require(not api(f'repos/{repo}')['private'], 'release repository must be public')
    path = f'index/{name}.toml'
    files = index_files(index, upstream_head, path, name, entry, row, schema)
    branch = f'honk-publish/{name}/{version}'
    ref = existing_branch(fork, branch,
                          lambda parent: index_files(fork, parent, path, name, entry, row, schema)) if files else None
    ensure_release(repo, tag, archive, row)
    if not files:
        print(f'{name} {version} is already in the index')
        return
    propose(index, fork, base, upstream_head, branch, ref, files, f'Publish {name} {version}',
            f'Archive: {row["url"]}\n\nSHA-256: `{row["sha256"]}`')


def existing_branch(fork, branch, files_at_parent):
    ref = api(f'repos/{fork}/git/ref/heads/{quote(branch)}', missing=True)
    if ref is None:
        return None
    branch_head = ref['object']['sha']
    commit = api(f'repos/{fork}/git/commits/{branch_head}')
    require(len(commit['parents']) == 1, 'existing index branch has unexpected history')
    parent = commit['parents'][0]['sha']
    expected = files_at_parent(parent)
    changed_paths = {path for path, content in expected.items() if file_at(fork, path, parent) != content}
    details = api(f'repos/{fork}/commits/{branch_head}')
    require(changed_paths and {item['filename'] for item in details['files']} == changed_paths
            and all(file_at(fork, path, branch_head) == content for path, content in expected.items()),
            'existing index branch has different content')
    return ref


def propose(index, fork, base, upstream_head, branch, ref, files, title, body):
    if not ref:
        parent = api(f'repos/{fork}/git/commits/{upstream_head}')
        tree = api(f'repos/{fork}/git/trees', {
            'base_tree': parent['tree']['sha'],
            'tree': [dict(path=p, mode='100644', type='blob', content=content)
                     for p, content in files.items()],
        })
        commit = api(f'repos/{fork}/git/commits', {
            'tree': tree['sha'], 'parents': [upstream_head], 'message': title,
        })
        api(f'repos/{fork}/git/refs', {'ref': f'refs/heads/{branch}', 'sha': commit['sha']})
    head = fork.split('/')[0] + ':' + branch
    pulls = f'repos/{index}/pulls'
    query = urlencode(dict(state='open', head=head, base=base))
    existing = api(f'{pulls}?{query}')
    if existing:
        result = existing[0]
    else:
        result = api(pulls, dict(title=title, head=head, base=base,
                                 body=body))
    print(result['html_url'])


RELEASE_HEADER = re.compile(r'(?m)^\s*\[\[releases\]\]\s*(?:#[^\r\n]*)?$')
YANKED_FIELD = re.compile(r'(?m)^([ \t]*yanked[ \t]*=[ \t]*)(true|false)([ \t]*(?:#[^\r\n]*)?\r?)$')


def set_yanked(text, name, version, desired):
    doc = tomllib.loads(text)
    require(doc['schema'] in (1, 2) and doc['package'] == name, 'invalid package index')
    releases = doc['releases']
    positions = [i for i, row in enumerate(releases) if row['version'] == version]
    require(len(positions) == 1, 'expected exactly one published release for the requested version')
    position, = positions
    row = releases[position]
    require(type(row['yanked']) is bool, 'invalid yank state')
    if row['yanked'] == desired:
        return text
    headers = list(RELEASE_HEADER.finditer(text))
    require(len(headers) == len(releases), 'expected canonical [[releases]] tables')
    start = headers[position].end()
    end = headers[position + 1].start() if position + 1 < len(headers) else len(text)
    updated, count = YANKED_FIELD.subn(lambda m: m[1] + ('true' if desired else 'false') + m[3], text[start:end])
    result = text[:start] + updated + text[end:]
    row['yanked'] = desired
    require(count == 1 and tomllib.loads(result) == doc, 'could not edit only the requested yank state')
    return result


def yank(index, fork, name, version, undo):
    index, fork, base, upstream_head = index_target(index, fork)
    path = f'index/{name}.toml'

    def changes(repo, commit):
        original = file_at(repo, path, commit)
        require(original is not None, 'package was not found in the index')
        updated = set_yanked(original, name, version, not undo)
        return {} if updated == original else catalog_files(repo, commit, path, name, updated)

    files = changes(index, upstream_head)
    if not files:
        print(f'{name} {version} is already {"active" if undo else "yanked"}')
        return
    action = 'Restore' if undo else 'Yank'
    branch = f'honk-{action.lower()}/{name}/{version}/{upstream_head[:12]}'
    ref = existing_branch(fork, branch, lambda parent: changes(fork, parent))
    propose(index, fork, base, upstream_head, branch, ref, files, f'{action} {name} {version}',
            'Update the yank flag for this release and regenerate the search catalog.')


def repository(value):
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+', value)
            and value.split('/')[1] not in ('.', '..'), 'expected a GitHub OWNER/REPO')


if __name__ == '__main__':
    action, *arguments = sys.argv[1:]
    try:
        if action == 'publish':
            repo, index, fork, path, entry = arguments
            repository(repo)
            repository(index)
            if fork:
                repository(fork)
            publish(repo, index, fork, Path(path), entry)
        else:
            index, fork, name, version, undo = arguments
            repository(index)
            if fork:
                repository(fork)
            yank(index, fork, name, version, undo == 'undo')
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        print(f'honk {action}: {error}', file=sys.stderr)
        sys.exit(1)

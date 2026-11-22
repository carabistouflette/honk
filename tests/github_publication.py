# SPDX-License-Identifier: Apache-2.0
import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from publish_github import ensure_release, publish, set_yanked, yank


class GitHubPublication(unittest.TestCase):
    def test_yank_edits_only_requested_flag_and_restores_original(self):
        source = ('schema = 2\npackage = "example"\n\n[[releases]]\nversion = "1.0.0"\n'
                  'yanked = false\n\n[[releases]]\nversion = "2.0.0"\n'
                  'yanked = false # latest\nfeatures = { extras = [] }\n')
        changed = set_yanked(source, 'example', '2.0.0', True)
        self.assertEqual(changed, source.replace('false # latest', 'true # latest'))
        self.assertEqual(set_yanked(changed, 'example', '2.0.0', True), changed)
        self.assertEqual(set_yanked(changed, 'example', '2.0.0', False), source)
        with self.assertRaisesRegex(ValueError, 'requested version'):
            set_yanked(source, 'example', '3.0.0', True)

    def test_yank_updates_search_catalog_and_retry_is_a_noop_after_merge(self):
        path = 'index/example.toml'
        package = ('schema = 1\npackage = "example"\n[[releases]]\nversion = "1.0.0"\nyanked = false\n'
                   '[[releases]]\nversion = "2.0.0"\nyanked = false\n')
        catalog = 'schema = 1\n\n[[packages]]\nname = "example"\nversion = "2.0.0"\n'
        files = {path: package, 'index/_catalog.toml': catalog}
        with patch('publish_github.index_target', return_value=('owner/index', 'owner/index', 'main', 'abc123')), \
             patch('publish_github.file_at', side_effect=lambda repo, path, commit: files[path]), \
             patch('publish_github.existing_branch', return_value=None), \
             patch('publish_github.propose') as propose:
            yank('owner/index', '', 'example', '2.0.0', False)
            changes = propose.call_args.args[6]
            self.assertEqual(changes['index/_catalog.toml'], catalog.replace('2.0.0', '1.0.0'))
            self.assertEqual(changes[path], set_yanked(package, 'example', '2.0.0', True))
            files.update(changes)
            yank('owner/index', '', 'example', '2.0.0', False)
            self.assertEqual(propose.call_count, 1)

    def test_retry_reuses_uploaded_asset_and_existing_index_branch(self):
        for schema in (1, 2):
            with self.subTest(schema=schema):
                self.check_retry(schema)

    def check_retry(self, schema):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'example-1.0.0.tar.gz'
            archive.write_bytes(b'archive bytes')
            sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            url = f'https://github.com/author/lib/releases/download/v1.0.0/{archive.name}'
            entry = (f'schema = {schema}\npackage = "example"\n\n[[releases]]\nversion = "1.0.0"\n'
                     f'url = "{url}"\nsha256 = "{sha}"\nyanked = false\n'
                     'entry = "lib.goose"\ndependencies = []\n')
            if schema == 2:
                entry += 'features = { extras = [] }\n'
            asset = dict(name=archive.name, state='uploaded', digest='sha256:' + sha, browser_download_url=url)
            state = dict(branch=False, release=False, pr=False, fail_pr=True)
            marker = None
            blobs = {}
            calls = []

            def api(path, data=None, **_):
                calls.append((path, data))
                if path == 'repos/author/lib':
                    return {'private': False}
                if path == 'repos/registry/nest':
                    return {'full_name': 'registry/nest', 'permissions': {'push': True}, 'default_branch': 'main'}
                if path.endswith('/git/ref/heads/main'):
                    return {'object': {'sha': 'base'}}
                if '/contents/' in path:
                    path, commit = path.split('/contents/')[1].split('?ref=')
                    content = blobs.get(path) if commit == 'publish' else (
                        'schema = 1\npackages = []\n' if path == 'index/_catalog.toml' else None)
                    if path == 'index/_schema':
                        content = marker
                    return None if content is None else dict(type='file', encoding='base64', size=len(content),
                                                             content=base64.b64encode(content.encode()).decode())
                if path.endswith('/git/ref/heads/honk-publish/example/1.0.0'):
                    return {'object': {'sha': 'publish'}} if state['branch'] else None
                if path.endswith('/git/commits/base'):
                    return {'tree': {'sha': 'base-tree'}}
                if path.endswith('/git/commits/publish'):
                    return {'parents': [{'sha': 'base'}]}
                if path.endswith('/releases/tags/v1.0.0'):
                    return {'draft': False, 'assets': [asset]} if state['release'] else None
                if path.endswith('/commits/publish'):
                    return {'files': [{'filename': path} for path in blobs]}
                if path.endswith('/git/trees'):
                    blobs.update((item['path'], item['content']) for item in data['tree'])
                    return {'sha': 'new-tree'}
                if path.endswith('/git/commits'):
                    return {'sha': 'publish'}
                if path.endswith('/git/refs'):
                    state['branch'] = True
                    return {}
                if '/pulls?' in path:
                    return [{'html_url': 'https://github.com/registry/nest/pull/7'}] if state['pr'] else []
                if path.endswith('/pulls'):
                    if state['fail_pr']:
                        raise ValueError('temporary PR failure')
                    state['pr'] = True
                    return {'html_url': 'https://github.com/registry/nest/pull/7'}
                self.fail(path)

            def gh(*args, cwd, **_):
                self.assertEqual(args[:3], ('release', 'create', 'v1.0.0'))
                self.assertIn('--verify-tag', args)
                self.assertEqual((Path(cwd) / archive.name).read_bytes(), archive.read_bytes())
                state['release'] = True

            with patch('publish_github.api', side_effect=api), patch('publish_github.gh', side_effect=gh) as transport:
                marker = '1\n' if schema == 2 else '2\n'
                with self.assertRaisesRegex(ValueError, 'index schema mismatch'):
                    publish('author/lib', 'registry/nest', '', archive, entry)
                self.assertFalse(any('/releases/' in path or data is not None for path, data in calls))
                self.assertEqual(transport.call_count, 0)
                marker = '2\n' if schema == 2 else None
                with self.assertRaisesRegex(ValueError, 'temporary PR failure'):
                    publish('author/lib', 'registry/nest', '', archive, entry)
                state['fail_pr'] = False
                publish('author/lib', 'registry/nest', '', archive, entry)
                publish('author/lib', 'registry/nest', '', archive, entry)
                self.assertEqual(transport.call_count, 1)
                self.assertEqual(sum(path.endswith('/git/refs') for path, _ in calls), 1)
                self.assertIn('name = "example"', blobs['index/_catalog.toml'])
                self.assertEqual(blobs['index/example.toml'], entry)
                asset['digest'] = 'sha256:' + '0' * 64
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    ensure_release('author/lib', 'v1.0.0', archive, dict(sha256=sha, url=url))
                self.assertEqual(transport.call_count, 1)


if __name__ == '__main__':
    unittest.main()

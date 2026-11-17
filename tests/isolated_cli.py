"""Real Honk -> scoped graph -> Goose JIT/native qualification."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HONK = Path(os.environ.get('HONK', '.build/honk')).resolve()
GOOSE = Path(os.environ['GRAPH_GOOSE']).resolve()
REVISION = json.loads(subprocess.check_output([str(GOOSE), 'version', '--json']))['compiler_revision']


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GOOSE=str(GOOSE), GOOSE_HOME=str(self.root / 'compiler-cache'))

    def package(self, folder, code, dependencies=None, name=None):
        path = self.root / folder
        path.mkdir()
        manifest = f'[package]\nname = "{name or folder}"\nentry = "entry.goose"\n'
        manifest += f'[toolchain]\nrevision = "{REVISION}"\n[dependencies]\n'
        for alias, target in (dependencies or {}).items():
            manifest += f'{alias} = {{ path = "../{target}" }}\n'
        (path / 'Honk.toml').write_text(manifest)
        (path / 'entry.goose').write_text(code)
        return path

    def run_honk(self, command='run', ok=True, extra=()):
        result = subprocess.run([str(HONK), command, '--isolated', *extra], cwd=self.root / 'app',
                                env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def diamond(self):
        self.package('one', 'namespace versioned; struct Value { x: i64 } fn make() -> Value { Value { 1 } }', name='dep')
        self.package('two', 'namespace versioned; struct Value { x: i64, y: i64 } fn make() -> Value { Value { 2, 3 } }', name='dep')
        self.package('a', 'namespace client; import dep; fn answer() -> i64 { dep::make().x }', {'dep': 'one'})
        self.package('b', 'namespace client; import dep; fn answer() -> i64 { dep::make().x }', {'dep': 'two'})
        self.package('app', 'import a; import b; import std; fn main() { print(a::answer(), " ", b::answer()); }', {'a': 'a', 'b': 'b'})

    def test_scoped_diamond_jit_and_native(self):
        self.diamond()
        self.run_honk('check')
        self.assertEqual(self.run_honk().stdout.strip(), '1 2')
        self.run_honk('build')
        binary = self.root / 'app/target/isolated/app'
        self.assertEqual(subprocess.check_output([str(binary)], text=True).strip(), '1 2')
        graph = json.loads((binary.parent / 'graph.json').read_text())
        self.assertEqual(len(graph['nodes']), 5)
        owners = [n for n in graph['nodes'] if n['source']['name'] in ('a', 'b')]
        self.assertNotEqual(owners[0]['bindings']['dep'], owners[1]['bindings']['dep'])
        self.assertFalse((self.root / 'app/Honk.lock').exists())

    def test_shared_alias_instance(self):
        self.package('dep', 'namespace shared; var count: i64 = 0; fn next() -> i64 { count++; count }')
        self.package('app', 'import a; import b; import std; fn main() { let x = a::next(); let y = b::next(); print(x, " ", y); }', {'a': 'dep', 'b': 'dep'})
        self.assertEqual(self.run_honk().stdout.strip(), '1 2')

    def test_snapshot_refresh_and_stability(self):
        self.diamond()
        self.run_honk('check')
        path = self.root / 'app/target/isolated/graph.json'
        original = path.read_bytes()
        self.run_honk('check')
        self.assertEqual(path.read_bytes(), original)
        with (self.root / 'one/entry.goose').open('a') as f:
            f.write('\n// source edit\n')
        self.run_honk('check')
        self.assertNotEqual(path.read_bytes(), original)

    def test_cycle_and_unsupported_lock_preserve_lock(self):
        self.package('app', 'fn main() {}', {'dep': 'dep'})
        self.package('dep', 'fn answer() {}', {'app': 'app'})
        lock = self.root / 'app/Honk.lock'
        lock.write_text('sentinel')
        self.assertIn('cycle', self.run_honk('check', ok=False).stderr)
        self.assertIn('locks', self.run_honk('check', ok=False, extra=('--frozen',)).stderr)
        self.assertEqual(lock.read_text(), 'sentinel')

    def test_sourced_import_and_embedded_resource_rejected(self):
        self.package('app', 'import dep from "../dep"; fn main() {}')
        self.assertIn('sourced imports', self.run_honk('check', ok=False).stderr)
        (self.root / 'app/entry.goose').write_text('fn main() { embed_file("resource"); }')
        self.assertIn('embedded resources', self.run_honk('check', ok=False).stderr)

    def test_wrong_nominal_version_rejected(self):
        self.diamond()
        p = self.root / 'app'
        text = (p / 'Honk.toml').read_text()
        (p / 'Honk.toml').write_text(text + 'old = { path = "../one" }\nnewer = { path = "../two" }\n')
        (p / 'entry.goose').write_text('import old; import newer; fn take(v: newer::Value) {} fn main() { take(old::make()); }')
        self.assertIn('dep@', self.run_honk('check', ok=False).stderr)


if __name__ == '__main__':
    unittest.main()

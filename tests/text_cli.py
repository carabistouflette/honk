#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise shared strict UTF-8 checks through Honk's actual CLI boundary."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import unittest

HONK = str(Path(os.environ["HONK"]).resolve())
GOOSE = str(Path(os.environ["GOOSE"]).resolve())

@unittest.skipUnless(os.name == "posix", "raw byte argv/path checks require POSIX")
class TextCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="honk-text-")
        self.root = Path(self.temp.name)
        self.env = {**os.environ, "GOOSE": GOOSE, "HONK_HOME": str(self.root / "cache")}
        self.call("new", "app", "--name", "app")
        self.app = self.root / "app"
    def tearDown(self):
        self.temp.cleanup()
    def call(self, *args, cwd=None, ok=True):
        proc = subprocess.run([HONK, *args], cwd=cwd or self.root, env=self.env,
                              capture_output=True, timeout=15)
        self.assertEqual(proc.returncode == 0, ok, proc.stdout + proc.stderr)
        self.assertNotIn(b"AddressSanitizer", proc.stderr)
        self.assertNotIn(b"runtime error:", proc.stderr)
        return proc
    def test_invalid_dependency_bytes_preserve_manifest(self):
        manifest = self.app / "Honk.toml"
        original = manifest.read_bytes()
        invalid = [b"\x80", b"\xc0\x80", b"\xc1\xbf", b"\xed\xa0\x80",
                   b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80", b"\xc2", b"\xe0\xa0", b"\xf0\x90\x80"]
        for bad in invalid:
            for field in ("path", "git", "rev"):
                with self.subTest(bad=bad.hex(), field=field):
                    if field == "path":
                        args = ["--path", b"../valid-" + bad]
                    elif field == "git":
                        args = ["--git", b"https://example.invalid/" + bad, "--rev", "main"]
                    else:
                        args = ["--git", "https://example.invalid/repo", "--rev", b"valid-" + bad]
                    proc = self.call("add", "helper", *args, cwd=self.app, ok=False)
                    self.assertIn(b"dependency values must be valid UTF-8", proc.stderr)
                    self.assertEqual(manifest.read_bytes(), original)
    def test_valid_unicode_dependency_roundtrips(self):
        for value in ("../café/世界/🦆", "../a\u0301/\ufeff/\uffff/\U0010ffff"):
            with self.subTest(value=value):
                self.call("add", "helper", "--path", value, cwd=self.app)
                manifest = tomllib.loads((self.app / "Honk.toml").read_text())
                self.assertEqual(manifest["dependencies"]["helper"]["path"], value)
                metadata = json.loads(self.call("metadata", cwd=self.app).stdout)
                self.assertEqual(metadata["dependencies"][0]["path"], value)
                self.call("remove", "helper", cwd=self.app)
                self.assertEqual(json.loads(self.call("metadata", cwd=self.app).stdout)["dependencies"], [])
    def test_valid_unicode_project_path(self):
        path = "projet-café-世界-🦆"
        self.call("new", path, "--name", "unicode")
        metadata = json.loads(self.call("metadata", cwd=self.root / path).stdout)
        self.assertEqual(metadata["root"], str((self.root / path).resolve()))
    def test_invalid_project_path_has_no_metadata_output(self):
        for suffix in (b"bad\xff", b"bad\xed\xa0\x80", b"bad\xf4\x90\x80\x80"):
            with self.subTest(suffix=suffix.hex()):
                path = os.fsencode(self.root) + b"/" + suffix
                self.call("new", path, "--name", "invalid_path")
                proc = self.call("metadata", cwd=path, ok=False)
                self.assertEqual(proc.stdout, b"")
                self.assertIn(b"UTF-8 project path", proc.stderr)
    def test_self_check_and_package_include_declared_libraries(self):
        source = Path(__file__).resolve().parents[1]
        project = self.root / "self-project"
        project.mkdir()
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=source).split(b"\0")
        for raw in tracked:
            if not raw:
                continue
            name = os.fsdecode(raw)
            original = source / name
            self.assertTrue(original.is_file() and not original.is_symlink(), name)
            destination = project / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
        subprocess.run(["git", "init", "-q"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
        lock = (project / "Honk.lock").read_bytes()
        manifest = tomllib.loads((project / "Honk.toml").read_text())
        self.assertEqual(manifest["dependencies"]["text"], {"path": "vendor/goose-text"})
        self.assertEqual(manifest["dependencies"]["toml_edit"], {"path": "vendor/goose-toml-edit"})
        self.call("check", "--frozen", cwd=project)
        self.call("package", "--frozen", cwd=project)
        label = manifest["package"]["name"] + "-" + manifest["package"]["version"]
        archive = project / "target" / "package" / (label + ".tar.gz")
        with tarfile.open(archive, "r:gz") as package:
            for name in ("text.goose", "LICENSE"):
                expected = (project / "vendor" / "goose-text" / name).read_bytes()
                self.assertEqual(package.extractfile(label + "/vendor/goose-text/" + name).read(), expected)
            for name in ("toml_edit.goose", "LICENSE"):
                expected = (project / "vendor" / "goose-toml-edit" / name).read_bytes()
                self.assertEqual(package.extractfile(label + "/vendor/goose-toml-edit/" + name).read(), expected)
        self.assertEqual((project / "Honk.lock").read_bytes(), lock)

if __name__ == "__main__":
    unittest.main()

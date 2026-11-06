# Vendored dependencies

Honk includes Apache-2.0 library snapshots so its own dependencies work in a
standalone clone. [manifest.json](manifest.json) records each upstream URL,
full revision and source/license hash. [Third-party notices](../THIRD_PARTY_NOTICES.md)
link the licenses. To check the local copies:

```sh
python3 scripts/check-vendor.py
```

This is a consistency check against committed metadata, not signature or
publisher authentication. Updates are deliberate; this docs audit changes none.
Compiler bootstrap still fetches the pinned Goose compiler unless a matching
trusted executable is supplied explicitly.

The TOML companion supplies single-edit compatibility calls. Multi-remove uses
canonical TOML alpha.4 `2043d9c0b32a8237d54b2a45578f2cc4b7ea384c` directly;
the companion remains `f8d1b1664a86b768a6f1375636d9b2c3a440aa31`.
UTC logging uses the included goose-log adapter and goose-time snapshot.
HTTP metadata uses the included consumer example. The manifest records exact
source files for all of them; a newer upstream release is not adopted implicitly.

Target filtering uses only goose-glob v0.1.0-alpha.1 at `4e8d7830e81b8ffd1c4d8ae2716ea93edc7ea8e3`
(`glob.goose` and LICENSE). The optional filesystem collector is not vendored.

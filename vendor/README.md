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

Optional CLI presentation uses goose-terminal and its POSIX adapter; the manifest
records the exact source/license snapshot. Renderer output stays application-owned.

Target filtering uses only goose-glob v0.1.0-alpha.4 at `2022a04e1847490c9c76af91e1e5c01a3c6e3cc0`
(`glob.goose` and LICENSE). The optional filesystem collector is not vendored.

Directory notifications use the source/build/native files from goose-watch alpha.1
at `7bbd7ef8c9a4d6323ef9d065d1461bae9ba9fe58`, with its LICENSE and NOTICE.

Dependency-cycle validation uses goose-task at `166b684ca96403fea94072cc8e0c630321fb832d`
(`task.goose` and LICENSE only). The returned topological plan is discarded;
Honk retains its existing resolver, lockfile and build ordering.

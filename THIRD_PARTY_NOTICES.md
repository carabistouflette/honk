# Third-party notices

Honk is distributed under [Apache-2.0](LICENSE). Its source distribution vendors
the following unmodified Apache-2.0 source snapshots. Their full license texts
are retained beside the files. These pins are independent of any newer upstream
release; changing them requires explicit review and validation.

| Component | Upstream commit | Included source | License |
| --- | --- | --- | --- |
| [goose-toml](https://github.com/carabistouflette/goose-toml) | `de7dfe092f6d72811417355044e5d024d5600613` | `vendor/goose-toml/` canonical parser/writer/source profile | [Apache-2.0](vendor/goose-toml/LICENSE) |
| [goose-toml-edit](https://github.com/carabistouflette/goose-toml-edit) | `ae32f13d69b69c9604a44d7acd71d2f966daef35` | `vendor/goose-toml-edit/toml_edit.goose` thin legacy adapter | [Apache-2.0](vendor/goose-toml-edit/LICENSE) |
| [goose-argparse](https://github.com/carabistouflette/goose-argparse) | `d23af7aff17c6720d17a2e8f6b80bd3bf8f14275` | `vendor/goose-argparse/argparse.goose` | [Apache-2.0](vendor/goose-argparse/LICENSE) |
| [goose-log](https://github.com/carabistouflette/goose-log) | `a3919c5e9135b9812db422d5052bb1ea5d1d202b` | `vendor/goose-log/logger.goose` | [Apache-2.0](vendor/goose-log/LICENSE), [NOTICE](vendor/goose-log/NOTICE) |
| [goose-text](https://github.com/carabistouflette/goose-text) | `46059e30be79ece6efd4317eb0adc6d213c808ab` | `vendor/goose-text/text.goose` | [Apache-2.0](vendor/goose-text/LICENSE) |
| [goose-semver](https://github.com/carabistouflette/goose-semver) | `2311ae69a7edacb545f284b02e345be07dd2fb05` | `vendor/goose-semver/semver.goose` | [Apache-2.0](vendor/goose-semver/LICENSE) |
| [goose-process](https://github.com/carabistouflette/goose-process) | `191a9423197e850e699eff500620a5c7d111aa54` | `vendor/goose-process/process.goose`, `process.build`, `native/` | [Apache-2.0](vendor/goose-process/LICENSE) |
| [goose-http](https://github.com/carabistouflette/goose-http) | `c879c6fec88eaf7229f890a5dd6e3fc313261eab` | `vendor/goose-http/` Goose/build/CMake/native files | [Apache-2.0](vendor/goose-http/LICENSE) |
| [Honk metadata example](https://github.com/carabistouflette/goose-http) | `c879c6fec88eaf7229f890a5dd6e3fc313261eab` | `vendor/honk-metadata/honk_metadata.goose` | [Apache-2.0](vendor/honk-metadata/LICENSE) |

The source bytes and license copies were compared with the immutable Git objects
at these upstream commits during the publication audit. The goose-log NOTICE is retained; the other pinned trees have no additional
NOTICE/COPYING file. [vendor/manifest.json](vendor/manifest.json)
records SHA-256 hashes; `python3 scripts/check-vendor.py` verifies the standalone
checkout against those records without fetching anything.

The Goose compiler/standard library/runtime are Apache-2.0 upstream components
selected by [GOOSE_REVISION](GOOSE_REVISION). Compiler bootstrap fetches that
separate repository; its own third-party components retain their upstream
licenses there. Honk does not vendor or ship a compiler, TinyCC, generated C,
compiled runtime, or prebuilt executables in this source repository. If
redistributing compiler/build outputs, retain their applicable upstream notices.

Honk's native adapter uses system libc/POSIX/Linux interfaces. Git, CMake, C/C++
compilers, Python, GNU tar and gzip are external development/runtime tools, not
vendored source packages in this distribution.

The vendored goose-toml-edit editor is Apache-2.0; see vendor/goose-toml-edit/LICENSE and vendor/manifest.json. Its pinned TOML parser includes the original nested vendor notices and licenses.
The pinned goose-http test helpers in `tests/http_fixture/` are Apache-2.0; their source revision and hashes are recorded in that directory. `scripts/metadata-test-build.py` adapts the upstream test builder under the same license. Test transport redirection/CA overrides are excluded from production builds. System libcurl and its TLS/resolver dependencies are external libraries, not vendored source; distribution of those libraries follows their own licenses.

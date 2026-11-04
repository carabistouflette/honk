# Third-party notices

Honk is distributed under [Apache-2.0](LICENSE). Its source distribution vendors
the following unmodified Apache-2.0 source snapshots. Their full license texts
are retained beside the files. These pins are independent of any newer upstream
release; changing them requires explicit review and validation.

| Component | Upstream commit | Included source | License |
| --- | --- | --- | --- |
| [goose-toml](https://github.com/carabistouflette/goose-toml) | `fb055e32098c3de312896952aa86d18edafdaf98` | `vendor/goose-toml/toml.goose` | [Apache-2.0](vendor/goose-toml/LICENSE) |
| [goose-argparse](https://github.com/carabistouflette/goose-argparse) | `d23af7aff17c6720d17a2e8f6b80bd3bf8f14275` | `vendor/goose-argparse/argparse.goose` | [Apache-2.0](vendor/goose-argparse/LICENSE) |

The source bytes and license copies were compared with the immutable Git objects
at these upstream commits during the publication audit. Neither pinned tree has
an additional NOTICE/COPYING file. [vendor/manifest.json](vendor/manifest.json)
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

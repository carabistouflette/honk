# Pinned HTTPS test fixtures

Unmodified Apache-2.0 test sources from goose-http `c879c6fec88eaf7229f890a5dd6e3fc313261eab`. These helpers and the GNU transport wrapper are linked/imported only by test targets. Production `make build` uses the system libcurl transport and never the fixture routing or CA override. Full license: [vendored upstream license](../../vendor/goose-http/LICENSE).

| File | SHA-256 |
| --- | --- |
| `metadata.py` | `2b337cec0b0b8d9ef5699758a662bbe05299838d46b224defc37de19cdb0e6ea` |
| `integration.py` | `a98ccae28223f037dcde7ca5f6b3bc65849efcc2568c904c1ff03be01153b839` |
| `metadata_transport.c` | `19d347b71d232033c5d82225663f8510b7e57d7d8a47e9a439e35d9a0bfe3b8e` |

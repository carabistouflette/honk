# Vendored libraries

Unmodified Apache-2.0 Goose sources from the local coordination workspace:

- goose-toml: carabistouflette/goose-toml, commit fb055e32098c3de312896952aa86d18edafdaf98, `toml.goose`.
- goose-argparse: carabistouflette/goose-argparse; exact source identity recorded in `goose-argparse/REVISION`.

Each directory includes its upstream license. Vendoring keeps a clean standalone checkout buildable before all libraries have public releases. Updates are explicit, reviewed commits. No consumer process performs network access to import these libraries.

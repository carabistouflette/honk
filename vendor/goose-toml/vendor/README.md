# Vendored strict UTF-8 implementation

`text.goose` is goose-text commit `09d5f0c39e50d3270189bd0c6798cd10ab2f0c0d` from https://github.com/carabistouflette/goose-text. Apache-2.0; see LICENSE.

The only patch renames `namespace text` to `namespace toml_text` so consumers
can also import goose-text independently without duplicate namespace members.
The snapshot supplies strict validation and scalar encoding. TOML keeps its
syntax restrictions, input limits and public compatibility wrapper.

Update from an immutable reviewed commit, preserve its license, review the
diff and provenance, and rerun TOML's full validation suite. Never vendor
uncommitted source. Run `python3 scripts/check-text-vendor.py SOURCE_REPOSITORY`
to verify the snapshot against its pinned source commit when updating it.

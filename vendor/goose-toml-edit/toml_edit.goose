// SPDX-License-Identifier: Apache-2.0
namespace toml_edit;
import toml.source.editor;

let MAX_INPUT_BYTES = 1048576;
let MAX_DEPTH = 64;

// Complete the owned canonical result before mutating any caller input alias.
// Builtin clear/append avoids consumer str/copy overloads.
fn set(source: u8[:], path: const u8[:][:], value: u8[:], out: u8[>..]&) -> u8[>..] {
    let result, error = toml_source::legacy_set(source, path, value);
    out.clear(); out.append(result); return error;
}
fn remove(source: u8[:], path: const u8[:][:], out: u8[>..]&) -> u8[>..] {
    let result, error = toml_source::legacy_remove(source, path);
    out.clear(); out.append(result); return error;
}

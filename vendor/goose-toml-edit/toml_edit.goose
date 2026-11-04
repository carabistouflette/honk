// SPDX-License-Identifier: Apache-2.0
namespace toml_edit;
import std;
import toml;

let MAX_INPUT_BYTES = 1048576;
let MAX_DEPTH = 64;
// Internal offsets are into the original input, never decoded TOML storage.
struct Statement {
    node:        i64, start: i64, end: i64, after: i64,
    value_start: i64 = -1, header: bool = false,
}

// Keep the parser's grammar, limits and semantic identities in one place. Only
// the outer statement loop is instrumented; pinned helpers decode every token.
fn scan(source: u8[:], doc: toml::Document&, statements: Statement[>..]&) -> u8[>..] {
    if source.len > MAX_INPUT_BYTES { return str("toml-edit: input exceeds 1 MiB"); }
    if !toml::valid_utf8(source) { return str("toml-edit: invalid UTF-8"); }
    toml::init(doc);
    var r = toml::Reader { source: source, error: [] };
    var current = 0;
    while r.pos < source.len && r.error.len == 0 {
        toml::horizontal(r);
        if toml::peek(r) == '#' { toml::comment(r); }
        if toml::newline(r) { continue; }
        if r.pos == source.len { break; }
        let start = r.pos;
        let header = toml::peek(r) == '[';
        var node = -1; var value_start = -1;
        if header { current = toml::header(r, doc); node = current; }
        else {
            node = toml::assignment_target(r, doc, current);
            if node >= 0 {
                toml::horizontal(r); value_start = r.pos;
                toml::value(r, doc, node);
            }
        }
        let end = r.pos;
        toml::horizontal(r);
        if toml::peek(r) == '#' { toml::comment(r); }
        if r.pos < source.len && !toml::newline(r) { toml::fail(r, "expected newline"); }
        if r.error.len > 0 { return copy(r.error); }
        statements.push(Statement { node: node, start: start, end: end, after: r.pos,
            value_start: value_start, header: header });
    }
    return copy(r.error);
}

fn path_error(path: const u8[:][:]) -> u8[>..] {
    if path.len == 0 || path.len > MAX_DEPTH { return str("toml-edit: path needs 1..64 decoded components"); }
    var bytes = 0;
    for part in path {
        if part.len > MAX_INPUT_BYTES - bytes || !toml::valid_utf8(part) { return str("toml-edit: invalid or oversized key path"); }
        bytes += part.len;
    }
    return [];
}
// Locate only table-key paths. Array indexing and edits inside inline values
// are deliberately unsupported; replacing an entire assigned value is allowed.
fn locate(doc: toml::Document&, path: const u8[:][:]) -> i64, u8[>..] {
    var node = 0;
    for part in path {
        if node < 0 { return -1, str(""); }
        if doc.nodes[node].kind != toml::Kind.Table || doc.nodes[node].state == toml::State.Sealed {
            return -1, str("toml-edit: cannot traverse an array, scalar or inline table");
        }
        node = toml::find(doc, node, part);
    }
    return node, [];
}
fn within(doc: toml::Document&, node: i64, target: i64) -> bool {
    if target < 0 { return false; }
    var current = node;
    for step in MAX_DEPTH + 1 {
        if current == target { return true; }
        if current <= 0 { return false; }
        current = doc.nodes[current].parent;
    }
    return false;
}
fn line_ending(source: u8[:]) -> const u8[:] {
    for c, i in source { if c == '\n' { return if i > 0 && source[i - 1] == '\r' { "\r\n" } else { "\n" }; } }
    return "\n";
}
fn append_bounded(out: u8[>..]&, text: u8[:]) -> bool {
    if text.len > MAX_INPUT_BYTES - out.len { return false; }
    out.append(text); return true;
}
// Reuse TOML's encoder, including DEL and control-character escapes.
fn quoted_key(out: u8[>..]&, key: u8[:]) {
    var error: u8[>..] = []; var seen: bool[0] = []; var names: toml::WriteName[0] = [];
    var writer = toml::Writer { output: out, error: error, seen: seen, names: names };
    toml::write_quoted(writer, key);
    assert(error.len == 0); // Caller has reserved a conservative <=1 MiB bound.
}

fn replacement_error(value: u8[:]) -> u8[>..] {
    if value.len == 0 || value.len > MAX_INPUT_BYTES - 4 { return str("toml-edit: empty or oversized replacement"); }
    let source = str("x = ", value);
    var doc = toml::Document { .. }; toml::init(doc);
    if !toml::valid_utf8(source) { return str("toml-edit: invalid replacement UTF-8"); }
    var r = toml::Reader { source: source, error: [] };
    let node = toml::assignment_target(r, doc, 0);
    if node >= 0 { toml::value(r, doc, node); }
    toml::horizontal(r);
    if r.error.len > 0 { return copy(r.error); }
    if r.pos != source.len { return str("toml-edit: replacement must be exactly one value without a trailing comment or newline"); }
    return [];
}

// out is replaced on success and cleared on error. Inputs are borrowed only
// during the call; the returned output owns its bytes. Source may alias out.
fn set(source: u8[:], path: const u8[:][:], value: u8[:], out: u8[>..]&) -> u8[>..] {
    var result: u8[>..] = [];
    let error = edit(source, path, value, false, result);
    out = copy(result); return copy(error);
}
// Missing keys are a successful byte-preserving no-op.
fn remove(source: u8[:], path: const u8[:][:], out: u8[>..]&) -> u8[>..] {
    var result: u8[>..] = [];
    let error = edit(source, path, "", true, result);
    out = copy(result); return copy(error);
}
fn edit(source: u8[:], path: const u8[:][:], value: u8[:], removing: bool, out: u8[>..]&) -> u8[>..] {
    let pe = path_error(path); if pe.len > 0 { return copy(pe); }
    if !removing { let ve = replacement_error(value); if ve.len > 0 { return copy(ve); } }
    var doc = toml::Document { .. }; var statements: Statement[>..] = [];
    let parse_error = scan(source, doc, statements); if parse_error.len > 0 { return copy(parse_error); }
    let target, lookup_error = locate(doc, path);
    if lookup_error.len > 0 { return copy(lookup_error); }
    if removing {
        var offset = 0;
        for statement in statements {
            if within(doc, statement.node, target) {
                out.append(source[offset..statement.start]); offset = statement.end;
            }
        }
        out.append(source[offset..]);
    } else {
        // Replacing an assignment leaves the original key, spacing and comment.
        var assigned = false;
        for statement in statements {
            if !statement.header && statement.node == target {
                if !append_bounded(out, source[..statement.value_start]) || !append_bounded(out, value) ||
                    !append_bounded(out, source[statement.end..]) { out.clear(); return str("toml-edit: output exceeds 1 MiB"); }
                assigned = true; break;
            }
        }
        if !assigned {
            if target >= 0 { return str("toml-edit: replace a complete assignment, not a declared table"); }
            // Select the closest explicit ancestor. A root dotted declaration
            // before a matching explicit header would make the result invalid.
            var parent = 0; var anchor = 0; var consumed = 0;
            for part, i in path[..path.len - 1] {
                parent = toml::find(doc, parent, part);
                if parent < 0 { break; }
                for statement in statements {
                    if statement.header && statement.node == parent { anchor = statement.after; consumed = i + 1; break; }
                }
            }
            var insertion: u8[>..] = [];
            let newline = line_ending(source);
            if anchor > 0 && source[anchor - 1] != '\n' { insertion.append(newline); }
            for part, i in path[consumed..] {
                if i > 0 && !append_bounded(insertion, ".") { return str("toml-edit: rendered path exceeds 1 MiB"); }
                // Worst-case TOML escaping is six bytes per input byte.
                if insertion.len > MAX_INPUT_BYTES - 2 || part.len > (MAX_INPUT_BYTES - insertion.len - 2) / 6 { return str("toml-edit: rendered path exceeds 1 MiB"); }
                quoted_key(insertion, part);
            }
            if !append_bounded(insertion, " = ") || !append_bounded(insertion, value) || !append_bounded(insertion, newline) ||
                !append_bounded(out, source[..anchor]) || !append_bounded(out, insertion) || !append_bounded(out, source[anchor..]) {
                out.clear(); return str("toml-edit: output exceeds 1 MiB");
            }
        }
    }
    // Combined key/value depth and declaration-state rules are authoritative.
    let final_error = toml::parse_into(out, doc);
    if final_error.len > 0 { out.clear(); return copy(final_error); }
    return [];
}

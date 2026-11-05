// SPDX-License-Identifier: Apache-2.0
namespace toml_source;
import toml;
import std;
import json;

// Builder appends are compiler built-ins; consumer str/copy overloads must
// never turn a validation failure into an empty (successful) diagnostic.
fn owned(bytes: const u8[:]) -> u8[>..] {
    var output: u8[>..] = []; output.append(bytes); return output;
}
const MAX_BYTES:      i64 = 1048576;
const MAX_STATEMENTS: i64 = 65536;
const MAX_PATH_BYTES: i64 = 4096;
const MAX_PATH_DEPTH: i64 = 64;
// Policy stays in this engine; the companion wrapper only adapts ownership.
enum Profile { Source, LegacyEditor }
fn legacy(profile: Profile) -> bool { return profile == Profile.LegacyEditor; }
// Internal, valid only during the call that parsed the original source.
struct Statement {
    node:  i64, context: i64, header: bool,
    start: i64, value_start: i64, end: i64, line_end: i64,
}
// Reuse the parser's grammar and declaration rules, recording source offsets
// before decoded strings enter its arena. Node spans are NOT source positions.
fn index(source: const u8[:], doc: toml::Document&, statements: Statement[>..]&, version: toml::Version, profile: Profile = Profile.Source) -> u8[>..] {
    statements.clear(); toml::init(doc);
    if source.len > MAX_BYTES { return owned(if legacy(profile) { "toml-edit: input exceeds 1 MiB" } else { "toml source: input exceeds 1 MiB" }); }
    if !toml::valid_utf8(source) { return owned(if legacy(profile) { "toml-edit: invalid UTF-8" } else { "toml source: invalid UTF-8" }); }
    var r = toml::Reader { source: source, version: version, error: [] };
    var current = 0;
    while r.pos < source.len && r.error.len == 0 {
        toml::horizontal(r);
        if toml::peek(r) == '#' { toml::comment(r); }
        if toml::newline(r) { continue; }
        if r.pos == source.len { break; }
        let start = r.pos;
        let header = toml::peek(r) == '[';
        var node = -1; var value_start = start;
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
        if r.error.len > 0 { return owned(r.error); }
        if statements.len == MAX_STATEMENTS { return owned("toml source: statement limit exceeded"); }
        statements.push(Statement { node: node, context: current, header: header,
            start: start, value_start: value_start, end: end, line_end: r.pos });
    }
    return owned(r.error);
}
fn check_path(path: const (const u8[:])[:], profile: Profile) -> u8[>..] {
    if path.len == 0 || path.len > MAX_PATH_DEPTH { return owned(if legacy(profile) { "toml-edit: path needs 1..64 decoded components" } else { "toml source: path needs 1..64 decoded key segments" }); }
    let limit = if legacy(profile) { MAX_BYTES } else { MAX_PATH_BYTES };
    var bytes = 0;
    for part in path {
        if part.len > limit - bytes { return owned(if legacy(profile) { "toml-edit: invalid or oversized key path" } else { "toml source: path exceeds 4096 bytes" }); }
        if !toml::valid_utf8(part) { return owned(if legacy(profile) { "toml-edit: invalid or oversized key path" } else { "toml source: invalid UTF-8 key" }); }
        bytes += part.len;
    }
    return [];
}
// Each lookup walks a different sibling list along a decoded path, avoiding
// unmetered hash probes. The document is freshly built, never caller-mutated.
fn child(doc: toml::Document&, parent: i64, name: const u8[:]) -> i64 {
    if parent < 0 || doc.nodes[parent].kind != toml::Kind.Table { return -1; }
    var id = doc.nodes[parent].first;
    while id >= 0 {
        if toml::key(doc, id) == name { return id; }
        id = doc.nodes[id].next;
    }
    return -1;
}
fn resolve(doc: toml::Document&, path: const (const u8[:])[:], profile: Profile) -> i64, const u8[:] {
    var id = 0;
    for part in path {
        if id < 0 { return -1, ""; }
        if legacy(profile) && (doc.nodes[id].kind != toml::Kind.Table || doc.nodes[id].state == toml::State.Sealed) {
            return -1, "toml-edit: cannot traverse an array, scalar or inline table";
        }
        id = child(doc, id, part);
    }
    return id, "";
}
fn check_value(value: const u8[:], version: toml::Version, profile: Profile) -> u8[>..] {
    if legacy(profile) {
        if value.len == 0 || value.len > MAX_BYTES - 4 { return owned("toml-edit: empty or oversized replacement"); }
        // Parse only the first value: a malformed suffix must not mask the
        // legacy strict-suffix error. Keep this exact four-byte wrapper.
        var input = owned("x = "); input.append(value);
        var doc = toml::Document { .. }; toml::init(doc);
        if !toml::valid_utf8(input) { return owned("toml-edit: invalid replacement UTF-8"); }
        var r = toml::Reader { source: input, version: version, error: [] };
        let node = toml::assignment_target(r, doc, 0);
        if node >= 0 { toml::value(r, doc, node); }
        toml::horizontal(r);
        if r.error.len > 0 { return owned(r.error); }
        if r.pos != input.len { return owned("toml-edit: replacement must be exactly one value without a trailing comment or newline"); }
        return [];
    }
    if value.len > MAX_BYTES - 4 { return owned("toml source: replacement value exceeds limit"); }
    var input = owned("v = "); input.append(value);
    var doc = toml::Document { .. }; var statements: Statement[>..] = [];
    let error = index(input, doc, statements, version);
    if error.len > 0 { return error; }
    if statements.len != 1 || statements[0].header { return owned("toml source: expected exactly one TOML value"); }
    return [];
}
fn newline(source: const u8[:]) -> const u8[:] {
    for byte, at in source {
        if byte == '\n' { return if at > 0 && source[at - 1] == '\r' { "\r\n" } else { "\n" }; }
    }
    return "\n";
}
// Terminal validation: source node IDs and arena views are no longer read.
fn validate_output(output: const u8[:], doc: toml::Document&, version: toml::Version) -> u8[>..] {
    return toml::parse_into(output, doc, version);
}
fn splice(source: const u8[:], start: i64, end: i64, replacement: const u8[:], doc: toml::Document&, version: toml::Version, profile: Profile) -> u8[>..], u8[>..] {
    let kept = source.len - (end - start);
    if replacement.len > MAX_BYTES - kept { return [], owned(if legacy(profile) { "toml-edit: output exceeds 1 MiB" } else { "toml source: output exceeds 1 MiB" }); }
    var output: u8[>..] = [];
    output.append(source[..start]); output.append(replacement); output.append(source[end..]);
    let error = validate_output(output, doc, version);
    if error.len > 0 { return [], owned(error); }
    return output, [];
}
// JSON and TOML share escapes except that DEL must also be escaped in TOML.
fn quoted_key(output: u8[>..]&, name: const u8[:], profile: Profile) {
    if legacy(profile) {
        var error: u8[>..] = []; var seen: bool[0] = []; var names: toml::WriteName[0] = [];
        var writer = toml::Writer { output: output, error: error, seen: seen, names: names };
        toml::write_quoted(writer, name);
        assert(error.len == 0); // Caller reserved the conservative encoded bound.
        return;
    }
    if find(name, "\x7f") < 0 { json::format_string(output, name); return; }
    var quoted: u8[>..] = [];
    json::format_string(quoted, name);
    for byte in quoted {
        if byte == 127 { output.append("\\u007f"); } else { output.push(byte); }
    }
}
// Insertion metadata is shared by single edits and snapshot batches.
fn body_ends(doc: toml::Document&, statements: const Statement[:], profile: Profile) -> i64[>..] {
    var ends: i64[>..] = [];
    for node in doc.nodes { ends.push(-1); }
    ends[0] = 0;
    for statement in statements {
        if !legacy(profile) || statement.header { ends[statement.context] = statement.line_end; }
    }
    return ends;
}
fn insertion_position(doc: toml::Document&, ends: const i64[:], path: const (const u8[:])[:]) -> i64, i64, const u8[:] {
    var parent = 0; var context = 0; var depth = 0;
    for part, i in path[..path.len - 1] {
        let next = child(doc, parent, part);
        if next < 0 { break; }
        if doc.nodes[next].kind != toml::Kind.Table { return 0, 0, "toml source: path crosses a non-table"; }
        if doc.nodes[next].state == toml::State.Sealed || doc.nodes[next].state == toml::State.Inline {
            return 0, 0, "toml source: editing inside inline tables is unsupported";
        }
        parent = next;
        if ends[parent] >= 0 { context = parent; depth = i + 1; }
    }
    return ends[context], depth, "";
}
fn insertion_text(path: const (const u8[:])[:], value: const u8[:], depth: i64, eol: const u8[:], leading: bool, profile: Profile) -> u8[>..], u8[>..] {
    var addition: u8[>..] = [];
    if leading { addition.append(eol); }
    for part, i in path[depth..] {
        if i > 0 { addition.push('.'); }
        if legacy(profile) && (addition.len > MAX_BYTES - 2 || part.len > (MAX_BYTES - addition.len - 2) / 6) {
            return [], owned("toml-edit: rendered path exceeds 1 MiB");
        }
        quoted_key(addition, part, profile);
    }
    if legacy(profile) && (addition.len > MAX_BYTES - 3 || value.len > MAX_BYTES - addition.len - 3 ||
        eol.len > MAX_BYTES - addition.len - 3 - value.len) { return [], owned("toml-edit: output exceeds 1 MiB"); }
    addition.append(" = "); addition.append(value); addition.append(eol);
    return addition, [];
}
// Replace a directly assigned value or insert a new member. Existing bytes
// outside the splice, including comments and source spellings, are copied.
fn put_impl(source: const u8[:], path: const u8[:][:], value: const u8[:], version: toml::Version, profile: Profile) -> u8[>..], u8[>..] {
    let path_error = check_path(path, profile);
    if path_error.len > 0 { return [], owned(path_error); }
    let value_error = check_value(value, version, profile);
    if value_error.len > 0 { return [], owned(value_error); }
    var doc = toml::Document { .. }; var statements: Statement[>..] = [];
    let error = index(source, doc, statements, version, profile);
    if error.len > 0 { return [], owned(error); }
    let target, lookup_error = resolve(doc, path, profile);
    if lookup_error.len > 0 { return [], owned(lookup_error); }
    if target >= 0 {
        for statement in statements {
            if !statement.header && statement.node == target {
                return splice(source, statement.value_start, statement.end, value, doc, version, profile);
            }
        }
        return [], owned(if legacy(profile) { "toml-edit: replace a complete assignment, not a declared table" } else { "toml source: value is not a directly assigned source span" });
    }
    let ends = body_ends(doc, statements, profile);
    let at, depth, position_error = insertion_position(doc, ends, path);
    if position_error.len > 0 { return [], owned(position_error); }
    let addition, addition_error = insertion_text(path, value, depth, newline(source), at > 0 && source[at - 1] != '\n', profile);
    if addition_error.len > 0 { return [], owned(addition_error); }
    return splice(source, at, at, addition, doc, version, profile);
}
// Remove assignment/header token spans belonging to a named subtree. Leading
// and trailing comments, indentation, and surrounding newlines are retained.
fn remove_impl(source: const u8[:], path: const u8[:][:], version: toml::Version, profile: Profile) -> u8[>..], u8[>..] {
    let path_error = check_path(path, profile);
    if path_error.len > 0 { return [], owned(path_error); }
    var doc = toml::Document { .. }; var statements: Statement[>..] = [];
    let error = index(source, doc, statements, version, profile);
    if error.len > 0 { return [], owned(error); }
    let target, lookup_error = resolve(doc, path, profile);
    if lookup_error.len > 0 { return [], owned(lookup_error); }
    if target < 0 {
        var output = owned(source);
        if legacy(profile) {
            let error = validate_output(output, doc, version);
            if error.len > 0 { return [], owned(error); }
        }
        return output, [];
    }
    var selected: bool[>..] = [];
    for node, id in doc.nodes {
        selected.push(id == target || (node.parent >= 0 && selected[node.parent]));
    }
    var output: u8[>..] = []; var copied = 0; var edits = 0;
    for statement in statements {
        if !selected[statement.node] { continue; }
        output.append(source[copied..statement.start]); copied = statement.end; edits++;
    }
    if edits == 0 { return [], owned("toml source: value is inside an unsupported inline span"); }
    output.append(source[copied..]);
    let output_error = validate_output(output, doc, version);
    if output_error.len > 0 { return [], owned(output_error); }
    return output, [];
}

// Default source profile: preserve its API, version selection and policies.
fn put(source: const u8[:], path: const u8[:][:], value: const u8[:], version: toml::Version = toml::Version.V1_0) -> u8[>..], u8[>..] {
    return put_impl(source, path, value, version, Profile.Source);
}
fn remove(source: const u8[:], path: const u8[:][:], version: toml::Version = toml::Version.V1_0) -> u8[>..], u8[>..] {
    return remove_impl(source, path, version, Profile.Source);
}
// Supported companion compatibility profile, fixed to strict TOML 1.0.
fn legacy_set(source: const u8[:], path: const u8[:][:], value: const u8[:]) -> u8[>..], u8[>..] {
    return put_impl(source, path, value, toml::Version.V1_0, Profile.LegacyEditor);
}
fn legacy_remove(source: const u8[:], path: const u8[:][:]) -> u8[>..], u8[>..] {
    return remove_impl(source, path, toml::Version.V1_0, Profile.LegacyEditor);
}

// Requests borrow their data for apply; no views escape into the result.
enum Edit {
    Put { path: const (const u8[:])[:], value: const u8[:] },
    Remove { path: const (const u8[:])[:] },
}
const MAX_BATCH_EDITS: i64 = 64;
struct BatchSpan { start: i64, end: i64, request: i64, depth: i64 = -1 }
fn batch_path(edit: Edit) -> const (const u8[:])[:] {
    match edit { Put p => p.path, Remove r => r.path }
}
fn batch_value(edit: Edit) -> const u8[:] {
    match edit { Put p => p.value, Remove r => "" }
}
fn batch_put(edit: Edit) -> bool {
    match edit { Put p => true, Remove r => false }
}
fn batch_error(request: i64, error: const u8[:]) -> u8[>..] {
    var output = owned("toml source: batch edit ");
    if request >= 10 { output.push('0' + (request / 10) as u8); }
    output.push('0' + (request % 10) as u8);
    output.append(": "); output.append(error); return output;
}
fn batch_overlap(a: const (const u8[:])[:], b: const (const u8[:])[:]) -> bool {
    for i in min(a.len, b.len) { if a[i] != b[i] { return false; } }
    return true;
}
fn batch_append(output: u8[>..]&, bytes: const u8[:]) -> bool {
    if bytes.len > MAX_BYTES - output.len { return false; }
    output.append(bytes); return true;
}
// Original-snapshot selectors; no partial output is returned on any failure.
fn apply(source: const u8[:], edits: const Edit[:], version: toml::Version = toml::Version.V1_0) -> u8[>..], u8[>..] {
    if edits.len > MAX_BATCH_EDITS { return [], owned("toml source: batch exceeds 64 edits"); }
    var bytes = 0;
    for edit, i in edits {
        let path = batch_path(edit);
        let path_error = check_path(path, Profile.Source);
        if path_error.len > 0 { return [], batch_error(i, path_error); }
        for part in path {
            if part.len > MAX_BYTES - bytes { return [], owned("toml source: batch request exceeds 1 MiB"); }
            bytes += part.len;
        }
        let value = batch_value(edit);
        if value.len > MAX_BYTES - bytes { return [], owned("toml source: batch request exceeds 1 MiB"); }
        bytes += value.len;
        for j in i {
            if batch_overlap(path, batch_path(edits[j])) { return [], batch_error(i, "overlapping batch paths"); }
        }
    }
    for edit, i in edits {
        if batch_put(edit) {
            let error = check_value(batch_value(edit), version, Profile.Source);
            if error.len > 0 { return [], batch_error(i, error); }
        }
    }
    var doc = toml::Document { .. }; var statements: Statement[>..] = [];
    let error = index(source, doc, statements, version);
    if error.len > 0 { return [], owned(error); }
    if edits.len == 0 { return owned(source), []; }
    var assignment: i64[>..] = []; var owner: i64[>..] = [];
    for node in doc.nodes { assignment.push(-1); owner.push(-1); }
    let ends = body_ends(doc, statements, Profile.Source);
    var targets: i64[>..] = []; var removed: i64[>..] = [];
    for edit, i in edits {
        let target, lookup_error = resolve(doc, batch_path(edit), Profile.Source);
        if lookup_error.len > 0 { return [], batch_error(i, lookup_error); }
        targets.push(target); removed.push(0);
        if !batch_put(edit) && target >= 0 { owner[target] = i; }
    }
    for node, id in doc.nodes {
        if node.parent >= 0 && owner[node.parent] >= 0 { owner[id] = owner[node.parent]; }
    }
    var spans: BatchSpan[>..] = [];
    for statement, i in statements {
        if !statement.header { assignment[statement.node] = i; }
        let request = owner[statement.node];
        if request >= 0 {
            spans.push(BatchSpan { start: statement.start, end: statement.end, request: request });
            removed[request]++;
        }
    }
    for edit, i in edits {
        let target = targets[i];
        if !batch_put(edit) {
            if target >= 0 && removed[i] == 0 { return [], batch_error(i, "toml source: value is inside an unsupported inline span"); }
        } else if target >= 0 {
            let slot = assignment[target];
            if slot < 0 { return [], batch_error(i, "toml source: value is not a directly assigned source span"); }
            let statement = statements[slot];
            spans.push(BatchSpan { start: statement.value_start, end: statement.end, request: i });
        } else {
            let at, depth, error = insertion_position(doc, ends, batch_path(edit));
            if error.len > 0 { return [], batch_error(i, error); }
            spans.push(BatchSpan { start: at, end: at, request: i, depth: depth });
        }
    }
    if spans.len == 0 { return owned(source), []; }
    sort(spans) { a, b => a.start < b.start || (a.start == b.start &&
        (a.end < b.end || (a.end == b.end && a.request < b.request))) };
    var output: u8[>..] = []; var copied = 0;
    let eol = newline(source);
    for span in spans {
        if span.start < copied { return [], owned("toml source: overlapping batch spans"); }
        if !batch_append(output, source[copied..span.start]) { return [], owned("toml source: output exceeds 1 MiB"); }
        let edit = edits[span.request];
        if batch_put(edit) {
            if span.start == span.end {
                let addition, error = insertion_text(batch_path(edit), batch_value(edit), span.depth, eol,
                    output.len > 0 && output[output.len - 1] != '\n', Profile.Source);
                if error.len > 0 { return [], batch_error(span.request, error); }
                if !batch_append(output, addition) { return [], owned("toml source: output exceeds 1 MiB"); }
            } else if !batch_append(output, batch_value(edit)) { return [], owned("toml source: output exceeds 1 MiB"); }
        }
        copied = span.end;
    }
    if !batch_append(output, source[copied..]) { return [], owned("toml source: output exceeds 1 MiB"); }
    let output_error = validate_output(output, doc, version);
    if output_error.len > 0 { return [], owned(output_error); }
    return output, [];
}

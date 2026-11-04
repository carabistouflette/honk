// SPDX-License-Identifier: Apache-2.0
namespace toml;
import std;

// Inputs are borrowed only for the call. Strings, keys and dates are copied.
// Containers start empty; use their returned IDs to populate them.
enum Input {
    Table, Array, String { value: const u8[:] }, Integer { value: i64 },
    Float { value: f64 }, Boolean { value: bool }, DateTime { kind: Kind, value: const u8[:] },
}

// Reset all storage. IDs and borrowed views from the previous document expire.
fn init(doc: Document&) {
    doc.indexed = 0; doc.nodes.clear(); doc.bytes.clear(); doc.index.clear();
    doc.nodes.push(Node { state: State.Explicit, .. });
}

fn input_kind(input: Input) -> Kind {
    match input {
        Table => Kind.Table, Array => Kind.Array, String s => Kind.String,
        Integer n => Kind.Integer, Float n => Kind.Float, Boolean b => Kind.Boolean,
        DateTime d => d.kind,
    }
}
fn input_text(input: Input) -> const u8[:] {
    match input { String s => s.value, DateTime d => d.value, _ => "" }
}
fn date_kind(kind: Kind) -> bool {
    kind == Kind.OffsetDateTime || kind == Kind.LocalDateTime || kind == Kind.LocalDate || kind == Kind.LocalTime
}
fn check_input(doc: Document&, input: Input, key_bytes: i64 = 0) -> u8[>..] {
    let value = input_text(input);
    if key_bytes < 0 || doc.bytes.len > MAX_INPUT_BYTES || key_bytes > MAX_INPUT_BYTES - doc.bytes.len ||
            value.len > MAX_INPUT_BYTES - doc.bytes.len - key_bytes { return str("toml: document byte limit exceeded"); }
    match input {
        String s => { if !valid_utf8(s.value) { return str("toml: invalid UTF-8 string"); } },
        DateTime d => {
            if d.value.len > MAX_NUMBER_BYTES { return str("toml: date/time exceeds 128 bytes"); }
            let kind, ok = datetime(d.value, Version.V1_1);
            if !date_kind(d.kind) || !ok || kind != d.kind { return str("toml: invalid date/time input"); }
        },
        _ => {},
    }
    return [];
}
// Mutation expects a document from init/parse_into and unmodified internals.
// A failure may leave a partial document; discard or reinitialize it.
fn check_live(doc: Document&, id: i64) -> u8[>..] {
    if doc.nodes.len == 0 || doc.nodes.len > MAX_NODES || doc.bytes.len > MAX_INPUT_BYTES ||
            id < 0 || id >= doc.nodes.len { return str("toml: invalid document or node ID"); }
    if doc.nodes[0].kind != Kind.Table || doc.nodes[0].parent != -1 || doc.nodes[0].depth != 0 {
        return str("toml: invalid document root");
    }
    var current = id;
    var depth = doc.nodes[id].depth;
    if depth < 0 || depth > MAX_DEPTH { return str("toml: invalid node depth"); }
    for step in MAX_DEPTH + 1 {
        if current == 0 { return if depth == 0 { str("") } else { str("toml: invalid node depth") }; }
        let parent = doc.nodes[current].parent;
        if parent < 0 || parent >= doc.nodes.len || depth <= 0 || doc.nodes[parent].depth != depth - 1 ||
                (doc.nodes[parent].kind != Kind.Table && doc.nodes[parent].kind != Kind.Array) {
            return str("toml: node is retired or has invalid parent");
        }
        current = parent; depth--;
    }
    return str("toml: nesting limit exceeded");
}
fn store_input(doc: Document&, id: i64, input: Input) {
    let value = input_text(input);
    let start = doc.bytes.len;
    doc.bytes.append(value);
    doc.nodes[id].kind = input_kind(input);
    // Declaration state describes source declarations, not semantic edit rights.
    doc.nodes[id].state = if doc.nodes[id].kind == Kind.Table { State.Explicit } else { State.Sealed };
    doc.nodes[id].text = Span { start: start, len: value.len };
    doc.nodes[id].integer = 0; doc.nodes[id].number = 0.0; doc.nodes[id].boolean = false;
    match input {
        Integer n => { doc.nodes[id].integer = n.value; },
        Float n => { doc.nodes[id].number = n.value; },
        Boolean b => { doc.nodes[id].boolean = b.value; },
        _ => {},
    }
}
recursive fn retire(doc: Document&, id: i64, depth: i64, work: i64&) -> bool {
    work++;
    if id <= 0 || id >= doc.nodes.len || depth > MAX_DEPTH || work > MAX_NODES || doc.nodes[id].parent == -2 { return false; }
    var child = doc.nodes[id].first;
    while child != -1 {
        if child <= 0 || child >= doc.nodes.len || doc.nodes[child].parent != id { return false; }
        let next = doc.nodes[child].next;
        if !retire(doc, child, depth + 1, work) { return false; }
        child = next;
    }
    doc.nodes[id].parent = -2;
    doc.nodes[id].first = -1; doc.nodes[id].last = -1; doc.nodes[id].next = -1; doc.nodes[id].count = 0;
    return true;
}
fn retire_children(doc: Document&, id: i64) -> u8[>..] {
    var child = doc.nodes[id].first;
    var work = 0;
    while child != -1 {
        if child <= 0 || child >= doc.nodes.len || doc.nodes[child].parent != id { return str("toml: invalid child link"); }
        let next = doc.nodes[child].next;
        if !retire(doc, child, 1, work) { return str("toml: invalid subtree"); }
        child = next;
    }
    doc.nodes[id].first = -1; doc.nodes[id].last = -1; doc.nodes[id].count = 0;
    return [];
}

// Replace a value in place, preserving its ID, key and sibling position.
fn set(doc: Document&, id: i64, input: Input) -> u8[>..] {
    let live_error = check_live(doc, id); if live_error.len > 0 { return copy(live_error); }
    if id == 0 && input_kind(input) != Kind.Table { return str("toml: root must be a table"); }
    let input_error = check_input(doc, input); if input_error.len > 0 { return copy(input_error); }
    let retired_error = retire_children(doc, id); if retired_error.len > 0 { return copy(retired_error); }
    store_input(doc, id, input);
    return [];
}

// Insert or replace one decoded key. Dots in key are literal.
fn put(doc: Document&, table: i64, name: const u8[:], input: Input) -> i64, u8[>..] {
    let live_error = check_live(doc, table); if live_error.len > 0 { return -1, copy(live_error); }
    if doc.nodes[table].kind != Kind.Table { return -1, str("toml: put requires a table"); }
    if name.len > MAX_INPUT_BYTES || !valid_utf8(name) { return -1, str("toml: invalid UTF-8 key or key limit exceeded"); }
    var r = Reader { source: "", error: [] };
    // Copy only after finding an existing entry; replacing does not grow key storage.
    let h = key_hash(table, name);
    var found = -1;
    if doc.index.len > 0 {
        var slot = (h & ((doc.index.len - 1) as u64)) as i64;
        loop {
            r.work++;
            if r.work > MAX_KEY_WORK { return -1, str("toml: key lookup work limit exceeded"); }
            let id = doc.index[slot];
            if id < 0 { break; }
            if id >= doc.nodes.len { return -1, str("toml: invalid key index"); }
            let n = doc.nodes[id];
            if n.parent == table && n.key_hash == h && n.key.len == name.len {
                r.work += name.len;
                if r.work > MAX_KEY_WORK { return -1, str("toml: key lookup work limit exceeded"); }
                if doc.bytes[n.key.start..n.key.start + n.key.len] == name { found = id; break; }
            }
            slot = (slot + 1) & (doc.index.len - 1);
        }
    }
    if found >= 0 {
        let error = set(doc, found, input);
        return if error.len == 0 { found } else { -1 }, copy(error);
    }
    let input_error = check_input(doc, input, name.len); if input_error.len > 0 { return -1, copy(input_error); }
    let start = doc.bytes.len; doc.bytes.append(name);
    let id = add(r, doc, table, Span { start: start, len: name.len }, input_kind(input), State.Sealed);
    if r.error.len > 0 { return -1, copy(r.error); }
    store_input(doc, id, input);
    return id, [];
}
fn push(doc: Document&, array: i64, input: Input) -> i64, u8[>..] {
    let live_error = check_live(doc, array); if live_error.len > 0 { return -1, copy(live_error); }
    if doc.nodes[array].kind != Kind.Array { return -1, str("toml: push requires an array"); }
    let input_error = check_input(doc, input); if input_error.len > 0 { return -1, copy(input_error); }
    var r = Reader { source: "", error: [] };
    let id = add(r, doc, array, Span { .. }, input_kind(input), State.Sealed);
    if r.error.len > 0 { return -1, copy(r.error); }
    store_input(doc, id, input);
    return id, [];
}
fn unlink(doc: Document&, parent: i64, id: i64, previous: i64) -> u8[>..] {
    let next = doc.nodes[id].next;
    if previous < 0 { doc.nodes[parent].first = next; } else { doc.nodes[previous].next = next; }
    if doc.nodes[parent].last == id { doc.nodes[parent].last = previous; }
    doc.nodes[parent].count--;
    var work = 0;
    if !retire(doc, id, 0, work) { return str("toml: invalid subtree"); }
    return [];
}
fn remove(doc: Document&, table: i64, name: const u8[:]) -> bool, u8[>..] {
    let live_error = check_live(doc, table); if live_error.len > 0 { return false, copy(live_error); }
    if doc.nodes[table].kind != Kind.Table { return false, str("toml: remove requires a table"); }
    if name.len > MAX_INPUT_BYTES || !valid_utf8(name) { return false, str("toml: invalid UTF-8 key or key limit exceeded"); }
    var child = doc.nodes[table].first; var previous = -1; var work = 0; var count = 0;
    while child != -1 {
        count++;
        if count > MAX_NODES || child <= 0 || child >= doc.nodes.len || doc.nodes[child].parent != table { return false, str("toml: invalid child link"); }
        let n = doc.nodes[child];
        if n.key.len == name.len {
            work += name.len;
            if work > MAX_KEY_WORK { return false, str("toml: key lookup work limit exceeded"); }
            if doc.bytes[n.key.start..n.key.start + n.key.len] == name {
                let error = unlink(doc, table, child, previous);
                return error.len == 0, copy(error);
            }
        }
        previous = child; child = n.next;
    }
    return false, [];
}
fn erase(doc: Document&, array: i64, ordinal: i64) -> bool, u8[>..] {
    let live_error = check_live(doc, array); if live_error.len > 0 { return false, copy(live_error); }
    if doc.nodes[array].kind != Kind.Array { return false, str("toml: erase requires an array"); }
    if ordinal < 0 || ordinal >= doc.nodes[array].count { return false, []; }
    var child = doc.nodes[array].first; var previous = -1; var at = 0;
    while child != -1 {
        if at > MAX_NODES || child <= 0 || child >= doc.nodes.len || doc.nodes[child].parent != array { return false, str("toml: invalid child link"); }
        if at == ordinal {
            let error = unlink(doc, array, child, previous);
            return error.len == 0, copy(error);
        }
        previous = child; child = doc.nodes[child].next; at++;
    }
    return false, str("toml: invalid array count");
}

// Reclaim retired nodes/bytes by a semantic round trip. All IDs/views expire.
// Serialization can exceed the parser's 1 MiB cap; that failure leaves doc intact.
fn compact(doc: Document&) -> u8[>..] {
    let source, error = serialize(doc);
    if error.len > 0 { return copy(error); }
    if source.len > MAX_INPUT_BYTES { return str("toml: compacted input exceeds 1 MiB"); }
    return parse_into(source, doc);
}

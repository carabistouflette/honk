// SPDX-License-Identifier: Apache-2.0
namespace toml;
import std;
import vendor.text;
import document;
import writer;

enum Version { V1_0, V1_1 }
enum Kind { Table, Array, String, Integer, Float, Boolean, OffsetDateTime, LocalDateTime, LocalDate, LocalTime }
// Declaration state is distinct from value kind. Inline tables are sealed recursively.
enum State { Implicit, Dotted, Explicit, Inline, Sealed, ArrayOfTables }
struct Span { start: i64 = 0, len: i64 = 0 }
struct Node {
    kind:    Kind                            = Kind.Table, state: State = State.Implicit,
    parent:  i64                             = -1, first: i64 = -1, last: i64 = -1, next: i64 = -1,
    count:   i64                             = 0, depth: i64 = 0,
    key:     Span, text: Span, key_hash: u64 = 0,
    integer: i64                             = 0, number: f64 = 0.0, boolean: bool = false,
}
root struct Document { indexed: i64 = 0, nodes: Node[>..], bytes: u8[>..], index: i64[>..] }
struct Reader { source: const u8[:], version: Version = Version.V1_0, pos: i64 = 0, work: i64 = 0, error: u8[>..] }
let MAX_INPUT_BYTES = 1048576;
let MAX_NODES = 65536;
let MAX_DEPTH = 64;
let MAX_NUMBER_BYTES = 128;
let MAX_KEY_WORK = 16777216;

// Replaces the destination. A failure leaves a partial document: discard it.
fn parse_into(source: u8[:], doc: Document&, version: Version = Version.V1_0) -> u8[>..] {
    doc.indexed = 0; doc.nodes.clear(); doc.bytes.clear(); doc.index.clear();
    if source.len > MAX_INPUT_BYTES { return str("toml: input exceeds 1 MiB at byte 0"); }
    if !valid_utf8(source) { return str("toml: invalid UTF-8 at byte 0"); }
    var r = Reader { source: source, version: version, error: [] };
    doc.nodes.push(Node { state: State.Explicit, .. });
    var current = 0;
    while r.pos < source.len && r.error.len == 0 {
        horizontal(r);
        if peek(r) == '#' { comment(r); }
        if newline(r) { continue; }
        if r.pos == source.len { break; }
        if peek(r) == '[' { current = header(r, doc); }
        else { assignment(r, doc, current); }
        horizontal(r);
        if peek(r) == '#' { comment(r); }
        if r.pos < source.len && !newline(r) { fail(r, "expected newline"); }
    }
    return copy(r.error);
}

// Look up one decoded key (dots are literal). Returns -1 for missing/wrong parent.
fn find(doc: Document&, parent: i64, key: u8[:]) -> i64 {
    if parent < 0 || parent >= doc.nodes.len || doc.nodes[parent].kind != Kind.Table || doc.index.len == 0 { return -1; }
    let h = key_hash(parent, key);
    var slot = (h & ((doc.index.len - 1) as u64)) as i64;
    loop {
        let id = doc.index[slot];
        if id < 0 { return -1; }
        let n = doc.nodes[id];
        if n.parent == parent && n.key_hash == h && doc.bytes[n.key.start..n.key.start + n.key.len] == key { return id; }
        slot = (slot + 1) & (doc.index.len - 1);
    }
}
fn text(doc: Document&, id: i64) -> u8[:] {
    assert(id >= 0 && id < doc.nodes.len);
    let s = doc.nodes[id].text;
    return doc.bytes[s.start..s.start + s.len];
}
fn key(doc: Document&, id: i64) -> u8[:] {
    assert(id >= 0 && id < doc.nodes.len);
    let s = doc.nodes[id].key;
    return doc.bytes[s.start..s.start + s.len];
}
fn key_hash(parent: i64, s: u8[:]) -> u64 { hash_combine(hash(parent), hash(s)) }
fn fail(r: Reader&, message: u8[:]) {
    if r.error.len > 0 { return; }
    var line = 1; var column = 1;
    for c in r.source[..r.pos] { if c == '\n' { line++; column = 1; } else { column++; } }
    r.error = str("toml: ", message, " at byte ", r.pos, " (line ", line, ", byte column ", column, ")");
}
fn peek(r: Reader&) -> u8 { if r.pos < r.source.len { r.source[r.pos] } else { 0 } }
fn horizontal(r: Reader&) { while r.pos < r.source.len && (peek(r) == ' ' || peek(r) == '\t') { r.pos++; } }
fn newline(r: Reader&) -> bool {
    if r.pos >= r.source.len { return false; }
    if peek(r) == '\n' { r.pos++; return true; }
    if peek(r) == '\r' {
        if r.pos + 1 < r.source.len && r.source[r.pos + 1] == '\n' { r.pos += 2; return true; }
        fail(r, "bare carriage return");
    }
    return false;
}
fn comment(r: Reader&) {
    while r.pos < r.source.len && peek(r) != '\n' && peek(r) != '\r' {
        let c = peek(r);
        if (c < 32 && c != '\t') || c == 127 { fail(r, "control character in comment"); return; }
        r.pos++;
    }
}
fn whitespace(r: Reader&) {
    loop {
        horizontal(r);
        if peek(r) == '#' { comment(r); }
        if r.error.len > 0 || !newline(r) { return; }
    }
}
fn expect(r: Reader&, c: u8) -> bool {
    if r.pos >= r.source.len || peek(r) != c { fail(r, "unexpected delimiter"); return false; }
    r.pos++; return true;
}
fn lookup(r: Reader&, doc: Document&, parent: i64, s: Span) -> i64 {
    if doc.index.len == 0 { return -1; }
    let h = key_hash(parent, doc.bytes[s.start..s.start + s.len]);
    var slot = (h & ((doc.index.len - 1) as u64)) as i64;
    loop {
        r.work++;
        if r.work > MAX_KEY_WORK { fail(r, "key lookup work limit exceeded"); return -1; }
        let id = doc.index[slot];
        if id < 0 { return -1; }
        let n = doc.nodes[id];
        if n.parent == parent && n.key_hash == h && n.key.len == s.len {
            r.work += s.len;
            if r.work > MAX_KEY_WORK { fail(r, "key lookup work limit exceeded"); return -1; }
            if doc.bytes[n.key.start..n.key.start + n.key.len] == doc.bytes[s.start..s.start + s.len] { return id; }
        }
        slot = (slot + 1) & (doc.index.len - 1);
    }
}
fn index_node(r: Reader&, doc: Document&, id: i64) {
    // Size by named entries, not array elements. Rehash only existing index
    // entries so a large preceding array does not amplify table growth work.
    doc.indexed++;
    if doc.index.len < doc.indexed * 2 {
        let previous = copy(doc.index);
        let size = max(16, doc.index.len * 2);
        doc.index.clear();
        for i in size { doc.index.push(-1); }
        for old in previous {
            if old >= 0 {
                place(r, doc, old);
                if r.error.len > 0 { return; }
            }
        }
    }
    place(r, doc, id);
}

fn place(r: Reader&, doc: Document&, id: i64) {
    var slot = (doc.nodes[id].key_hash & ((doc.index.len - 1) as u64)) as i64;
    while doc.index[slot] >= 0 {
        r.work++;
        if r.work > MAX_KEY_WORK { fail(r, "key index work limit exceeded"); return; }
        slot = (slot + 1) & (doc.index.len - 1);
    }
    doc.index[slot] = id;
}
fn add(r: Reader&, doc: Document&, parent: i64, s: Span, kind: Kind, state: State) -> i64 {
    if r.error.len > 0 { return -1; }
    if doc.nodes.len >= MAX_NODES { fail(r, "node limit exceeded"); return -1; }
    let depth = doc.nodes[parent].depth + 1;
    if depth > MAX_DEPTH { fail(r, "nesting limit exceeded"); return -1; }
    let h = if doc.nodes[parent].kind == Kind.Table { key_hash(parent, doc.bytes[s.start..s.start + s.len]) } else { 0 };
    let id = doc.nodes.len;
    doc.nodes.push(Node { kind: kind, state: state, parent: parent, depth: depth, key: s, key_hash: h, .. });
    let last = doc.nodes[parent].last;
    if last >= 0 { doc.nodes[last].next = id; } else { doc.nodes[parent].first = id; }
    doc.nodes[parent].last = id; doc.nodes[parent].count++;
    if doc.nodes[parent].kind == Kind.Table { index_node(r, doc, id); }
    return id;
}
fn path(r: Reader&, doc: Document&) -> Span[>..] {
    var parts: Span[>..] = [];
    loop {
        horizontal(r);
        let start = doc.bytes.len;
        if peek(r) == '"' || peek(r) == '\'' { string(r, doc.bytes, false); }
        else {
            while r.pos < r.source.len {
                let c = peek(r);
                if !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-') { break; }
                doc.bytes.push(c); r.pos++;
            }
            if doc.bytes.len == start { fail(r, "expected key"); }
        }
        parts.push(Span { start: start, len: doc.bytes.len - start });
        if parts.len > MAX_DEPTH { fail(r, "key path limit exceeded"); }
        if r.error.len > 0 { return parts; }
        horizontal(r);
        if peek(r) != '.' { return parts; }
        r.pos++;
    }
}
fn descend(r: Reader&, doc: Document&, parent: i64, s: Span, headers: bool) -> i64 {
    var id = lookup(r, doc, parent, s);
    if r.error.len > 0 { return -1; }
    if id < 0 { return add(r, doc, parent, s, Kind.Table, if headers { State.Implicit } else { State.Dotted }); }
    if headers && doc.nodes[id].state == State.ArrayOfTables { return doc.nodes[id].last; }
    if doc.nodes[id].kind != Kind.Table || doc.nodes[id].state == State.Sealed || (!headers && doc.nodes[id].state == State.Explicit) {
        fail(r, "cannot extend or redefine value"); return -1;
    }
    if !headers && doc.nodes[id].state == State.Implicit { doc.nodes[id].state = State.Dotted; }
    return id;
}
fn header(r: Reader&, doc: Document&) -> i64 {
    r.pos++;
    let array = peek(r) == '[';
    if array { r.pos++; }
    let parts = path(r, doc);
    if !expect(r, ']') { return 0; }
    if array && !expect(r, ']') { return 0; }
    if r.error.len > 0 { return 0; }
    var parent = 0;
    for s, i in parts {
        if i + 1 < parts.len {
            parent = descend(r, doc, parent, s, true);
            if parent < 0 { return 0; }
        } else {
            var id = lookup(r, doc, parent, s);
            if r.error.len > 0 { return 0; }
            if array {
                if id < 0 { id = add(r, doc, parent, s, Kind.Array, State.ArrayOfTables); }
                else if doc.nodes[id].state != State.ArrayOfTables { fail(r, "array of tables conflicts with existing value"); return 0; }
                if id < 0 { return 0; }
                let child = add(r, doc, id, Span { .. }, Kind.Table, State.Explicit);
                return if child < 0 { 0 } else { child };
            }
            if id < 0 { id = add(r, doc, parent, s, Kind.Table, State.Explicit); }
            else if doc.nodes[id].kind == Kind.Table && doc.nodes[id].state == State.Implicit { doc.nodes[id].state = State.Explicit; }
            else { fail(r, "table already defined"); return 0; }
            return if id < 0 { 0 } else { id };
        }
    }
    return 0;
}
fn assignment_target(r: Reader&, doc: Document&, table: i64) -> i64 {
    let parts = path(r, doc);
    if !expect(r, '=') || r.error.len > 0 { return -1; }
    var parent = table;
    for s, i in parts {
        if i + 1 < parts.len {
            parent = descend(r, doc, parent, s, false);
            if parent < 0 { return -1; }
        } else {
            let existing = lookup(r, doc, parent, s);
            if r.error.len > 0 { return -1; }
            if existing >= 0 { fail(r, "duplicate key"); return -1; }
            return add(r, doc, parent, s, Kind.Table, State.Implicit);
        }
    }
    return -1;
}
recursive fn assignment(r: Reader&, doc: Document&, table: i64) {
    let id = assignment_target(r, doc, table);
    if id >= 0 { value(r, doc, id); }
}
recursive fn seal(doc: Document&, id: i64) {
    // A closed inline subtree cannot be extended. Avoid walking it again
    // when enclosing inline tables close: every edge is visited at most once.
    if doc.nodes[id].state == State.Sealed { return; }
    doc.nodes[id].state = State.Sealed;
    var child = doc.nodes[id].first;
    while child >= 0 { seal(doc, child); child = doc.nodes[child].next; }
}
recursive fn value(r: Reader&, doc: Document&, id: i64) {
    horizontal(r);
    if r.error.len > 0 { return; }
    let c = peek(r);
    if c == '"' || c == '\'' {
        doc.nodes[id].kind = Kind.String;
        let start = doc.bytes.len;
        string(r, doc.bytes, true);
        doc.nodes[id].text = Span { start: start, len: doc.bytes.len - start };
    } else if c == '[' {
        doc.nodes[id].kind = Kind.Array; r.pos++;
        whitespace(r);
        while r.error.len == 0 && peek(r) != ']' {
            let child = add(r, doc, id, Span { .. }, Kind.Table, State.Implicit);
            if child < 0 { return; }
            value(r, doc, child);
            whitespace(r);
            if peek(r) != ',' { break; }
            r.pos++; whitespace(r);
        }
        expect(r, ']');
    } else if c == '{' {
        doc.nodes[id].kind = Kind.Table; doc.nodes[id].state = State.Inline; r.pos++;
        if r.version == Version.V1_1 { whitespace(r); } else { horizontal(r); }
        if peek(r) != '}' {
            loop {
                assignment(r, doc, id);
                if r.error.len > 0 { return; }
                if r.version == Version.V1_1 { whitespace(r); } else { horizontal(r); }
                if peek(r) != ',' { break; }
                r.pos++;
                if r.version == Version.V1_1 {
                    whitespace(r);
                    if peek(r) == '}' { break; }
                }
            }
        }
        if !expect(r, '}') { return; }
        seal(doc, id);
    } else { scalar(r, doc, id); }
}

fn hex(c: u8) -> i64 {
    if c >= '0' && c <= '9' { return c - '0'; }
    if c >= 'a' && c <= 'f' { return (c - 'a') as i64 + 10; }
    if c >= 'A' && c <= 'F' { return (c - 'A') as i64 + 10; }
    return -1;
}
// Prepared once. The standard byte-set search uses bounded loads and may scan
// several bytes at a time; all special bytes still enter the scalar decoder.
fn string_stop_set(quote: u8) -> ByteSet {
    var members: bool[256] = [false; 256];
    for c in 32 { if c != 9 { members[c] = true; } }
    members[127] = true; members[quote] = true;
    if quote == '"' { members['\\'] = true; }
    return byte_set(members);
}
let BASIC_STRING_STOPS = string_stop_set('"');
let LITERAL_STRING_STOPS = string_stop_set('\'');
fn string(r: Reader&, out: u8[>..]&, multiline_allowed: bool) {
    let quote = peek(r); r.pos++;
    var multi = false;
    if multiline_allowed && r.pos + 1 < r.source.len && r.source[r.pos] == quote && r.source[r.pos + 1] == quote { multi = true; r.pos += 2; newline(r); }
    // Copy the ordinary prefix in one span. After its first escape/newline,
    // use the scalar decoder, avoiding repeated scans in escape-heavy text.
    let start = r.pos;
    if r.source.len - r.pos >= 128 {
        let stop = if quote == '"' { find_any(r.source[r.pos..], BASIC_STRING_STOPS) }
            else { find_any(r.source[r.pos..], LITERAL_STRING_STOPS) };
        r.pos = if stop < 0 { r.source.len } else { r.pos + stop };
    }
    while r.pos < r.source.len {
        let c = peek(r);
        if c == quote || (c == '\\' && quote == '\"') || (c < 32 && c != '\t') || c == 127 { break; }
        r.pos++;
    }
    if r.pos > start { out.append(r.source[start..r.pos]); }
    while r.pos < r.source.len && r.error.len == 0 {
        let c = peek(r);
        if c == quote {
            var count = 0;
            while r.pos < r.source.len && peek(r) == quote { count++; r.pos++; if !multi { break; } }
            if !multi { return; }
            if count >= 3 {
                if count > 5 { fail(r, "too many closing quotes"); return; }
                for i in count - 3 { out.push(quote); }
                return;
            }
            for i in count { out.push(quote); }
            continue;
        }
        if c == '\n' || c == '\r' {
            if !multi { fail(r, "newline in single-line string"); return; }
            if !newline(r) { return; }
            out.push('\n'); continue;
        }
        if (c < 32 && c != '\t') || c == 127 { fail(r, "control character in string"); return; }
        r.pos++;
        if c != '\\' || quote == '\'' { out.push(c); continue; }
        // A multiline continuation must contain a newline; horizontal whitespace alone is invalid.
        if multi && (peek(r) == ' ' || peek(r) == '\t' || peek(r) == '\n' || peek(r) == '\r') {
            horizontal(r);
            if !newline(r) { fail(r, "expected newline after continuation"); return; }
            loop { horizontal(r); if !newline(r) { break; } }
            continue;
        }
        let e = peek(r);
        if r.pos >= r.source.len { fail(r, "unfinished escape"); return; }
        r.pos++;
        if e == 'b' { out.push(8); } else if e == 't' { out.push('\t'); }
        else if e == 'n' { out.push('\n'); } else if e == 'f' { out.push(12); }
        else if e == 'r' { out.push('\r'); } else if e == '"' || e == '\\' { out.push(e); }
        else if e == 'e' && r.version == Version.V1_1 { out.push(27); }
        else if e == 'u' || e == 'U' || (e == 'x' && r.version == Version.V1_1) {
            let digits = if e == 'x' { 2 } else if e == 'u' { 4 } else { 8 };
            var code = 0;
            for i in digits {
                if r.pos >= r.source.len { fail(r, "unfinished Unicode escape"); return; }
                let d = hex(peek(r));
                if d < 0 { fail(r, "invalid Unicode escape"); return; }
                code = code * 16 + d; r.pos++;
            }
            if code > 1114111 || (code >= 55296 && code <= 57343) { fail(r, "invalid Unicode scalar"); return; }
            assert(toml_text::append_utf8(out, code));
        } else { fail(r, "invalid escape"); return; }
    }
    fail(r, "unterminated string");
}

fn digit(c: u8) -> bool { c >= '0' && c <= '9' }
fn scalar(r: Reader&, doc: Document&, id: i64) {
    let start = r.pos;
    while r.pos < r.source.len {
        let c = peek(r);
        if c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '#' || c == ',' || c == ']' || c == '}' { break; }
        r.pos++;
        if r.pos - start > MAX_NUMBER_BYTES { fail(r, "scalar token exceeds 128 bytes"); return; }
    }
    // A date-time permits exactly one space between the date and time.
    if r.pos - start == 10 && r.source[start + 4] == '-' && r.source[start + 7] == '-' && peek(r) == ' ' && r.pos + 1 < r.source.len && digit(r.source[r.pos + 1]) {
        r.pos++;
        while r.pos < r.source.len {
            let c = peek(r);
            if c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '#' || c == ',' || c == ']' || c == '}' { break; }
            r.pos++;
            if r.pos - start > MAX_NUMBER_BYTES { fail(r, "scalar token exceeds 128 bytes"); return; }
        }
    }
    let token = r.source[start..r.pos];
    if token == "true" || token == "false" { doc.nodes[id].kind = Kind.Boolean; doc.nodes[id].boolean = token == "true"; return; }
    if (token.len >= 10 && token[4] == '-' && token[7] == '-') || (token.len >= 5 && token[2] == ':') {
        let kind, ok = datetime(token, r.version);
        if !ok { fail(r, "invalid date/time"); return; }
        let offset = doc.bytes.len;
        doc.bytes.append(token);
        doc.nodes[id].kind = kind; doc.nodes[id].text = Span { start: offset, len: token.len };
        return;
    }
    number(r, doc, id, token);
}
fn number(r: Reader&, doc: Document&, id: i64, token: u8[:]) {
    var start = 0;
    if token.len > 0 && (token[0] == '+' || token[0] == '-') { start = 1; }
    let unsigned = token[start..];
    if unsigned == "inf" || unsigned == "nan" {
        doc.nodes[id].kind = Kind.Float;
        doc.nodes[id].number = if unsigned == "nan" { 0.0 / 0.0 } else if token[0] == '-' { -1.0 / 0.0 } else { 1.0 / 0.0 };
        return;
    }
    var base = 10;
    if start == 0 && token.len >= 2 && token[0] == '0' {
        if token[1] == 'x' { base = 16; } else if token[1] == 'o' { base = 8; } else if token[1] == 'b' { base = 2; }
    }
    if base != 10 { start = 2; }
    // Validate underscores before removing them, using the relevant radix.
    var clean: u8[>..] = [];
    for c, i in token {
        if c != '_' { clean.push(c); continue; }
        if i <= start || i + 1 >= token.len { fail(r, "misplaced underscore"); return; }
        let a = hex(token[i - 1]); let b = hex(token[i + 1]);
        if a < 0 || a >= base || b < 0 || b >= base { fail(r, "misplaced underscore"); return; }
    }
    if base != 10 {
        for c in clean[2..] {
            let d = hex(c);
            if d < 0 || d >= base { fail(r, "invalid radix digit"); return; }
        }
        let n, ok = parse_int(clean[2..], base);
        if !ok { fail(r, "invalid or overflowing integer"); return; }
        doc.nodes[id].kind = Kind.Integer; doc.nodes[id].integer = n; return;
    }
    var i = if clean.len > 0 && (clean[0] == '+' || clean[0] == '-') { 1 } else { 0 };
    let whole = i;
    while i < clean.len && digit(clean[i]) { i++; }
    if i == whole || (i - whole > 1 && clean[whole] == '0') { fail(r, "invalid decimal integer part"); return; }
    var floating = false;
    if i < clean.len && clean[i] == '.' {
        floating = true; i++;
        let fraction = i;
        while i < clean.len && digit(clean[i]) { i++; }
        if i == fraction { fail(r, "missing fractional digits"); return; }
    }
    if i < clean.len && (clean[i] == 'e' || clean[i] == 'E') {
        floating = true; i++;
        if i < clean.len && (clean[i] == '+' || clean[i] == '-') { i++; }
        let exponent = i;
        while i < clean.len && digit(clean[i]) { i++; }
        if i == exponent { fail(r, "missing exponent digits"); return; }
    }
    if i != clean.len { fail(r, "invalid scalar"); return; }
    if floating {
        let n, ok = parse_flt(clean);
        if !ok || n != n || n > 1.7976931348623157e308 || n < -1.7976931348623157e308 { fail(r, "float outside finite f64 range"); return; }
        doc.nodes[id].kind = Kind.Float; doc.nodes[id].number = n;
    } else {
        let n, ok = parse_int(clean);
        if !ok { fail(r, "integer outside i64 range"); return; }
        doc.nodes[id].kind = Kind.Integer; doc.nodes[id].integer = n;
    }
}
fn decimal(s: u8[:]) -> i64 {
    var n = 0;
    for c in s { if !digit(c) { return -1; } n = n * 10 + (c - '0'); }
    return n;
}
// Retain arbitrary fractional precision lexically; do not round or apply timezones.
fn datetime(s: u8[:], version: Version = Version.V1_0) -> Kind, bool {
    var i = 0; var date = false;
    if s.len >= 10 && s[4] == '-' && s[7] == '-' {
        let year = decimal(s[..4]); let month = decimal(s[5..7]); let day = decimal(s[8..10]);
        if year < 0 || month < 1 || month > 12 || day < 1 { return Kind.LocalDate, false; }
        var days = 31;
        if month == 4 || month == 6 || month == 9 || month == 11 { days = 30; }
        if month == 2 { days = if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) { 29 } else { 28 }; }
        if day > days { return Kind.LocalDate, false; }
        if s.len == 10 { return Kind.LocalDate, true; }
        if s[10] != 'T' && s[10] != 't' && s[10] != ' ' { return Kind.LocalDateTime, false; }
        i = 11; date = true;
    }
    if s.len - i < 5 || s[i + 2] != ':' { return Kind.LocalTime, false; }
    let hour = decimal(s[i..i + 2]); let minute = decimal(s[i + 3..i + 5]);
    if hour < 0 || hour > 23 || minute < 0 || minute > 59 { return Kind.LocalTime, false; }
    i += 5;
    var seconds = false;
    if i < s.len && s[i] == ':' {
        if s.len - i < 3 { return Kind.LocalTime, false; }
        let second = decimal(s[i + 1..i + 3]);
        if second < 0 || second > 60 { return Kind.LocalTime, false; }
        i += 3; seconds = true;
    } else if version == Version.V1_0 { return Kind.LocalTime, false; }
    if i < s.len && s[i] == '.' {
        if !seconds { return Kind.LocalTime, false; }
        i++;
        let fraction = i;
        while i < s.len && digit(s[i]) { i++; }
        if i == fraction { return Kind.LocalTime, false; }
    }
    if i == s.len { return if date { Kind.LocalDateTime } else { Kind.LocalTime }, true; }
    if !date { return Kind.LocalTime, false; }
    if s[i] == 'Z' || s[i] == 'z' { return Kind.OffsetDateTime, i + 1 == s.len; }
    if s.len - i != 6 || (s[i] != '+' && s[i] != '-') || s[i + 3] != ':' { return Kind.OffsetDateTime, false; }
    let oh = decimal(s[i + 1..i + 3]); let om = decimal(s[i + 4..i + 6]);
    return Kind.OffsetDateTime, oh >= 0 && oh <= 23 && om >= 0 && om <= 59;
}

// Supported compatibility entry point; accepts Unicode scalars including NUL.
// TOML syntax applies its own control-character restrictions after preflight.
fn valid_utf8(source: u8[:]) -> bool { toml_text::valid_utf8(source) }

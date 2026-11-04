// SPDX-License-Identifier: Apache-2.0
import std;
namespace log;

fn unsafe_bytes() -> ByteSet {
    var members: bool[256] = [false; 256];
    for i in 256 { members[i] = i < 32 || i > 126 || i == 92; }
    byte_set(members)
}
const UNSAFE_BYTES = unsafe_bytes();

// Preserve the original default (Debug) and representation tags. Filtering
// uses named variants rather than declaration/tag order.
enum Level { Debug, Info, Warn, Error, Off, Trace, Fatal }
enum Status { Filtered, Written, SinkError }

struct Logger {
    minimum: Level = Level.Info,
    color:   bool  = false,
}

const MAX_MESSAGE_BYTES = 4096;
// Largest label (8), color + reset (9), escaped payload (4 per byte),
// truncation suffix (15), and final newline (1).
const MAX_LINE_BYTES = 8 + 9 + 4 * MAX_MESSAGE_BYTES + 15 + 1;

fn enabled(logger: Logger, level: Level) -> bool {
    if level == Level.Off || logger.minimum == Level.Off { return false; }
    if logger.minimum == Level.Trace { return true; }
    if logger.minimum == Level.Debug { return level != Level.Trace; }
    if logger.minimum == Level.Info { return level != Level.Trace && level != Level.Debug; }
    if logger.minimum == Level.Warn { return level == Level.Warn || level == Level.Error || level == Level.Fatal; }
    if logger.minimum == Level.Error { return level == Level.Error || level == Level.Fatal; }
    level == Level.Fatal
}

fn level_name(level: Level) -> const u8[:] {
    if level == Level.Trace { return "TRACE"; }
    if level == Level.Debug { return "DEBUG"; }
    if level == Level.Info { return "INFO"; }
    if level == Level.Warn { return "WARN"; }
    if level == Level.Error { return "ERROR"; }
    if level == Level.Fatal { return "FATAL"; }
    "OFF"
}

fn name_matches(text: const u8[:], name: const u8[:]) -> bool {
    if text.len != name.len { return false; }
    for i in name.len {
        var c = text[i];
        if c >= 'a' && c <= 'z' { c -= 32; }
        if c != name[i] { return false; }
    }
    true
}

// Exact ASCII names only; reject oversized input before reading its bytes.
fn parse_level(text: const u8[:]) -> Level, bool {
    if text.len > 5 { return Level.Off, false; }
    if name_matches(text, "TRACE") { return Level.Trace, true; }
    if name_matches(text, "DEBUG") { return Level.Debug, true; }
    if name_matches(text, "INFO") { return Level.Info, true; }
    if name_matches(text, "WARN") { return Level.Warn, true; }
    if name_matches(text, "ERROR") { return Level.Error, true; }
    if name_matches(text, "FATAL") { return Level.Fatal, true; }
    if name_matches(text, "OFF") { return Level.Off, true; }
    return Level.Off, false;
}

// Replaces out only when enabled. Input must not borrow from out.
// All non-printable/non-ASCII bytes are escaped, as is backslash itself.
inline fn append_prefix(logger: Logger, level: Level, out: u8[>..]&) {
    if logger.color {
        if level == Level.Trace { out.append("\x1b[94m"); }
        else if level == Level.Debug { out.append("\x1b[36m"); }
        else if level == Level.Info { out.append("\x1b[32m"); }
        else if level == Level.Warn { out.append("\x1b[33m"); }
        else if level == Level.Error { out.append("\x1b[31m"); }
        else { out.append("\x1b[35m"); }
    }
    out.push('[');
    out.append(level_name(level));
    out.push(']');
    if logger.color { out.append("\x1b[0m"); }
    out.push(' ');
}

inline fn append_message(message: const u8[:], out: u8[>..]&) {
    let hex = "0123456789abcdef";
    let count = if message.len < MAX_MESSAGE_BYTES { message.len } else { MAX_MESSAGE_BYTES };
    let prefix = message[..count];
    var first: i64 = 0;
    if count >= 512 {
        let found = find_any(prefix, UNSAFE_BYTES);
        if found < 0 { out.append(prefix); first = count; }
        else if found > 0 { out.append(prefix[..found]); first = found; }
    }
    for c in prefix[first..] {
        if c == '\\' { out.append("\\\\"); }
        else if c >= 0x20 && c <= 0x7e { out.push(c); }
        else {
            out.append("\\x");
            out.push(hex[(c >> 4) as i64]);
            out.push(hex[(c & 15) as i64]);
        }
    }
    if message.len > MAX_MESSAGE_BYTES { out.append("... [truncated]"); }
}

fn render(logger: Logger, level: Level, message: const u8[:], out: u8[>..]&) -> bool {
    if !enabled(logger, level) { return false; }
    out.clear();
    append_prefix(logger, level, out);
    append_message(message, out);
    out.push('\n');
    true
}

// The sink borrows one complete line synchronously and reports success.
// A failed sink may already have written bytes: there is no retry/rollback.
fn emit<F>(logger: Logger, level: Level, message: const u8[:], out: u8[>..]&) -> Status {
    if !render(logger, level, message, out) { return Status.Filtered; }
    let line:    const u8[:] = out;
    let success: bool        = F(line);
    if success { Status.Written } else { Status.SinkError }
}

// Build() is evaluated once only when enabled, before Sink(line). It may
// return owned bytes or a borrowed slice; Goose checks the resulting lifetime.
// Builder work is application code and is outside the formatter's byte cap.
fn emit_lazy<Build, Sink>(logger: Logger, level: Level, out: u8[>..]&) -> Status {
    if !enabled(logger, level) { return Status.Filtered; }
    let message = Build();
    emit(logger, level, message, out, Sink)
}

struct Field {
    key:       const u8[:],
    value:     const u8[:],
    sensitive: bool = false,
}

const EMPTY_FIELDS: Field[0] = [];

struct Record {
    level:     Level          = Level.Info,
    message:   const u8[:]    = "",
    timestamp: const u8[:]    = "",
    target:    const u8[:]    = "",
    file:      const u8[:]    = "",
    line:      u32            = 0,
    fields:    const Field[:] = EMPTY_FIELDS,
}

const MAX_TIMESTAMP_BYTES = 64;
const MAX_TARGET_BYTES = 64;
const MAX_FILE_BYTES = 256;
const MAX_FIELD_KEY_BYTES = 64;
const MAX_FIELD_VALUE_BYTES = 256;
const MAX_FIELDS = 8;
// Three quoted metadata fields: expanded bytes, 15-byte truncation marker
// each, 31 syntax bytes; line= plus ten decimal digits and a space: 16.
// Each arbitrary field adds six syntax bytes, two possible markers, and
// its escaped key/value. The extra-field marker adds 19 bytes.
const MAX_RECORD_LINE_BYTES = MAX_LINE_BYTES
    + 4 * (MAX_TIMESTAMP_BYTES + MAX_TARGET_BYTES + MAX_FILE_BYTES) + 3 * 15 + 31 + 16
    + MAX_FIELDS * (4 * (MAX_FIELD_KEY_BYTES + MAX_FIELD_VALUE_BYTES) + 2 * 15 + 6) + 19;

fn append_quoted(text: const u8[:], cap: i64, out: u8[>..]&) {
    out.push('"');
    let count = if text.len < cap { text.len } else { cap };
    let hex = "0123456789abcdef";
    for c in text[..count] {
        if c == '"' || c == '\\' { out.push('\\'); out.push(c); }
        else if c >= 0x20 && c <= 0x7e { out.push(c); }
        else {
            out.append("\\x");
            out.push(hex[(c >> 4) as i64]);
            out.push(hex[(c & 15) as i64]);
        }
    }
    if text.len > cap { out.append("... [truncated]"); }
    out.push('"');
}

fn append_metadata(name: const u8[:], text: const u8[:], cap: i64, out: u8[>..]&) {
    if text.len == 0 { return; }
    out.append(name);
    out.push('=');
    append_quoted(text, cap, out);
    out.push(' ');
}

// Fixed bounded decimal formatting, independent of application format overloads.
fn append_line_number(line: u32, out: u8[>..]&) {
    if line == 0 { return; }
    var digits: u8[10] = [0; 10];
    var at:     i64    = 10;
    var n = line;
    while true {
        at -= 1;
        digits[at] = '0' + ((n % 10) as u8);
        n /= 10;
        if n == 0 { break; }
    }
    out.append("line=");
    out.append(digits[at..]);
    out.push(' ');
}

fn render_record(logger: Logger, record: const Record&, out: u8[>..]&) -> bool {
    if !enabled(logger, record.level) { return false; }
    out.clear();
    append_prefix(logger, record.level, out);
    append_metadata("timestamp", record.timestamp, MAX_TIMESTAMP_BYTES, out);
    append_metadata("target", record.target, MAX_TARGET_BYTES, out);
    append_metadata("file", record.file, MAX_FILE_BYTES, out);
    append_line_number(record.line, out);
    let count = if record.fields.len < MAX_FIELDS { record.fields.len } else { MAX_FIELDS };
    for field in record.fields[..count] {
        append_quoted(field.key, MAX_FIELD_KEY_BYTES, out);
        out.push('=');
        if field.sensitive { out.append("\"***\""); }
        else { append_quoted(field.value, MAX_FIELD_VALUE_BYTES, out); }
        out.push(' ');
    }
    if record.fields.len > MAX_FIELDS { out.append("[fields truncated] "); }
    append_message(record.message, out);
    out.push('\n');
    true
}

fn emit_record<Sink>(logger: Logger, record: const Record&, out: u8[>..]&) -> Status {
    if !render_record(logger, record, out) { return Status.Filtered; }
    let line:    const u8[:] = out;
    let success: bool        = Sink(line);
    if success { Status.Written } else { Status.SinkError }
}

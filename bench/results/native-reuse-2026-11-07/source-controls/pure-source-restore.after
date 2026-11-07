// SPDX-License-Identifier: Apache-2.0
namespace diff;
import std;

const MAX_BYTES = 1048576;
const MAX_LINES = 16384;
const MAX_CELLS = 4194304;
const MAX_WORK = 67108864;
enum Error { None, InvalidOptions, LimitExceeded }
enum Kind { Equal, Delete, Insert }
struct Edit { kind: Kind, old_start: i64, old_end: i64, new_start: i64, new_end: i64 }
struct Limits {
    max_bytes: i64 = 1048576,
    max_lines: i64 = 16384,
    max_cells: i64 = 1048576,
    max_work:  i64 = 16777216,
}
struct Line { start: i64, end: i64 }
struct Budget { remaining: i64, exhausted: bool = false }

// LF belongs to the preceding line. Empty input has no lines; a trailing LF
// creates no phantom empty line. All other bytes are opaque data.
fn split(text: const u8[:], out: Line[>..]&, max_lines: i64) -> bool {
    out.clear();
    var start = 0;
    for c, i in text {
        if c == '\n' {
            if out.len == max_lines { out.clear(); return false; }
            out.push(Line { start: start, end: i + 1 }); start = i + 1;
        }
    }
    if start < text.len {
        if out.len == max_lines { out.clear(); return false; }
        out.push(Line { start: start, end: text.len });
    }
    return true;
}

// Each compared pair of bytes costs one unit, including trimming and
// reconstruction. Rejecting different lengths requires no byte comparisons.
fn same(a: const u8[:], x: Line, b: const u8[:], y: Line, budget: Budget&) -> bool {
    let size = x.end - x.start;
    if size != y.end - y.start { return false; }
    for i in size {
        if budget.remaining == 0 { budget.exhausted = true; return false; }
        budget.remaining--;
        if a[x.start + i] != b[y.start + i] { return false; }
    }
    return true;
}

fn emit(out: Edit[>..]&, kind: Kind, a: i64, ae: i64, b: i64, be: i64) {
    if a == ae && b == be { return; }
    if out.len > 0 {
        let last = out.len - 1;
        if out[last].kind == kind && out[last].old_end == a && out[last].new_end == b {
            out[last].old_end = ae; out[last].new_end = be; return;
        }
    }
    out.push(Edit { kind: kind, old_start: a, old_end: ae, new_start: b, new_end: be });
}

fn valid(limits: Limits) -> bool {
    return limits.max_bytes >= 0 && limits.max_bytes <= MAX_BYTES &&
           limits.max_lines >= 0 && limits.max_lines <= MAX_LINES &&
           limits.max_cells >= 0 && limits.max_cells <= MAX_CELLS &&
           limits.max_work >= 0 && limits.max_work <= MAX_WORK;
}

fn compare_impl(old: const u8[:], fresh: const u8[:], out: Edit[>..]&, limits: Limits) -> Error {
    if !valid(limits) { return Error.InvalidOptions; }
    if old.len > limits.max_bytes || fresh.len > limits.max_bytes { return Error.LimitExceeded; }
    var a: Line[>..] = []; var b: Line[>..] = [];
    if !split(old, a, limits.max_lines) || !split(fresh, b, limits.max_lines) { return Error.LimitExceeded; }
    var budget = Budget { remaining: limits.max_work };
    var prefix = 0;
    while prefix < a.len && prefix < b.len && same(old, a[prefix], fresh, b[prefix], budget) { prefix++; }
    if budget.exhausted { return Error.LimitExceeded; }
    var ae = a.len; var be = b.len;
    while ae > prefix && be > prefix && same(old, a[ae - 1], fresh, b[be - 1], budget) { ae--; be--; }
    if budget.exhausted { return Error.LimitExceeded; }
    emit(out, Kind.Equal, 0, prefix, 0, prefix);
    let n = ae - prefix; let m = be - prefix;
    if n == 0 || m == 0 {
        emit(out, Kind.Delete, prefix, ae, prefix, prefix);
        emit(out, Kind.Insert, ae, ae, prefix, be);
    } else {
        // Dimensions are line-bounded; count sentinels, divide before multiply.
        let width = m + 1;
        if n + 1 > limits.max_cells / width { return Error.LimitExceeded; }
        let cells = (n + 1) * width;
        var table: i64[>..] = [];
        for i in cells { table.push(0); }
        var i = n;
        while i > 0 {
            i--; var j = m;
            while j > 0 {
                j--;
                let equal = same(old, a[prefix + i], fresh, b[prefix + j], budget);
                if budget.exhausted { return Error.LimitExceeded; }
                let down = table[(i + 1) * width + j];
                let right = table[i * width + j + 1];
                table[i * width + j] = if equal { table[(i + 1) * width + j + 1] + 1 }
                                      else if down >= right { down } else { right };
            }
        }
        i = 0; var j = 0;
        while i < n && j < m {
            let equal = same(old, a[prefix + i], fresh, b[prefix + j], budget);
            if budget.exhausted { return Error.LimitExceeded; }
            if equal {
                emit(out, Kind.Equal, prefix + i, prefix + i + 1, prefix + j, prefix + j + 1); i++; j++;
            } else if table[(i + 1) * width + j] >= table[i * width + j + 1] {
                emit(out, Kind.Delete, prefix + i, prefix + i + 1, prefix + j, prefix + j); i++;
            } else {
                emit(out, Kind.Insert, prefix + i, prefix + i, prefix + j, prefix + j + 1); j++;
            }
        }
        emit(out, Kind.Delete, prefix + i, ae, prefix + j, prefix + j);
        emit(out, Kind.Insert, ae, ae, prefix + j, be);
    }
    emit(out, Kind.Equal, ae, a.len, be, b.len);
    return Error.None;
}

// Edits own indices, never borrowed input storage. Retain the exact input
// bytes to interpret the ranges. Every recoverable error clears output.
fn compare(old: const u8[:], fresh: const u8[:], out: Edit[>..]&, limits: Limits) -> Error {
    out.clear();
    let error = compare_impl(old, fresh, out, limits);
    if error != Error.None { out.clear(); }
    return error;
}

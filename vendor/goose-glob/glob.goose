// SPDX-License-Identifier: Apache-2.0
namespace glob;
import std;

const MAX_PATTERN_BYTES = 1024;
const MAX_PATH_BYTES = 4095;
const MAX_COMPONENTS = 128;
const MAX_WORK = 16777216;
enum Error { None, InvalidPattern, InvalidPath, InvalidOptions, LimitExceeded, Filesystem }
struct Status { error: Error = Error.None, os_error: i64 = 0 }
struct Options { hidden: bool = false, work_limit: i64 = 1048576 }
struct Span { start: i64, end: i64 }
struct Budget { remaining: i64, exhausted: bool = false }

fn spend(budget: Budget&) -> bool {
    if budget.remaining == 0 { budget.exhausted = true; return false; }
    budget.remaining--; return true;
}
fn split(path: const u8[:], out: Span[>..]&) -> bool {
    out.clear();
    if path.len == 0 || path.len > MAX_PATH_BYTES { return false; }
    var start = 0;
    for i in 0..path.len + 1 {
        if i < path.len && path[i] == 0 { return false; }
        if i == path.len || path[i] == '/' {
            let part = path[start..i];
            if part.len == 0 || part == "." || part == ".." || out.len == MAX_COMPONENTS { return false; }
            out.push(Span { start: start, end: i }); start = i + 1;
        }
    }
    return true;
}
// Returns the closing bracket, or -1 for an empty/malformed class.
fn class_end(pattern: const u8[:], start: i64) -> i64 {
    var at = start + 1;
    if at < pattern.len && (pattern[at] == '!' || pattern[at] == '^') { at++; }
    let first = at;
    while at < pattern.len && pattern[at] != ']' {
        // Escapes inside classes are deliberately unsupported.
        if pattern[at] == '\\' { return -1; }
        if at + 2 < pattern.len && pattern[at + 1] == '-' && pattern[at + 2] != ']' {
            if pattern[at] > pattern[at + 2] || pattern[at + 2] == '\\' { return -1; }
            at += 3;
        } else { at++; }
    }
    return if at < pattern.len && at > first { at } else { -1 };
}
fn valid_component(pattern: const u8[:]) -> bool {
    if pattern == "**" { return true; }
    var at = 0;
    while at < pattern.len {
        let c = pattern[at];
        if c == '\\' {
            at++;
            if at == pattern.len { return false; }
        } else if c == '[' {
            at = class_end(pattern, at);
            if at < 0 { return false; }
        } else if c == '*' && at + 1 < pattern.len && pattern[at + 1] == '*' { return false; }
        at++;
    }
    return true;
}
fn validate(pattern: const u8[:]) -> Status {
    var parts: Span[>..] = [];
    if pattern.len > MAX_PATTERN_BYTES || !split(pattern, parts) { return Status { error: Error.InvalidPattern }; }
    for part in parts {
        if !valid_component(pattern[part.start..part.end]) { return Status { error: Error.InvalidPattern }; }
    }
    return Status { .. };
}
fn class_matches(pattern: const u8[:], start: i64, end: i64, c: u8) -> bool {
    var at = start + 1;
    let negate = pattern[at] == '!' || pattern[at] == '^';
    if negate { at++; }
    var found = false;
    while at < end {
        if at + 2 < end && pattern[at + 1] == '-' {
            if c >= pattern[at] && c <= pattern[at + 2] { found = true; }
            at += 3;
        } else {
            if c == pattern[at] { found = true; }
            at++;
        }
    }
    return if negate { !found } else { found };
}
// Greedy component matching with one saved star. No recursive backtracking.
fn component_matches(pattern: const u8[:], name: const u8[:], hidden: bool, budget: Budget&) -> bool {
    let explicit_dot = pattern[0] == '.' || (pattern.len >= 2 && pattern[0] == '\\' && pattern[1] == '.');
    if !hidden && name[0] == '.' && !explicit_dot { return false; }
    var p = 0; var n = 0; var star = -1; var retry = 0;
    while n < name.len {
        if !spend(budget) { return false; }
        if p < pattern.len && pattern[p] == '*' { star = p; p++; retry = n; continue; }
        var next = p + 1;
        var matched = false;
        if p < pattern.len {
            let c = pattern[p];
            if c == '?' { matched = true; }
            else if c == '\\' { matched = pattern[p + 1] == name[n]; next = p + 2; }
            else if c == '[' {
                let end = class_end(pattern, p);
                // Charge the complete class scan, including ranges.
                if budget.remaining < end - p { budget.exhausted = true; return false; }
                budget.remaining -= end - p;
                matched = class_matches(pattern, p, end, name[n]); next = end + 1;
            } else { matched = c == name[n]; }
        }
        if matched { p = next; n++; }
        else if star >= 0 { retry++; n = retry; p = star + 1; }
        else { return false; }
    }
    if p < pattern.len && pattern[p] == '*' { p++; }
    return p == pattern.len;
}
// Inputs and options have been validated. A shared budget lets traversal bound
// the sum of its matching work rather than restarting the limit for each file.
fn match_with_budget(pattern: const u8[:], path: const u8[:], hidden: bool, budget: Budget&) -> bool {
    var patterns: Span[>..] = []; var names: Span[>..] = [];
    if !split(pattern, patterns) || !split(path, names) { return false; }
    var previous: bool[>..] = []; previous.resize(names.len + 1, false); previous[0] = true;
    for part in patterns {
        let component = pattern[part.start..part.end];
        var current: bool[>..] = []; current.resize(names.len + 1, false);
        if component == "**" { current[0] = previous[0]; }
        for j in 1..names.len + 1 {
            if !spend(budget) { return false; }
            let name = path[names[j - 1].start..names[j - 1].end];
            if component == "**" {
                current[j] = previous[j] || (current[j - 1] && (hidden || name[0] != '.'));
            } else if previous[j - 1] {
                current[j] = component_matches(component, name, hidden, budget);
                if budget.exhausted { return false; }
            }
        }
        for value, j in current { previous[j] = value; }
    }
    return previous[names.len];
}
fn matches(pattern: const u8[:], path: const u8[:], options: Options = Options { .. }) -> bool, Status {
    if options.work_limit < 1 || options.work_limit > MAX_WORK { return false, Status { error: Error.InvalidOptions }; }
    let checked = validate(pattern);
    if checked.error != Error.None { return false, checked; }
    var parts: Span[>..] = [];
    if !split(path, parts) { return false, Status { error: Error.InvalidPath }; }
    var budget = Budget { remaining: options.work_limit };
    let matched = match_with_budget(pattern, path, options.hidden, budget);
    if budget.exhausted { return false, Status { error: Error.LimitExceeded }; }
    return matched, Status { .. };
}

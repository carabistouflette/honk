// SPDX-License-Identifier: Apache-2.0
// Application-owned CLI diagnostics: canonical UTC, fixed events and numeric data.
import logger;
import time;
import utc;
import os;
namespace diagnostics;

enum Event { Started, ItemCompleted, Returned, Failed, ChildFailed }

fn event_name(event: Event) -> const u8[:] {
    if event == Event.Started { return "started"; }
    if event == Event.ItemCompleted { return "item_completed"; }
    if event == Event.Returned { return "returned"; }
    if event == Event.Failed { return "failed"; }
    "child_failed"
}

fn level(event: Event) -> log::Level {
    if event == Event.Failed || event == Event.ChildFailed { log::Level.Error }
    else { log::Level.Info }
}

fn append_unsigned(value: u64, out: u8[>..]&) {
    var digits: u8[20] = [0; 20];
    var at:     i64    = 20;
    var remaining = value;
    while true {
        at -= 1;
        digits[at] = '0' + ((remaining % 10) as u8);
        remaining /= 10;
        if remaining == 0 { break; }
    }
    out.append(digits[at..]);
}

fn message(event: Event, duration_ns: u64, outcome: u32) -> u8[>..] {
    var out: u8[>..] = [];
    out.append(event_name(event));
    out.append(" duration_ns=");
    append_unsigned(duration_ns, out);
    out.append(" outcome=");
    append_unsigned(outcome, out);
    out
}

extern fn append(path: const u8[:], line: const u8[:]) -> bool = "goose_cli_log_append";
// Reference consumer only; Honk uses its own checked stdout adapter.
extern fn stdout_ok() -> bool = "example_log_stdout_ok";

var destination:        u8[4096] = [0; 4096];
var destination_length: i64      = 0;
var config = log::Logger { .. };
var configured = false;
var failed = false;

// No I/O here. Only a successful explicit configuration clears errors.
fn configure(path: const u8[:], minimum: log::Level = log::Level.Info) -> bool {
    configured = false;
    failed = true;
    destination_length = 0;
    if path.len == 0 || path.len >= 4096 { return false; }
    for c in path { if c == 0 { return false; } }
    for c, i in path { destination[i] = c; }
    destination_length = path.len;
    config = log::Logger { minimum: minimum };
    failed = false;
    configured = true;
    true
}

// State/Off guard for lifecycle clocks; not a per-event severity check.
fn active() -> bool { configured && !failed && config.minimum != log::Level.Off }

// Shared production/test seam: callbacks are single-threaded and non-reentrant.
// Filtering precedes message construction, wall-clock acquisition and buffers.
fn write_with<Clock, Sink>(event: Event, duration_ns: u64, outcome: u32) -> bool {
    if failed { return false; }
    if !configured { return true; }
    let severity = level(event);
    if !log::enabled(config, severity) { return true; }
    // Keep lexical buffers: terminal diagnostics must not shrink shared storage
    // while callers hold parser/manifest borrows in the pinned compiler.
    var timestamp: u8[>..] = [];
    var scratch:   u8[>..] = [];
    let text = message(event, duration_ns, outcome);
    let status = utc_log::emit(config, severity, text, timestamp, scratch, Clock, Sink);
    if status == log::Status.SinkError {
        failed = true;
        return false;
    }
    true
}
fn wall_clock() -> i64 { time_ns() }
fn write(event: Event, duration_ns: u64 = 0, outcome: u32 = 0) -> bool {
    return write_with(event, duration_ns, outcome, wall_clock) { line =>
        append(destination[..destination_length], line)
    };
}

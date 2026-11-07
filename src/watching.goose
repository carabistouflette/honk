// SPDX-License-Identifier: Apache-2.0
namespace watching;
import watch;
import process;
import .platform;
import std;
import os;
const DRAIN_LIMIT = 256;
struct Run { code: i64 = 125, dirty: bool = false, lost: bool = false, stop: bool = false }
fn relevant(event: const watch::Event&) -> bool {
    return !watch::has(event, watch::IS_DIRECTORY) &&
        ends_with(event.name, ".goose") &&
        watch::has(event, watch::CLOSE_WRITE | watch::MOVED_FROM | watch::MOVED_TO | watch::DELETE);
}
// -1: stop; 0: idle; 1: dirty; 2: overflow recovered. No names are displayed.
fn changes(owner: watch::WatchSet&, directories: const (const u8[:])[:], timeout_ms: i64) -> i64 {
    var out = watch::SetEvent { .. }; var dirty = false;
    for i in DRAIN_LIMIT {
        let status = watch::next(owner, if i == 0 { timeout_ms } else { 0 }, out);
        if status.error == watch::Error.Interrupted { return if dirty { 1 } else { 0 }; }
        if status.error != watch::Error.None { return -1; }
        if !status.ready { return if dirty { 1 } else { 0 }; }
        if watch::has(out.event, watch::OVERFLOW) {
            let closed = watch::close(owner);
            if closed.error != watch::Error.None { return -1; }
            let reopened = watch::open_set(owner, directories);
            if reopened.status.error != watch::Error.None { return -1; }
            return 2;
        }
        if watch::has(out.event, watch::IGNORED | watch::DELETE_SELF | watch::MOVE_SELF | watch::UNMOUNT) { return -1; }
        dirty = dirty || relevant(out.event);
    }
    return if dirty { 1 } else { 0 }; // Retained records remain for the next bounded drain.
}
// Called only for a pending rerun with no active child. Loss bypasses batching.
fn settle(owner: watch::WatchSet&, directories: const (const u8[:])[:], quiet_ms: i64) -> i64 {
    let started = platform::watch_clock_ms();
    if started < 0 { return -1; }
    var last = started; var now = started;
    loop {
        if platform::process_guard_take(0) != 0 { return -1; }
        let wait = max(0, min(100, min(quiet_ms - (now - last), 1000 - (now - started))));
        let observed = changes(owner, directories, wait);
        if observed < 0 || observed == 2 { return observed; }
        let after = platform::watch_clock_ms();
        if after < now { return -1; }
        now = after;
        if observed > 0 { last = now; }
        if now - started >= 1000 || now - last >= quiet_ms { return 1; }
    }
}
fn compiled_honk() -> bool {
    var out: u8[>..] = []; var err: u8[>..] = [];
    let options = process::Options { timeout_ms: 2000, output_limit: 256, .. };
    let status = process::run(["/proc/self/exe", "--version"], options, out, err);
    platform::recover_status(status);
    return status.error == process::Error.None && status.exit_code == 0 && out == "honk 0.4.0\n";
}
fn command(owner: watch::WatchSet&, directories: const (const u8[:])[:], argv: const (const u8[:])[:]) -> Run {
    var result = Run { .. };
    if platform::process_guard_take(0) != 0 { result.stop = true; return result; }
    var child = process::Child { .. };
    let options = process::Options { timeout_ms: 0, capture: false,
        stdin: process::Input.Null, stdout: process::Output.Inherit, stderr: process::Output.Inherit, .. };
    var failed = false;
    var status = process::start(argv, options, child); platform::recover_status(status);
    if status.error == process::Error.None {
        var termination_requested = false;
        loop {
            let signals = platform::process_guard_take(0);
            if signals != 0 { result.stop = true; }
            if signals > 0 && (signals & 1) != 0 {
                // Kernel terminal-group SIGINT already reached the child.
                let sent = process::send_signal(child, 2); platform::recover_status(sent);
                if sent.error != process::Error.None && sent.error != process::Error.InvalidState { result.stop = true; }
            }
            let observed = if result.stop { 0 } else { changes(owner, directories, 0) };
            result.dirty = result.dirty || observed > 0; result.lost = result.lost || observed == 2;
            if observed < 0 || signals < 0 { result.stop = true; failed = true; }
            if (signals > 0 && (signals & 4) != 0) || (failed && !termination_requested) {
                termination_requested = true;
                let sent = process::send_signal(child, 15); platform::recover_status(sent);
                if sent.error != process::Error.None && sent.error != process::Error.InvalidState { result.stop = true; }
            }
            let next, complete = process::step(child, 20); status = next; platform::recover_status(next);
            if complete || next.error != process::Error.None { break; }
        }
    }
    let closed = process::close(child); platform::recover_status(closed);
    result.code = platform::process_status(status);
    if closed.error != process::Error.None || failed { result.code = 125; result.stop = true; }
    if status.error != process::Error.None || status.signal != 0 || result.code >= 128 { result.stop = true; }
    return result;
}
fn run(directories: const (const u8[:])[:], argv: const (const u8[:])[:], limit: i64, debounce_ms: i64) -> i64 {
    platform::require(compiled_honk(), "watch requires a compiled Honk executable and /proc/self/exe");
    var owner = watch::WatchSet { .. };
    let opened = watch::open_set(owner, directories);
    if opened.status.error != watch::Error.None {
        write_stderr(str("honk watch: cannot open directory request index ", opened.failed_directory, " (unique normalized absolute paths, no final symlinks)\n"));
        return 125;
    }
    if !platform::process_guard_begin() { let closed = watch::close(owner); return 125; }
    var completed: i64 = 0; var code: i64 = 0; var dirty = true; var immediate = false;
    write_stderr("honk watch: watching selected directories (nonrecursive)\n");
    loop {
        if platform::process_guard_take(0) != 0 { code = 125; break; }
        if dirty {
            if completed > 0 && debounce_ms > 0 && !immediate {
                write_stderr("honk watch: batching pending changes\n");
                let batched = settle(owner, directories, debounce_ms);
                if batched < 0 { code = 125; break; }
                if batched == 2 { write_stderr("honk watch: events lost; reopened watch, scheduling full command\n"); }
            }
            immediate = false;
            write_stderr("honk watch: running command\n");
            let outcome = command(owner, directories, argv);
            code = outcome.code; completed++;
            if outcome.lost { write_stderr("honk watch: events lost; reopened watch, scheduling full command\n"); }
            if outcome.stop { if code == 0 { code = 125; } break; }
            if limit > 0 && completed >= limit { break; }
            let queued = changes(owner, directories, 0);
            if queued < 0 { code = 125; break; }
            if queued == 2 { write_stderr("honk watch: events lost; reopened watch, scheduling full command\n"); }
            dirty = outcome.dirty || queued > 0; immediate = outcome.lost || queued == 2;
            write_stderr(if dirty { "honk watch: pending changes; rerunning\n" } else { "honk watch: command finished; waiting for changes\n" });
        } else {
            let observed = changes(owner, directories, 100);
            if observed < 0 { code = 125; break; }
            if observed == 2 { write_stderr("honk watch: events lost; reopened watch, scheduling full command\n"); }
            dirty = observed > 0; immediate = observed == 2;
        }
    }
    let closed = watch::close(owner);
    let cancelled = platform::process_guard_end();
    if cancelled < 0 || closed.error != watch::Error.None { return 125; }
    if cancelled > 0 { return 128 + cancelled; }
    if code == 125 { write_stderr("honk watch: watch or child supervision failed; stopping\n"); }
    return code;
}

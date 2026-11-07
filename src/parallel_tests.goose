// SPDX-License-Identifier: Apache-2.0
namespace parallel_tests;
import std;
import os;
import process;
import task;
import posix;
import .platform;
import .presentation;
const MAX_JOBS = 8;
const STREAM_LIMIT = 65536;
const MAX_TARGETS = 4096;
enum Failure { None, Launch, TimedOut, OutputLimit, Supervision, Output }
struct Result { code: i64 = 0, failure: Failure = Failure.None, target: i64 = -1 }
fn failure(status: process::Status, target: i64) -> Result {
    let reason = if status.error == process::Error.LaunchFailed { Failure.Launch }
        else if status.error == process::Error.TimedOut { Failure.TimedOut }
        else if status.error == process::Error.OutputLimit { Failure.OutputLimit }
        else { Failure.Supervision };
    return Result { code: 125, failure: reason, target: target };
}
fn report(result: Result) {
    if result.failure == Failure.None { return; }
    let message = if result.failure == Failure.Launch { "launch failed" }
        else if result.failure == Failure.TimedOut { "deadline exceeded" }
        else if result.failure == Failure.OutputLimit { "output limit exceeded" }
        else if result.failure == Failure.Output { "captured output write failed" }
        else { "supervision or cleanup failed" };
    let label = if result.target >= 0 { str("target ", result.target, ": ") } else { str("") };
    let written = write_output(2, str("honk: parallel test ", label, message, "\n"));
}
// Checked writes occur only after every cohort owner is closed.
fn write_output(fd: i64, bytes: const u8[:]) -> bool {
    var offset = 0;
    for attempt in bytes.len + 64 {
        if offset == bytes.len { return true; }
        let result = terminal_posix::write_step(fd, bytes[offset..]);
        offset += result.written;
        if result.cleanup_error != 0 { return false; }
        if result.error == terminal_posix::WriteError.Interrupted { continue; }
        if result.error != terminal_posix::WriteError.None || result.written == 0 { return false; }
    }
    return offset == bytes.len;
}
// No helper here exits or emits diagnostics while a process owner is live.
fn cohort(ids: const i64[:], executables: const (const u8[:])[:],
          args: const (const u8[:])[:], cwd: const u8[:], timeout_ms: i64,
          scheduler: task::Scheduler&) -> Result {
    var a = process::Child { .. }; var b = process::Child { .. };
    var c = process::Child { .. }; var d = process::Child { .. };
    var e = process::Child { .. }; var f = process::Child { .. };
    var g = process::Child { .. }; var h = process::Child { .. };
    let children: process::Child&[8] = [a, b, c, d, e, f, g, h];
    var active:    bool[8]            = [false; 8];
    var statuses:  process::Status[8] = [process::Status { .. }; 8];
    var transfers: i64[8]             = [0; 8];
    var failed = false; var cancelled = false; var count = 0;
    var problem = Result { code: 125, failure: Failure.Supervision, .. };
    for id, slot in ids {
        let signals = platform::process_guard_take(0);
        if signals != 0 { cancelled = true; failed = signals < 0; break; }
        var argv: (const u8[:])[>..] = []; argv.push(executables[id]);
        for arg in args { argv.push(arg); }
        let options = process::Options { cwd: cwd, timeout_ms: timeout_ms, output_limit: STREAM_LIMIT,
            stdin: process::Input.Null, stdout: process::Output.Capture, stderr: process::Output.Capture, .. };
        let status = process::start(argv, options, children[slot]);
        statuses[slot] = status; count++;
        if status.unreaped_pid > 0 { transfers[slot] = status.unreaped_pid; }
        if status.error != process::Error.None || status.unreaped_pid > 0 { problem = failure(status, id); failed = true; break; }
        active[slot] = true;
    }
    var cursor = 0;
    while !failed && !cancelled {
        let signals = platform::process_guard_take(0);
        if signals != 0 { cancelled = true; failed = signals < 0; break; }
        var remaining = false;
        for slot in count {
            if !active[slot] { continue; }
            let status, done = process::step(children[slot], 0);
            statuses[slot] = status;
            if status.unreaped_pid > 0 { transfers[slot] = status.unreaped_pid; }
            if status.error != process::Error.None || status.unreaped_pid > 0 { problem = failure(status, ids[slot]); failed = true; break; }
            if done { active[slot] = false; } else { remaining = true; }
        }
        if failed || !remaining { break; }
        // One rotating short wait per sweep avoids spinning without delaying
        // service of every other child by a full wait per owner.
        for offset in count {
            let slot = (cursor + offset) % count;
            if !active[slot] { continue; }
            let status, done = process::step(children[slot], 10);
            statuses[slot] = status;
            if status.unreaped_pid > 0 { transfers[slot] = status.unreaped_pid; }
            if status.error != process::Error.None || status.unreaped_pid > 0 { problem = failure(status, ids[slot]); failed = true; }
            if done { active[slot] = false; }
            cursor = (slot + 1) % count; break;
        }
    }
    // Close all owners before possibly blocking on a transferred PID recovery.
    for slot in count {
        let closed = process::close(children[slot]);
        if closed.unreaped_pid > 0 { transfers[slot] = closed.unreaped_pid; }
        if closed.error != process::Error.None || closed.unreaped_pid > 0 { if !failed { problem = failure(closed, ids[slot]); } failed = true; }
    }
    for slot in count { if transfers[slot] > 0 { platform::process_recover(transfers[slot]); } }
    var code = 0; var target = -1;
    for id, slot in ids {
        let success = slot < count && !cancelled && !failed && process::success(statuses[slot]);
        if task::finish(scheduler, id, success).kind != task::ErrorKind.None { if !failed { problem = Result { code: 125, failure: Failure.Supervision, target: id }; } failed = true; }
        if slot < count && code == 0 { code = platform::process_status(statuses[slot]); if code != 0 { target = id; } }
    }
    // Even exceptional paths replay only after cleanup. Captured prefixes are
    // retained; neither truncation nor killed siblings are reported as success.
    for slot in count {
        if !write_output(1, process::stdout(children[slot])) { problem = Result { code: 125, failure: Failure.Output, target: ids[slot] }; failed = true; break; }
        if !write_output(2, process::stderr(children[slot])) { problem = Result { code: 125, failure: Failure.Output, target: ids[slot] }; failed = true; break; }
    }
    if failed { return problem; }
    if cancelled { return Result { code: 125, .. }; }
    return Result { code: code, target: target, .. };
}
fn run(executables: const (const u8[:])[:], args: const (const u8[:])[:], cwd: const u8[:],
       jobs: i64, timeout_ms: i64, display: presentation::Output&) -> Result {
    if jobs < 1 || jobs > MAX_JOBS || timeout_ms < 1 || timeout_ms > process::MAX_TIMEOUT_MS || executables.len > MAX_TARGETS { return Result { code: 125, failure: Failure.Supervision, .. }; }
    var limits = task::Limits { tasks: MAX_TARGETS, edges: 0 };
    var scheduler = task::Scheduler { .. };
    if task::start(scheduler, executables.len, [], jobs, limits).kind != task::ErrorKind.None { return Result { code: 125, failure: Failure.Supervision, .. }; }
    if !platform::flush_stdout() { return Result { code: 125, failure: Failure.Output, .. }; }
    if !platform::process_guard_begin() { return Result { code: 125, failure: Failure.Supervision, .. }; }
    var result = Result { .. }; var completed = 0;
    loop {
        var ids: i64[>..] = [];
        let remaining = executables.len - completed;
        let count = if jobs < remaining { jobs } else { remaining };
        for slot in count {
            let next = task::take(scheduler);
            if next.kind == task::DispatchKind.Done { break; }
            if next.kind != task::DispatchKind.Ready { result = Result { code: 125, failure: Failure.Supervision, .. }; break; }
            ids.push(next.task);
        }
        if result.code != 0 || ids.len == 0 { break; }
        result = cohort(ids, executables, args, cwd, timeout_ms, scheduler);
        completed += ids.len;
        if result.code != 0 { break; }
        presentation::progress(display, completed, executables.len, "test");
    }
    let cancellation = platform::process_guard_end();
    if cancellation < 0 { return Result { code: 125, failure: Failure.Supervision, .. }; }
    if cancellation > 0 { return Result { code: 128 + cancellation, .. }; }
    return result;
}

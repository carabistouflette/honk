// SPDX-License-Identifier: Apache-2.0
// Optional command presentation. Complete snapshots never span child output.
namespace presentation;
import posix;
import std;
import os;

enum Mode { Never, Auto, Always }
struct Output { mode: Mode = Mode.Never, failed: bool = false, scratch: u8[>..] }
fn mode(value: const u8[:]) -> Mode {
    if value == "auto" { Mode.Auto } else if value == "always" { Mode.Always } else { Mode.Never }
}
fn enabled(output: Output&, snapshot: terminal_posix::Snapshot) -> bool {
    !output.failed && output.mode != Mode.Never && (output.mode == Mode.Always || snapshot.tty)
}
// Bounded attempts; partial bytes are never replayed. This is optional output:
// failures suppress later snapshots without replacing command/child outcomes.
// A blocking stderr may block; the adapter deliberately leaves its flags alone.
fn send(output: Output&) {
    // Child diagnostics may end mid-line. Begin a fresh line without erasing
    // those bytes; snapshots never issue cursor controls.
    insert_at(output.scratch, 0, '\n');
    var offset: i64 = 0;
    for attempt in 64 {
        let result = terminal_posix::write_step(2, output.scratch[offset..]);
        offset += result.written;
        // A failed signal-mask restoration must not leak into later children.
        if result.cleanup_error != 0 { exit(1); }
        if result.error == terminal_posix::WriteError.Interrupted { continue; }
        if result.error != terminal_posix::WriteError.None { output.failed = true; return; }
        if offset == output.scratch.len { return; }
        if result.written == 0 { output.failed = true; return; }
    }
    output.failed = true;
}
fn summary(output: Output&, message: const u8[:]) {
    if output.failed || output.mode == Mode.Never { return; }
    let snapshot = terminal_posix::snapshot(2);
    if !enabled(output, snapshot) { return; }
    if terminal::line(snapshot.capabilities, terminal::Style.Success, message, output.scratch) == terminal::Error.None { send(output); }
}
fn progress(output: Output&, completed: i64, total: i64, label: const u8[:]) {
    if output.failed || output.mode == Mode.Never || total == 0 { return; }
    let snapshot = terminal_posix::snapshot(2);
    if !enabled(output, snapshot) { return; }
    // Complete snapshots require no transient state and leave child diagnostics
    // intact. Re-probe for every snapshot so resizing changes the next frame.
    var caps = snapshot.capabilities; caps.redraw = false;
    if terminal::progress(caps, completed, total, 12, label, true, output.scratch) == terminal::Error.None { send(output); }
    else { summary(output, "Completed target"); }
}

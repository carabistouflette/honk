// SPDX-License-Identifier: Apache-2.0
namespace platform;
import std;
import os;
extern fn real(path: const u8[:], out: u8[>..]&) -> bool = "honk_real";
extern fn list(path: const u8[:], out: u8[>..]&) -> bool = "honk_list";
extern fn kind(path: const u8[:]) -> i64 = "honk_kind";
extern fn mkdir(path: const u8[:]) -> bool = "honk_mkdir";
extern fn read(path: const u8[:], out: u8[>..]&) -> bool = "honk_read";
extern fn install(from: const u8[:], to: const u8[:], force: bool) -> bool = "honk_install";
extern fn write(path: const u8[:], data: const u8[:], executable: bool, exclusive: bool) -> bool = "honk_write";
extern fn lock(path: const u8[:]) -> i64 = "honk_lock";
extern fn unlock(fd: i64) = "honk_unlock";
extern fn spawn(packed: const u8[:], cwd: const u8[:], capture: bool, out: u8[>..]&) -> i64 = "honk_spawn";
extern fn copy_tree(from: const u8[:], to: const u8[:]) -> bool = "honk_copy";
extern fn remove_tree(path: const u8[:]) -> bool = "honk_remove";
fn die(message: u8[:]) {
    var out = str("honk: ");
    for c, i in message {
        if i >= 4096 { out.append("..."); break; }
        if c < 32 || c >= 127 { out.append("\\x"); out.push("0123456789abcdef"[c >> 4]); out.push("0123456789abcdef"[c & 15]); }
        else { out.push(c); }
    }
    out.push('\n'); write_stderr(out); exit(1);
}
fn require(ok: bool, message: u8[:]) { if !ok { die(message); } }
fn absolute(path: u8[:]) -> u8[>..] {
    var out: u8[>..] = []; require(real(path, out), str("cannot resolve path: ", path)); return out;
}
fn load(path: u8[:]) -> u8[>..] {
    var out: u8[>..] = []; require(read(path, out), str("cannot read regular file (limit 1 MiB): ", path)); return out;
}
fn save(path: u8[:], data: u8[:]) { require(write(path, data, false, false), str("cannot atomically write: ", path)); }
fn pack(out: u8[>..]&, s: u8[:]) {
    for c in s { if c == 0 { die("NUL byte in process argument"); } }
    out.append(s); out.push(0);
}
fn command(args: const u8[:][:], cwd: u8[:], capture: bool = false) -> u8[>..], i64 {
    var packed: u8[>..] = []; for a in args { pack(packed, a); }
    var out:    u8[>..] = []; let status = spawn(packed, cwd, capture, out); return out, status;
}
fn run(args: const u8[:][:], cwd: u8[:]) {
    let out, status = command(args, cwd); if status != 0 { exit(status); }
}
fn git(args: const u8[:][:], cwd: u8[:]) -> u8[>..] {
    var packed: u8[>..] = [];
    for a in ["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never", "-c", "protocol.file.allow=never"] { pack(packed, a); }
    for a in args { pack(packed, a); }
    var out: u8[>..] = []; let code = spawn(packed, cwd, true, out);
    if code != 0 { die(str("git failed (exit ", code, ")")); }
    while out.len > 0 && (out[out.len - 1] == '\n' || out[out.len - 1] == '\r') { out.pop(); }
    return out;
}

// SPDX-License-Identifier: Apache-2.0
namespace platform;
import .diagnostics;
import std;
import process;
import os;
extern fn cache_open(path: const u8[:], limit: i64) -> i64 = "honk_cache_open";
extern fn cache_read(descriptor: i64, buffer: u8[:]) -> i64 = "honk_cache_read";
extern fn cache_close(descriptor: i64) -> bool = "honk_cache_close";
extern fn cache_private(path: const u8[:], directory: bool) -> bool = "honk_cache_private";
extern fn cache_seal(path: const u8[:]) -> bool = "honk_cache_seal";
extern fn cache_executable(path: const u8[:]) -> bool = "honk_cache_executable";
extern fn cache_environment(out: u8[>..]&) -> bool = "honk_cache_environment";
extern fn metadata_begin() -> bool = "honk_metadata_begin";
extern fn metadata_end() -> bool = "honk_metadata_end";
extern fn flush_stdout() -> bool = "honk_flush_stdout";
extern fn real(path: const u8[:], out: u8[>..]&) -> bool = "honk_real";
extern fn list(path: const u8[:], out: u8[>..]&) -> bool = "honk_list";
extern fn directory(base: const u8[:], relative: const u8[:]) -> bool = "honk_directory";
extern fn kind(path: const u8[:]) -> i64 = "honk_kind";
extern fn mkdir(path: const u8[:]) -> bool = "honk_mkdir";
extern fn read(path: const u8[:], out: u8[>..]&) -> bool = "honk_read";
extern fn read_staged(path: const u8[:], out: u8[>..]&) -> bool = "honk_read_staged";
extern fn install(from: const u8[:], to: const u8[:], force: bool) -> bool = "honk_install";
extern fn write(path: const u8[:], data: const u8[:], executable: bool, exclusive: bool) -> bool = "honk_write";
extern fn write_scratch(path: const u8[:], data: const u8[:]) -> bool = "honk_write_scratch";
extern fn lock(path: const u8[:]) -> i64 = "honk_lock";
extern fn unlock(fd: i64) = "honk_unlock";
extern fn watch_clock_ms() -> i64 = "honk_watch_clock_ms";
extern fn process_guard_begin() -> bool = "honk_process_guard_begin";
extern fn process_guard_take(child: i64) -> i64 = "honk_process_guard_take";
extern fn process_guard_end() -> i64 = "honk_process_guard_end";
extern fn process_recover(pid: i64) = "honk_process_recover";
fn process_status(status: process::Status) -> i64 {
    if status.error == process::Error.LaunchFailed { return if status.os_error == 2 { 127 } else { 126 }; }
    if status.error != process::Error.None { return 125; }
    if status.signal > 0 { return 128 + status.signal; }
    return if status.exit_code >= 0 { status.exit_code } else { 125 };
}
fn recover_status(status: process::Status) {
    if status.unreaped_pid > 0 { process_recover(status.unreaped_pid); }
}
fn spawn(packed: const u8[:], cwd: const u8[:], capture: bool, out: u8[>..]&, timeout_ms: i64 = 0) -> i64 {
    if packed.len < 2 || packed.len > 1048576 || packed[packed.len - 1] != 0 || packed[0] == 0 { return 125; }
    var argv: (const u8[:])[>..] = []; var start = 0;
    for c, i in packed { if c == 0 { if argv.len == 4096 { return 125; } argv.push(packed[start..i]); start = i + 1; } }
    var environment: process::EnvOverride[>..] = [];
    if argv[0] == "git" {
        environment.push(process::EnvOverride { key: "GIT_CONFIG_NOSYSTEM", value: "1" });
        environment.push(process::EnvOverride { key: "GIT_CONFIG_GLOBAL", value: "/dev/null" });
        environment.push(process::EnvOverride { key: "GIT_TERMINAL_PROMPT", value: "0" });
        environment.push(process::EnvOverride { key: "GIT_ALLOW_PROTOCOL", value: "https" });
        environment.push(process::EnvOverride { key: "HONK_GIT_SSL_VERIFY", value: "true" });
        for key in ["GIT_TEMPLATE_DIR", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_SHALLOW_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG", "GIT_REPLACE_REF_BASE", "GIT_SSL_NO_VERIFY"] {
            environment.push(process::EnvOverride { key: key, remove: true });
        }
    }
    if argv[0] == "tar" { for key in ["TAR_OPTIONS", "GZIP"] { environment.push(process::EnvOverride { key: key, remove: true }); } }
    let options = process::Options { cwd: cwd, timeout_ms: timeout_ms, output_limit: 1048576,
        stdout: if capture { process::Output.Capture } else { process::Output.Inherit },
        stderr: process::Output.Inherit, stdin: process::Input.Inherit, environment: environment[..], search_path: true, .. };
    if !process_guard_begin() { return 125; }
    // Cancellation already observed before start must not launch new work.
    let pending = process_guard_take(0);
    if pending != 0 { let cancellation = process_guard_end(); return if cancellation > 0 { 128 + cancellation } else { 125 }; }
    var child = process::Child { .. };
    var status = process::start(argv[..], options, child);
    recover_status(status);
    if status.error == process::Error.None {
        while true {
            let signals = process_guard_take(process::id(child));
            if signals < 0 { status = process::Status { error: process::Error.SystemError }; break; }
            var forwarding_failed = false;
            if (signals & 3) != 0 {
                let sent = process::send_signal(child, 2); recover_status(sent);
                if sent.error != process::Error.None && sent.error != process::Error.InvalidState { forwarding_failed = true; }
            }
            if (signals & 4) != 0 {
                let sent = process::send_signal(child, 15); recover_status(sent);
                if sent.error != process::Error.None && sent.error != process::Error.InvalidState { forwarding_failed = true; }
            }
            if forwarding_failed { status = process::Status { error: process::Error.SystemError }; break; }
            let next, complete = process::step(child, 20); status = next; recover_status(next);
            if complete || next.error != process::Error.None { break; }
        }
    }
    let closed = process::close(child); recover_status(closed);
    if status.error == process::Error.None && closed.error != process::Error.None { status = closed; }
    if capture { out.append(process::stdout(child)); }
    let cancellation = process_guard_end();
    if cancellation < 0 { return 125; }
    if cancellation > 0 { return 128 + cancellation; }
    return process_status(status);
}
extern fn copy_files(from: const u8[:], to: const u8[:], paths: const u8[:]) -> bool = "honk_copy_files";
extern fn copy_tree(from: const u8[:], to: const u8[:]) -> bool = "honk_copy";
extern fn unlink_regular(path: const u8[:]) -> bool = "honk_unlink_regular";
extern fn remove_tree(path: const u8[:]) -> bool = "honk_remove";
fn die(message: u8[:]) {
    if !diagnostics::write(diagnostics::Event.Failed, 0, 1) { write_stderr("honk: diagnostic log failed\n"); }
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
// Only after prepare has strictly validated original sources and remapped them.
fn load_staged(path: u8[:]) -> u8[>..] {
    var out: u8[>..] = []; require(read_staged(path, out), str("cannot read generated staged file (limit 8 MiB): ", path)); return out;
}
fn save(path: u8[:], data: u8[:]) { require(write(path, data, false, false), str("cannot atomically write: ", path)); }
// Only for replaceable files under private staging directories; persistent metadata uses save.
fn save_scratch(path: u8[:], data: u8[:]) { require(write_scratch(path, data), str("cannot write temporary file: ", path)); }
fn pack(out: u8[>..]&, s: u8[:]) {
    for c in s { if c == 0 { die("NUL byte in process argument"); } }
    out.append(s); out.push(0);
}
fn command(args: const u8[:][:], cwd: u8[:], capture: bool = false) -> u8[>..], i64 {
    var packed: u8[>..] = []; for a in args { pack(packed, a); }
    var out:    u8[>..] = []; let status = spawn(packed, cwd, capture, out); return out, status;
}
fn run(args: const u8[:][:], cwd: u8[:]) {
    let out, status = command(args, cwd); if status != 0 { child_exit(status); }
}
fn git(args: const u8[:][:], cwd: u8[:], timeout_ms: i64 = 0, trim: bool = true) -> u8[>..] {
    var packed: u8[>..] = [];
    for a in ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.ext.allow=never", "-c", "protocol.file.allow=never", "-c", "http.sslVerify=true"] { pack(packed, a); }
    // URL-specific settings outrank generic http.sslVerify. --config-env splits
    // at the final '=', retaining valid URL paths that themselves contain '='.
    for a in args {
        if a.len > 8 && a[..8] == "https://" { pack(packed, str("--config-env=http.", a, ".sslVerify=HONK_GIT_SSL_VERIFY")); }
    }
    for a in args { pack(packed, a); }
    var out: u8[>..] = []; let code = spawn(packed, cwd, true, out, timeout_ms);
    if code != 0 { die(str("git failed (exit ", code, ")")); }
    while trim && out.len > 0 && (out[out.len - 1] == '\n' || out[out.len - 1] == '\r') { out.pop(); }
    return out;
}

// Called after subprocess cleanup, never from a signal handler.
fn child_exit(status: i64) {
    let outcome = if status >= 0 && status <= 4294967295 { status as u32 } else { 125 as u32 };
    if !diagnostics::write(diagnostics::Event.ChildFailed, 0, outcome) { write_stderr("honk: diagnostic log failed\n"); }
    exit(status);
}

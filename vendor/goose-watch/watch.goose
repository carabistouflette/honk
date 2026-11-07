// SPDX-License-Identifier: Apache-2.0
namespace watch;
import std;

enum Error { None, InvalidInput, InvalidState, Interrupted, SystemError, End, CorruptEvent }
struct Status {
    error:         Error = Error.None,
    os_error:      i64   = 0,
    cleanup_error: i64   = 0,
    ready:         bool  = false,
}
const MODIFY = 2;
const ATTRIB = 4;
const CLOSE_WRITE = 8;
const MOVED_FROM = 64;
const MOVED_TO = 128;
const CREATE = 256;
const DELETE = 512;
const DELETE_SELF = 1024;
const MOVE_SELF = 2048;
const UNMOUNT = 8192;
const OVERFLOW = 16384;
const IGNORED = 32768;
const IS_DIRECTORY = 1073741824;
const MAX_PATH_BYTES = 4095;
const BUFFER_BYTES = 65536;
const MAX_NAME_BYTES = 255;
const MAX_TIMEOUT_MS = 60000;
struct Event { mask: i64 = 0, cookie: i64 = 0, name: u8[>..] = [] }
// Noncopyable owner. Fields are private API; never mutate them.
root struct Watcher {
    _state:  i64[8]    = [0; 8],
    _buffer: u8[65536] = [0; 65536],
}
extern fn detail_open(state: i64[:], path: const u8[:], meta: i64[:]) -> i64 = "gw_open";
extern fn detail_next(state: i64[:], buffer: u8[:], timeout_ms: i64,
                      name: u8[:], meta: i64[:]) -> i64 = "gw_next";
extern fn detail_close(state: i64[:], meta: i64[:]) -> i64 = "gw_close";
fn detail_status(code: i64, meta: const i64[:]) -> Status {
    let error = if code == 0 { Error.None } else if code == 1 { Error.InvalidInput }
        else if code == 2 { Error.InvalidState } else if code == 3 { Error.Interrupted }
        else if code == 4 { Error.SystemError } else if code == 5 { Error.End }
        else { Error.CorruptEvent };
    return Status { error: error, os_error: meta[0], cleanup_error: meta[1], ready: meta[2] != 0 };
}
fn open(watcher: Watcher&, path: const u8[:]) -> Status {
    var meta: i64[6] = [0; 6];
    let code = detail_open(watcher._state, path, meta);
    return detail_status(code, meta);
}
fn next(watcher: Watcher&, timeout_ms: i64, event: Event&) -> Status {
    var name: u8[256] = [0; 256];
    var meta: i64[6]  = [0; 6];
    let code = detail_next(watcher._state, watcher._buffer, timeout_ms, name, meta);
    event.mask = 0; event.cookie = 0; event.name.clear();
    if code == 0 && meta[2] != 0 {
        event.mask = meta[3]; event.cookie = meta[4]; event.name.append(name[..meta[5]]);
    }
    return detail_status(code, meta);
}
fn close(watcher: Watcher&) -> Status {
    var meta: i64[6] = [0; 6];
    let code = detail_close(watcher._state, meta);
    return detail_status(code, meta);
}
fn has(event: const Event&, mask: i64) -> bool { return (event.mask & mask) != 0; }

// Immutable bounded set. All fields are private API.
const MAX_DIRECTORIES = 256;
root struct WatchSet {
    _state:  i64[8]    = [0; 8],
    _map:    i64[512]  = [0; 512],
    _buffer: u8[65536] = [0; 65536],
}
struct SetEvent { directory: i64 = -1, event: Event = Event { .. } }
struct OpenSet { status: Status, failed_directory: i64 = -1 }
extern fn detail_set_open(state: i64[:], map: i64[:], packed: const u8[:], offsets: i64[:], meta: i64[:]) -> i64 = "gw_set_open";
extern fn detail_set_next(state: i64[:], map: i64[:], buffer: u8[:], timeout_ms: i64, name: u8[:], meta: i64[:]) -> i64 = "gw_set_next";
extern fn detail_set_close(state: i64[:], map: i64[:], meta: i64[:]) -> i64 = "gw_set_close";
fn open_set(owner: WatchSet&, paths: const (const u8[:])[:]) -> OpenSet {
    // Preserve a live owner even when the replacement request is invalid.
    if owner._state[0] != 0 { return OpenSet { status: Status { error: Error.InvalidState } }; }
    if paths.len < 1 || paths.len > MAX_DIRECTORIES { return OpenSet { status: Status { error: Error.InvalidInput } }; }
    for path, i in paths { if path.len > MAX_PATH_BYTES { return OpenSet { status: Status { error: Error.InvalidInput }, failed_directory: i }; } }
    var packed: u8[>..] = []; var offsets: i64[>..] = [];
    for path in paths { offsets.push(packed.len); offsets.push(path.len); packed.append(path); packed.push(0); }
    var meta: i64[8] = [0; 8];
    let code = detail_set_open(owner._state, owner._map, packed, offsets, meta);
    return OpenSet { status: detail_status(code, meta), failed_directory: meta[7] };
}
// Borrow directory descriptors through this call; never close or transfer them.
extern fn detail_set_open_fds(state: i64[:], map: i64[:], directories: const i64[:], meta: i64[:]) -> i64 = "gw_set_open_fds";
fn open_set_fds(owner: WatchSet&, directories: const i64[:]) -> OpenSet {
    var meta: i64[8] = [0; 8];
    let code = detail_set_open_fds(owner._state, owner._map, directories, meta);
    return OpenSet { status: detail_status(code, meta), failed_directory: meta[7] };
}
fn next(owner: WatchSet&, timeout_ms: i64, out: SetEvent&) -> Status {
    var name: u8[256] = [0; 256]; var meta: i64[8] = [0; 8];
    let code = detail_set_next(owner._state, owner._map, owner._buffer, timeout_ms, name, meta);
    out.directory = -1; out.event.mask = 0; out.event.cookie = 0; out.event.name.clear();
    if code == 0 && meta[2] != 0 {
        out.directory = meta[6]; out.event.mask = meta[3]; out.event.cookie = meta[4]; out.event.name.append(name[..meta[5]]);
    }
    return detail_status(code, meta);
}
fn close(owner: WatchSet&) -> Status {
    var meta: i64[8] = [0; 8]; let code = detail_set_close(owner._state, owner._map, meta);
    return detail_status(code, meta);
}

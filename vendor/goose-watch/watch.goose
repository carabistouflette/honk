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

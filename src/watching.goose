// SPDX-License-Identifier: Apache-2.0
namespace watching;
import watch;
import glob;
import process;
import .platform;
import .watch_tree;
import std;
import os;
const IGNORE_WORK = 16777216;
const IGNORE_MATCH_WORK = 4096;
struct Ignores { remaining: i64 = IGNORE_WORK, failed: bool = false, patterns: glob::Pattern[>..] = [] }
fn add_ignore(policy: Ignores&, text: const u8[:]) {
    platform::require(policy.patterns.len < 16, "watch accepts at most 16 ignore patterns");
    let pattern, status = glob::compile(text);
    platform::require(status.error == glob::Error.None, "invalid --watch-ignore glob");
    policy.patterns.push(copy(pattern));
}
// -1 matcher/path failure, 0 included, 1 excluded. Errors never imply exclusion.
fn ignored(policy: Ignores&, path: const u8[:]) -> i64 {
    for pattern in policy.patterns {
        if platform::watch_cancelled() != 0 { return -1; }
        if policy.remaining < IGNORE_MATCH_WORK { policy.failed = true; return -1; }
        policy.remaining -= IGNORE_MATCH_WORK;
        let matched, status = glob::matches(pattern, path, glob::Options { hidden: true, work_limit: IGNORE_MATCH_WORK });
        if status.error != glob::Error.None { policy.failed = true; return -1; }
        if matched { return 1; }
    }
    return 0;
}
fn ignored_event(policy: Ignores&, tree: watch_tree::Tree&, index: i64, name: const u8[:]) -> i64 {
    if policy.patterns.len == 0 { return 0; }
    var path: u8[4096] = [0; 4096];
    let length = watch_tree::path(tree._state, index, name, path);
    if length < 1 { policy.failed = true; return -1; }
    return ignored(policy, path[..length]);
}
fn decision(policy: Ignores&, tree: watch_tree::Tree&) -> bool {
    let excluded = ignored_event(policy, tree, -1, "");
    return excluded >= 0 && watch_tree::decide(tree._state, if excluded == 1 { 0 } else { 1 }) == 0;
}
const DRAIN_LIMIT = 256;
struct Run { code: i64 = 125, dirty: bool = false, lost: bool = false, stop: bool = false, repair: bool = false }
fn relevant(event: const watch::Event&) -> bool {
    return !watch::has(event, watch::IS_DIRECTORY) &&
        ends_with(event.name, ".goose") &&
        watch::has(event, watch::CLOSE_WRITE | watch::MOVED_FROM | watch::MOVED_TO | watch::DELETE);
}
// -1: stop; 0: idle; 1: dirty; 2: overflow recovered. No names are displayed.
fn changes(policy: Ignores&, owner: watch::WatchSet&, tree: watch_tree::Tree&, root_watch: watch::WatchSet&, guard_tree: watch_tree::Tree&, walk_enabled: bool, directories: const (const u8[:])[:], timeout_ms: i64) -> i64 {
    policy.remaining = IGNORE_WORK;
    if walk_enabled && !guard_ok(root_watch, guard_tree) { return if platform::watch_cancelled() != 0 { 0 } else { -1 }; }
    var out = watch::SetEvent { .. }; var dirty = false;
    for i in DRAIN_LIMIT {
        let status = watch::next(owner, if i == 0 { timeout_ms } else { 0 }, out);
        if status.error == watch::Error.Interrupted { return if dirty { 1 } else { 0 }; }
        if status.error != watch::Error.None { return -1; }
        if !status.ready { return if dirty { 1 } else { 0 }; }
        if watch::has(out.event, watch::OVERFLOW) {
            if walk_enabled { return 3; }
            let closed = watch::close(owner);
            if closed.error != watch::Error.None { return -1; }
            let reopened = watch::open_set(owner, directories);
            if reopened.status.error != watch::Error.None { return -1; }
            return 2;
        }
        if walk_enabled {
            let topology = watch_tree::event(tree._state, out.directory, out.event.name, out.event.mask);
            if topology < 0 { return -1; }
            if topology == 2 { continue; }
            if out.event.name.len > 0 {
                let excluded = ignored_event(policy, tree, out.directory, out.event.name);
                if excluded < 0 { return -1; }
                if excluded == 1 { continue; }
            }
            if topology == 1 { return 3; }
        }
        if !walk_enabled && watch::has(out.event, watch::IGNORED | watch::DELETE_SELF | watch::MOVE_SELF | watch::UNMOUNT) { return -1; }
        if !walk_enabled && policy.patterns.len > 0 && relevant(out.event) {
            let excluded = ignored(policy, out.event.name);
            if excluded < 0 { return -1; }
            if excluded == 1 { continue; }
        }
        dirty = dirty || relevant(out.event);
    }
    return if dirty { 1 } else { 0 }; // Retained records remain for the next bounded drain.
}
// Called only for a pending rerun with no active child. Loss bypasses batching.
fn settle(policy: Ignores&, owner: watch::WatchSet&, tree: watch_tree::Tree&, root_watch: watch::WatchSet&, guard_tree: watch_tree::Tree&, walk_enabled: bool, directories: const (const u8[:])[:], quiet_ms: i64) -> i64 {
    let started = platform::watch_clock_ms();
    if started < 0 { return -1; }
    var last = started; var now = started;
    loop {
        if platform::process_guard_take(0) != 0 { return -1; }
        let wait = max(0, min(100, min(quiet_ms - (now - last), 1000 - (now - started))));
        let observed = changes(policy, owner, tree, root_watch, guard_tree, walk_enabled, directories, wait);
        if observed < 0 || observed >= 2 { return observed; }
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
    return status.error == process::Error.None && status.exit_code == 0 && out == "honk 0.5.0-rc.1\n";
}
fn command(policy: Ignores&, owner: watch::WatchSet&, tree: watch_tree::Tree&, root_watch: watch::WatchSet&, guard_tree: watch_tree::Tree&, walk_enabled: bool, directories: const (const u8[:])[:], argv: const (const u8[:])[:]) -> Run {
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
            let observed = if result.stop { 0 } else if result.repair {
                if !guard_ok(root_watch, guard_tree) && platform::watch_cancelled() == 0 { -1 } else { 0 }
            } else { changes(policy, owner, tree, root_watch, guard_tree, walk_enabled, directories, 0) };
            result.repair = result.repair || observed == 3;
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
// Session guards survive candidate generations; loss fails conservatively.
fn guard_ok(owner: watch::WatchSet&, tree: watch_tree::Tree&) -> bool {
    if watch_tree::roots_valid(tree._state) < 0 { return false; }
    var out = watch::SetEvent { .. };
    for _ in 4096 {
        if platform::watch_cancelled() != 0 { return false; }
        let status = watch::next(owner, 0, out);
        if status.error == watch::Error.Interrupted { continue; }
        if status.error != watch::Error.None { return false; }
        if !status.ready { return true; }
        if watch::has(out.event, watch::OVERFLOW) || watch_tree::guard_event(tree._state, out.directory, out.event.name, out.event.mask) < 0 { return false; }
    }
    return false;
}
// A candidate is fully installed before verification. Only true idle commits it.
fn establish(policy: Ignores&, owner: watch::WatchSet&, tree: watch_tree::Tree&, root_watch: watch::WatchSet&, guard_tree: watch_tree::Tree&, roots: const (const u8[:])[:]) -> bool {
    for _ in 8 {
        if !guard_ok(root_watch, guard_tree) { return false; }
        if !watch_tree::close(tree) { return false; }
        if watch_tree::begin(tree._state) < 0 { return false; }
        var valid = true;
        for path in roots { if watch_tree::root(tree._state, path) < 0 { valid = false; break; } }
        if !valid { return false; }
        if policy.patterns.len > 0 && watch_tree::filter(tree._state) < 0 { return false; }
        policy.remaining = IGNORE_WORK;
        loop {
            if !guard_ok(root_watch, guard_tree) { return false; }
            let scanned = watch_tree::scan_step(tree._state);
            if scanned < 0 { valid = false; break; }
            if scanned == 2 && !decision(policy, tree) {
                if policy.failed { return false; }
                valid = false; break;
            }
            if scanned == 0 { break; }
        }
        if !valid { continue; }
        var descriptors: i64[256] = [0; 256];
        let count = watch_tree::fds(tree._state, descriptors);
        if count < 1 { return false; }
        if watch::open_set_fds(owner, descriptors[..count]).status.error != watch::Error.None { return false; }
        policy.remaining = IGNORE_WORK;
        if watch_tree::verify_begin(tree._state) < 0 { valid = false; }
        while valid {
            if platform::process_guard_take(0) != 0 { valid = false; break; }
            let verified = watch_tree::verify_step(tree._state);
            if verified < 0 { valid = false; break; }
            if verified == 2 && !decision(policy, tree) {
                if policy.failed { return false; }
                valid = false; break;
            }
            if verified == 0 { break; }
        }
        var out = watch::SetEvent { .. }; var idle = false;
        policy.remaining = IGNORE_WORK;
        if valid {
            for _ in 4096 {
                if platform::process_guard_take(0) != 0 { valid = false; break; }
                let status = watch::next(owner, 0, out);
                if status.error == watch::Error.Interrupted { continue; }
                if status.error != watch::Error.None { valid = false; break; }
                if !status.ready { idle = true; break; }
                if watch::has(out.event, watch::OVERFLOW) { valid = false; break; }
                let topology = watch_tree::event(tree._state, out.directory, out.event.name, out.event.mask);
                if topology < 0 { return false; }
                if topology == 2 { continue; }
                if out.event.name.len > 0 {
                    let excluded = ignored_event(policy, tree, out.directory, out.event.name);
                    if excluded < 0 { return false; }
                    if excluded == 1 { continue; }
                }
                if topology == 1 { valid = false; break; }
            }
        }
        if valid && idle && watch_tree::roots_valid(tree._state) == 0 && guard_ok(root_watch, guard_tree) { return true; }
        if watch::close(owner).error != watch::Error.None { return false; }
    }
    return false;
}
fn run(policy: Ignores&, directories: const (const u8[:])[:], argv: const (const u8[:])[:], limit: i64, debounce_ms: i64, walk_enabled: bool) -> i64 {
    platform::require(compiled_honk(), "watch requires a compiled Honk executable and /proc/self/exe");
    var first = watch::WatchSet { .. }; var second = watch::WatchSet { .. };
    var first_tree = watch_tree::Tree { .. }; var second_tree = watch_tree::Tree { .. };
    var root_watch = watch::WatchSet { .. }; var guard_tree = watch_tree::Tree { .. };
    var active = false;
    if !platform::process_guard_begin() { return 125; }
    var opened = true;
    if walk_enabled {
        opened = watch_tree::begin(guard_tree._state) == 0;
        for path in directories { if opened && watch_tree::root(guard_tree._state, path) < 0 { opened = false; } }
        var descriptors: i64[256] = [0; 256];
        let count = watch_tree::fds(guard_tree._state, descriptors);
        if opened && count > 0 { opened = watch::open_set_fds(root_watch, descriptors[..count]).status.error == watch::Error.None; }
        else { opened = false; }
        if opened { opened = establish(policy, first, first_tree, root_watch, guard_tree, directories); }
    }
    else { opened = watch::open_set(first, directories).status.error == watch::Error.None; }
    if !opened {
        let closed = watch::close(first); let tree_closed = watch_tree::close(first_tree);
        let guard_closed = watch::close(root_watch); let guard_anchors = watch_tree::close(guard_tree);
        let cancelled = platform::process_guard_end();
        if policy.failed { write_stderr("honk watch: --watch-ignore path or matcher work limit exceeded\n"); }
        write_stderr("honk watch: cannot establish complete selected-directory coverage\n");
        return if cancelled > 0 { 128 + cancelled } else { 125 };
    }
    var completed: i64 = 0; var code: i64 = 0; var dirty = true; var immediate = false; var repair = false;
    write_stderr(if walk_enabled { "honk watch: watching selected roots recursively\n" } else { "honk watch: watching selected directories (nonrecursive)\n" });
    loop {
        if platform::process_guard_take(0) != 0 { code = 125; break; }
        if repair {
            var restored = false;
            if active { restored = establish(policy, first, first_tree, root_watch, guard_tree, directories) && watch_tree::roots_valid(second_tree._state) == 0; }
            else { restored = establish(policy, second, second_tree, root_watch, guard_tree, directories) && watch_tree::roots_valid(first_tree._state) == 0; }
            if !restored { code = 125; break; }
            if active {
                let retired = watch::close(second); let anchors = watch_tree::close(second_tree);
                if retired.error != watch::Error.None || !anchors { code = 125; break; }
            } else {
                let retired = watch::close(first); let anchors = watch_tree::close(first_tree);
                if retired.error != watch::Error.None || !anchors { code = 125; break; }
            }
            active = !active; repair = false; dirty = true; immediate = true;
            write_stderr("honk watch: reconciled recursive coverage; scheduling full command\n");
        }
        let owner: watch::WatchSet&  = if active { second } else { first };
        let tree:  watch_tree::Tree& = if active { second_tree } else { first_tree };
        if dirty {
            if completed > 0 && debounce_ms > 0 && !immediate {
                write_stderr("honk watch: batching pending changes\n");
                let batched = settle(policy, owner, tree, root_watch, guard_tree, walk_enabled, directories, debounce_ms);
                if batched < 0 { code = 125; break; }
                if batched == 3 { repair = true; continue; }
                if batched == 2 { write_stderr("honk watch: events lost; reopened watch, scheduling full command\n"); }
            }
            immediate = false;
            write_stderr("honk watch: running command\n");
            let outcome = command(policy, owner, tree, root_watch, guard_tree, walk_enabled, directories, argv);
            code = outcome.code; completed++;
            if outcome.lost { write_stderr("honk watch: events lost; reopened watch, scheduling full command\n"); }
            if outcome.stop { if code == 0 { code = 125; } break; }
            if limit > 0 && completed >= limit { break; }
            if outcome.repair { repair = true; dirty = true; continue; }
            let queued = changes(policy, owner, tree, root_watch, guard_tree, walk_enabled, directories, 0);
            if queued < 0 { code = 125; break; }
            if queued == 2 { write_stderr("honk watch: events lost; reopened watch, scheduling full command\n"); }
            if queued == 3 { repair = true; dirty = true; continue; }
            dirty = outcome.dirty || queued > 0; immediate = outcome.lost || queued == 2;
            write_stderr(if dirty { "honk watch: pending changes; rerunning\n" } else { "honk watch: command finished; waiting for changes\n" });
        } else {
            let observed = changes(policy, owner, tree, root_watch, guard_tree, walk_enabled, directories, 100);
            if observed < 0 { code = 125; break; }
            if observed == 2 { write_stderr("honk watch: events lost; reopened watch, scheduling full command\n"); }
            if observed == 3 { repair = true; dirty = true; continue; }
            dirty = observed > 0; immediate = observed == 2;
        }
    }
    let closed_first = watch::close(first); let closed_second = watch::close(second);
    let anchors_first = watch_tree::close(first_tree); let anchors_second = watch_tree::close(second_tree);
    let closed_guard = watch::close(root_watch); let anchors_guard = watch_tree::close(guard_tree);
    let cancelled = platform::process_guard_end();
    if cancelled < 0 || closed_first.error != watch::Error.None || closed_second.error != watch::Error.None || !anchors_first || !anchors_second || closed_guard.error != watch::Error.None || !anchors_guard { return 125; }
    if cancelled > 0 { return 128 + cancelled; }
    if policy.failed { write_stderr("honk watch: --watch-ignore path or matcher work limit exceeded\n"); }
    if code == 125 { write_stderr("honk watch: watch or child supervision failed; stopping\n"); }
    return code;
}

// SPDX-License-Identifier: Apache-2.0
// Owner-scoped registry solving. Acquisition remains in the pinned Nest client.
namespace scoped_registry;
import std;
import nest;
import semver;
import task;
struct Request { owner: u8[], alias: u8[], registry: u8[], package: u8[], requirement: u8[] }
struct Pin { request: Request, record: nest::Record }
struct Edge { request: i64, target: i64 }
root struct State { selected: i64[>..], pending: i64[>..], requests: Request[>..], edges: Edge[>..], pins: Pin[>..], error: u8[>..], decisions: i64 = 0, work: i64 = 0 }
struct Frame { candidates: i64[512], count: i64, next: i64 = 0, cursor: i64, pending: i64, selected: i64, edges: i64 }
const MAX_WORK = 8000000;
fn spend(s: State&) -> bool { s.work++; if s.work > MAX_WORK { s.error = str("registry resolution scan budget exceeded (8000000)"); return false; } return true; }
fn key(record: const nest::Record&) -> u8[>..] { str("registry:", record.registry, "/", record.package, "@", record.version, "#", record.sha256) }
fn same_request(a: Request&, b: Request&) -> bool {
    return a.owner == b.owner && a.alias == b.alias && a.registry == b.registry && a.package == b.package && a.requirement == b.requirement;
}
fn same_record(a: const nest::Record&, b: const nest::Record&) -> bool {
    if a.registry != b.registry || a.package != b.package || a.version != b.version || a.sha256 != b.sha256 || a.url != b.url || a.entry != b.entry || a.dependencies.len != b.dependencies.len { return false; }
    var left = copy(a); var right = copy(b); left.yanked = false; right.yanked = false;
    return nest::record_text(left) == nest::record_text(right);
}
// Cargo unifies versions compatible according to caret requirements.
// https://doc.rust-lang.org/cargo/reference/resolver.html#semver-compatibility
fn compatible(a: u8[:], b: u8[:]) -> bool {
    let x, xe = semver::parse(a); let y, ye = semver::parse(b);
    if xe.kind != semver::ErrorKind.None || ye.kind != semver::ErrorKind.None || x.major != y.major { return false; }
    if x.major != "0" { return true; }
    if x.minor != y.minor { return false; }
    return x.minor != "0" || x.patch == y.patch;
}
fn allowed(s: State&, catalog: nest::Resolver&, id: i64) -> bool {
    let candidate = nest::record_at(catalog, id);
    for selected in s.selected {
        if !spend(s) { return false; }
        let record = nest::record_at(catalog, selected);
        if id != selected && record.registry == candidate.registry && record.package == candidate.package && compatible(record.version, candidate.version) { return false; }
    }
    return true;
}
fn reused(s: State&, id: i64) -> bool { for selected in s.selected { if selected == id { return true; } } return false; }
fn preferred(s: State&, record: const nest::Record&, request: Request&) -> bool {
    for pin in s.pins { if !spend(s) { return false; } if same_request(pin.request, request) && same_record(pin.record, record) { return true; } }
    return false;
}
fn enqueue(s: State&, request: Request&) -> bool {
    if s.pending.len >= 65536 { s.error = str("registry dependency work exceeds 65536 requests"); return false; }
    for known, i in s.requests { if !spend(s) { return false; } if same_request(known, request) { s.pending.push(i); return true; } }
    if s.requests.len >= 65536 { s.error = str("registry request arena exceeds 65536 entries"); return false; }
    s.pending.push(s.requests.len); s.requests.push(copy(request)); return true;
}
fn choose(s: State&, catalog: nest::Resolver&, request_id: i64, id: i64) -> bool {
    s.decisions++; if s.decisions > nest::MAX_DECISIONS { s.error = str("scoped registry resolution exceeded 100000 decisions"); return false; }
    s.edges.push(Edge { request: request_id, target: id });
    if reused(s, id) { return true; }
    if s.selected.len >= 256 { s.error = str("registry graph exceeds 256 instances"); return false; }
    s.selected.push(id); let record = nest::record_at(catalog, id); let owner = key(record);
    for dep in record.dependencies {
        var next = Request { owner: str(owner), alias: str(dep.alias), registry: str(record.registry), package: str(dep.package), requirement: str(dep.requirement) };
        if !enqueue(s, next) { return false; }
    }
    return true;
}
fn acyclic(s: State&, catalog: nest::Resolver&) -> bool {
    var edges: task::Edge[>..] = [];
    for edge in s.edges {
        var owner = -1; var target = -1;
        for id, i in s.selected {
            if !spend(s) { return false; }
            if key(nest::record_at(catalog, id)) == request_at(s, edge.request).owner { owner = i; }
            if id == edge.target { target = i; }
        }
        if owner >= 0 { edges.push(task::Edge { before: owner, after: target }); }
    }
    var limits = task::Limits { tasks: 256, edges: 65536 };
    let order, error = task::plan(s.selected.len, edges, limits); return error.kind == task::ErrorKind.None;
}
fn request_at(s: State&, index: i64) -> Request& { for request, i in s.requests { if i == index { return request; } } abort("invalid registry request index"); }
fn solve(s: State&, catalog: nest::Resolver&, roots: const Request[:], only_pins: bool, update: bool) -> bool {
    s.selected.clear(); s.pending.clear(); s.requests.clear(); s.edges.clear(); s.error.clear();
    for root in roots { var request = copy(root); if !enqueue(s, request) { return false; } }
    var frames: Frame[>..] = []; var cursor = 0; var conflict = false; var detail = str("constraints or cycle");
    loop {
        if !conflict && cursor == s.pending.len { if acyclic(s, catalog) { return true; } if s.error.len > 0 { return false; } detail = str("dependency cycle"); conflict = true; }
        if !conflict {
            let request_id = s.pending[cursor]; var request = copy(request_at(s, request_id)); cursor++;
            if !only_pins {
                let lookup = nest::Request { package: str(request.package), requirement: str(request.requirement), registry: str(request.registry) };
                if !nest::catalog(catalog, lookup) { s.error = str(catalog.error); return false; }
            }
            var candidates: i64[>..] = [];
            for record, i in catalog.records {
                if !spend(s) { return false; }
                if record.registry != request.registry || record.package != request.package || !nest::matches(request.requirement, record.version) || !allowed(s, catalog, i) { continue; }
                let pin = !update && preferred(s, record, request); if s.error.len > 0 { return false; }
                if (only_pins && !pin) || (record.yanked && !pin) { continue; }
                if !only_pins {
                    for locked in s.pins { if !spend(s) { return false; } if locked.record.registry == record.registry && locked.record.package == record.package && locked.record.version == record.version && !same_record(locked.record, record) { s.error = str("published registry metadata changed for ", record.package, " ", record.version); return false; } }
                }
                if candidates.len >= 512 { s.error = str("registry candidate limit exceeded (512)"); return false; }
                var at = candidates.len; candidates.push(i);
                while at > 0 {
                    let left = nest::record_at(catalog, candidates[at - 1]);
                    let left_reused = reused(s, candidates[at - 1]); let right_reused = reused(s, i);
                    let left_pin = !update && preferred(s, left, request); if s.error.len > 0 { return false; }
                    let lv, le = semver::parse(left.version); let rv, re = semver::parse(record.version);
                    if (left_reused && !right_reused) || (left_reused == right_reused && ((left_pin && !pin) || (left_pin == pin && semver::compare(lv, rv) >= 0))) { break; }
                    candidates[at] = candidates[at - 1]; at--;
                }
                candidates[at] = i;
            }
            if s.error.len > 0 { return false; }
            if candidates.len == 0 { detail = str(request.package, " ", request.requirement, " requested by ", request.owner, " -> ", request.alias); }
            if candidates.len == 1 {
                if !choose(s, catalog, request_id, candidates[0]) { return false; } continue;
            }
            if candidates.len > 1 {
                if frames.len >= 4096 { s.error = str("registry alternative frame limit exceeded (4096)"); return false; }
                var frame = Frame { candidates: [0; 512], count: candidates.len, cursor: cursor, pending: s.pending.len, selected: s.selected.len, edges: s.edges.len, .. };
                for id, i in candidates { frame.candidates[i] = id; } frames.push(copy(frame));
            }
            conflict = true;
        }
        while conflict {
            if frames.len == 0 { s.error = str("no compatible scoped registry graph: ", detail); return false; }
            let frame = frames[frames.len - 1];
            s.selected.resize(frame.selected); s.edges.resize(frame.edges); s.pending.resize(frame.pending); cursor = frame.cursor;
            if frame.next == frame.count { frames.pop(); continue; }
            let id = frame.candidates[frame.next]; frames[frames.len - 1].next++;
            if !choose(s, catalog, s.pending[cursor - 1], id) { return false; } conflict = false;
        }
    }
}
fn resolve(s: State&, catalog: nest::Resolver&, roots: const Request[:], locked: bool, update: bool) -> bool {
    catalog.records.clear(); catalog.catalogs.clear(); s.selected.clear(); s.pending.clear(); s.requests.clear(); s.edges.clear(); s.error.clear(); s.decisions = 0; s.work = 0;
    if !update && s.pins.len > 0 {
        for pin in s.pins {
            if !nest::valid(pin.record) { s.error = str("invalid locked registry record"); return false; }
            var found = false;
            for record in catalog.records { if !spend(s) { return false; } if record.registry == pin.record.registry && record.package == pin.record.package && record.version == pin.record.version {
                if !same_record(record, pin.record) { s.error = str("inconsistent locked registry metadata"); return false; } found = true;
            } }
            if !found { if catalog.records.len >= 8192 { s.error = str("locked registry release limit exceeded (8192)"); return false; } catalog.records.push(copy(pin.record)); }
        }
        if solve(s, catalog, roots, true, false) { return true; }
        if locked { return false; }
        catalog.records.clear(); catalog.catalogs.clear();
    } else if locked && roots.len > 0 { s.error = str("registry lock is missing or out of date"); return false; }
    if locked { return roots.len == 0; }
    return solve(s, catalog, roots, false, update);
}

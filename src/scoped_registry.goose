// SPDX-License-Identifier: Apache-2.0
// Owner-scoped registry solving. Acquisition remains in the pinned Nest client.
namespace scoped_registry;
import std;
import nest;
import semver;
import task;
struct Request { owner: u8[], alias: u8[], registry: u8[], package: u8[], requirement: u8[], features: u8[][] = [], default_features: bool = true, forwarded: u8[] = [] }
struct Pin { request: Request, record: nest::Record }
struct Edge { request: i64, target: i64 }
struct Activation { record: i64, index: i64 }
root struct State { refresh: u8[] = [], precise: u8[] = [], conflict: bool = false, target_os: u8[] = [], target_arch: u8[] = [], selected: i64[>..], pending: i64[>..], requests: Request[>..], edges: Edge[>..], pins: Pin[>..], features: Activation[>..], optional_edges: Activation[>..], error: u8[>..], decisions: i64 = 0, work: i64 = 0 }
struct Frame { candidates: i64[512], count: i64, next: i64 = 0, cursor: i64, pending: i64, selected: i64, edges: i64, features: i64, optional_edges: i64 }
const MAX_WORK = 8000000;
fn spend(s: State&, units: i64 = 1) -> bool { s.work += units; if s.work > MAX_WORK { s.error = str("registry resolution scan budget exceeded (8000000)"); return false; } return true; }
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
    if s.refresh == request.package { return false; }
    for pin in s.pins {
        if !spend(s) { return false; }
        if (same_request(pin.request, request) || (s.refresh.len > 0 && pin.request.registry == request.registry && pin.request.package == request.package)) && same_record(pin.record, record) { return true; }
    }
    return false;
}
fn enqueue(s: State&, request: Request&) -> bool {
    if s.pending.len >= 65536 { s.error = str("registry dependency work exceeds 65536 requests"); return false; }
    // A binding's owner and alias determine its declared feature requests for
    // this solve. Pins match the binding coordinates across manifest edits.
    for known, i in s.requests { if !spend(s) { return false; } if same_request(known, request) && known.forwarded == request.forwarded { s.pending.push(i); return true; } }
    if s.requests.len >= 65536 { s.error = str("registry request arena exceeds 65536 entries"); return false; }
    s.pending.push(s.requests.len); s.requests.push(copy(request)); return true;
}
fn feature_at(record: const nest::Record&, index: i64) -> const nest::Feature& {
    for feature, i in record.features { if i == index { return feature; } }
    abort("invalid registry feature index");
}
fn feature_index(record: const nest::Record&, name: u8[:]) -> i64 {
    for feature, i in record.features { if feature.name == name { return i; } }
    return -1;
}
fn missing_feature(record: const nest::Record&, request: Request&) -> u8[>..] {
    for name in request.features { if feature_index(record, name) < 0 { return str(name); } }
    return [];
}
fn enqueue_dependency(s: State&, record: const nest::Record&, dep: const nest::Dependency&, owner: u8[:], forwarded: u8[:] = "") -> bool {
    var next = if forwarded.len == 0 {
        Request { owner: str(owner), alias: str(dep.alias), registry: str(record.registry), package: str(dep.package), requirement: str(dep.requirement), features: copy(dep.features), default_features: dep.default_features, .. }
    } else {
        Request { owner: str(owner), alias: str(dep.alias), registry: str(record.registry), package: str(dep.package), requirement: str(dep.requirement), default_features: false, forwarded: str(forwarded), .. }
    };
    return enqueue(s, next);
}
// Append only the activation delta so a failed candidate can be rolled back
// along with the edges it enabled, including late requests on shared instances.
fn activate(s: State&, record: const nest::Record&, id: i64, request: Request&, owner: u8[:], fresh: bool) -> bool {
    var active:  bool[256] = [false; 256];
    var enabled: bool[256] = [false; 256];
    if !fresh {
        for feature in s.features { if !spend(s) { return false; } if feature.record == id { active[feature.index] = true; } }
        for edge in s.optional_edges { if !spend(s) { return false; } if edge.record == id { enabled[edge.index] = true; } }
    }
    var pending: i64[>..] = [];
    if !spend(s, (2 + request.features.len) * record.features.len) { return false; }
    let default_index = feature_index(record, "default");
    if request.default_features && default_index >= 0 && !active[default_index] { active[default_index] = true; pending.push(default_index); }
    for name in request.features {
        let i = feature_index(record, name);
        if !active[i] { active[i] = true; pending.push(i); }
    }
    if request.forwarded.len > 0 {
        let i = feature_index(record, request.forwarded);
        if !active[i] { active[i] = true; pending.push(i); }
    }
    var changed: bool[256] = [false; 256];
    var followups = false;
    var cursor = 0;
    while cursor < pending.len {
        let index = pending[cursor]; cursor++;
        s.features.push(Activation { record: id, index: index });
        if !spend(s, record.features.len) { return false; }
        let feature = feature_at(record, index);
        for item in feature.items {
            if !spend(s, item.len + 1) { return false; }
            let alias, name, weak = nest::forwarded_feature(item);
            let enable = item.len > 4 && item[..4] == "dep:";
            if enable || alias.len > 0 {
                let dependency = if enable { item[4..] } else { alias };
                if !spend(s, record.dependencies.len) { return false; }
                for dep, i in record.dependencies {
                    if !nest::active_on(dep, s.target_os, s.target_arch) || dep.alias != dependency { continue; }
                    if dep.optional && !enabled[i] && !weak {
                        enabled[i] = true;
                        s.optional_edges.push(Activation { record: id, index: i });
                        if !enqueue_dependency(s, record, dep, owner) { return false; }
                        changed[i] = true; followups = true;
                    }
                    if alias.len > 0 && (!dep.optional || enabled[i]) { changed[i] = true; followups = true; }
                    break;
                }
            } else {
                if !spend(s, record.features.len) { return false; }
                let i = feature_index(record, item);
                if !active[i] { active[i] = true; pending.push(i); }
            }
        }
    }
    if followups {
        // Re-read active groups so a weak request also takes effect when a
        // different group enables its edge in a later solver decision.
        for group, i in record.features {
            if !active[i] { continue; }
            for item in group.items {
                if !spend(s, item.len + 1) { return false; }
                let alias, name, weak = nest::forwarded_feature(item);
                if alias.len == 0 { continue; }
                if !spend(s, record.dependencies.len) { return false; }
                for dep, j in record.dependencies {
                    if !nest::active_on(dep, s.target_os, s.target_arch) || dep.alias != alias { continue; }
                    if changed[j] && !enqueue_dependency(s, record, dep, owner, name) { return false; }
                    break;
                }
            }
        }
    }
    return true;
}
fn choose(s: State&, catalog: nest::Resolver&, request_id: i64, id: i64) -> bool {
    s.decisions++; if s.decisions > nest::MAX_DECISIONS { s.error = str("scoped registry resolution exceeded 100000 decisions"); return false; }
    s.edges.push(Edge { request: request_id, target: id });
    let fresh = !reused(s, id);
    let record = nest::record_at(catalog, id); let owner = key(record);
    if fresh {
        if s.selected.len >= 256 { s.error = str("registry graph exceeds 256 instances"); return false; }
        s.selected.push(id);
        for dep in record.dependencies {
            if !dep.optional && nest::active_on(dep, s.target_os, s.target_arch) && !enqueue_dependency(s, record, dep, owner) { return false; }
        }
    }
    if record.features.len == 0 { return true; }
    let incoming = request_at(s, request_id);
    if incoming.features.len == 0 && !incoming.default_features { return true; }
    var request = copy(incoming);
    return activate(s, record, id, request, owner, fresh);
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
// Forwarding constrains the release already selected for this alias. A
// missing feature is a solver conflict so the original choice can backtrack.
fn forwarded_target(s: State&, request: Request&) -> i64 {
    for edge in s.edges {
        if !spend(s) { return -1; }
        if same_request(request_at(s, edge.request), request) { return edge.target; }
    }
    s.error = str("missing registry binding for forwarded feature: ", request.owner, " -> ", request.alias);
    return -1;
}
// An older release must not win just because it fits a pin considered
// earlier in the search. Try the graph with upgrades required wherever a
// newer release satisfies the selected edge's own version and features.
fn refresh_floor(s: State&, catalog: nest::Resolver&, request: Request&, strict: bool) -> u8[>..], bool {
    if s.refresh != request.package || s.precise.len > 0 { return [], false; }
    for pin in s.pins {
        if !spend(s) { return [], false; }
        if !same_request(pin.request, request) { continue; }
        if strict {
            let old, error = semver::parse(pin.record.version);
            for candidate in catalog.records {
                if !spend(s) { return [], false; }
                if candidate.yanked || candidate.registry != request.registry || candidate.package != request.package
                    || !nest::matches(request.requirement, candidate.version) { continue; }
                if !spend(s, request.features.len * (candidate.features.len + 1)) { return [], false; }
                if missing_feature(candidate, request).len > 0 { continue; }
                let newer, parse_error = semver::parse(candidate.version);
                if semver::compare(newer, old) > 0 { return str(pin.record.version), true; }
            }
        }
        return str(pin.record.version), false;
    }
    return [], false;
}
fn solve(s: State&, catalog: nest::Resolver&, roots: const Request[:], only_pins: bool, update: bool, strict_refresh: bool = false) -> bool {
    s.selected.clear(); s.pending.clear(); s.requests.clear(); s.edges.clear(); s.features.clear(); s.optional_edges.clear(); s.error.clear(); s.conflict = false;
    for root in roots { var request = copy(root); if !enqueue(s, request) { return false; } }
    var frames: Frame[>..] = []; var cursor = 0; var conflict = false; var detail = str("constraints or cycle");
    loop {
        if !conflict && cursor == s.pending.len { if acyclic(s, catalog) { return true; } if s.error.len > 0 { return false; } detail = str("dependency cycle"); conflict = true; }
        if !conflict {
            let request_id = s.pending[cursor]; var request = copy(request_at(s, request_id)); cursor++;
            if request.forwarded.len > 0 {
                let id = forwarded_target(s, request); if id < 0 { return false; }
                let record = nest::record_at(catalog, id);
                if feature_index(record, request.forwarded) >= 0 {
                    if !activate(s, record, id, request, key(record), false) { return false; }
                    continue;
                }
                detail = str("unknown feature ", request.forwarded, " in ", request.package, " requested by ", request.owner, " -> ", request.alias);
                conflict = true;
            } else {
                if !only_pins {
                    let lookup = nest::Request { package: str(request.package), requirement: str(request.requirement), registry: str(request.registry) };
                    if !nest::catalog(catalog, lookup, true) { s.error = str(catalog.error); return false; }
                }
                let exact = s.precise.len > 0 && request.package == s.refresh;
                let floor, require_newer = refresh_floor(s, catalog, request, strict_refresh);
                if s.error.len > 0 { return false; }
                let minimum, minimum_error = semver::parse(if floor.len > 0 { floor[..] } else { "0.0.0" });
                var candidates: i64[>..] = [];
                var missing:    u8[>..]  = [];
                for record, i in catalog.records {
                    if !spend(s) { return false; }
                    if record.registry != request.registry || record.package != request.package || !nest::matches(request.requirement, record.version) || !allowed(s, catalog, i) { continue; }
                    let pin = !update && preferred(s, record, request); if s.error.len > 0 { return false; }
                    if (only_pins && !pin) || (record.yanked && !pin) { continue; }
                    if !only_pins {
                        for locked in s.pins { if !spend(s) { return false; } if locked.record.registry == record.registry && locked.record.package == record.package && locked.record.version == record.version && !same_record(locked.record, record) { s.error = str("published registry metadata changed for ", record.package, " ", record.version); return false; } }
                    }
                    if exact && record.version != s.precise { continue; }
                    if floor.len > 0 {
                        let candidate, error = semver::parse(record.version);
                        let order = semver::compare(candidate, minimum);
                        if order < 0 || (order == 0 && require_newer) { continue; }
                    }
                    if request.features.len > 0 {
                        if !spend(s, request.features.len * (record.features.len + 1)) { return false; }
                        let unknown = missing_feature(record, request);
                        if unknown.len > 0 { missing = str(unknown); continue; }
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
                if candidates.len == 0 { detail = str(request.package, " ", request.requirement, " requested by ", request.owner, " -> ", request.alias); if exact { detail.append(str(" (--precise ", s.precise, ")")); } if missing.len > 0 { detail.append(str(" (unknown feature ", missing, ")")); } }
                if candidates.len == 1 {
                    if !choose(s, catalog, request_id, candidates[0]) { return false; } continue;
                }
                if candidates.len > 1 {
                    if frames.len >= 4096 { s.error = str("registry alternative frame limit exceeded (4096)"); return false; }
                    var frame = Frame { candidates: [0; 512], count: candidates.len, cursor: cursor, pending: s.pending.len, selected: s.selected.len, edges: s.edges.len, features: s.features.len, optional_edges: s.optional_edges.len, .. };
                    for id, i in candidates { frame.candidates[i] = id; } frames.push(copy(frame));
                }
                conflict = true;
            }
        }
        while conflict {
            if frames.len == 0 { s.conflict = true; s.error = str("no compatible scoped registry graph: ", detail); return false; }
            let frame = frames[frames.len - 1];
            s.selected.resize(frame.selected); s.edges.resize(frame.edges); s.pending.resize(frame.pending); cursor = frame.cursor;
            s.features.resize(frame.features); s.optional_edges.resize(frame.optional_edges);
            if frame.next == frame.count { frames.pop(); continue; }
            let id = frame.candidates[frame.next]; frames[frames.len - 1].next++;
            if !choose(s, catalog, s.pending[cursor - 1], id) { return false; } conflict = false;
        }
    }
}
fn seed_pins(s: State&, catalog: nest::Resolver&) -> bool {
    for pin in s.pins {
        if pin.record.package == s.refresh { continue; }
        if s.refresh.len > 0 {
            var covered = false;
            for saved in catalog.catalogs {
                if saved.registry == pin.record.registry && saved.package == pin.record.package { covered = true; break; }
            }
            if !covered { catalog.catalogs.push(nest::Catalog { package: str(pin.record.package), registry: str(pin.record.registry) }); }
        }
        if !nest::valid(pin.record) { s.error = str("invalid locked registry record"); return false; }
        var found = false;
        for record in catalog.records { if !spend(s) { return false; } if record.registry == pin.record.registry && record.package == pin.record.package && record.version == pin.record.version {
            if !same_record(record, pin.record) { s.error = str("inconsistent locked registry metadata"); return false; } found = true;
        } }
        if !found { if catalog.records.len >= 8192 { s.error = str("locked registry release limit exceeded (8192)"); return false; } catalog.records.push(copy(pin.record)); }
    }
    return true;
}
fn resolve(s: State&, catalog: nest::Resolver&, roots: const Request[:], locked: bool, update: bool) -> bool {
    catalog.records.clear(); catalog.catalogs.clear(); s.selected.clear(); s.pending.clear(); s.requests.clear(); s.edges.clear(); s.features.clear(); s.optional_edges.clear(); s.error.clear(); s.decisions = 0; s.work = 0;
    if s.refresh.len > 0 {
        if !seed_pins(s, catalog) { return false; }
        if solve(s, catalog, roots, false, false, true) { return true; }
        if !s.conflict { return false; }
        catalog.records.clear(); catalog.catalogs.clear();
        if solve(s, catalog, roots, false, false, true) { return true; }
        if !s.conflict || s.precise.len > 0 { return false; }
        return solve(s, catalog, roots, false, false);
    }
    if !update && s.pins.len > 0 {
        if !seed_pins(s, catalog) { return false; }
        if solve(s, catalog, roots, true, false) { return true; }
        if locked { return false; }
        catalog.records.clear(); catalog.catalogs.clear();
    } else if locked && roots.len > 0 { s.error = str("registry lock is missing or out of date"); return false; }
    if locked { return roots.len == 0; }
    return solve(s, catalog, roots, false, update);
}

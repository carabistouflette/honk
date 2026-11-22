// SPDX-License-Identifier: Apache-2.0
// One package version per graph; aliases are assigned by the consuming build tool.
namespace nest;
import std;
import toml;
import semver;
const DEFAULT_REGISTRY = "https://carabistouflette.github.io/goose-nest/index";
const VERSION = "0.1.0-alpha.1";
const MAX_PACKAGES = 256;
const MAX_DECISIONS = 100000;
struct Request { package: u8[], requirement: u8[], registry: u8[] }
struct Dependency { alias: u8[], package: u8[], requirement: u8[], optional: bool = false, features: u8[][] = [], default_features: bool = true, target_os: u8[] = [], target_arch: u8[] = [] }
struct Feature { name: u8[], items: u8[][] }
struct Record {
    package:      u8[], version: u8[], registry: u8[], url: u8[], sha256: u8[], entry: u8[],
    dependencies: Dependency[], yanked: bool = false, features: Feature[] = [],
}
struct Catalog { package: u8[], registry: u8[] }
root struct Resolver {
    cache:    u8[>..], records: Record[>..], catalogs: Catalog[>..],
    selected: i64[>..], pending: i64[>..], requests: Request[>..], locked_records: Record[>..],
    error:    u8[>..], decisions: i64 = 0, offline: bool = false, locked: bool = false, update: bool = false,
}
extern fn native_index(registry: const u8[:], package: const u8[:], cache: const u8[:], offline: bool, refresh: bool, out: u8[:]) -> i64 = "nest_index";
extern fn native_materialize(url: const u8[:], sha256: const u8[:], label: const u8[:], cache: const u8[:], offline: bool) -> bool = "nest_materialize";
extern fn native_prefetch(records: const u8[:], starts: const i64[:], cache: const u8[:]) -> bool = "nest_prefetch";
extern fn native_error(out: u8[:]) -> i64 = "nest_error";
fn last_error() -> u8[>..] {
    var out: u8[256] = [0; 256]; let n = native_error(out); return if n >= 0 { str(out[..n]) } else { str("registry operation failed") };
}
fn package_name(s: const u8[:]) -> bool {
    if s.len == 0 || s.len > 64 || s[0] < 'a' || s[0] > 'z' { return false; }
    for c in s { if !((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-') { return false; } }
    return s[s.len - 1] != '-';
}
fn alias_name(s: const u8[:]) -> bool {
    if s.len == 0 || s.len > 64 { return false; }
    for c, i in s { if !((c >= 'a' && c <= 'z') || c == '_' || (i > 0 && c >= '0' && c <= '9')) { return false; } }
    return true;
}
fn url(s: const u8[:]) -> bool {
    if s.len == 0 || s.len > 2048 { return false; }
    if !starts_with(s, "https://") && !starts_with(s, "http://127.0.0.1:") { return false; }
    for c in s { if c <= 32 || c >= 127 || c == '@' || c == '#' || c == '\\' { return false; } }
    return true;
}
fn registry_url(s: const u8[:]) -> bool { url(s) && s[s.len - 1] != '/' && find(s, "?") < 0 }
fn relative(s: const u8[:]) -> bool {
    if s.len == 0 || s.len > 1024 || s[0] == '/' { return false; }
    var start = 0;
    for c, i in s {
        if c <= 32 || c >= 127 || c == '\\' || c == ':' { return false; }
        if c == '/' { if start == i || s[start..i] == "." || s[start..i] == ".." { return false; } start = i + 1; }
    }
    return start < s.len && s[start..] != "." && s[start..] != "..";
}
fn valid_requirement(s: const u8[:]) -> bool {
    if s.len == 0 || s.len > 256 { return false; }
    let requirement, error = semver::parse_requirement(s); return error.kind == semver::ErrorKind.None;
}
fn matches(requirement: const u8[:], version: const u8[:]) -> bool {
    let req, re = semver::parse_requirement(requirement); let ver, ve = semver::parse(version);
    return re.kind == semver::ErrorKind.None && ve.kind == semver::ErrorKind.None && semver::matches(req, ver);
}
fn string(doc: toml::Document&, id: i64, key: u8[:]) -> u8[>..] {
    let child = toml::find(doc, id, key); if child < 0 || doc.nodes[child].kind != toml::Kind.String { return []; }
    return str(toml::text(doc, child));
}
fn keys(doc: toml::Document&, id: i64, allowed: const u8[:][:]) -> bool {
    if id < 0 || doc.nodes[id].kind != toml::Kind.Table { return false; }
    var child = doc.nodes[id].first;
    while child >= 0 { var known = false; for key in allowed { if key == toml::key(doc, child) { known = true; } } if !known { return false; } child = doc.nodes[child].next; }
    return true;
}
fn feature_name(name: const u8[:]) -> bool {
    if name.len == 0 || name.len > 64 || name[0] < 'a' || name[0] > 'z' { return false; }
    for c in name { if !((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_') { return false; } }
    return true;
}
fn forwarded_feature(item: const u8[:]) -> const u8[:], const u8[:], bool {
    for byte, i in item {
        if byte != '/' || i == 0 { continue; }
        let weak = item[i - 1] == '?';
        return item[..i - (if weak { 1 } else { 0 })], item[i + 1..], weak;
    }
    return "", "", false;
}
fn supported_os(name: const u8[:]) -> bool {
    return name == "linux" || name == "macos" || name == "windows" || name == "freebsd";
}
fn supported_arch(name: const u8[:]) -> bool {
    return name == "x86_64" || name == "aarch64";
}
fn target_parts(name: const u8[:]) -> const u8[:], const u8[:], bool {
    let dash = find(name, "-");
    if dash < 0 { return name, "", supported_os(name); }
    let os = name[..dash]; let arch = name[dash + 1..];
    return os, arch, supported_os(os) && supported_arch(arch);
}
fn targets_overlap(left_os: u8[:], left_arch: u8[:], right_os: u8[:], right_arch: u8[:]) -> bool {
    return (left_os.len == 0 || right_os.len == 0 || left_os == right_os)
        && (left_arch.len == 0 || right_arch.len == 0 || left_arch == right_arch);
}
fn active_on(dep: const Dependency&, target_os: u8[:], target_arch: u8[:] = "") -> bool {
    return (dep.target_os.len == 0 || dep.target_os == target_os)
        && (dep.target_arch.len == 0 || dep.target_arch == target_arch);
}
fn has_feature_metadata(record: const Record&) -> bool {
    if record.features.len > 0 { return true; }
    for dep in record.dependencies { if dep.optional || dep.features.len > 0 || !dep.default_features || dep.target_os.len > 0 || dep.target_arch.len > 0 { return true; } }
    return false;
}
fn read_feature_array(doc: toml::Document&, array: i64, out: u8[][>..]&) -> bool {
    if array < 0 { return true; }
    if doc.nodes[array].kind != toml::Kind.Array || doc.nodes[array].count > 256 { return false; }
    var item = doc.nodes[array].first;
    while item >= 0 {
        if doc.nodes[item].kind != toml::Kind.String { return false; }
        let name = toml::text(doc, item);
        if name.len == 0 || name.len > 130 { return false; }
        out.push(str(name));
        item = doc.nodes[item].next;
    }
    return true;
}
fn valid_features(record: const Record&) -> bool {
    if record.features.len > 256 { return false; }
    for dep in record.dependencies {
        if dep.features.len > 256 { return false; }
        for name in dep.features { if !feature_name(name) { return false; } }
    }
    for feature, i in record.features {
        if !feature_name(feature.name) || feature.items.len > 256 { return false; }
        for previous, j in record.features { if j < i && previous.name == feature.name { return false; } }
        for item in feature.items {
            var found = false;
            if item.len > 4 && item[..4] == "dep:" {
                for dep in record.dependencies { if dep.optional && dep.alias == item[4..] { found = true; break; } }
            } else {
                let alias, name, weak = forwarded_feature(item);
                if alias.len > 0 {
                    if !feature_name(name) { return false; }
                    for dep in record.dependencies { if dep.alias == alias && (!weak || dep.optional) { found = true; break; } }
                } else {
                    for group in record.features { if group.name == item { found = true; break; } }
                }
            }
            if !found { return false; }
        }
    }
    return true;
}
fn valid(record: const Record&) -> bool {
    let version, error = semver::parse(record.version);
    if !package_name(record.package) || !registry_url(record.registry) || !url(record.url) || !relative(record.entry) ||
        record.version.len > 64 || error.kind != semver::ErrorKind.None || version.build.len > 0 || record.sha256.len != 64 || record.dependencies.len > 256 { return false; }
    for c in record.sha256 { if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) { return false; } }
    for dep, i in record.dependencies {
        if !alias_name(dep.alias) || !package_name(dep.package) || !valid_requirement(dep.requirement) { return false; }
        if dep.target_os.len > 0 && !supported_os(dep.target_os) { return false; }
        if dep.target_arch.len > 0 && (dep.target_os.len == 0 || !supported_arch(dep.target_arch)) { return false; }
        for previous, j in record.dependencies {
            if j < i && previous.alias == dep.alias && targets_overlap(previous.target_os, previous.target_arch, dep.target_os, dep.target_arch) { return false; }
        }
    }
    return valid_features(record);
}
fn parse_record(doc: toml::Document&, id: i64, registry: u8[:], package: u8[:], feature_metadata: bool = false) -> Record, u8[>..] {
    if !keys(doc, id, ["version", "url", "sha256", "entry", "yanked", "dependencies", "features"]) { return Record { .. }, str("unknown registry record field"); }
    var record = Record { package: str(package), version: string(doc, id, "version"), registry: str(registry), url: string(doc, id, "url"), sha256: string(doc, id, "sha256"), entry: string(doc, id, "entry"), .. };
    let yanked = toml::find(doc, id, "yanked");
    if yanked >= 0 { if doc.nodes[yanked].kind != toml::Kind.Boolean { return Record { .. }, str("yanked must be a boolean"); } record.yanked = doc.nodes[yanked].boolean; }
    var features: Feature[>..] = [];
    let table = toml::find(doc, id, "features");
    if table >= 0 {
        if !feature_metadata || doc.nodes[table].kind != toml::Kind.Table || doc.nodes[table].count > 256 {
            return Record { .. }, str("invalid or unsupported feature table");
        }
        var item = doc.nodes[table].first;
        while item >= 0 {
            var values: u8[][>..] = [];
            if !read_feature_array(doc, item, values) { return Record { .. }, str("invalid feature group"); }
            features.push(Feature { name: str(toml::key(doc, item)), items: copy(values) });
            item = doc.nodes[item].next;
        }
    }
    var dependencies: Dependency[>..] = [];
    let array = toml::find(doc, id, "dependencies");
    if array >= 0 {
        if doc.nodes[array].kind != toml::Kind.Array || doc.nodes[array].count > 256 { return Record { .. }, str("invalid registry dependency list"); }
        var child = doc.nodes[array].first;
        while child >= 0 {
            if !keys(doc, child, ["alias", "package", "version", "optional", "features", "default-features", "target-os", "target-arch"]) { return Record { .. }, str("unknown dependency field"); }
            let opt = toml::find(doc, child, "optional");
            let requested = toml::find(doc, child, "features");
            let defaults = toml::find(doc, child, "default-features");
            if defaults >= 0 && doc.nodes[defaults].kind != toml::Kind.Boolean { return Record { .. }, str("default-features must be a boolean"); }
            let target = toml::find(doc, child, "target-os");
            let target_os = string(doc, child, "target-os");
            if target >= 0 && !supported_os(target_os) { return Record { .. }, str("invalid dependency target-os"); }
            let arch = toml::find(doc, child, "target-arch");
            let target_arch = string(doc, child, "target-arch");
            if arch >= 0 && (target < 0 || !supported_arch(target_arch)) { return Record { .. }, str("invalid dependency target-arch"); }
            if !feature_metadata && (opt >= 0 || requested >= 0 || defaults >= 0 || target >= 0 || arch >= 0) { return Record { .. }, str("dependency feature metadata requires schema 2"); }
            if opt >= 0 && doc.nodes[opt].kind != toml::Kind.Boolean { return Record { .. }, str("optional must be a boolean"); }
            var names: u8[][>..] = [];
            if !read_feature_array(doc, requested, names) { return Record { .. }, str("invalid requested features"); }
            dependencies.push(Dependency { alias: string(doc, child, "alias"), package: string(doc, child, "package"), requirement: string(doc, child, "version"),
                optional: opt >= 0 && doc.nodes[opt].boolean, features: copy(names), default_features: defaults < 0 || doc.nodes[defaults].boolean, target_os: str(target_os), target_arch: str(target_arch) });
            child = doc.nodes[child].next;
        }
    }
    let complete = Record { package: str(record.package), version: str(record.version), registry: str(record.registry), url: str(record.url), sha256: str(record.sha256), entry: str(record.entry), dependencies: copy(dependencies), yanked: record.yanked, features: copy(features) };
    if !valid(complete) { return Record { .. }, str("invalid registry package record"); }
    return copy(complete), [];
}
fn parse_index(input: u8[:], registry: u8[:], package: u8[:], records: Record[>..]&, feature_metadata: bool = false) -> u8[>..] {
    var doc = toml::Document { .. }; let error = toml::parse_into(input, doc); if error.len > 0 { return error; }
    if !keys(doc, 0, ["schema", "package", "releases"]) { return str("invalid registry index fields"); }
    let schema = toml::find(doc, 0, "schema"); let array = toml::find(doc, 0, "releases");
    if schema < 0 || doc.nodes[schema].kind != toml::Kind.Integer || (doc.nodes[schema].integer != 1 && !(feature_metadata && doc.nodes[schema].integer == 2)) ||
        string(doc, 0, "package") != package || array < 0 || doc.nodes[array].kind != toml::Kind.Array || doc.nodes[array].count > 512 { return str("invalid registry index schema, name, or release count"); }
    var id = doc.nodes[array].first;
    while id >= 0 {
        let record, record_error = parse_record(doc, id, registry, package, doc.nodes[schema].integer == 2); if record_error.len > 0 { return record_error; }
        for previous in records { if previous.registry == registry && previous.package == package && previous.version == record.version { return str("duplicate published version"); } }
        if records.len >= 8192 { return str("registry index work limit exceeded (8192 releases)"); }
        records.push(copy(record)); id = doc.nodes[id].next;
    }
    return [];
}
fn catalog(resolver: Resolver&, request: const Request&, feature_metadata: bool = false) -> bool {
    for loaded in resolver.catalogs { if loaded.package == request.package && loaded.registry == request.registry { return true; } }
    if resolver.catalogs.len >= MAX_PACKAGES { resolver.error = str("registry graph exceeds 256 packages"); return false; }
    var input: u8[>..] = []; input.resize(1048576, 0);
    let size = native_index(request.registry, request.package, str(resolver.cache, "/index"), resolver.offline, !resolver.offline, input[..]);
    if size < 0 { resolver.error = last_error(); return false; } input.resize(size);
    let error = parse_index(input, request.registry, request.package, resolver.records, feature_metadata);
    if error.len > 0 { resolver.error = copy(error); return false; }
    resolver.catalogs.push(Catalog { package: str(request.package), registry: str(request.registry) }); return true;
}
fn enqueue(resolver: Resolver&, request: const Request&) -> bool {
    if resolver.pending.len >= 65536 { resolver.error = str("registry dependency work limit exceeded"); return false; }
    for existing, i in resolver.requests { if existing.package == request.package && existing.requirement == request.requirement && existing.registry == request.registry { resolver.pending.push(i); return true; } }
    if resolver.requests.len >= 65536 { resolver.error = str("registry request limit exceeded"); return false; }
    resolver.pending.push(resolver.requests.len); resolver.requests.push(copy(request)); return true;
}
fn record_at(resolver: const Resolver&, index: i64) -> const Record& {
    for record, i in resolver.records { if i == index { return record; } } abort("invalid record index");
}
fn request_at(resolver: const Resolver&, index: i64) -> const Request& {
    for request, i in resolver.requests { if i == index { return request; } } abort("invalid request index");
}
fn selected(resolver: const Resolver&, request: const Request&) -> i64 {
    for index in resolver.selected { let record = record_at(resolver, index); if record.package == request.package && record.registry == request.registry { return index; } }
    return -1;
}
// Explicit frames avoid recursive ownership, stack growth, and copying the graph at each decision.
struct Frame { candidates: i64[512], count: i64, next: i64 = 0, pending: i64, cursor: i64, selected: i64 }
fn acyclic(resolver: const Resolver&) -> bool {
    var degrees: i64[256] = [0; 256]; var removed: bool[256] = [false; 256];
    for id, i in resolver.selected { let record = record_at(resolver, id); degrees[i] = record.dependencies.len; }
    var count = 0;
    loop {
        var changed = false;
        for id, i in resolver.selected {
            if removed[i] || degrees[i] != 0 { continue; }
            removed[i] = true; count++; changed = true;
            let child = record_at(resolver, id);
            for parent_id, j in resolver.selected {
                if removed[j] { continue; }
                let parent = record_at(resolver, parent_id);
                for dep in parent.dependencies { if dep.package == child.package && parent.registry == child.registry { degrees[j]--; } }
            }
        }
        if !changed { return count == resolver.selected.len; }
    }
}
fn solve(resolver: Resolver&, roots: const Request[:], use_lock: bool) -> bool {
    resolver.selected.clear(); resolver.pending.clear(); resolver.decisions = 0;
    resolver.requests.clear();
    for root in roots { if !enqueue(resolver, root) { return false; } }
    var frames: Frame[>..] = [];
    var conflict = false; var cursor = 0; var conflict_message = str("incompatible dependency constraints");
    loop {
        if !conflict && cursor == resolver.pending.len { if acyclic(resolver) { return true; } conflict_message = str("dependency cycle"); conflict = true; }
        if !conflict {
            let request = copy(request_at(resolver, resolver.pending[cursor])); cursor++;
            let existing = selected(resolver, request);
            if existing >= 0 { if matches(request.requirement, record_at(resolver, existing).version) { continue; } conflict_message = str(request.package, " requires ", request.requirement, "; selected ", record_at(resolver, existing).version); conflict = true; }
            else {
                if resolver.selected.len >= MAX_PACKAGES { resolver.error = str("registry graph exceeds 256 packages"); return false; }
                if !use_lock && !catalog(resolver, request) { return false; }
                var candidates: i64[>..] = [];
                for record, i in resolver.records {
                    if record.registry != request.registry || record.package != request.package || (!use_lock && record.yanked) || !matches(request.requirement, record.version) { continue; }
                    var at = candidates.len; candidates.push(i);
                    while at > 0 {
                        let left, le = semver::parse(record_at(resolver, candidates[at - 1]).version); let right, re = semver::parse(record.version);
                        if semver::compare(left, right) >= 0 { break; }
                        candidates[at] = candidates[at - 1]; at--;
                    }
                    candidates[at] = i;
                }
                if candidates.len == 0 { conflict_message = str("no eligible release of ", request.package, " satisfies ", request.requirement); }
                var frame = Frame { candidates: [0; 512], count: candidates.len, pending: resolver.pending.len, cursor: cursor, selected: resolver.selected.len, .. };
                for candidate, i in candidates { frame.candidates[i] = candidate; } frames.push(copy(frame));
                conflict = true;
            }
        }
        while conflict {
            if frames.len == 0 { resolver.error = str("no compatible registry graph (one version per package): ", conflict_message); return false; }
            let frame = frames[frames.len - 1];
            resolver.pending.resize(frame.pending); cursor = frame.cursor; resolver.selected.resize(frame.selected);
            if frame.next == frame.count { frames.pop(); continue; }
            let candidate = frame.candidates[frame.next]; frames[frames.len - 1].next++;
            resolver.decisions++; if resolver.decisions > MAX_DECISIONS { resolver.error = str("registry resolution exceeded 100000 candidate decisions"); return false; }
            resolver.selected.push(candidate); let record = record_at(resolver, candidate);
            for dep in record.dependencies { let request = Request { package: str(dep.package), requirement: str(dep.requirement), registry: str(record.registry) }; if !enqueue(resolver, request) { return false; } }
            conflict = false;
        }
    }
}
fn resolve(resolver: Resolver&, roots: const Request[:]) -> bool {
    resolver.error.clear(); resolver.records.clear(); resolver.catalogs.clear();
    for root in roots { if !package_name(root.package) || !registry_url(root.registry) || !valid_requirement(root.requirement) { resolver.error = str("invalid registry request"); return false; } }
    if !resolver.update && resolver.locked_records.len > 0 {
        for record in resolver.locked_records { if !valid(record) || has_feature_metadata(record) { resolver.error = str("invalid or feature-aware locked registry record"); return false; } resolver.records.push(copy(record)); }
        if solve(resolver, roots, true) { return true; }
        if resolver.locked { return false; }
        resolver.error.clear(); resolver.records.clear();
    } else if resolver.locked && roots.len > 0 { resolver.error = str("registry lock is missing or out of date"); return false; }
    return solve(resolver, roots, false);
}
// Stage verified blobs. Materialization still verifies and extracts each archive.
fn prefetch(resolver: const Resolver&, selected: const i64[:]) -> u8[>..] {
    if resolver.offline || selected.len < 2 { return []; }
    if selected.len > MAX_PACKAGES { return str("registry graph exceeds 256 packages"); }
    var records: u8[>..]  = [];
    var starts:  i64[>..] = [0];
    for id in selected {
        let record = record_at(resolver, id);
        if !valid(record) { return str("invalid package record"); }
        records.append(record.sha256);
        records.append(record.url);
        starts.push(records.len);
    }
    if !native_prefetch(records[..], starts[..], str(resolver.cache, "/packages")) { return last_error(); }
    return [];
}
fn materialize(record: const Record&, cache: u8[:], offline: bool) -> u8[>..] {
    if !valid(record) { return str("invalid package record"); }
    if !native_materialize(record.url, record.sha256, str(record.package, "-", record.version), str(cache, "/packages"), offline) { return last_error(); }
    return [];
}
fn directory(record: const Record&, cache: u8[:]) -> u8[>..] { str(cache, "/packages/", record.sha256) }
fn quoted(out: u8[>..]&, value: const u8[:]) {
    out.push('"'); for c in value { if c == '"' || c == '\\' { out.push('\\'); } if c == '\n' { out.append("\\n"); } else { out.push(c); } } out.push('"');
}
fn write_feature_array(out: u8[>..]&, values: const u8[][:]) {
    out.push('[');
    for value, i in values { if i > 0 { out.append(", "); } quoted(out, value); }
    out.push(']');
}
fn record_text(record: const Record&) -> u8[>..] {
    var out: u8[>..] = [];
    out.append("version = "); quoted(out, record.version); out.append("\nurl = "); quoted(out, record.url);
    out.append("\nsha256 = "); quoted(out, record.sha256); out.append("\nentry = "); quoted(out, record.entry);
    out.append("\nyanked = "); out.append(if record.yanked { "true" } else { "false" }); out.append("\ndependencies = [");
    for dep, i in record.dependencies {
        if i > 0 { out.append(", "); }
        out.append("{ alias = "); quoted(out, dep.alias); out.append(", package = "); quoted(out, dep.package);
        out.append(", version = "); quoted(out, dep.requirement);
        if dep.optional { out.append(", optional = true"); }
        if dep.target_os.len > 0 { out.append(", target-os = "); quoted(out, dep.target_os); }
        if dep.target_arch.len > 0 { out.append(", target-arch = "); quoted(out, dep.target_arch); }
        if !dep.default_features { out.append(", default-features = false"); }
        if dep.features.len > 0 { out.append(", features = "); write_feature_array(out, dep.features); }
        out.append(" }");
    }
    out.append("]\n");
    if record.features.len > 0 {
        out.append("features = { ");
        for feature, i in record.features {
            if i > 0 { out.append(", "); }
            quoted(out, feature.name); out.append(" = "); write_feature_array(out, feature.items);
        }
        out.append(" }\n");
    }
    return out;
}
fn locked_record(input: u8[:], registry: u8[:], package: u8[:], feature_metadata: bool = false) -> Record, u8[>..] {
    var doc = toml::Document { .. }; let error = toml::parse_into(input, doc); if error.len > 0 { return Record { .. }, copy(error); }
    return parse_record(doc, 0, registry, package, feature_metadata);
}

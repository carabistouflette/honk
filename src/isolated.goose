// SPDX-License-Identifier: Apache-2.0
// Opt-in producer for the compiler's pure-Goose graph contract.
namespace isolated;
import std;
import os;
import json;
import crypto;
import toml;
import task;
import nest;
import .deps;
import .scoped_registry;
import .project;
import .toolchain;
import .manifest;
import .platform;
import .source;
import .build;
import .build_cache;
struct Binding { owner: i64, alias: u8[], target: i64, git: u8[] = [], rev: u8[] = [], requirement: u8[] = [], selected_ref: u8[] = [], commit: u8[] = [], registry: u8[] = [], package: u8[] = [], record: u8[] = [] }
struct Pin { owner: u8[], alias: u8[], git: u8[], rev: u8[], requirement: u8[], selected_ref: u8[], commit: u8[] }
struct Package { directory: u8[], name: u8[], version: u8[], entry: u8[], ns: u8[], digest: u8[], git: u8[] = [], commit: u8[] = [], git_root: u8[] = [], subdir: u8[] = [], registry: u8[] = [], archive_sha: u8[] = [] }
struct ActiveFeature { owner: i64, name: u8[] }
root struct Graph { packages: Package[>..], bindings: Binding[>..], pins: Pin[>..], pins_loaded: bool = false, requests: scoped_registry::Request[>..], registry_pins: scoped_registry::Pin[>..], feature_rows: u8[][>..], active_features: ActiveFeature[>..], feature_bytes: i64 = 0 }
fn field(state: crypto::Sha256&, value: u8[:]) {
    platform::require(build_cache::feed(state, value), "cannot hash package snapshot");
}
fn before(a: u8[:], b: u8[:]) -> bool {
    for c, i in a { if i >= b.len { return false; } if c != b[i] { return c < b[i]; } }
    return a.len < b.len;
}
fn snapshot(p: manifest::Project&) -> u8[>..] {
    var paths: u8[][>..] = []; build::files(p.root, "", paths);
    paths.push(str("Honk.toml"));
    let sidecar = str(p.entry[..p.entry.len - 6], ".build");
    if platform::kind(str(p.root, "/", sidecar)) != 0 { paths.push(copy(sidecar)); }
    var ordered: (const u8[:])[>..] = []; for path in paths { ordered.push(path); }
    sort(ordered[..]) { a, b => before(a, b) }
    var state = crypto::Sha256 { .. }; platform::require(crypto::init(state) == crypto::Error.None, "cannot initialize snapshot hash");
    field(state, "honk-local-snapshot-v1");
    var total = 0;
    for path in ordered {
        platform::require(platform::kind(str(p.root, "/", path)) == 1, "snapshot inputs must be regular files");
        let data = platform::load(str(p.root, "/", path)); total += data.len;
        platform::require(total <= 33554432, "package snapshot exceeds 32 MiB");
        if build::suffix(path, ".goose") {
            platform::require(source::requirements(data).len == 0, "isolated mode requires manifest dependencies without sourced imports");
            var scan = source::Reader { text: data };
            loop { let token = source::token(scan); if token.start == token.end { break; }
                if !token.quoted { let word = data[token.start..token.end]; platform::require(word != "embed_file" && word != "embed_shader", "isolated snapshots do not support embedded resources yet"); }
            }
        }
        field(state, path); field(state, data);
    }
    var digest: u8[32] = [0; 32]; var hex: u8[64] = [0; 64];
    platform::require(crypto::finish(state, digest[..]) == crypto::Error.None && crypto::hex_encode(digest[..], hex[..]) == crypto::Error.None, "snapshot hash failed");
    return str(hex[..]);
}
fn namespace_of(text: u8[:]) -> u8[>..] {
    var scan = source::Reader { text: text };
    loop {
        let word = source::token(scan); if word.start == word.end { return []; }
        if !word.quoted && text[word.start..word.end] == "namespace" {
            let name = source::token(scan); let end = source::token(scan);
            platform::require(!name.quoted && manifest::module_component(text[name.start..name.end]) && text[end.start..end.end] == ";", "invalid entry namespace");
            return str(text[name.start..name.end]);
        }
        if !word.quoted && (text[word.start..word.end] == "fn" || text[word.start..word.end] == "struct" || text[word.start..word.end] == "let" || text[word.start..word.end] == "var") { return []; }
    }
}
fn visit(g: Graph&, directory: u8[:], revision: u8[:], git: u8[:] = "", commit: u8[:] = "", git_root: u8[:] = "", registry: u8[:] = "", archive_sha: u8[:] = "") -> i64 {
    let root = platform::absolute(directory);
    for pkg, i in g.packages { if pkg.directory == root && pkg.git == git && pkg.commit == commit && pkg.registry == registry && pkg.archive_sha == archive_sha { return i; } }
    platform::require(g.packages.len < 256, "isolated graph limit is 256 packages");
    var p = manifest::Project { .. }; manifest::load(root, p, true);
    let qualified_base = g.packages.len > 0 && p.revision == "eadca409f68210893f366e60d0c2f0dc29a339be";
    platform::require(p.name.len > 0 && (p.revision.len == 0 || p.revision == revision || qualified_base), "isolated package needs a package manifest and matching compiler revision");
    let text = platform::load(str(root, "/", p.entry));
    let id = g.packages.len;
    g.packages.push(Package { directory: str(root), name: str(p.name), version: str(p.version), entry: str(p.entry), ns: namespace_of(text), digest: snapshot(p), git: str(git), commit: str(commit), git_root: str(git_root), subdir: if git.len > 0 && root != git_root { str(root[git_root.len + 1..]) } else { str("") }, registry: str(registry), archive_sha: str(archive_sha), .. });
    return id;
}
fn render(g: Graph&, revision: u8[:], root_id: i64, graph_features: bool) -> u8[>..] {
    var out = str("{\"schema\":\"goose-package-graph-v1\",\"compiler_revision\":"); manifest::quoted(out, revision);
    out.append(",\"root\":"); manifest::quoted(out, str(root_id)); out.append(",\"nodes\":[");
    var reachable: bool[256] = [false; 256]; reachable[root_id] = true;
    loop {
        var changed = false;
        for binding in g.bindings {
            if reachable[binding.owner] && !reachable[binding.target] { reachable[binding.target] = true; changed = true; }
        }
        if !changed { break; }
    }
    var first_node = true;
    for pkg, i in g.packages {
        if !reachable[i] { continue; }
        if !first_node { out.push(','); } first_node = false;
        out.append("{\"key\":"); manifest::quoted(out, str(i));
        let locator: u8[>..] = if pkg.registry.len > 0 { str("registry:", pkg.registry, "/", pkg.name) } else if pkg.git.len > 0 { str("git:", pkg.git) } else { str("path:", pkg.name) };
        out.append(",\"source\":{\"locator\":"); manifest::quoted(out, locator);
        let source_revision: u8[>..] = if pkg.registry.len > 0 { str("sha256:", pkg.archive_sha) } else if pkg.git.len > 0 { str(pkg.commit) } else { str("snapshot:", pkg.digest) };
        out.append(",\"revision\":"); manifest::quoted(out, source_revision);
        out.append(",\"name\":"); manifest::quoted(out, pkg.name); out.append(",\"subdir\":"); manifest::quoted(out, pkg.subdir); out.append("},\"directory\":"); manifest::quoted(out, pkg.directory);
        out.append(",\"entry\":"); manifest::quoted(out, pkg.entry); out.append(",\"entry_namespace\":"); manifest::quoted(out, pkg.ns);
        out.append(",\"config\":{");
        if graph_features {
            var names: (const u8[:])[>..] = [];
            for feature in g.active_features { if feature.owner == i { names.push(feature.name); } }
            if names.len > 0 {
                sort(names[..]) { a, b => before(a, b) }
                out.append("\"features\":[");
                for name, j in names { if j > 0 { out.push(','); } manifest::quoted(out, name); }
                out.push(']');
            }
        }
        out.append("},\"bindings\":{"); var first = true;
        for binding in g.bindings { if binding.owner == i { if !first { out.push(','); } first = false; manifest::quoted(out, binding.alias); out.push(':'); manifest::quoted(out, str(binding.target)); } }
        out.append("}}");
    }
    out.append("]}\n"); platform::require(out.len <= manifest::MAX_INPUT_BYTES, "isolated graph exceeds 1 MiB"); return out;
}
// Locks record source coordinates and dependency edges, not mutable path contents.
fn coordinate(base: u8[:], path: u8[:]) -> u8[>..] {
    var ancestor = str(base); var up = 0;
    loop {
        let prefix = if ancestor == "/" { str("/") } else { str(ancestor, "/") };
        if path == ancestor || (path.len > prefix.len && path[..prefix.len] == prefix) {
            var out: u8[>..] = []; for i in up { out.append("../"); }
            if path == ancestor { if out.len > 0 { out.pop(); } else { out.append("."); } }
            else { out.append(path[prefix.len..]); }
            return out;
        }
        let parent = project::parent(ancestor);
        platform::require(parent != ancestor && parent.len > 0, "cannot relativize isolated package directory");
        ancestor = str(parent); up++;
    }
}
fn sorted_rows(out: u8[>..]&, rows: u8[][>..]&) {
    var order: (const u8[:])[>..] = []; for row in rows { order.push(row); }
    sort(order[..]) { a, b => before(a, b) }
    for row in order { out.append(row); }
}
fn package_key(pkg: Package&, base: u8[:]) -> u8[>..] {
    if pkg.registry.len > 0 { return str("registry:", pkg.registry, "/", pkg.name, "@", pkg.version, "#", pkg.archive_sha); }
    if pkg.git.len == 0 { return coordinate(base, pkg.directory); }
    return str("git:", pkg.git, "@", pkg.commit, if pkg.subdir.len > 0 { str("/", pkg.subdir) } else { str("") });
}
fn read_pins(g: Graph&, p: manifest::Project&) {
    if g.pins_loaded { return; } g.pins_loaded = true;
    let path = str(p.root, "/Honk.lock"); if platform::kind(path) == 0 { return; }
    let previous = platform::load(path); var doc = toml::Document { .. }; let error = toml::parse_into(previous, doc);
    platform::require(error.len == 0, "invalid existing lockfile; original is unchanged");
    let version = toml::find(doc, 0, "version");
    platform::require(version >= 0 && doc.nodes[version].kind == toml::Kind.Integer && doc.nodes[version].integer == 2, "isolated mode requires a version-2 lockfile; legacy lockfile is unchanged");
    manifest::keys(doc, 0, ["version", "mode", "compiler", "package", "binding", "members", "feature"]);
    platform::require(manifest::string(doc, 0, "mode") == "isolated", "incompatible lockfile mode");
    let bindings = toml::find(doc, 0, "binding"); if bindings < 0 { return; }
    platform::require(doc.nodes[bindings].kind == toml::Kind.Array, "invalid lock bindings");
    var row = doc.nodes[bindings].first;
    while row >= 0 {
        manifest::keys(doc, row, ["owner", "alias", "target", "git", "rev", "requirement", "selected_ref", "commit", "registry", "package", "record"]);
        let git = manifest::string(doc, row, "git"); let registry = manifest::string(doc, row, "registry");
        platform::require(git.len == 0 || registry.len == 0, "ambiguous locked source kind");
        if git.len > 0 {
            let owner = manifest::string(doc, row, "owner"); let alias = manifest::string(doc, row, "alias");
            var dep = manifest::Dependency { name: str(alias), git: str(git), rev: manifest::string(doc, row, "rev"), requirement: manifest::string(doc, row, "requirement"), .. };
            platform::require(manifest::identifier(alias), "invalid locked alias"); manifest::validate_dependency(dep);
            let commit = manifest::string(doc, row, "commit"); let selected = manifest::string(doc, row, "selected_ref");
            platform::require(manifest::commit(commit) && (dep.requirement.len > 0 || selected == dep.rev), "invalid locked Git identity");
            platform::require(!manifest::commit(dep.rev) || dep.rev == commit, "locked commit differs from exact requested commit");
            platform::require(dep.requirement.len == 0 || deps::locked_version(selected, dep.requirement), "invalid locked Git version selection");
            platform::require(manifest::string(doc, row, "target") == str("git:", git, "@", commit), "locked Git target differs from commit identity");
            for pin in g.pins { platform::require(pin.owner != owner || pin.alias != alias, "duplicate locked Git binding"); }
            platform::require(g.pins.len < 65536, "locked Git binding limit exceeded");
            g.pins.push(Pin { owner: str(owner), alias: str(alias), git: str(git), rev: str(dep.rev), requirement: str(dep.requirement), selected_ref: str(selected), commit: str(commit) });
        }
        if registry.len > 0 {
            let owner = manifest::string(doc, row, "owner"); let alias = manifest::string(doc, row, "alias"); let package = manifest::string(doc, row, "package"); let requirement = manifest::string(doc, row, "requirement");
            let record_id = toml::find(doc, row, "record");
            platform::require(record_id >= 0 && doc.nodes[record_id].kind == toml::Kind.String, "locked registry record must be a string");
            let record, error = nest::locked_record(str(toml::text(doc, record_id)), registry, package, true);
            platform::require(error.len == 0 && manifest::identifier(alias) && nest::valid_requirement(requirement) && nest::matches(requirement, record.version), "invalid locked scoped registry record");
            platform::require(manifest::string(doc, row, "target") == scoped_registry::key(record), "locked registry target differs from archive identity");
            for pin in g.registry_pins { platform::require(pin.request.owner != owner || pin.request.alias != alias, "duplicate locked registry binding"); }
            g.registry_pins.push(scoped_registry::Pin { request: scoped_registry::Request { owner: str(owner), alias: str(alias), registry: str(registry), package: str(package), requirement: str(requirement) }, record: copy(record) });
        }
        row = doc.nodes[row].next;
    }
}
fn lock_field(out: u8[>..]&, key: u8[:], value: u8[:]) { out.append(str("\n", key, " = ")); manifest::quoted(out, value); }
fn lock_text(g: Graph&, p: manifest::Project&) -> u8[>..] {
    var out = str("# Generated by Honk. Commit this file.\nversion = 2\nmode = \"isolated\"\ncompiler = "); manifest::quoted(out, p.revision); out.push('\n');
    if p.members.len > 0 {
        var members: (const u8[:])[>..] = []; for member in p.members { members.push(member); }
        sort(members[..]) { a, b => before(a, b) }
        out.append("members = [");
        for member, i in members { if i > 0 { out.append(", "); } manifest::quoted(out, member); }
        out.append("]\n");
    }
    var packages: u8[][>..] = []; var bindings: u8[][>..] = []; var bytes = out.len + g.feature_bytes;
    for pkg in g.packages {
        var row = str("\n[[package]]\ndirectory = "); manifest::quoted(row, package_key(pkg, p.root));
        row.append("\nname = "); manifest::quoted(row, pkg.name); row.append("\nversion = "); manifest::quoted(row, pkg.version);
        row.append("\nentry = "); manifest::quoted(row, pkg.entry); row.push('\n'); bytes += row.len; platform::require(bytes <= manifest::MAX_INPUT_BYTES, "isolated lockfile exceeds 1 MiB"); packages.push(copy(row));
    }
    for binding in g.bindings {
        var row = str("\n[[binding]]\nowner = ");
        for pkg, i in g.packages { if i == binding.owner { manifest::quoted(row, package_key(pkg, p.root)); } }
        row.append("\nalias = "); manifest::quoted(row, binding.alias); row.append("\ntarget = ");
        for pkg, i in g.packages { if i == binding.target { manifest::quoted(row, package_key(pkg, p.root)); } }
        if binding.git.len > 0 {
            lock_field(row, "git", binding.git); lock_field(row, "rev", binding.rev); lock_field(row, "requirement", binding.requirement); lock_field(row, "selected_ref", binding.selected_ref); lock_field(row, "commit", binding.commit);
        }
        if binding.registry.len > 0 { lock_field(row, "registry", binding.registry); lock_field(row, "package", binding.package); lock_field(row, "requirement", binding.requirement); lock_field(row, "record", binding.record); }
        row.push('\n'); bytes += row.len; platform::require(bytes <= manifest::MAX_INPUT_BYTES, "isolated lockfile exceeds 1 MiB"); bindings.push(copy(row));
    }
    sorted_rows(out, packages); sorted_rows(out, bindings); sorted_rows(out, g.feature_rows);
    platform::require(out.len <= manifest::MAX_INPUT_BYTES, "isolated lockfile exceeds 1 MiB"); return out;
}
fn lock_graph(g: Graph&, p: manifest::Project&, locked: bool) {
    let path = str(p.root, "/Honk.lock"); let desired = lock_text(g, p);
    if platform::kind(path) != 0 {
        let previous = platform::load(path);
        if previous == desired { return; }
        var doc = toml::Document { .. }; let error = toml::parse_into(previous, doc);
        platform::require(error.len == 0, "invalid existing lockfile; original is unchanged");
        let version = toml::find(doc, 0, "version");
        platform::require(version >= 0 && doc.nodes[version].kind == toml::Kind.Integer && doc.nodes[version].integer == 2, "isolated mode requires a version-2 lockfile; legacy lockfile is unchanged");
        manifest::keys(doc, 0, ["version", "mode", "compiler", "package", "binding", "members", "feature"]);
        platform::require(manifest::string(doc, 0, "mode") == "isolated", "incompatible lockfile mode; original is unchanged");
    }
    platform::require(!locked, "isolated lockfile is missing or out of date; run honk check --isolated without --locked");
    platform::save(path, desired);
}
fn record_feature(g: Graph&, owner: i64, key: u8[:], name: u8[:]) {
    var row = str("\n[[feature]]");
    lock_field(row, "owner", key); lock_field(row, "name", name); row.push('\n');
    g.feature_bytes += row.len;
    platform::require(g.feature_bytes <= manifest::MAX_INPUT_BYTES, "isolated feature lock exceeds 1 MiB");
    g.feature_rows.push(copy(row));
    g.active_features.push(ActiveFeature { owner: owner, name: str(name) });
}
fn same_names(left: const u8[][:], right: const u8[][:]) -> bool {
    if left.len != right.len { return false; }
    var names: (const u8[:])[>..] = [];
    for name in right { names.push(name); }
    for name, i in left { if name != names[i] { return false; } }
    return true;
}
struct RegistrySelection { record: i64, node: i64 }
fn apply_registry(g: Graph&, p: manifest::Project&, cache: u8[:], locked: bool, offline: bool, update: bool, graph_features: bool) {
    if g.requests.len == 0 { return; } read_pins(g, p);
    var state = scoped_registry::State { .. }; for pin in g.registry_pins { state.pins.push(copy(pin)); }
    var catalog = nest::Resolver { cache: str(cache, "/nest"), offline: offline, .. };
    platform::require(scoped_registry::resolve(state, catalog, g.requests[..], locked, update), state.error);
    platform::require(graph_features || state.features.len == 0, "registry features require a compiler with package graph feature support");
    platform::require(g.packages.len + state.selected.len <= 256 && g.bindings.len + state.edges.len <= 65536, "combined dependency graph limit exceeded");
    var selected: RegistrySelection[>..] = [];
    for id in state.selected {
        let record = nest::record_at(catalog, id);
        let error = nest::materialize(record, catalog.cache, offline); platform::require(error.len == 0, error);
        let directory = nest::directory(record, catalog.cache);
        var child = manifest::Project { .. }; manifest::load(directory, child, true);
        platform::require(child.name == record.package && child.version == record.version && child.entry == record.entry && child.kind == "lib", "archive manifest differs from registry metadata");
        var count = 0;
        for dep in child.dependencies {
            if dep.dev { continue; } count++;
            platform::require(dep.registry == record.registry, "registry archives require same-registry manifest dependencies");
            var found = false; for expected in record.dependencies { if expected.alias == dep.name && expected.package == dep.package && expected.requirement == dep.requirement && expected.optional == dep.optional && same_names(expected.features, dep.features) { found = true; break; } }
            platform::require(found, "archive dependency differs from registry metadata");
        }
        platform::require(count == record.dependencies.len, "archive dependency count differs from registry metadata");
        platform::require(child.features.len == record.features.len, "archive feature count differs from registry metadata");
        for feature in record.features {
            var found = false;
            for declared in child.features { if declared.name == feature.name && same_names(declared.items, feature.items) { found = true; break; } }
            platform::require(found, "archive feature differs from registry metadata");
        }
        let node = visit(g, directory, p.revision, "", "", "", record.registry, record.sha256);
        selected.push(RegistrySelection { record: id, node: node });
        if record.features.len > 0 {
            let key = scoped_registry::key(record);
            for feature in state.features {
                if feature.record == id { record_feature(g, node, key, scoped_registry::feature_at(record, feature.index).name); }
            }
        }
    }
    for edge in state.edges {
        let request = scoped_registry::request_at(state, edge.request);
        var owner = -1; var target = -1;
        for pkg, i in g.packages { if package_key(pkg, p.root) == request.owner { owner = i; } }
        for selection in selected { if selection.record == edge.target { target = selection.node; } }
        platform::require(owner >= 0 && target >= 0, "invalid internal registry edge");
        let record = nest::record_at(catalog, edge.target); var encoded = nest::record_text(record);
        if !update { for pin in state.pins { if scoped_registry::same_request(pin.request, request) && scoped_registry::same_record(pin.record, record) { encoded = nest::record_text(pin.record); break; } } }
        g.bindings.push(Binding { owner: owner, alias: str(request.alias), target: target, requirement: str(request.requirement), registry: str(record.registry), package: str(record.package), record: copy(encoded), .. });
    }
}
struct Target { id: i64, root: u8[], entry: u8[], name: u8[], output: u8[], kind: u8[] }
fn add_root(graph: Graph&, workspace: manifest::Project&, targets: Target[>..]&, directory: u8[:], selected: u8[:]) {
    var member = manifest::Project { .. }; manifest::load(directory, member, true);
    platform::require(member.name.len > 0 && (member.root == workspace.root || member.members.len == 0), "workspace members need a package and cannot contain nested workspaces");
    platform::require(member.revision.len == 0 || member.revision == workspace.revision, "workspace member compiler pin must match the workspace");
    let id = visit(graph, member.root, workspace.revision);
    if selected.len > 0 && member.root != selected { return; }
    var output = str(workspace.root, "/target/isolated");
    if workspace.members.len > 0 {
        // Put root and member targets in distinct directory trees.
        output.append(if member.root == workspace.root { str("/root") } else { str("/members/", id) });
    }
    targets.push(Target { id: id, root: str(member.root), entry: str(member.entry), name: str(member.name), output: copy(output), kind: str(member.kind) });
}
fn parse_features(out: u8[][>..]&, value: u8[:]) {
    var start = 0;
    for end in value.len + 1 {
        if end < value.len && value[end] != ',' { continue; }
        let name = value[start..end];
        platform::require(manifest::package_name(name) && out.len < 256, "features must be comma-separated names (limit 256)");
        out.push(str(name)); start = end + 1;
    }
}
// One state per graph instance. Work only grows, including across late requests.
struct Activation {
    requested: bool[256] = [false; 256],
    active:    bool[256] = [false; 256],
    emitted:   bool[256] = [false; 256],
    enabled:   bool[256] = [false; 256],
    dirty:     bool      = true,
}
fn request_features(state: Activation&, dep: manifest::Dependency&, directory: u8[:]) {
    if dep.features.len == 0 { return; }
    var target = manifest::Project { .. };
    manifest::load(directory, target, true);
    for name in dep.features {
        let index = manifest::feature_index(target, name);
        platform::require(index >= 0, str("unknown feature ", name, " in ", target.name, " requested through ", dep.name));
        if !state.requested[index] { state.requested[index] = true; state.dirty = true; }
    }
}
fn activate_features(graph: Graph&, owner: manifest::Project&, owner_id: i64, key: u8[:], requested: u8[][>..]&, defaults: bool, state: Activation&) {
    var pending: i64[>..] = [];
    if defaults {
        let index = manifest::feature_index(owner, "default");
        if index >= 0 { state.requested[index] = true; }
    }
    for name in requested {
        let index = manifest::feature_index(owner, name);
        platform::require(index >= 0, str("unknown feature ", name, " in ", owner.name));
        state.requested[index] = true;
    }
    for i in owner.features.len {
        if state.requested[i] && !state.active[i] { state.active[i] = true; pending.push(i); }
    }
    var cursor = 0;
    while cursor < pending.len {
        let index = pending[cursor]; cursor++;
        for feature, i in owner.features {
            if i != index { continue; }
            for item in feature.items {
                if item.len > 4 && item[..4] == "dep:" {
                    for dep, j in owner.dependencies { if dep.name == item[4..] { state.enabled[j] = true; break; } }
                } else {
                    let other = manifest::feature_index(owner, item);
                    if !state.active[other] { state.active[other] = true; pending.push(other); }
                }
            }
            record_feature(graph, owner_id, key, feature.name);
            break;
        }
    }
}
const FEATURE_COMPILER = "eeab7eebcae92d9a04b6caf43c321da560b8d269";
fn execute(p: manifest::Project&, selected: u8[:], features: u8[][>..]&, no_defaults: bool, command: u8[:], arguments: u8[:][:], release: bool, locked: bool, offline: bool) {
    platform::require(command != "update" || !locked, "update cannot be combined with --locked or --frozen");
    platform::require(p.revision == FEATURE_COMPILER || p.revision == "0ce3a5edb5679e10a490e9f66d5db5f6a30b9f63" || p.revision == "6471713c6c18f64e172c4c778ac5987a5a177358", "isolated mode requires an explicitly qualified graph compiler revision in [toolchain]");
    var compiler: u8[>..] = []; platform::require(env("GOOSE", compiler), "isolated mode requires an explicit GOOSE compiler");
    let probe: const u8[:][] = [compiler, "version", "--json"];
    let report, status = platform::command(probe, p.root, true);
    platform::require(status == 0, "graph compiler capability probe failed");
    var document: json::Node[>..] = []; var decoded: u8[>..] = []; var input = copy(report);
    let root, error = json::parse(input, document, decoded);
    platform::require(error.len == 0, "invalid graph compiler report");
    let revision, valid = json::as_string(json::member(root, "compiler_revision"));
    let schema, supported = json::as_string(json::member(root, "package_graph"));
    platform::require(valid && supported && revision == p.revision && schema == "goose-package-graph-v1", "compiler graph capability or full revision mismatch");
    let graph_features, feature_capability = json::as_bool(json::member(root, "package_graph_features"));
    platform::require(p.revision != FEATURE_COMPILER || (feature_capability && graph_features), "compiler does not advertise package graph features");
    let cache = toolchain::home(); let cache_lock = platform::lock(str(cache, "/lock")); platform::require(cache_lock >= 0, "Honk cache is locked by another process");
    platform::require(platform::mkdir(str(p.root, "/.honk")), "cannot create graph lock directory");
    let project_lock = platform::lock(str(p.root, "/.honk/isolated.lock")); platform::require(project_lock >= 0, "isolated project is locked by another process");
    var graph = Graph { .. }; var targets: Target[>..] = [];
    if p.name.len > 0 { add_root(graph, p, targets, p.root, selected); }
    var members: (const u8[:])[>..] = []; for member in p.members { members.push(member); }
    sort(members[..]) { a, b => before(a, b) }
    for member in members {
        platform::require(platform::directory(p.root, member), "workspace member must be a directory without symlink components");
        add_root(graph, p, targets, str(p.root, "/", member), selected);
    }
    let resolve_only = command == "fetch" || command == "update";
    if command == "run" { platform::require(targets.len == 1, "isolated run requires a single target, select a workspace member with -p"); }
    var compile_count = 0;
    for target in targets {
        if command == "run" || (command == "build" && selected.len > 0) {
            platform::require(target.kind == "bin", "isolated executable targets require a binary package");
        }
        if command != "build" || target.kind == "bin" { compile_count++; }
    }
    platform::require(resolve_only || compile_count > 0, "no isolated compilation target matched");
    var states: Activation[256] = [Activation { .. }; 256];
    var cursor = 0;
    while cursor < graph.packages.len {
        if !states[cursor].dirty { cursor++; continue; }
        states[cursor].dirty = false;
        var next = cursor + 1;
        var directory: u8[>..] = []; var origin: u8[>..] = []; var commit: u8[>..] = []; var git_root: u8[>..] = []; var owner_key: u8[>..] = [];
        for pkg, i in graph.packages { if i == cursor { directory = str(pkg.directory); origin = str(pkg.git); commit = str(pkg.commit); git_root = str(pkg.git_root); owner_key = package_key(pkg, p.root); } }
        var owner = manifest::Project { .. }; manifest::load(directory, owner, true);
        var empty: u8[][>..] = [];
        if directory == selected { activate_features(graph, owner, cursor, owner_key, features, !no_defaults, states[cursor]); }
        else { activate_features(graph, owner, cursor, owner_key, empty, true, states[cursor]); }
        for dep, index in owner.dependencies {
            if dep.dev || states[cursor].emitted[index] || (dep.optional && !states[cursor].enabled[index]) { continue; }
            states[cursor].emitted[index] = true;
            if dep.registry.len > 0 {
                platform::require(graph.requests.len < 65536, "registry request limit exceeded");
                graph.requests.push(scoped_registry::Request { owner: str(owner_key), alias: str(dep.name), registry: str(dep.registry), package: str(dep.package), requirement: str(dep.requirement), features: copy(dep.features) }); continue;
            }
            var target = -1;
            if dep.git.len > 0 {
                read_pins(graph, p);
                var materialized = deps::Graph { cache: str(cache), locked: locked, offline: offline, update: command == "update", .. };
                for pin in graph.pins { if pin.owner == owner_key && pin.alias == dep.name && pin.git == dep.git && pin.rev == dep.rev && pin.requirement == dep.requirement {
                    materialized.old.push(deps::Node { name: str(dep.name), path: [], git: str(pin.git), rev: str(pin.selected_ref), commit: str(pin.commit), directory: [], entry: [], visiting: false, requirement: str(pin.requirement), .. });
                } }
                // Resolve an unlocked source request only once in this invocation.
                // Owner-specific locked pins still take precedence, including distinct pins.
                if !locked && (command == "update" || materialized.old.len == 0) {
                    for prior in graph.bindings {
                        if prior.git == dep.git && prior.rev == dep.rev && prior.requirement == dep.requirement {
                            materialized.old.clear();
                            materialized.old.push(deps::Node { name: str(dep.name), path: [], git: str(prior.git), rev: str(prior.selected_ref), commit: str(prior.commit), directory: [], entry: [], visiting: false, requirement: str(prior.requirement), .. });
                            materialized.update = false; break;
                        }
                    }
                }
                var registry = nest::Resolver { .. }; deps::add(materialized, dep, directory, registry, true);
                for node in materialized.nodes {
                    target = visit(graph, node.directory, p.revision, dep.git, node.commit, node.directory);
                    request_features(states[target], dep, node.directory);
                    graph.bindings.push(Binding { owner: cursor, alias: str(dep.name), target: target, git: str(dep.git), rev: str(dep.rev), requirement: str(dep.requirement), selected_ref: str(node.rev), commit: str(node.commit) });
                }
            } else {
                let candidate = if dep.path[0] == '/' { str(dep.path) } else { str(directory, "/", dep.path) };
                let path = platform::absolute(candidate);
                if origin.len > 0 { platform::require(path == git_root || (path.len > git_root.len && path[..git_root.len] == git_root && path[git_root.len] == '/'), "Git path dependency escapes its checkout"); }
                target = visit(graph, path, p.revision, origin, commit, git_root);
                request_features(states[target], dep, path);
                graph.bindings.push(Binding { owner: cursor, alias: str(dep.name), target: target, .. });
            }
            if states[target].dirty && target < next { next = target; }
        }
        cursor = next;
    }
    apply_registry(graph, p, cache, locked, offline, command == "update", feature_capability && graph_features);
    var edges: task::Edge[>..] = []; for binding in graph.bindings { edges.push(task::Edge { before: binding.owner, after: binding.target }); }
    var limits = task::Limits { tasks: 256, edges: 65536 };
    let order, graph_error = task::plan(graph.packages.len, edges, limits);
    platform::require(graph_error.kind == task::ErrorKind.None, "isolated dependency cycle or graph limit exceeded");
    // Validate every selected graph before changing the shared lock.
    var documents: u8[][>..] = [];
    for target in targets { documents.push(render(graph, p.revision, target.id, feature_capability && graph_features)); }
    lock_graph(graph, p, locked);
    for target, i in targets {
        if command == "build" && target.kind != "bin" { continue; }
        // Resolution-only workspace commands have no compiler output.
        if resolve_only && p.members.len > 0 { break; }
        platform::require(platform::mkdir(target.output), "cannot create isolated build directory");
        let path = str(target.output, "/graph.json");
        for document, j in documents { if i == j { platform::save(path, document); break; } }
        if resolve_only { break; }
        var words: u8[][>..] = [str(compiler), str(command), str(target.root, "/", target.entry), str("--package-graph"), str(path)];
        if command == "build" { words.push(str("-o")); words.push(str(target.output, "/", target.name)); }
        if release { words.push(str("-O2")); }
        if arguments.len > 0 { words.push(str("--")); for argument in arguments { words.push(str(argument)); } }
        var argv: (const u8[:])[>..] = []; for word in words { argv.push(word); }
        platform::run(argv[..], target.root);
    }
    platform::unlock(project_lock); platform::unlock(cache_lock);
}

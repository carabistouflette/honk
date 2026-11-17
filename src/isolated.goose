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
import .project;
import .toolchain;
import .manifest;
import .platform;
import .source;
import .build;
import .build_cache;
struct Binding { owner: i64, alias: u8[], target: i64, git: u8[] = [], rev: u8[] = [], requirement: u8[] = [], selected_ref: u8[] = [], commit: u8[] = [] }
struct Pin { owner: u8[], alias: u8[], git: u8[], rev: u8[], requirement: u8[], selected_ref: u8[], commit: u8[] }
struct Package { directory: u8[], name: u8[], version: u8[], entry: u8[], ns: u8[], digest: u8[], git: u8[] = [], commit: u8[] = [], git_root: u8[] = [], subdir: u8[] = [] }
root struct Graph { packages: Package[>..], bindings: Binding[>..], pins: Pin[>..], pins_loaded: bool = false }
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
fn visit(g: Graph&, directory: u8[:], revision: u8[:], git: u8[:] = "", commit: u8[:] = "", git_root: u8[:] = "") -> i64 {
    let root = platform::absolute(directory);
    for pkg, i in g.packages { if pkg.directory == root { platform::require(pkg.git == git && pkg.commit == commit, "one directory has conflicting source identities"); return i; } }
    platform::require(g.packages.len < 256, "isolated graph limit is 256 packages");
    var p = manifest::Project { .. }; manifest::load(root, p);
    platform::require(p.name.len > 0 && (p.revision.len == 0 || p.revision == revision), "isolated package needs a package manifest and matching compiler revision");
    let text = platform::load(str(root, "/", p.entry));
    let id = g.packages.len;
    g.packages.push(Package { directory: str(root), name: str(p.name), version: str(p.version), entry: str(p.entry), ns: namespace_of(text), digest: snapshot(p), git: str(git), commit: str(commit), git_root: str(git_root), subdir: if git.len > 0 && root != git_root { str(root[git_root.len + 1..]) } else { str("") }, .. });
    return id;
}
fn render(g: Graph&, revision: u8[:]) -> u8[>..] {
    var out = str("{\"schema\":\"goose-package-graph-v1\",\"compiler_revision\":"); manifest::quoted(out, revision);
    out.append(",\"root\":\"0\",\"nodes\":[");
    for pkg, i in g.packages {
        if i > 0 { out.push(','); }
        out.append("{\"key\":"); manifest::quoted(out, str(i));
        let locator: u8[>..] = if pkg.git.len > 0 { str("git:", pkg.git) } else { str("path:", pkg.name) };
        out.append(",\"source\":{\"locator\":"); manifest::quoted(out, locator);
        let source_revision: u8[>..] = if pkg.git.len > 0 { str(pkg.commit) } else { str("snapshot:", pkg.digest) };
        out.append(",\"revision\":"); manifest::quoted(out, source_revision);
        out.append(",\"name\":"); manifest::quoted(out, pkg.name); out.append(",\"subdir\":"); manifest::quoted(out, pkg.subdir); out.append("},\"directory\":"); manifest::quoted(out, pkg.directory);
        out.append(",\"entry\":"); manifest::quoted(out, pkg.entry); out.append(",\"entry_namespace\":"); manifest::quoted(out, pkg.ns);
        out.append(",\"config\":{},\"bindings\":{"); var first = true;
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
    manifest::keys(doc, 0, ["version", "mode", "compiler", "package", "binding"]);
    platform::require(manifest::string(doc, 0, "mode") == "isolated", "incompatible lockfile mode");
    let bindings = toml::find(doc, 0, "binding"); if bindings < 0 { return; }
    platform::require(doc.nodes[bindings].kind == toml::Kind.Array, "invalid lock bindings");
    var row = doc.nodes[bindings].first;
    while row >= 0 {
        manifest::keys(doc, row, ["owner", "alias", "target", "git", "rev", "requirement", "selected_ref", "commit"]);
        let git = manifest::string(doc, row, "git");
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
        row = doc.nodes[row].next;
    }
}
fn lock_field(out: u8[>..]&, key: u8[:], value: u8[:]) { out.append(str("\n", key, " = ")); manifest::quoted(out, value); }
fn lock_text(g: Graph&, p: manifest::Project&) -> u8[>..] {
    var out = str("# Generated by Honk. Commit this file.\nversion = 2\nmode = \"isolated\"\ncompiler = "); manifest::quoted(out, p.revision); out.push('\n');
    var packages: u8[][>..] = []; var bindings: u8[][>..] = []; var bytes = out.len;
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
        row.push('\n'); bytes += row.len; platform::require(bytes <= manifest::MAX_INPUT_BYTES, "isolated lockfile exceeds 1 MiB"); bindings.push(copy(row));
    }
    sorted_rows(out, packages); sorted_rows(out, bindings);
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
        manifest::keys(doc, 0, ["version", "mode", "compiler", "package", "binding"]);
        platform::require(manifest::string(doc, 0, "mode") == "isolated", "incompatible lockfile mode; original is unchanged");
    }
    platform::require(!locked, "isolated lockfile is missing or out of date; run honk check --isolated without --locked");
    platform::save(path, desired);
}
fn execute(p: manifest::Project&, command: u8[:], arguments: u8[:][:], release: bool, locked: bool, offline: bool) {
    platform::require(command != "update" || !locked, "update cannot be combined with --locked or --frozen");
    platform::require(p.revision == "0ce3a5edb5679e10a490e9f66d5db5f6a30b9f63" || p.revision == "6471713c6c18f64e172c4c778ac5987a5a177358", "isolated mode requires an explicitly qualified graph compiler revision in [toolchain]");
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
    let cache = toolchain::home(); let cache_lock = platform::lock(str(cache, "/lock")); platform::require(cache_lock >= 0, "Honk cache is locked by another process");
    platform::require(platform::mkdir(str(p.root, "/.honk")), "cannot create graph lock directory");
    let project_lock = platform::lock(str(p.root, "/.honk/isolated.lock")); platform::require(project_lock >= 0, "isolated project is locked by another process");
    var graph = Graph { .. }; let root_id = visit(graph, p.root, p.revision);
    var cursor = 0;
    while cursor < graph.packages.len {
        var directory: u8[>..] = []; var origin: u8[>..] = []; var commit: u8[>..] = []; var git_root: u8[>..] = []; var owner_key: u8[>..] = [];
        for pkg, i in graph.packages { if i == cursor { directory = str(pkg.directory); origin = str(pkg.git); commit = str(pkg.commit); git_root = str(pkg.git_root); owner_key = package_key(pkg, p.root); } }
        var owner = manifest::Project { .. }; manifest::load(directory, owner);
        for dep in owner.dependencies {
            if dep.dev { continue; }
            platform::require(dep.registry.len == 0, "isolated registry resolution is not implemented yet");
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
                var registry = nest::Resolver { .. }; deps::add(materialized, dep, directory, registry);
                for node in materialized.nodes {
                    target = visit(graph, node.directory, p.revision, dep.git, node.commit, node.directory);
                    graph.bindings.push(Binding { owner: cursor, alias: str(dep.name), target: target, git: str(dep.git), rev: str(dep.rev), requirement: str(dep.requirement), selected_ref: str(node.rev), commit: str(node.commit) });
                }
            } else {
                let candidate = if dep.path[0] == '/' { str(dep.path) } else { str(directory, "/", dep.path) };
                let path = platform::absolute(candidate);
                if origin.len > 0 { platform::require(path == git_root || (path.len > git_root.len && path[..git_root.len] == git_root && path[git_root.len] == '/'), "Git path dependency escapes its checkout"); }
                target = visit(graph, path, p.revision, origin, commit, git_root);
                graph.bindings.push(Binding { owner: cursor, alias: str(dep.name), target: target, .. });
            }
        }
        cursor++;
    }
    var edges: task::Edge[>..] = []; for binding in graph.bindings { edges.push(task::Edge { before: binding.owner, after: binding.target }); }
    var limits = task::Limits { tasks: 256, edges: 65536 };
    let order, graph_error = task::plan(graph.packages.len, edges, limits);
    platform::require(graph_error.kind == task::ErrorKind.None, "isolated dependency cycle or graph limit exceeded");
    lock_graph(graph, p, locked);
    let metadata = render(graph, p.revision);
    let target = str(p.root, "/target/isolated"); platform::require(platform::mkdir(target), "cannot create isolated build directory");
    let path = str(target, "/graph.json"); platform::save(path, metadata);
    if command == "fetch" || command == "update" { platform::unlock(project_lock); platform::unlock(cache_lock); return; }
    var words: u8[][>..] = [str(compiler), str(command), str(p.root, "/", p.entry), str("--package-graph"), str(path)];
    if command == "build" { words.push(str("-o")); words.push(str(target, "/", p.name)); }
    if release { words.push(str("-O2")); }
    if arguments.len > 0 { words.push(str("--")); for argument in arguments { words.push(str(argument)); } }
    var argv: (const u8[:])[>..] = []; for word in words { argv.push(word); } platform::run(argv[..], p.root); platform::unlock(project_lock); platform::unlock(cache_lock);
}

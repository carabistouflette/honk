// SPDX-License-Identifier: Apache-2.0
// Opt-in producer for the compiler's pure-Goose graph contract.
namespace isolated;
import std;
import os;
import json;
import crypto;
import toml;
import task;
import .project;
import .toolchain;
import .manifest;
import .platform;
import .source;
import .build;
import .build_cache;
struct Binding { owner: i64, alias: u8[], target: i64 }
struct Package { directory: u8[], name: u8[], version: u8[], entry: u8[], ns: u8[], digest: u8[] }
root struct Graph { packages: Package[>..], bindings: Binding[>..] }
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
fn visit(g: Graph&, directory: u8[:], revision: u8[:]) -> i64 {
    let root = platform::absolute(directory);
    for pkg, i in g.packages { if pkg.directory == root { return i; } }
    platform::require(g.packages.len < 256, "isolated graph limit is 256 packages");
    var p = manifest::Project { .. }; manifest::load(root, p);
    platform::require(p.name.len > 0 && (p.revision.len == 0 || p.revision == revision), "isolated package needs a package manifest and matching compiler revision");
    let text = platform::load(str(root, "/", p.entry));
    let id = g.packages.len;
    g.packages.push(Package { directory: str(root), name: str(p.name), version: str(p.version), entry: str(p.entry), ns: namespace_of(text), digest: snapshot(p), .. });
    return id;
}
fn render(g: Graph&, revision: u8[:]) -> u8[>..] {
    var out = str("{\"schema\":\"goose-package-graph-v1\",\"compiler_revision\":"); manifest::quoted(out, revision);
    out.append(",\"root\":\"0\",\"nodes\":[");
    for pkg, i in g.packages {
        if i > 0 { out.push(','); }
        out.append("{\"key\":"); manifest::quoted(out, str(i));
        out.append(",\"source\":{\"locator\":"); manifest::quoted(out, str("path:", pkg.name));
        out.append(",\"revision\":"); manifest::quoted(out, str("snapshot:", pkg.digest));
        out.append(",\"name\":"); manifest::quoted(out, pkg.name); out.append(",\"subdir\":\"\"},\"directory\":"); manifest::quoted(out, pkg.directory);
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
fn lock_text(g: Graph&, p: manifest::Project&) -> u8[>..] {
    var out = str("# Generated by Honk. Commit this file.\nversion = 2\nmode = \"isolated\"\ncompiler = "); manifest::quoted(out, p.revision); out.push('\n');
    var packages: u8[][>..] = []; var bindings: u8[][>..] = []; var bytes = out.len;
    for pkg in g.packages {
        var row = str("\n[[package]]\ndirectory = "); manifest::quoted(row, coordinate(p.root, pkg.directory));
        row.append("\nname = "); manifest::quoted(row, pkg.name); row.append("\nversion = "); manifest::quoted(row, pkg.version);
        row.append("\nentry = "); manifest::quoted(row, pkg.entry); row.push('\n'); bytes += row.len; platform::require(bytes <= manifest::MAX_INPUT_BYTES, "isolated lockfile exceeds 1 MiB"); packages.push(copy(row));
    }
    for binding in g.bindings {
        var row = str("\n[[binding]]\nowner = ");
        for pkg, i in g.packages { if i == binding.owner { manifest::quoted(row, coordinate(p.root, pkg.directory)); } }
        row.append("\nalias = "); manifest::quoted(row, binding.alias); row.append("\ntarget = ");
        for pkg, i in g.packages { if i == binding.target { manifest::quoted(row, coordinate(p.root, pkg.directory)); } }
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
fn execute(p: manifest::Project&, command: u8[:], arguments: u8[:][:], release: bool, locked: bool) {
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
        var directory: u8[>..] = []; for pkg, i in graph.packages { if i == cursor { directory = str(pkg.directory); } }
        var owner = manifest::Project { .. }; manifest::load(directory, owner);
        for dep in owner.dependencies {
            if dep.dev { continue; }
            platform::require(dep.path.len > 0, "isolated mode currently supports path dependencies only");
            let path = if dep.path[0] == '/' { str(dep.path) } else { str(directory, "/", dep.path) };
            let target = visit(graph, path, p.revision);
            graph.bindings.push(Binding { owner: cursor, alias: str(dep.name), target: target });
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
    var words: u8[][>..] = [str(compiler), str(command), str(p.root, "/", p.entry), str("--package-graph"), str(path)];
    if command == "build" { words.push(str("-o")); words.push(str(target, "/", p.name)); }
    if release { words.push(str("-O2")); }
    if arguments.len > 0 { words.push(str("--")); for argument in arguments { words.push(str(argument)); } }
    var argv: (const u8[:])[>..] = []; for word in words { argv.push(word); } platform::run(argv[..], p.root); platform::unlock(project_lock); platform::unlock(cache_lock);
}

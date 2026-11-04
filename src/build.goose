// SPDX-License-Identifier: Apache-2.0
namespace build;
import std;
import os;
import json;
import .platform;
import .manifest;
import .project;
import .source;
import .deps;
fn suffix(s: u8[:], ending: u8[:]) -> bool { s.len >= ending.len && s[s.len - ending.len..] == ending }
fn skip(name: u8[:]) -> bool { name == ".git" || name == "target" || name == ".honk" || name == ".toolchain" || name == ".build" }
fn item(paths: u8[][:], index: i64) -> u8[:] {
    for path, i in paths { if i == index { return path; } } abort("invalid source index");
}
fn files(root: u8[:], prefix: u8[:], out: u8[][>..]&) {
    var directories: u8[][>..] = []; directories.push(str(prefix)); var cursor = 0;
    while cursor < directories.len {
        let current = item(directories, cursor); cursor++;
        platform::require(platform::kind(str(root, "/", current)) == 2, "source directories must not be symlinks");
        var entries: u8[>..] = []; platform::require(platform::list(str(root, "/", current), entries), "cannot list source directory");
        var start = 0;
        for c, i in entries {
            if c != '\n' { continue; } let name = entries[start..i]; start = i + 1;
            if skip(name) { continue; }
            let path = if current.len > 0 { str(current, "/", name) } else { str(name) };
            let kind = platform::kind(str(root, "/", path)); platform::require(kind == 1 || kind == 2, "source tree contains a symlink or special file");
            if kind == 2 {
                platform::require(directories.len < 4096, "source directory limit is 4096"); directories.push(str(path));
            } else if suffix(name, ".goose") {
                platform::require(out.len < 4096, "source file limit is 4096"); out.push(str(path));
            }
        }
    }
}
fn rewrite(text: u8[:], g: deps::Graph&, directory: u8[:], original: u8[:], p: manifest::Project&, stage: u8[:]) -> u8[>..] {
    let reqs = source::requirements(text); var out: u8[>..] = []; var start = 0;
    for req in reqs {
        let id = deps::index(g, req.name);
        if id < 0 {
            platform::require(req.source.len > 0 && (req.source[0] == '.' || req.source[0] == '/'), str("declare sourced import in Honk.toml: ", req.name));
            let path = if req.source[0] == '/' { str(req.source) } else { str(original, "/", req.source) };
            let resolved = platform::absolute(path);
            platform::require(resolved == p.root, str("undeclared source import: ", req.name));
            let alias = str(stage, "/", req.name, ".goose");
            if p.entry != str(req.name, ".goose") && !file_exists(alias) { platform::save(alias, str("import .", module(p.entry), ";\n")); }
        }
        out.append(text[start..req.start]);
        out.append("from "); let mapped = if id >= 0 { str(directory, "/deps/", req.name) } else { str(stage) }; manifest::quoted(out, mapped);
        start = req.end;
    }
    out.append(text[start..]); return out;
}
fn module(path: u8[:]) -> u8[>..] {
    platform::require(suffix(path, ".goose"), "entry must have .goose extension"); var out: u8[>..] = [];
    for c in path[..path.len - 6] { out.push(if c == '/' { '.' } else { c }); } return out;
}
fn prepare(p: manifest::Project&, g: deps::Graph&) -> u8[>..] {
    let directory = str(p.root, "/.honk/stage");
    platform::require(platform::remove_tree(directory), "cannot clear staged sources");
    let app = str(directory, "/app"); platform::require(platform::mkdir(app), "cannot create source staging directory");
    platform::require(platform::copy_tree(p.root, app), "cannot stage sources (symlink, special file, depth, file, or size limit)");
    for n in g.nodes {
        if !n.enabled { continue; }
        let to = str(directory, "/deps/", n.name); platform::require(platform::mkdir(to), "cannot create dependency staging directory");
        platform::require(platform::copy_tree(n.directory, to), str("cannot stage dependency: ", n.name));
        if n.entry != str(n.name, ".goose") { platform::save(str(to, "/", n.name, ".goose"), str("import .", module(n.entry), ";\n")); }
    }
    // Map every sourced import to Honk's resolved graph, including legacy test roots.
    for n in g.nodes {
        if !n.enabled { continue; }
        let to = str(directory, "/deps/", n.name); var paths: u8[][>..] = []; files(to, "", paths);
        for path in paths {
            let text = platform::load(str(to, "/", path));
            let transformed = rewrite(text, g, directory, project::parent(str(n.directory, "/", path)), p, app);
            if transformed != text { platform::save(str(to, "/", path), transformed); }
        }
    }
    var paths: u8[][>..] = []; files(app, "", paths);
    for path in paths {
        let text = platform::load(str(app, "/", path));
        let transformed = rewrite(text, g, directory, project::parent(str(p.root, "/", path)), p, app);
        if transformed != text { platform::save(str(app, "/", path), transformed); }
    }
    return app;
}
fn imports(g: deps::Graph&, stage: u8[:], out: u8[>..]&) {
    let directory = project::parent(stage);
    for n in g.nodes { out.append("import "); out.append(n.name); out.append(" from "); manifest::quoted(out, str(directory, "/deps/", n.name)); out.append(";\n"); }
}
fn root_entry(stage: u8[:], entry: u8[:], g: deps::Graph&) -> u8[>..] {
    let file = str(stage, "/", entry); let source = platform::load(file);
    // Source declarations already name their dependency; avoid duplicate declarations.
    let declared = source::requirements(source); var out: u8[>..] = [];
    for n in g.nodes {
        if !n.enabled { continue; }
        var found = false; for req in declared { if req.name == n.name { found = true; } }
        if !found { out.append("import "); out.append(n.name); out.append(" from "); manifest::quoted(out, str(project::parent(stage), "/deps/", n.name)); out.append(";\n"); }
    }
    out.append(source); platform::save(file, out); return file;
}
fn binary(compiler: u8[:], entry: u8[:], stage: u8[:], output: u8[:], release: bool, root: u8[:]) {
    let kind = platform::kind(output);
    platform::require(kind == 0 || kind == 1, "binary output must not be a symlink or special file");
    let private_dir = str(stage, "/.honk"); platform::require(platform::mkdir(private_dir), "cannot create private compiler output directory");
    let temporary = str(private_dir, "/program");
    var packed: u8[>..] = [];
    let argv: const u8[:][] = [compiler, "build", entry, "--offline", "-o", temporary]; for a in argv { platform::pack(packed, a); }
    if !release { platform::pack(packed, "--debug"); }
    var captured: u8[>..] = []; let code = platform::spawn(packed, root, true, captured);
    if code != 0 { write_stdout(captured); exit(code); }
    platform::require(platform::install(temporary, output, true), "cannot atomically publish executable");
    print("built ", output);
}
fn compile(p: manifest::Project&, g: deps::Graph&, compiler: u8[:], cmd: u8[:], release: bool, args: u8[:][:]) {
    deps::activate(g, cmd == "test" || cmd == "bench");
    let stage = prepare(p, g); let profile = if release { "release" } else { "debug" };
    let output = str(p.root, "/target/", profile); platform::require(platform::mkdir(output), "cannot create build output directory");
    if cmd == "test" || cmd == "bench" {
        let dir = if cmd == "test" { "tests" } else { "bench" };
        if !is_dir(str(stage, "/", dir)) { print("No ", dir, " targets"); return; }
        var paths: u8[][>..] = []; files(stage, dir, paths);
        for path, i in paths {
            let target_dir = str(output, "/.honk/", dir); platform::require(platform::mkdir(target_dir), "cannot create test output directory");
            let entry = root_entry(stage, path, g); let executable = str(target_dir, "/", i);
            binary(compiler, entry, stage, executable, release, p.root);
            var packed:   u8[>..] = []; platform::pack(packed, executable); for a in args { platform::pack(packed, a); }
            var captured: u8[>..] = []; let status = platform::spawn(packed, p.root, false, captured); if status != 0 { exit(status); }
        }
        print("Passed ", paths.len, " ", cmd, " targets"); return;
    }
    let entry = root_entry(stage, p.entry, g);
    if cmd == "doc" {
        let argv: const u8[:][] = [compiler, "--check", "--dump-docs", "--offline", entry];
        let text, status = platform::command(argv, p.root, true); if status != 0 { exit(status); }
        let directory = str(p.root, "/target/doc"); platform::require(platform::mkdir(directory), "cannot create documentation directory");
        let output = str(directory, "/", p.name, ".goose"); platform::save(output, text); print(output); return;
    }
    if cmd == "check" || p.kind == "lib" {
        let argv: const u8[:][] = [compiler, "check", entry, "--offline"]; platform::run(argv, p.root);
        platform::require(cmd != "run", "run requires a binary package"); return;
    }
    let executable = str(output, "/", p.name); binary(compiler, entry, stage, executable, release, p.root);
    if cmd == "run" {
        var packed:   u8[>..] = []; platform::pack(packed, executable); for a in args { platform::pack(packed, a); }
        var captured: u8[>..] = []; let status = platform::spawn(packed, p.root, false, captured); if status != 0 { exit(status); }
    }
}

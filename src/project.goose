// SPDX-License-Identifier: Apache-2.0
namespace project;
import std;
import os;
import json;
import text;
import .manifest;
import .platform;
fn parent(path: u8[:]) -> u8[>..] {
    var end = path.len; while end > 1 && path[end - 1] != '/' { end--; }
    if end > 1 { end--; } return str(path[..end]);
}
fn locate(start: u8[:]) -> u8[>..] {
    var root = platform::absolute(start);
    loop {
        if file_exists(str(root, "/Honk.toml")) { return root; }
        if root == "/" { platform::die("no Honk.toml found in this directory or its ancestors"); }
        let next = parent(root); root = copy(next);
    }
}
fn create(path: u8[:], name: u8[:], library: bool, init: bool) {
    platform::require(manifest::package_name(name), "invalid package name");
    var module_name: u8[>..] = [];
    for c in name { module_name.push(if c == '-' { '_' } else { c }); }
    if library { platform::require(manifest::identifier(module_name), "library namespace must be a nonreserved import identifier"); }
    if !init { platform::require(!is_dir(path) && !file_exists(path), "destination already exists"); }
    platform::require(platform::mkdir(path), "cannot create project directory");
    let root = platform::absolute(path);
    platform::require(!file_exists(str(root, "/Honk.toml")), "Honk.toml already exists");
    // Refuse to overwrite any existing source or ignore file.
    let entry = if library { "src/lib.goose" } else { "src/main.goose" };
    platform::require(!file_exists(str(root, "/", entry)), "source entry already exists");
    platform::require(platform::mkdir(str(root, "/src")), "cannot create src directory");
    var p = manifest::Project { root: str(root), name: str(name), version: str("0.1.0"), entry: str(entry), kind: str(if library { "lib" } else { "bin" }), .. };
    var source: u8[>..] = [];
    if library {
        source.append("// SPDX-License-Identifier: Apache-2.0\nnamespace ");
        source.append(module_name);
        source.append(";\nfn answer() -> i64 { 42 }\n");
    } else { source.append("fn main() { print(\"Hello, Goose!\"); }\n"); }
    platform::require(platform::write(str(root, "/", entry), source, false, true), "cannot create source entry");
    platform::require(platform::write(str(root, "/Honk.toml"), manifest::serialize(p), false, true), "cannot create manifest");
    if !file_exists(str(root, "/.gitignore")) { platform::require(platform::write(str(root, "/.gitignore"), "/target/\n/.honk/\n", false, true), "cannot create ignore file"); }
    print("Created ", if library { "library " } else { "application " }, name);
}
fn metadata(p: manifest::Project&) -> u8[>..] {
    platform::require(text::validate_utf8(p.root) == -1, "metadata requires a UTF-8 project path");
    var out = str("{\"name\":"); json::format_string(out, p.name);
    out.append(",\"version\":"); json::format_string(out, p.version);
    out.append(",\"root\":"); json::format_string(out, p.root);
    out.append(",\"kind\":"); json::format_string(out, p.kind);
    out.append(",\"entry\":"); json::format_string(out, p.entry);
    out.append(",\"dependencies\":[");
    for dep, i in p.dependencies {
        if i > 0 { out.push(','); } out.append("{\"name\":"); json::format_string(out, dep.name);
        out.append(",\"path\":"); json::format_string(out, dep.path); out.append(",\"git\":"); json::format_string(out, dep.git);
        out.append(",\"rev\":"); json::format_string(out, dep.rev); out.append(",\"dev\":"); json::format_bool(out, dep.dev); out.push('}');
    }
    out.append("],\"members\":["); for member, i in p.members { if i > 0 { out.push(','); } json::format_string(out, member); } out.append("]}");
    return out;
}

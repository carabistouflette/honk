// SPDX-License-Identifier: Apache-2.0
namespace commands;
import std;
import os;
import argparse;
import .platform;
import .manifest;
import .project;
import .deps;
import .build;
import .toolchain;
fn execute(p: manifest::Project&, cmd: u8[:], options: const argparse::Result&, args: u8[:][:], cache: u8[:]) {
    platform::require(platform::mkdir(str(p.root, "/.honk")), "cannot create project state directory");
    let lock = platform::lock(str(p.root, "/.honk/lock")); platform::require(lock >= 0, "project is locked by another Honk process");
    if cmd == "clean" {
        platform::require(platform::remove_tree(str(p.root, "/target")), "cannot clean target directory");
        platform::require(platform::remove_tree(str(p.root, "/.honk/stage")), "cannot clean stage directory");
        platform::unlock(lock); return;
    }
    if cmd == "add" || cmd == "remove" {
        platform::require(options.positionals.len == 1, "add/remove needs one dependency import name");
        let name = options.positionals[0]; platform::require(manifest::identifier(name), "invalid dependency import name");
        if cmd == "add" {
            platform::require(deps_name(p, name) < 0, "dependency already exists; remove it before replacing it");
            var dep = manifest::Dependency { name: str(name), path: str(options.get("path")), git: str(options.get("git")), rev: str(options.get("rev")), dev: options.has("dev") };
            platform::require((dep.path.len > 0) != (dep.git.len > 0), "add needs exactly one of --path or --git");
            platform::require(dep.path.len == 0 || dep.rev.len == 0, "path dependency cannot have --rev");
            if dep.git.len > 0 {
                platform::require(dep.git.len > 8 && dep.git[..8] == "https://" && dep.rev.len > 0 && dep.rev[0] != '-', "Git dependency needs HTTPS URL and --rev");
                for c in dep.git { platform::require(c > 32 && c != 127 && c != '@' && c != '?' && c != '#' && c != '"' && c != '\\', "invalid Git URL"); }
                for c in dep.rev { platform::require(c > 32 && c != 127 && c != ':' && c != '\\' && c != '"', "invalid Git ref"); }
            }
            p.dependencies.push(copy(dep));
        } else {
            platform::require(deps_name(p, name) >= 0, "dependency does not exist");
            // Rebuild once: variable-size array elements are sequential, not random-access.
            var kept: manifest::Dependency[>..] = [];
            for dep in p.dependencies { if dep.name != name { kept.push(copy(dep)); } }
            p.dependencies.clear(); for dep in kept { p.dependencies.push(copy(dep)); }
        }
        platform::save(str(p.root, "/Honk.toml"), manifest::serialize(p));
        print(if cmd == "add" { "Added " } else { "Removed " }, name, "; run honk fetch to update Honk.lock");
        platform::unlock(lock); return;
    }
    let offline = options.has("offline") || options.has("frozen");
    if cmd == "toolchain" {
        let binary = toolchain::compiler(p, cache, offline); let argv: const u8[:][] = [binary, "version"]; platform::run(argv, p.root); platform::unlock(lock); return;
    }
    let compiler = toolchain::compiler(p, cache, offline);
    if cmd == "fmt" {
        var paths:  u8[][>..] = []; build::files(p.root, "", paths);
        var packed: u8[>..]   = []; platform::pack(packed, compiler); platform::pack(packed, "format");
        if options.has("check") { platform::pack(packed, "--check"); }
        for path in paths { platform::pack(packed, str(p.root, "/", path)); }
        var captured: u8[>..] = []; let status = platform::spawn(packed, p.root, false, captured); if status != 0 { exit(status); }
        platform::unlock(lock); return;
    }
    var graph = deps::Graph { cache: str(cache), locked: options.has("locked") || options.has("frozen"), offline: offline, update: cmd == "update", .. };
    platform::require(!(graph.update && graph.locked), "update cannot be combined with --locked or --frozen"); deps::resolve(p, graph);
    if cmd == "fetch" || cmd == "update" { print("Resolved ", graph.nodes.len, " dependencies"); platform::unlock(lock); return; }
    if cmd == "tree" {
        print(p.name, " ", p.version);
        for node in graph.nodes { print("  ", node.name, " ", if node.git.len > 0 { node.commit[..] } else { node.path[..] }); }
        platform::unlock(lock); return;
    }
    if options.has("bin") {
        let name = options.get("bin"); platform::require(manifest::package_name(name), "invalid binary target name");
        p.entry = str("src/bin/", name, ".goose"); p.name = str(name); p.kind = str("bin");
    }
    build::compile(p, graph, compiler, cmd, options.has("release"), args);
    platform::unlock(lock);
}
fn deps_name(p: manifest::Project&, name: u8[:]) -> i64 { for d, i in p.dependencies { if d.name == name { return i; } } return -1; }

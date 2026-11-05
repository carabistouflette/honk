// SPDX-License-Identifier: Apache-2.0
namespace commands;
import std;
import os;
import argparse;
import toml_edit;
import .platform;
import .manifest;
import .project;
import .deps;
import .build;
import .toolchain;
import .distribution;
fn execute(p: manifest::Project&, cmd: u8[:], options: const argparse::Result&, args: u8[:][:], cache: u8[:]) {
    if cmd != "clean" && cmd != "add" && cmd != "remove" && cmd != "fetch" && cmd != "update" && cmd != "tree" {
        platform::require(toolchain::compatible_path(p.root), "project path contains a backslash unsupported by the pinned compiler");
    }
    platform::require(platform::mkdir(str(p.root, "/.honk")), "cannot create project state directory");
    let lock = platform::lock(str(p.root, "/.honk/lock")); platform::require(lock >= 0, "project is locked by another Honk process");
    if cmd == "clean" {
        platform::require(platform::remove_tree(str(p.root, "/target")), "cannot clean target directory");
        platform::require(platform::remove_tree(str(p.root, "/.honk/stage")), "cannot clean stage directory");
        platform::require(platform::remove_tree(str(p.root, "/.honk/package")), "cannot clean package staging directory");
        platform::require(platform::remove_tree(str(p.root, "/.honk/package-files")), "cannot clean package file list");
        platform::unlock(lock); return;
    }
    if cmd == "add" || cmd == "remove" {
        platform::require(options.positionals.len == 1, "add/remove needs one dependency import name");
        let name = options.positionals[0]; platform::require(manifest::identifier(name), "invalid dependency import name");
        // Re-read and validate after taking the project lock. Decisions and
        // source spans must describe the same manifest snapshot.
        let source = platform::load(str(p.root, "/Honk.toml"));
        var current = manifest::Project { root: str(p.root), .. };
        manifest::parse(source, current);
        var edited: u8[>..] = [];
        if cmd == "add" {
            platform::require(current.dependencies.len < 256, "dependency limit is 256");
            platform::require(deps_name(current, name) < 0, "dependency already exists; remove it before replacing it");
            platform::require(!(options.has("rev") && options.has("version")), "rev and version options are mutually exclusive");
            platform::require(!options.has("path") || (!options.has("version") && !options.has("rev")), "path dependency cannot specify rev or version");
            if options.has("version") { platform::require(manifest::version_requirement(options.get("version")), "invalid Git version requirement (ASCII space only, limit 4096 bytes)"); }
            var dep = manifest::Dependency { name: str(name), path: str(options.get("path")), git: str(options.get("git")), rev: str(options.get("rev")), dev: options.has("dev"), requirement: str(options.get("version")) };
            manifest::validate_dependency(dep);
            var value = str("{ ");
            if dep.path.len > 0 { value.append("path = "); manifest::quoted(value, dep.path); }
            else { value.append("git = "); manifest::quoted(value, dep.git); value.append(if dep.requirement.len > 0 { ", version = " } else { ", rev = " }); manifest::quoted(value, if dep.requirement.len > 0 { dep.requirement[..] } else { dep.rev[..] }); }
            value.append(" }");
            let path: const u8[:][] = [if dep.dev { "dev-dependencies" } else { "dependencies" }, name];
            let error = toml_edit::set(source, path, value, edited);
            platform::require(error.len == 0, error);
        } else {
            platform::require(deps_name(current, name) >= 0, "dependency does not exist");
            var dev = false;
            for dep in current.dependencies { if dep.name == name { dev = dep.dev; } }
            let path: const u8[:][] = [if dev { "dev-dependencies" } else { "dependencies" }, name];
            let error = toml_edit::remove(source, path, edited);
            platform::require(error.len == 0, error);
        }
        platform::require(edited.len <= manifest::MAX_INPUT_BYTES, "updated manifest exceeds 1 MiB; original is unchanged");
        var validated = manifest::Project { root: str(p.root), .. };
        manifest::parse(edited, validated);
        platform::save(str(p.root, "/Honk.toml"), edited);
        print(if cmd == "add" { "Added " } else { "Removed " }, name, "; run honk fetch to update Honk.lock");
        platform::unlock(lock); return;
    }
    let offline = options.has("offline") || options.has("frozen");
    if cmd == "toolchain" {
        let binary = toolchain::compiler(p, cache, offline); let argv: const u8[:][] = [binary, "version"];
        let text, status = platform::command(argv, p.root, true); write_stdout(text); if status != 0 { platform::child_exit(status); }
        platform::unlock(lock); return;
    }
    if cmd == "fmt" {
        let compiler = toolchain::compiler(p, cache, offline);
        var paths: u8[][>..] = []; build::files(p.root, "", paths);
        // Bound both argv count and bytes; the supported source-file limit is
        // larger than one subprocess argv. An empty list must not format stdin.
        var packed: u8[>..] = []; var count = 0;
        for path in paths {
            let absolute = str(p.root, "/", path);
            if count > 0 && (count >= 256 || packed.len + absolute.len + 1 > 65536) {
                var captured: u8[>..] = []; let status = platform::spawn(packed, p.root, false, captured); if status != 0 { platform::child_exit(status); }
                packed.clear(); count = 0;
            }
            if count == 0 {
                platform::pack(packed, compiler); platform::pack(packed, "format");
                if options.has("check") { platform::pack(packed, "--check"); }
            }
            platform::pack(packed, absolute); count++;
        }
        if count > 0 {
            var captured: u8[>..] = []; let status = platform::spawn(packed, p.root, false, captured); if status != 0 { platform::child_exit(status); }
        }
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
    let compiler = toolchain::compiler(p, cache, offline);
    if options.has("bin") {
        let name = options.get("bin"); platform::require(manifest::package_name(name), "invalid binary target name");
        p.entry = str("src/bin/", name, ".goose"); p.name = str(name); p.kind = str("bin");
    }
    if cmd == "package" {
        distribution::package(p, graph, compiler);
    } else {
        let release = options.has("release") || cmd == "install";
        build::compile(p, graph, compiler, if cmd == "install" { "build" } else { cmd }, release, args);
        if cmd == "install" {
            let destination = if options.has("root") { str(options.get("root")) } else { str(cache, "/installed") };
            distribution::install(p, release, destination, options.has("force"));
        }
    }
    platform::unlock(lock);
}
fn deps_name(p: manifest::Project&, name: u8[:]) -> i64 { for d, i in p.dependencies { if d.name == name { return i; } } return -1; }

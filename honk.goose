// SPDX-License-Identifier: Apache-2.0
import toml from "./vendor/goose-toml";
import argparse from "./vendor/goose-argparse";
import .src.platform;
import .src.manifest;
import .src.project;
import .src.deps;
import .src.build;
import .src.toolchain;
import .src.commands;
import std;
import os;
fn usage() {
    print("honk 0.1.0-dev — Goose project manager\n\nUsage: honk <command> [options]\n\nCommands: new init metadata build run check test bench fmt fetch update add remove\n          tree clean package install uninstall doc toolchain version help\n\nUse honk help for project conventions. --help prints this message.");
}
fn main() {
    let argv = args();
    if argv.len < 2 || argv[1] == "help" || argv[1] == "--help" || argv[1] == "-h" { usage(); return; }
    let cmd = argv[1];
    if cmd == "version" || cmd == "--version" { print("honk 0.1.0-dev"); return; }
    let spec = [argparse::flag("force"), argparse::flag("help", 'h'), argparse::flag("lib"), argparse::flag("release"), argparse::flag("locked"), argparse::flag("offline"), argparse::flag("frozen"), argparse::flag("workspace"), argparse::flag("check"), argparse::flag("dev"),
                argparse::option("name"), argparse::option("path"), argparse::option("git"), argparse::option("rev"), argparse::option("manifest-path"), argparse::option("package", 'p'), argparse::option("bin"), argparse::option("root")];
    var separator = argv.len;
    for a, i in argv { if i >= 2 && a == "--" { separator = i; break; } }
    let options = argparse::parse(spec, argv[2..separator]);
    let program_args = argv[if separator < argv.len { separator + 1 } else { separator }..];
    if options.error != argparse::Error.None { platform::die(options.message); }
    if options.has("help") { usage(); return; }
    validate_options(cmd, options, program_args.len);
    if cmd == "new" || cmd == "init" {
        platform::require(options.positionals.len <= 1, "expected one project path");
        let path = if options.positionals.len > 0 { options.positionals[0] } else { "." };
        platform::require(cmd == "init" || options.positionals.len == 1, "new needs a destination path");
        var default_name = str(path); while default_name.len > 0 && default_name[default_name.len - 1] == '/' { default_name.pop(); }
        if default_name == "." { default_name = platform::absolute("."); }
        var start = default_name.len; while start > 0 && default_name[start - 1] != '/' { start--; }
        project::create(path, options.get("name", default_name[start..]), options.has("lib"), cmd == "init"); return;
    }
    if cmd == "uninstall" {
        platform::require(options.positionals.len == 1, "uninstall needs one executable name");
        let cache = toolchain::home(); let lock = platform::lock(str(cache, "/lock")); platform::require(lock >= 0, "Honk cache is locked");
        let destination = if options.has("root") { str(options.get("root")) } else { str(cache, "/installed") };
        distribution::uninstall(destination, options.positionals[0]); platform::unlock(lock); return;
    }
    dispatch(cmd, options, program_args);
}
fn dispatch(cmd: u8[:], options: argparse::Result&, program_args: u8[:][:]) {
    var p = manifest::Project { .. };
    let root = select_root(options);
    manifest::load(root, p);
    if cmd == "metadata" { project::metadata(p); return; }
    var known = false;
    for name in ["build", "run", "check", "test", "bench", "fmt", "fetch", "update", "tree", "clean", "add", "remove", "toolchain", "package", "install", "doc"] { if cmd == name { known = true; } }
    platform::require(known, str("unknown command: ", cmd));
    platform::require(options.positionals.len == 0 || cmd == "add" || cmd == "remove", "unexpected positional argument (program arguments follow --)");
    let cache = toolchain::home(); let cache_lock = platform::lock(str(cache, "/lock")); platform::require(cache_lock >= 0, "Honk cache is locked by another process");
    if options.has("workspace") || p.name.len == 0 || options.has("package") {
        platform::require(p.members.len > 0, "manifest has no workspace members"); var selected = 0;
        for member in p.members {
            platform::require(platform::directory(p.root, member), "workspace member must be a directory without symlink components");
            var child = manifest::Project { .. }; manifest::load(str(p.root, "/", member), child);
            platform::require(child.members.len == 0, "nested workspaces are not supported");
            if options.has("package") && options.get("package") != child.name { continue; }
            commands::execute(child, cmd, options, program_args, cache); selected++;
        }
        platform::require(selected > 0, "no workspace package matched");
    } else { commands::execute(p, cmd, options, program_args, cache); }
    platform::unlock(cache_lock);
}

fn validate_options(cmd: u8[:], options: argparse::Result&, arguments: i64) {
    platform::require(arguments == 0 || cmd == "run" || cmd == "test" || cmd == "bench", "only run/test/bench accept arguments after --");
    for entry in options.entries {
        let name = entry.name; var allowed = false;
        if name == "help" { allowed = true; }
        else if name == "lib" || name == "name" { allowed = cmd == "new" || cmd == "init"; }
        else if name == "path" || name == "git" || name == "rev" || name == "dev" { allowed = cmd == "add"; }
        else if name == "root" || name == "force" { allowed = cmd == "install" || cmd == "uninstall"; }
        else if name == "release" { allowed = cmd == "build" || cmd == "run" || cmd == "test" || cmd == "bench" || cmd == "install"; }
        else if name == "bin" { allowed = cmd == "build" || cmd == "run" || cmd == "check" || cmd == "install" || cmd == "doc"; }
        else if name == "check" { allowed = cmd == "fmt"; }
        else { allowed = cmd != "new" && cmd != "init"; }
        platform::require(allowed, str("--", name, " is not supported by ", cmd));
    }
}

fn select_root(options: argparse::Result&) -> u8[>..] {
    if !options.has("manifest-path") { return project::locate("."); }
    let path = options.get("manifest-path");
    platform::require(path == "Honk.toml" || build::suffix(path, "/Honk.toml"), "--manifest-path must name Honk.toml");
    // Check the selected file without following a final symlink before canonicalizing its parent.
    let content = platform::load(path);
    return project::parent(platform::absolute(path));
}

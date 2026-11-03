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
    print("honk 0.1.0-dev — Goose project manager\n\nUsage: honk <command> [options]\n\nCommands: new init metadata build run check test bench fmt fetch update add remove\n          tree clean package install toolchain version help\n\nUse honk help for project conventions. --help prints this message.");
}
fn main() {
    let argv = args();
    if argv.len < 2 || argv[1] == "help" || argv[1] == "--help" || argv[1] == "-h" { usage(); return; }
    let cmd = argv[1];
    if cmd == "version" || cmd == "--version" { print("honk 0.1.0-dev"); return; }
    let spec = [argparse::flag("help", 'h'), argparse::flag("lib"), argparse::flag("release"), argparse::flag("locked"), argparse::flag("offline"), argparse::flag("frozen"), argparse::flag("workspace"), argparse::flag("check"), argparse::flag("dev"),
                argparse::option("name"), argparse::option("path"), argparse::option("git"), argparse::option("rev"), argparse::option("manifest-path"), argparse::option("package", 'p'), argparse::option("bin"), argparse::option("root")];
    var separator = argv.len;
    for a, i in argv { if i >= 2 && a == "--" { separator = i; break; } }
    let options = argparse::parse(spec, argv[2..separator]);
    let program_args = argv[if separator < argv.len { separator + 1 } else { separator }..];
    if options.error != argparse::Error.None { platform::die(options.message); }
    if options.has("help") { usage(); return; }
    if cmd == "new" || cmd == "init" {
        platform::require(options.positionals.len <= 1, "expected one project path");
        let path = if options.positionals.len > 0 { options.positionals[0] } else { "." };
        platform::require(cmd == "init" || options.positionals.len == 1, "new needs a destination path");
        var default_name = str(path); while default_name.len > 0 && default_name[default_name.len - 1] == '/' { default_name.pop(); }
        if default_name == "." { default_name = platform::absolute("."); }
        var start = default_name.len; while start > 0 && default_name[start - 1] != '/' { start--; }
        project::create(path, options.get("name", default_name[start..]), options.has("lib"), cmd == "init"); return;
    }
    dispatch(cmd, options, program_args);
}
fn dispatch(cmd: u8[:], options: argparse::Result&, program_args: u8[:][:]) {
    var p = manifest::Project { .. };
    let root = if options.has("manifest-path") { project::parent(platform::absolute(options.get("manifest-path"))) } else { project::locate(".") };
    manifest::load(root, p);
    if cmd == "metadata" { project::metadata(p); return; }
    var known = false;
    for name in ["build", "run", "check", "test", "bench", "fmt", "fetch", "update", "tree", "clean", "add", "remove", "toolchain"] { if cmd == name { known = true; } }
    platform::require(known, str("unknown command: ", cmd));
    platform::require(options.positionals.len == 0 || cmd == "add" || cmd == "remove", "unexpected positional argument (program arguments follow --)");
    let cache = toolchain::home(); let cache_lock = platform::lock(str(cache, "/lock")); platform::require(cache_lock >= 0, "Honk cache is locked by another process");
    if options.has("workspace") || p.name.len == 0 || options.has("package") {
        platform::require(p.members.len > 0, "manifest has no workspace members"); var selected = 0;
        for member in p.members {
            var child = manifest::Project { .. }; manifest::load(str(p.root, "/", member), child);
            platform::require(child.members.len == 0, "nested workspaces are not supported");
            if options.has("package") && options.get("package") != child.name { continue; }
            commands::execute(child, cmd, options, program_args, cache); selected++;
        }
        platform::require(selected > 0, "no workspace package matched");
    } else { commands::execute(p, cmd, options, program_args, cache); }
    platform::unlock(cache_lock);
}

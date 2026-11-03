// SPDX-License-Identifier: Apache-2.0
import toml from "./vendor/goose-toml";
import argparse from "./vendor/goose-argparse";
import .src.platform;
import .src.manifest;
import .src.project;
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
    let options = argparse::parse(spec, argv[2..]);
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
    let root = if options.has("manifest-path") { project::parent(platform::absolute(options.get("manifest-path"))) } else { project::locate(".") };
    var p = manifest::Project { .. }; manifest::load(root, p);
    if cmd == "metadata" { project::metadata(p); return; }
    platform::die(str("command not implemented yet: ", cmd));
}

// SPDX-License-Identifier: Apache-2.0
import task from "./vendor/goose-task";
import watch from "./vendor/goose-watch";
import .src.watching;
import glob from "./vendor/goose-glob";
import crypto from "./vendor/goose-crypto";
import http from "./vendor/goose-http";
import honk_metadata from "./vendor/honk-metadata";
import process from "./vendor/goose-process";
import semver from "./vendor/goose-semver";
import text from "./vendor/goose-text";
import toml_edit from "./vendor/goose-toml-edit";
import toml from "./vendor/goose-toml";
import argparse from "./vendor/goose-argparse";
import logger from "./vendor/goose-log";
import time from "./vendor/goose-time";
import utc from "./vendor/goose-log/examples/utc";
import posix from "./vendor/goose-terminal";
import .src.diagnostics;
import .src.platform;
import .src.manifest;
import .src.project;
import .src.deps;
import .src.build;
import .src.toolchain;
import .src.commands;
import .src.version_policy;
import .src.tag_select;
import .src.tag_catalog;
import std;
import os;
fn usage() {
    print("honk 0.4.0 — Goose project manager\n\nUsage: honk <command> [options]\n\nCommands: new init metadata build run check test bench fmt fetch update add remove\n          tree clean package install uninstall doc toolchain watch version help\n\nUse honk help for project conventions. --help prints this message.\nOptional status: --progress auto|always|never (default never) for build/run/check/test/bench/install.\nCompiler diagnostics: honk check --diagnostics text|json (single-package JSON).\nParallel tests: honk test --jobs 1..8 [--test-timeout-ms N] (bounded captured output, null stdin).\nWatch: honk watch check|test --watch-dir ABS_DIR [--watch-dir ABS_DIR ...] [--watch-runs N] [--watch-debounce-ms 0..1000] (nonrecursive).");
}
var logging_started_ns: i64 = 0;
var logging_requested = false;
fn main() {
    cli_main();
    platform::require(platform::flush_stdout(), "cannot write standard output");
    if logging_requested {
        let elapsed = clock_ns() - logging_started_ns;
        let duration = if elapsed > 0 { elapsed as u64 } else { 0 as u64 };
        platform::require(diagnostics::write(diagnostics::Event.Returned, duration), "diagnostic log failed");
    }
}
fn cli_main() {
    let argv = args();
    if argv.len < 2 || argv[1] == "help" || argv[1] == "--help" || argv[1] == "-h" { usage(); return; }
    let cmd = argv[1];
    if cmd == "version" || cmd == "--version" { print("honk 0.4.0"); return; }
    let spec = [argparse::flag("reuse-build"), argparse::flag("metadata"), argparse::flag("force"), argparse::flag("help", 'h'), argparse::flag("lib"), argparse::flag("release"), argparse::flag("locked"), argparse::flag("offline"), argparse::flag("frozen"), argparse::flag("workspace"), argparse::flag("check"), argparse::flag("dev"),
                argparse::option("diagnostics"), argparse::option("jobs"), argparse::option("test-timeout-ms"), argparse::option("watch-dir"), argparse::option("watch-runs"), argparse::option("watch-debounce-ms"), argparse::option("progress"), argparse::option("filter"), argparse::option("log-file"), argparse::option("name"), argparse::option("path"), argparse::option("git"), argparse::option("rev"), argparse::option("version"), argparse::option("manifest-path"), argparse::option("package", 'p'), argparse::option("bin"), argparse::option("root")];
    var separator = argv.len;
    for a, i in argv { if i >= 2 && a == "--" { separator = i; break; } }
    let options = argparse::parse(spec, argv[2..separator]);
    let program_args = argv[if separator < argv.len { separator + 1 } else { separator }..];
    if options.error != argparse::Error.None { platform::die(options.message); }
    if options.has("help") { usage(); return; }
    if cmd == "watch" {
        platform::require(options.positionals.len == 1 && (options.positionals[0] == "check" || options.positionals[0] == "test"), "watch needs check or test");
        var directories: (const u8[:])[>..] = [];
        for entry in options.entries {
            if entry.name != "watch-dir" { continue; }
            platform::require(directories.len < watch::MAX_DIRECTORIES, "watch accepts at most 256 explicit directories");
            platform::require(entry.value.len > 0 && entry.value.len <= 4095 && entry.value[0] == '/', "--watch-dir must be an absolute directory path");
            directories.push(entry.value);
        }
        platform::require(directories.len > 0, "watch requires --watch-dir (1..256 nonrecursive directories)");
        let selected = options.positionals[0];
        let filter = validate_options(selected, options, program_args.len, true);
        let limit, valid = parse_int(options.get("watch-runs", "0"));
        platform::require(valid && limit >= 0 && limit <= 10000, "--watch-runs must be 0..10000 (0 waits indefinitely)");
        let debounce, debounce_valid = parse_int(options.get("watch-debounce-ms", "0"));
        platform::require(debounce_valid && debounce >= 0 && debounce <= 1000, "--watch-debounce-ms must be 0..1000 (0 disables batching)");
        var words: u8[][>..] = []; words.push(str("/proc/self/exe")); words.push(str(selected));
        for entry in options.entries {
            if entry.name == "watch-dir" || entry.name == "watch-runs" || entry.name == "watch-debounce-ms" { continue; }
            words.push(str("--", entry.name));
            for option in spec { if option.name == entry.name && option.value_name.len > 0 { words.push(str(entry.value)); } }
        }
        if program_args.len > 0 { words.push(str("--")); for arg in program_args { words.push(str(arg)); } }
        var child: (const u8[:])[>..] = []; for word in words { child.push(word); }
        let code = watching::run(directories[..], child[..], limit, debounce);
        if code != 0 { exit(code); }
        return;
    }
    let filter = validate_options(cmd, options, program_args.len);
    if options.has("log-file") {
        platform::require(diagnostics::configure(options.get("log-file")), "invalid diagnostic configuration");
        logging_requested = true; logging_started_ns = clock_ns();
        platform::require(diagnostics::write(diagnostics::Event.Started), "diagnostic log failed");
    }
    if options.has("metadata") { emit_toolchain_metadata(options); return; }
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
    dispatch(cmd, options, program_args, filter);
}
fn dispatch(cmd: u8[:], options: argparse::Result&, program_args: u8[:][:], filter: build::TargetFilter&) {
    var p = manifest::Project { .. };
    let root = select_root(options);
    manifest::load(root, p);
    platform::require(options.positionals.len == 0 || cmd == "add" || cmd == "remove", "unexpected positional argument (program arguments follow --)");
    if cmd == "metadata" { emit_metadata(p, options); return; }
    var known = false;
    for name in ["build", "run", "check", "test", "bench", "fmt", "fetch", "update", "tree", "clean", "add", "remove", "toolchain", "package", "install", "doc"] { if cmd == name { known = true; } }
    platform::require(known, str("unknown command: ", cmd));
    if options.get("diagnostics", "text") == "json" {
        platform::require(options.has("package") || (!options.has("workspace") && p.name.len > 0), "JSON diagnostics require a single package; select a workspace member with -p");
    }
    let cache = toolchain::home(); let cache_lock = platform::lock(str(cache, "/lock")); platform::require(cache_lock >= 0, "Honk cache is locked by another process");
    if options.has("package") {
        let selected = selected_member(p, options.get("package"));
        var child = manifest::Project { .. }; manifest::load(selected, child);
        commands::execute(child, cmd, options, program_args, cache, filter);
        platform::require(diagnostics::write(diagnostics::Event.ItemCompleted), "diagnostic log failed");
    } else if options.has("workspace") || p.name.len == 0 {
        platform::require(p.members.len > 0, "manifest has no workspace members"); var selected = 0;
        for member in p.members {
            platform::require(platform::directory(p.root, member), "workspace member must be a directory without symlink components");
            var child = manifest::Project { .. }; manifest::load(str(p.root, "/", member), child);
            platform::require(child.members.len == 0, "nested workspaces are not supported");
            commands::execute(child, cmd, options, program_args, cache, filter);
            platform::require(diagnostics::write(diagnostics::Event.ItemCompleted), "diagnostic log failed"); selected++;
        }
        platform::require(selected > 0, "no workspace package matched");
    } else { commands::execute(p, cmd, options, program_args, cache, filter);
        platform::require(diagnostics::write(diagnostics::Event.ItemCompleted), "diagnostic log failed"); }
    platform::unlock(cache_lock);
}

fn emit_metadata(p: manifest::Project&, options: const argparse::Result&) {
    if options.has("package") {
        let selected = selected_member(p, options.get("package"));
        var child = manifest::Project { .. }; manifest::load(selected, child);
        if options.has("workspace") { print("[", project::metadata(child), "]"); } else { print(project::metadata(child)); }
        return;
    }
    if !options.has("workspace") { print(project::metadata(p)); return; }
    platform::require(p.members.len > 0, "manifest has no workspace members");
    var selected = 0; write_stdout("[");
    for member in p.members {
        platform::require(platform::directory(p.root, member), "workspace member must be a directory without symlink components");
        var child = manifest::Project { .. }; manifest::load(str(p.root, "/", member), child);
        platform::require(child.members.len == 0, "nested workspaces are not supported");
        if selected > 0 { write_stdout(","); }
        write_stdout(project::metadata(child)); selected++;
    }
    platform::require(selected > 0, "no workspace package matched"); write_stdout("]\n");
}

fn selected_member(p: manifest::Project&, selector: u8[:]) -> u8[>..] {
    var at = selector.len; for c, i in selector { if c == '@' { at = i; break; } }
    let name = selector[..at]; platform::require(manifest::package_name(name), "invalid workspace package selector");
    let versioned = at < selector.len;
    let requested_text = if versioned { selector[at + 1..] } else { "0.0.0" };
    platform::require(requested_text.len <= 64, "workspace selector version exceeds 64 bytes");
    let requested, requested_error = semver::parse(requested_text);
    platform::require(requested_error.kind == semver::ErrorKind.None, "workspace selector needs a strict full SemVer version");
    platform::require(p.members.len > 0, "manifest has no workspace members");
    var selected: u8[>..] = [];
    for member in p.members {
        platform::require(platform::directory(p.root, member), "workspace member must be a directory without symlink components");
        var child = manifest::Project { .. }; manifest::load(str(p.root, "/", member), child);
        platform::require(child.members.len == 0, "nested workspaces are not supported");
        if child.name != name { continue; }
        if versioned {
            let candidate, error = semver::parse(child.version);
            platform::require(error.kind == semver::ErrorKind.None, "invalid workspace member version");
            if semver::compare(candidate, requested) != 0 { continue; }
        }
        platform::require(selected.len == 0, "ambiguous workspace package name"); selected = str(child.root);
    }
    platform::require(selected.len > 0, "no workspace package matched"); return selected;
}

fn validate_options(cmd: u8[:], options: argparse::Result&, arguments: i64, watching: bool = false) -> build::TargetFilter {
    platform::require(!options.has("root") || options.get("root").len > 0, "installation root must not be empty");
    let filter = if options.has("filter") {
        let pattern, status = glob::compile(options.get("filter"));
        platform::require(status.error == glob::Error.None, "invalid --filter glob (syntax or pattern limit)");
        build::TargetFilter { enabled: true, pattern: copy(pattern) }
    } else { build::TargetFilter { .. } };
    platform::require(arguments == 0 || cmd == "run" || cmd == "test" || cmd == "bench", "only run/test/bench accept arguments after --");
    if options.has("progress") {
        let policy = options.get("progress");
        platform::require(policy == "auto" || policy == "always" || policy == "never", "--progress must be auto, always, or never");
    }
    if options.has("diagnostics") {
        let mode = options.get("diagnostics");
        platform::require(mode == "text" || mode == "json", "--diagnostics must be text or json");
    }
    for entry in options.entries {
        let name = entry.name; var allowed = false;
        if name == "watch-dir" || name == "watch-runs" || name == "watch-debounce-ms" { allowed = watching; }
        else if name == "diagnostics" { allowed = cmd == "check" && !watching; }
        else if name == "progress" { allowed = cmd == "build" || cmd == "run" || cmd == "check" || cmd == "test" || cmd == "bench" || cmd == "install"; }
        else if name == "jobs" || name == "test-timeout-ms" { allowed = cmd == "test" && !watching; }
        else if name == "filter" { allowed = cmd == "test" || cmd == "bench"; }
        else if name == "reuse-build" { allowed = cmd == "build" || cmd == "run"; }
        else if name == "metadata" { allowed = cmd == "toolchain"; }
        else if name == "help" || name == "log-file" { allowed = true; }
        else if name == "lib" || name == "name" { allowed = cmd == "new" || cmd == "init"; }
        else if name == "path" || name == "git" || name == "rev" || name == "version" || name == "dev" { allowed = cmd == "add"; }
        else if name == "root" { allowed = cmd == "install" || cmd == "uninstall"; }
        else if name == "force" { allowed = cmd == "install"; }
        else if name == "release" { allowed = cmd == "build" || cmd == "run" || cmd == "test" || cmd == "bench" || cmd == "install"; }
        else if name == "bin" { allowed = cmd == "build" || cmd == "run" || cmd == "check" || cmd == "install" || cmd == "doc"; }
        else if name == "check" { allowed = cmd == "fmt"; }
        else { allowed = cmd != "new" && cmd != "init" && cmd != "uninstall"; }
        platform::require(allowed, str("--", name, " is not supported by ", cmd));
    }
    if options.has("jobs") {
        let value = options.get("jobs");
        platform::require(value.len == 1 && value[0] >= '1' && value[0] <= '8', "--jobs must be 1..8");
    }
    if options.has("test-timeout-ms") {
        platform::require(options.has("jobs"), "--test-timeout-ms requires --jobs");
        let text = options.get("test-timeout-ms");
        platform::require(text.len > 0 && text.len <= 8, "--test-timeout-ms must be 1..86400000");
        for c in text { platform::require(c >= '0' && c <= '9', "--test-timeout-ms must be 1..86400000"); }
        let value, valid = parse_int(text);
        platform::require(valid && value >= 1 && value <= 86400000, "--test-timeout-ms must be 1..86400000");
    }
    return filter;
}

fn select_root(options: argparse::Result&) -> u8[>..] {
    if !options.has("manifest-path") { return project::locate("."); }
    let path = options.get("manifest-path");
    platform::require(path == "Honk.toml" || build::suffix(path, "/Honk.toml"), "--manifest-path must name Honk.toml");
    // Check the selected file without following a final symlink before canonicalizing its parent.
    let content = platform::load(path);
    return project::parent(platform::absolute(path));
}

// This opt-in branch runs before home/cache locks, compiler selection or Git.
fn emit_toolchain_metadata(options: argparse::Result&) {
    platform::require(options.positionals.len == 0, "toolchain metadata accepts no positional arguments");
    for entry in options.entries {
        platform::require(entry.name == "metadata" || entry.name == "manifest-path" || entry.name == "log-file", "toolchain --metadata supports only --manifest-path/--log-file; offline/frozen cannot request network metadata");
    }
    var p = manifest::Project { .. };
    if options.has("manifest-path") { manifest::load(select_root(options), p); }
    else {
        var root = platform::absolute(".");
        while true {
            if platform::kind(str(root, "/Honk.toml")) != 0 { manifest::load(root, p); break; }
            if root == "/" { break; }
            let next = project::parent(root); root = copy(next);
        }
    }
    let revision = if p.revision.len > 0 { p.revision[..] } else { toolchain::REVISION };
    platform::require(platform::metadata_begin(), "cannot establish HTTPS signal policy");
    var info, error = honk_metadata::fetch(revision);
    let restored = platform::metadata_end();
    platform::require(restored, "cannot restore HTTPS signal policy");
    platform::require(error.len == 0, error);
    print(honk_metadata::render(info));
}

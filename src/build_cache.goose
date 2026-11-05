// SPDX-License-Identifier: Apache-2.0
// Application-owned, explicitly requested local reuse. See INCREMENTAL-BUILDS.md.
namespace build_cache;
import std;
import os;
import crypto;
import .platform;
import .project;
import .source;
import .deps;
const MAX_BYTES = 33554432;
fn suffix(s: u8[:], ending: u8[:]) -> bool { s.len >= ending.len && s[s.len - ending.len..] == ending }
fn digest(path: u8[:], limit: i64) -> u8[>..], bool {
    var state = crypto::Sha256 { .. };
    if crypto::init(state) != crypto::Error.None { return [], false; }
    let descriptor = platform::cache_open(path, limit);
    if descriptor < 0 { return [], false; }
    var buffer: u8[32768] = [0; 32768]; var total = 0; var ok = true; var elf = false;
    loop {
        let count = platform::cache_read(descriptor, buffer[..]);
        if count < 0 || count > buffer.len || count > limit - total { ok = false; break; }
        if count == 0 { break; }
        if total == 0 { elf = count >= 4 && buffer[0] == 127 && buffer[1..4] == "ELF"; }
        total += count;
        if crypto::update(state, buffer[..count]) != crypto::Error.None { ok = false; break; }
    }
    if !platform::cache_close(descriptor) { ok = false; }
    var bytes: u8[32] = [0; 32]; var hex: u8[64] = [0; 64];
    if !ok || crypto::finish(state, bytes[..]) != crypto::Error.None || crypto::hex_encode(bytes[..], hex[..]) != crypto::Error.None { return [], false; }
    var out: u8[>..] = []; out.append(hex[..]); return out, elf;
}
fn feed(state: crypto::Sha256&, text: u8[:]) -> bool {
    let size = str(text.len, ":");
    return crypto::update(state, size) == crypto::Error.None && crypto::update(state, text) == crypto::Error.None;
}
fn pure(text: u8[:], graph: deps::Graph&, standard: bool = false) -> bool {
    var reader = source::Reader { text: text };
    loop {
        let token = source::token(reader); if token.start == token.end { break; }
        if token.quoted { continue; }
        let word = text[token.start..token.end];
        if word == "embed_file" || word == "embed_shader" || (!standard && word == "extern") { return false; }
        if word != "import" { continue; }
        if standard { return false; }
        let name = source::token(reader);
        if name.quoted || name.start == name.end { return false; }
        let value = text[name.start..name.end];
        if value == "." {
            let next = source::token(reader);
            if next.quoted || text[next.start..next.end] == "." { return false; }
            continue;
        }
        if value != "std" && deps::index(graph, value) < 0 { return false; }
        if value == "std" {
            let end = source::token(reader); if end.quoted || text[end.start..end.end] != ";" { return false; }
        }
    }
    return true;
}
fn on_path(name: u8[:], root: u8[:]) -> u8[>..] {
    var path: u8[>..] = []; if !env("PATH", path) { return []; }
    var start = 0;
    for i in path.len + 1 {
        if i < path.len && path[i] != ':' { continue; }
        if i == start { start = i + 1; continue; }
        let component = path[start..i];
        let candidate = str(if component[0] == '/' { str(component) } else { str(root, "/", component) }, "/", name); start = i + 1;
        if !platform::cache_executable(candidate) { continue; }
        var absolute: u8[>..] = []; if platform::real(candidate, absolute) { return str(candidate); }
        return [];
    }
    return [];
}
fn std_source(compiler: u8[:], root: u8[:]) -> u8[>..] {
    var override: u8[>..] = [];
    let selected = env("GOOSE_STDLIB", override);
    let exedir = project::parent(compiler);
    let candidates: const u8[:][] = [override[..], exedir[..], "../stdlib", "../../stdlib", "../../../stdlib", "stdlib"];
    for candidate, i in candidates {
        if i == 0 && (!selected || override.len == 0) { continue; }
        let directory = if i == 0 { if override.len > 0 && override[0] == '/' { str(override) } else { str(root, "/", override) } } else if i == 1 { str(exedir, "/stdlib") } else if i == 5 { str(root, "/stdlib") } else { str(exedir, "/", candidate) };
        var absolute: u8[>..] = [];
        if !platform::real(directory, absolute) { continue; }
        let file = str(absolute, "/std.goose");
        if platform::kind(file) == 0 { continue; }
        var selected_file: u8[>..] = [];
        if !platform::real(file, selected_file) || platform::kind(selected_file) != 1 { return []; }
        return selected_file;
    }
    return [];
}
// Empty key means conservative fallback. Full staging still happens either way.
fn key(compiler: u8[:], entry: u8[:], stage: u8[:], release: bool, root: u8[:], graph: deps::Graph&, cc: u8[>..]&) -> u8[>..] {
    cc.clear();
    var configured: u8[>..] = []; if env("GOOSE_CC", configured) && configured.len > 0 { return []; }
    var home:       u8[>..] = [];
    if !env("GOOSE_HOME", home) || home.len == 0 {
        home.clear(); if !env("HOME", home) || home.len == 0 { return []; } home.append("/.goose");
    }
    let compiler_home = if home[0] == '/' { str(home) } else { str(root, "/", home) };
    if platform::kind(str(compiler_home, "/config")) != 0 { return []; }
    if compiler.len == 0 || compiler[0] != '/' { return []; }
    cc = on_path("cc", root); if cc.len == 0 { return []; }
    var cc_real: u8[>..] = []; if !platform::real(cc, cc_real) { return []; }
    var state = crypto::Sha256 { .. };
    if crypto::init(state) != crypto::Error.None { return []; }
    var environment: u8[>..] = []; if !platform::cache_environment(environment) { return []; }
    for text in ["honk-reuse-1-standalone", compiler, cc[..], cc_real[..], environment[..], root, entry, if release { "release" } else { "debug" }] {
        if !feed(state, text) { return []; }
    }
    let original_std = std_source(compiler, root); if original_std.len == 0 { return []; }
    var standard: u8[>..] = [];
    if !platform::read(original_std, standard) || !pure(standard, graph, true) || !feed(state, original_std) || !feed(state, standard) { return []; }
    let stdlib = str(stage, "/.honk/stdlib");
    if !platform::mkdir(stdlib) || !platform::write_scratch(str(stdlib, "/std.goose"), standard) { return []; }
    let directory = project::parent(stage);
    var directories: u8[][>..]        = []; let first .= directories.push("");
    var queue:       const u8[:][>..] = []; queue.push(first); var cursor = 0; var bytes = 0; var count = 0;
    while cursor < queue.len {
        let current = queue[cursor]; cursor++;
        var entries: u8[>..] = []; if !platform::list(str(directory, "/", current), entries) { return []; }
        var start = 0;
        for c, i in entries {
            if c != '\n' { continue; } let name = entries[start..i]; start = i + 1;
            if name == ".honk" { continue; }
            let relative = str(current, "/", name); let file = str(directory, relative);
            let kind = platform::kind(file);
            if !feed(state, if kind == 2 { "directory" } else { "file" }) || !feed(state, relative) { return []; }
            if kind == 2 {
                if directories.len >= 4096 { return []; }
                let next .= directories.push(str(relative)); queue.push(next); continue;
            }
            if kind != 1 || suffix(name, ".build") || count >= 4096 { return []; }
            count++;
            // Metadata length is not trusted: read through the same bounded path.
            var data: u8[>..] = [];
            if !platform::read_staged(file, data) || data.len > MAX_BYTES - bytes { return []; }
            bytes += data.len;
            if suffix(name, ".goose") && !pure(data, graph) { return []; }
            if !feed(state, data) { return []; }
        }
    }
    // Source eligibility is cheaper than reading executable images; keep every
    // tool digest in the key, but avoid that work for conservative fallback.
    let compiler_hash, compiler_elf = digest(compiler, 268435456); if !compiler_elf { return []; }
    let cc_hash, cc_elf = digest(cc_real, 268435456); if !cc_elf { return []; }
    if !feed(state, compiler_hash) || !feed(state, cc_hash) { return []; }
    var hash: u8[32] = [0; 32]; var hex: u8[64] = [0; 64];
    if crypto::finish(state, hash[..]) != crypto::Error.None || crypto::hex_encode(hash[..], hex[..]) != crypto::Error.None { return []; }
    var out: u8[>..] = []; out.append(hex[..]); return out;
}
fn slot(root: u8[:], release: bool, create: bool) -> u8[>..] {
    let parent = str(root, "/.honk"); if !platform::cache_private(parent, true) { return []; }
    let state = str(parent, "/reuse"); if (create && !platform::mkdir(state)) || !platform::cache_private(state, true) { return []; }
    let directory = str(state, if release { "/release" } else { "/debug" });
    if (create && !platform::mkdir(directory)) || !platform::cache_private(directory, true) { return []; }
    return directory;
}
fn invalidate(directory: u8[:]) -> bool {
    if directory.len == 0 { return false; }
    let record = str(directory, "/record"); return platform::kind(record) == 0 || platform::unlink_regular(record);
}
fn restore(directory: u8[:], key: u8[:], private_dir: u8[:]) -> bool {
    if directory.len == 0 || key.len != 64 { return false; }
    let record = str(directory, "/record"); let program = str(directory, "/program");
    if !platform::cache_private(record, false) || !platform::cache_private(program, false) { return false; }
    var text: u8[>..] = [];
    if !platform::read(record, text) || text.len != 130 || text[..64] != key || text[64] != '\n' || text[129] != '\n' { return false; }
    if !platform::copy_files(directory, private_dir, "program\0") { return false; }
    let actual, elf = digest(str(private_dir, "/program"), 268435456);
    return elf && actual.len == 64 && actual == text[65..129];
}
fn store(directory: u8[:], key: u8[:], program: u8[:]) {
    if directory.len == 0 || key.len != 64 || !invalidate(directory) { return; }
    let digest, elf = digest(program, 268435456); if !elf { return; }
    let cached = str(directory, "/program");
    if !platform::install(program, cached, true) || !platform::cache_seal(cached) { return; }
    let record = str(key, "\n", digest, "\n"); platform::write(str(directory, "/record"), record, false, false);
}

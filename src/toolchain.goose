// SPDX-License-Identifier: Apache-2.0
namespace toolchain;
import std;
import os;
import .platform;
import .manifest;
let REVISION = "eadca409f68210893f366e60d0c2f0dc29a339be";
fn home() -> u8[>..] {
    var value: u8[>..] = [];
    if env("HONK_HOME", value) && value.len > 0 { platform::require(platform::mkdir(value), "cannot create HONK_HOME"); return platform::absolute(value); }
    value.clear();
    if env("XDG_CACHE_HOME", value) && value.len > 0 { value.append("/honk"); }
    else { value.clear(); platform::require(env("HOME", value) && value.len > 0, "set HONK_HOME or HOME"); value.append("/.cache/honk"); }
    platform::require(platform::mkdir(value), "cannot create Honk cache"); return platform::absolute(value);
}
// The pinned compiler treats backslashes as package path separators on POSIX.
// Reject incompatible roots before they can select or overwrite another tree.
fn compatible_path(path: u8[:]) -> bool {
    for c in path { if c == '\\' { return false; } } return true;
}
fn compiler(p: manifest::Project&, cache: u8[:], offline: bool) -> u8[>..] {
    let revision = if p.revision.len > 0 { p.revision[..] } else { REVISION };
    var selected: u8[>..] = [];
    if env("GOOSE", selected) && selected.len > 0 {
        // An explicit compiler must still match the project's pin.
        let binary = platform::absolute(selected);
        validate(binary, p.root, revision); return binary;
    }
    platform::require(compatible_path(cache), "compiler cache path contains a backslash unsupported by the pinned compiler; use another HONK_HOME or explicit GOOSE");
    let root = str(cache, "/toolchains/", revision); let binary = str(root, "/build/goose");
    let ready = str(root, "/build/.honk-complete");
    let complete = platform::kind(binary) == 1 && platform::kind(ready) == 1 && platform::load(ready) == revision;
    if !complete {
        platform::require(!offline, "compiler cache is missing or incomplete; set GOOSE or run honk toolchain online");
        if platform::kind(ready) != 0 { platform::require(platform::unlink_regular(ready), "cannot invalidate compiler completion marker"); }
        write_stderr(str("honk: bootstrapping Goose ", revision, "\n"));
        platform::require(platform::mkdir(root), "cannot create toolchain directory");
        if !is_dir(str(root, "/.git")) { platform::git(["init", root], p.root); }
        platform::git(["-C", root, "fetch", "--depth=1", "--", "https://github.com/aardappel/goose.git", revision], p.root);
        platform::git(["-C", root, "checkout", "--detach", revision], p.root);
        let actual = platform::git(["-C", root, "rev-parse", "HEAD"], p.root);
        platform::require(actual == revision, "compiler checkout has the wrong revision");
        platform::require(platform::mkdir(str(root, "/build")), "cannot create compiler build directory");
        platform::run(["cmake", "-S", root, "-B", str(root, "/build"), "-DCMAKE_BUILD_TYPE=Release", "-DGOOSE_BUILTIN_LIBS=none"], p.root);
        platform::run(["cmake", "--build", str(root, "/build"), "--parallel", "2"], p.root);
    }
    let actual = platform::git(["-C", root, "rev-parse", "HEAD"], p.root);
    platform::require(actual == revision, "cached compiler checkout has the wrong revision");
    validate(binary, p.root, revision);
    if !complete { platform::save(ready, revision); }
    return binary;
}

fn validate(binary: u8[:], cwd: u8[:], revision: u8[:]) {
    platform::require(platform::kind(binary) == 1, "compiler must be a regular file");
    let argv: const u8[:][] = [binary, "version"]; let version, code = platform::command(argv, cwd, true);
    let matching = version.len >= 13 && version[..6] == "goose " && version[6..13] == revision[..7] &&
                   (version.len == 13 || version[13] == ' ' || version[13] == '\n' || version[13] == '\r');
    platform::require(code == 0 && matching, "compiler does not match the pinned compiler revision");
}

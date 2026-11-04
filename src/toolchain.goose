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
fn compiler(p: manifest::Project&, cache: u8[:], offline: bool) -> u8[>..] {
    let revision = if p.revision.len > 0 { p.revision[..] } else { REVISION };
    var selected: u8[>..] = [];
    if env("GOOSE", selected) && selected.len > 0 {
        // An explicit compiler must still match the project's pin.
        let binary = if selected[0] == '/' { str(selected) } else { platform::absolute(selected) };
        let argv: const u8[:][] = [binary, "version"]; let version, code = platform::command(argv, p.root, true);
        let matching = version.len >= 13 && version[..6] == "goose " && version[6..13] == revision[..7] &&
                       (version.len == 13 || version[13] == ' ' || version[13] == '\n' || version[13] == '\r');
        platform::require(code == 0 && matching, "GOOSE does not match the pinned compiler revision"); return binary;
    }
    let root = str(cache, "/toolchains/", revision); let binary = str(root, "/build/goose");
    if !file_exists(binary) {
        platform::require(!offline, "compiler is not cached; set GOOSE or run honk toolchain online");
        write_stderr(str("honk: bootstrapping Goose ", revision, "\n"));
        platform::require(platform::mkdir(root), "cannot create toolchain directory");
        if !is_dir(str(root, "/.git")) { platform::git(["init", root], p.root); }
        platform::git(["-C", root, "fetch", "--depth=1", "--", "https://github.com/aardappel/goose.git", revision], p.root);
        platform::git(["-C", root, "checkout", "--detach", revision], p.root);
        platform::run(["cmake", "-S", root, "-B", str(root, "/build"), "-DCMAKE_BUILD_TYPE=Release", "-DGOOSE_BUILTIN_LIBS=none"], p.root);
        platform::run(["cmake", "--build", str(root, "/build"), "--parallel", "2"], p.root);
    }
    let actual = platform::git(["-C", root, "rev-parse", "HEAD"], p.root);
    platform::require(actual == revision, "cached compiler checkout has the wrong revision"); return binary;
}

// SPDX-License-Identifier: Apache-2.0
namespace distribution;
import std;
import os;
import .platform;
import .manifest;
import .deps;
import .build;
fn package(p: manifest::Project&, g: deps::Graph&) {
    // Path dependencies cannot be reproduced by recipients of a source archive.
    for n in g.nodes {
        let inside = n.directory.len > p.root.len && n.directory[..p.root.len] == p.root && n.directory[p.root.len] == '/';
        platform::require(n.git.len > 0 || inside, "package requires Git dependencies or vendored paths inside the project");
    }
    let stage = str(p.root, "/.honk/package"); platform::require(platform::remove_tree(stage), "cannot clear package staging directory");
    let label = str(p.name, "-", p.version); let directory = str(stage, "/", label);
    platform::require(platform::mkdir(directory), "cannot create package staging directory");
    platform::require(platform::copy_tree(p.root, directory), "cannot stage package sources");
    // Git's tracked file set defines a package. Never copy ignored/untracked local secrets.
    // copy_tree above validates all source entries before any archive operation.
    let staged = platform::git(["-C", p.root, "ls-files", "--stage", "-z"], p.root);
    var record = 0;
    for c, i in staged {
        if c != 0 { continue; }
        platform::require(i - record >= 7 && (staged[record..record + 6] == "100644" || staged[record..record + 6] == "100755"), "package does not support tracked submodules or symlinks"); record = i + 1;
    }
    let unmerged = platform::git(["-C", p.root, "ls-files", "--unmerged", "-z"], p.root); platform::require(unmerged.len == 0, "resolve merge conflicts before packaging");
    let tracked = platform::git(["-C", p.root, "ls-files", "-z", "--cached"], p.root);
    platform::require(tracked.len > 0, "package requires a Git repository with tracked files");
    // Tar reads an explicit NUL-delimited tracked list, with option parsing disabled for filenames.
    let list = str(p.root, "/.honk/package-files");
    var names: u8[>..] = []; var start = 0; var manifest_found = false; var lock_found = false;
    for c, i in tracked {
        if c != 0 { continue; } let name = tracked[start..i]; start = i + 1;
        platform::require(manifest::relative(name), "unsafe tracked package path");
        // Build state is never distributable, even if accidentally tracked.
        var first = name.len; for ch, j in name { if ch == '/' { first = j; break; } }
        platform::require(!build::skip(name[..first]), "build state must not be tracked in a package");
        if name == "Honk.toml" { manifest_found = true; } if name == "Honk.lock" { lock_found = true; }
        names.append(label); names.push('/'); names.append(name); names.push(0);
    }
    platform::require(manifest_found && lock_found, "track Honk.toml and Honk.lock before packaging");
    platform::save(list, names);
    let output = str(p.root, "/target/package"); platform::require(platform::mkdir(output), "cannot create package output directory");
    let archive = str(output, "/", label, ".tar.gz"); let temp = str(stage, "/archive.tar.gz");
    platform::run(["tar", "--create", "--gzip", "--file", temp, "--directory", stage, "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner", "--null", "--verbatim-files-from", "--no-recursion", "--files-from", list], p.root);
    platform::require(rename_file(temp, archive), "cannot commit package archive"); platform::require(platform::remove_tree(stage), "cannot clear packaged sources"); print(archive);
}
fn install(p: manifest::Project&, release: bool, destination: u8[:], force: bool) {
    platform::require(p.kind == "bin", "install requires a binary package");
    let binary = str(p.root, "/target/", if release { "release" } else { "debug" }, "/", p.name);
    let bin = str(destination, "/bin"); platform::require(platform::mkdir(bin), "cannot create installation bin directory");
    platform::require(platform::install(binary, str(bin, "/", p.name), force), "cannot install executable (already exists? use --force)");
    print("Installed ", bin, "/", p.name);
}

fn uninstall(destination: u8[:], name: u8[:]) {
    platform::require(manifest::package_name(name), "invalid executable name");
    let path = str(destination, "/bin/", name);
    platform::require(platform::kind(path) == 1, "installed executable does not exist or is a symlink");
    platform::require(delete_file(path), "cannot remove installed executable"); print("Uninstalled ", name);
}

// SPDX-License-Identifier: Apache-2.0
namespace distribution;
import std;
import os;
import nest;
import semver;
import toml;
import .platform;
import .manifest;
import .deps;
import .build;
import .build_cache;
import .source;
import .isolated;
struct PublishTarget { repo: const u8[:] = "", index: const u8[:] = "", fork: const u8[:] = "" }

fn https_url(url: const u8[:]) -> bool {
    return nest::url(url) && starts_with(url, "https://") && url.len > 8 &&
        url[8] != '/' && url[8] != '?' && url[8] != ':';
}
fn validate_publication(p: manifest::Project&, registry: u8[:], url: u8[:], schema_two: bool = false) {
    platform::require(nest::registry_url(registry) && (https_url(registry) || (schema_two && starts_with(registry, "http://127.0.0.1:"))),
        "publish requires an HTTPS registry index URL");
    platform::require(https_url(url), "publish requires an HTTPS archive URL without credentials or fragments");
    platform::require(p.kind == "lib" && nest::package_name(p.name), "publish requires a library with a valid registry package name");
    let version, error = semver::parse(p.version);
    platform::require(error.kind == semver::ErrorKind.None && version.build.len == 0, "publish requires SemVer without build metadata");
    for dep in p.dependencies {
        if dep.dev { continue; }
        platform::require(dep.registry == registry, "published production dependencies must come from the selected registry index");
    }
}
fn release_entry(p: manifest::Project&, registry: u8[:], url: u8[:], sha: u8[:], schema_two: bool) -> u8[>..] {
    validate_publication(p, registry, url, schema_two);
    var doc = toml::Document { .. };
    let error = toml::parse_into(platform::load(str(p.root, "/Honk.toml")), doc);
    platform::require(error.len == 0, error);
    let package = toml::find(doc, 0, "package");
    platform::require(package >= 0 && toml::find(doc, package, "version") >= 0 && toml::find(doc, package, "entry") >= 0,
        "publish requires explicit package.version and package.entry");
    platform::require(platform::kind(str(p.root, "/LICENSE")) == 1, "track LICENSE before publishing");
    var paths: u8[][>..] = []; build::files(p.root, "", paths);
    for path in paths {
        let text = platform::load(str(p.root, "/", path));
        platform::require(source::requirements(text).len == 0, "registry packages must declare dependencies in Honk.toml, without sourced imports");
    }
    var deps: nest::Dependency[>..] = [];
    for dep in p.dependencies {
        if !dep.dev {
            deps.push(nest::Dependency { alias: str(dep.name), package: str(dep.package), requirement: str(dep.requirement),
                optional: dep.optional, features: copy(dep.features), default_features: dep.default_features,
                target_os: str(dep.target_os), target_arch: str(dep.target_arch) });
        }
    }
    var features: nest::Feature[>..] = [];
    for feature in p.features { features.push(nest::Feature { name: str(feature.name), items: copy(feature.items) }); }
    let record = nest::Record { package: str(p.name), version: str(p.version), registry: str(registry), url: str(url), sha256: str(sha), entry: str(p.entry), dependencies: copy(deps), features: copy(features), .. };
    platform::require(nest::valid(record), "archive manifest cannot be represented in the registry index");
    var text = str("schema = ", if schema_two { 2 } else { 1 }, "\npackage = ");
    nest::quoted(text, record.package);
    text.append("\n\n[[releases]]\n");
    text.append(nest::record_text(record));
    return text;
}
fn package(p: manifest::Project&, g: deps::Graph&, compiler: u8[:], url: u8[:] = "", registry: u8[:] = "", target: PublishTarget = PublishTarget { .. }, schema_two: bool = false) {
    // Path dependencies cannot be reproduced by recipients of a source archive.
    for n in g.nodes {
        let inside = n.directory.len > p.root.len && n.directory[..p.root.len] == p.root && n.directory[p.root.len] == '/';
        platform::require(n.registry.len > 0 || n.git.len > 0 || (inside && n.path.len > 0 && n.path[0] != '/'), "package requires Git dependencies or vendored paths inside the project");
    }
    let stage = str(p.root, "/.honk/package"); platform::require(platform::remove_tree(stage), "cannot clear package staging directory");
    let label = str(p.name, "-", p.version); let directory = str(stage, "/", label);
    platform::require(platform::mkdir(directory), "cannot create package staging directory");
    // Only tracked paths enter staging; untracked files and secrets are never copied.
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
    platform::require(platform::copy_files(p.root, directory, tracked), "cannot copy tracked regular package files safely");
    platform::save_scratch(list, names);
    let output = str(p.root, "/target/package"); platform::require(platform::mkdir(output), "cannot create package output directory");
    let archive = str(output, "/", label, ".tar.gz"); let temp = str(stage, "/archive.tar.gz");
    platform::run(["tar", "--create", "--gzip", "--file", temp, "--directory", stage, "--format=gnu", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner", "--null", "--verbatim-files-from", "--no-recursion", "--files-from", list], p.root);
    // Verify the exact exported files, rather than accidentally depending on untracked local files.
    var staged_archive = str(temp);
    var source_root: u8[>..] = [];
    var sha:         u8[>..] = [];
    if url.len > 0 {
        let digest, _ = build_cache::digest(temp, 16777216);
        sha = str(digest);
        platform::require(sha.len == 64, "cannot hash registry archive (limit 16 MiB)");
        let cache = str(stage, "/registry/packages");
        platform::require(platform::mkdir(cache), "cannot create package verification directory");
        staged_archive = str(cache, "/", sha, ".tar.gz");
        platform::require(platform::cache_seal(temp), "cannot secure registry archive for verification");
        platform::require(rename_file(temp, staged_archive), "cannot stage registry archive for verification");
        platform::require(nest::native_materialize(url, sha, label, cache, true), nest::last_error());
        source_root = str(cache, "/", sha);
    } else {
        let verify = str(stage, "/verify");
        platform::require(platform::mkdir(verify), "cannot create package verification directory");
        platform::run(["tar", "--extract", "--gzip", "--file", temp, "--directory", verify, "--no-same-owner", "--no-same-permissions"], p.root);
        source_root = str(verify, "/", label);
    }
    var exported = manifest::Project { .. }; manifest::load(source_root, exported, schema_two);
    var metadata: u8[>..] = [];
    if url.len > 0 {
        platform::require(exported.name == p.name && exported.version == p.version && exported.revision == p.revision,
            "archive package identity or compiler pin differs from the selected manifest");
        metadata = release_entry(exported, registry, url, sha, schema_two);
    }
    if schema_two {
        var features: u8[][>..] = [];
        let no_args: u8[:][0] = [];
        isolated::execute(exported, exported.root, features, false, "check", no_args, false, true, true, false,
            "", "", "", "", "", "", "", false, true);
    } else {
        var resolved = deps::Graph { cache: str(g.cache), locked: true, offline: true, .. }; deps::resolve(exported, resolved);
        let no_args: u8[:][0] = [];
        let filter = build::TargetFilter { .. };
        build::compile(exported, resolved, compiler, "check", false, no_args, false, filter, "never", 0, 30000, "text", url.len > 0);
    }
    platform::require(rename_file(staged_archive, archive), "cannot commit package archive");
    platform::require(platform::remove_tree(stage), "cannot clear packaged sources");
    if metadata.len > 0 {
        write_stderr(str("honk: prepared ", archive, "\n"));
        if target.repo.len > 0 {
            platform::run(["python3", "-I", "-c", embed_file("publish_github.py"), "publish", target.repo, target.index, target.fork, archive, metadata], p.root);
        } else { write_stdout(metadata); }
    } else { print(archive); }
}
fn yank(name: u8[:], version: u8[:], index: u8[:], fork: u8[:], undo: bool) {
    platform::run(["python3", "-I", "-c", embed_file("publish_github.py"), "yank", index, fork, name, version,
        if undo { "undo" } else { "yank" }], platform::absolute("."));
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
    platform::require(platform::unlink_regular(path), "cannot remove installed executable (missing, nonregular, or symlinked prefix)"); print("Uninstalled ", name);
}

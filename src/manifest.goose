// SPDX-License-Identifier: Apache-2.0
namespace manifest;
const MAX_INPUT_BYTES = 1048576;
import std;
import semver;
import nest;
import toml;
import text;
import json;
import .platform;

struct Dependency { name: u8[], path: u8[], git: u8[], rev: u8[], dev: bool = false, requirement: u8[] = [], registry: u8[] = [], package: u8[] = [], optional: bool = false, features: u8[][] = [], default_features: bool = true }
struct Feature { name: u8[], items: u8[][] }
root struct Project {
    root:     u8[>..], name: u8[>..], version: u8[>..], entry: u8[>..], kind: u8[>..],
    revision: u8[>..], description: u8[>..], license: u8[>..], dependencies: Dependency[>..], members: u8[][>..], features: Feature[>..],
}
// Exact keywords from the pinned compiler lexer. Contextual names and builtin
// module names remain valid components of relative module imports.
fn keyword(s: u8[:]) -> bool {
    for reserved in ["import", "namespace", "struct", "enum", "type", "fn", "thread_fn", "export", "simd", "recursive",
                     "let", "var", "extern", "const", "pad", "reusable", "if", "else", "while", "for",
                     "in", "loop", "block", "guard", "match", "defer", "return", "break", "continue", "as",
                     "true", "false", "null", "self", "bool", "varint", "i8", "i16", "i32", "i64",
                     "u8", "u16", "u32", "u64", "f32", "f64"] {
        if s == reserved { return true; }
    }
    return false;
}
fn module_component(s: u8[:]) -> bool {
    if s.len == 0 { return false; }
    for c, i in s {
        if !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || (i > 0 && c >= '0' && c <= '9')) { return false; }
    }
    return !keyword(s);
}
fn source_entry(s: u8[:]) -> bool { relative(s) && s.len > 6 && s[s.len - 6..] == ".goose" }
fn module_entry(s: u8[:]) -> bool {
    if !source_entry(s) { return false; }
    let name = s[..s.len - 6]; var start = 0;
    for c, i in name {
        if c == '/' { if !module_component(name[start..i]) { return false; } start = i + 1; }
    }
    return module_component(name[start..]);
}
fn identifier(s: u8[:]) -> bool {
    if s.len == 0 || s.len > 64 { return false; }
    for c, i in s {
        if !((c >= 'a' && c <= 'z') || c == '_' || (i > 0 && c >= '0' && c <= '9')) { return false; }
    }
    if keyword(s) { return false; }
    for reserved in ["std", "os", "json", "math", "string", "base64", "binary", "csv", "exception", "ffi",
                     "regex", "vec", "rng", "utf8", "thread", "slot_pool", "slice_pool", "dictionary", "from", "root",
                     "inline"] {
        if s == reserved { return false; }
    }
    return true;
}
fn package_name(s: u8[:]) -> bool {
    if s.len == 0 || s.len > 64 || s[0] < 'a' || s[0] > 'z' { return false; }
    for c in s { if !((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_') { return false; } }
    return true;
}
fn relative(s: u8[:]) -> bool {
    if s.len == 0 || s.len > 1024 || s[0] == '/' || s[s.len - 1] == '/' { return false; }
    var start = 0;
    for c, i in s {
        if c < 32 || c == 127 || c == '\\' || c == ':' { return false; }
        if c == '/' { if i == start || s[start..i] == ".." || s[start..i] == "." { return false; } start = i + 1; }
    }
    return s[start..] != ".." && s[start..] != "." && s != "target" && !(s.len >= 7 && s[..7] == "target/");
}
fn commit(s: u8[:]) -> bool {
    if s.len != 40 { return false; }
    for c in s { if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) { return false; } }
    return true;
}
fn version(s: u8[:]) -> bool {
    if s.len > 64 { return false; }
    let parsed, error = semver::parse(s); return error.kind == semver::ErrorKind.None;
}

fn string(doc: toml::Document&, parent: i64, key: u8[:], fallback: u8[:] = "") -> u8[] {
    let id = toml::find(doc, parent, key);
    if id < 0 { return str(fallback); }
    platform::require(doc.nodes[id].kind == toml::Kind.String, str("expected string for ", key));
    let s = toml::text(doc, id);
    platform::require(s.len <= 4096, "manifest string exceeds 4096 bytes");
    for c in s { platform::require(c >= 32 && c != 127, "control character in manifest value"); }
    return str(s);
}
fn keys(doc: toml::Document&, parent: i64, allowed: const u8[:][:]) {
    platform::require(parent >= 0 && doc.nodes[parent].kind == toml::Kind.Table, "expected a TOML table");
    var id = doc.nodes[parent].first;
    while id >= 0 {
        var known = false; for k in allowed { if toml::key(doc, id) == k { known = true; } }
        platform::require(known, str("unknown manifest key: ", toml::key(doc, id)));
        id = doc.nodes[id].next;
    }
}
fn version_requirement(value: const u8[:]) -> bool {
    if value.len == 0 || value.len > 4096 || text::validate_utf8(value) != -1 { return false; }
    for c in value { if c < 32 || c == 127 { return false; } }
    let requirement, error = semver::parse_requirement(value); return error.kind == semver::ErrorKind.None;
}
fn validate_dependency(dep: Dependency&) {
    if dep.registry.len > 0 {
        platform::require(dep.path.len == 0 && dep.git.len == 0 && dep.rev.len == 0 && nest::registry_url(dep.registry) && nest::package_name(dep.package) && nest::valid_requirement(dep.requirement), "invalid registry dependency"); return;
    }
    platform::require((dep.path.len > 0) != (dep.git.len > 0), "dependency needs exactly one of path, git, or registry");
    if dep.git.len > 0 {
        platform::require(dep.git.len > 8 && dep.git[..8] == "https://", "Git sources must use https://");
        platform::require((dep.rev.len > 0) != (dep.requirement.len > 0), "Git dependency needs exactly one of rev or version");
        if dep.rev.len > 0 { platform::require(dep.rev.len <= 256 && dep.rev[0] != '-', "Git dependency needs a non-option rev"); }
        if dep.requirement.len > 0 { platform::require(version_requirement(dep.requirement), "Git version needs an explicit full-version requirement (ASCII space only, limit 4096 bytes)"); }
        for c in dep.git { platform::require(c != '@' && c != '?' && c != '#', "Git URL must not contain credentials, query, or fragment"); }
        for c in dep.rev { platform::require(c > 32 && c != 127 && c != ':' && c != '\\', "invalid Git ref"); }
    } else { platform::require(dep.rev.len == 0 && dep.requirement.len == 0, "path dependency cannot specify rev or version"); }
    for value in [dep.path[..], dep.git[..], dep.rev[..], dep.requirement[..]] {
        platform::require(text::validate_utf8(value) == -1, "dependency values must be valid UTF-8");
        platform::require(value.len <= 4096, "dependency value exceeds 4096 bytes");
        for c in value { platform::require(c >= 32 && c != 127, "control character in dependency value"); }
    }
}
fn read_dependencies(doc: toml::Document&, key: u8[:], dev: bool, project: Project&, isolated: bool) {
    let table = toml::find(doc, 0, key); if table < 0 { return; }
    platform::require(doc.nodes[table].kind == toml::Kind.Table, "dependencies must be a table");
    var id = doc.nodes[table].first;
    while id >= 0 {
        let name = toml::key(doc, id);
        platform::require(identifier(name), str("invalid dependency import name: ", name));

        keys(doc, id, ["path", "git", "rev", "version", "registry", "package", "optional", "features", "default-features"]);
        let optional_id = toml::find(doc, id, "optional");
        var optional = false;
        if optional_id >= 0 {
            platform::require(isolated && !dev && doc.nodes[optional_id].kind == toml::Kind.Boolean, "optional requires an isolated production dependency and a boolean");
            optional = doc.nodes[optional_id].boolean;
        }
        let defaults = toml::find(doc, id, "default-features");
        if defaults >= 0 {
            platform::require(isolated && doc.nodes[defaults].kind == toml::Kind.Boolean, "default-features requires an isolated dependency and a boolean");
        }
        let default_features = defaults < 0 || doc.nodes[defaults].boolean;
        let has_rev = toml::find(doc, id, "rev") >= 0; let has_version = toml::find(doc, id, "version") >= 0;
        platform::require(!(has_rev && has_version), "rev and version fields are mutually exclusive");
        platform::require(toml::find(doc, id, "path") < 0 || (!has_rev && !has_version), "path dependency cannot contain rev or version fields");
        if has_version { platform::require(version_requirement(string(doc, id, "version")), "invalid Git version requirement (ASCII space only, limit 4096 bytes)"); }
        let registry_source = string(doc, id, "path").len == 0 && string(doc, id, "git").len == 0;
        var features: u8[][>..] = [];
        let feature_list = toml::find(doc, id, "features");
        if feature_list >= 0 {
            platform::require(isolated, "dependency features require an isolated dependency");
            platform::require(doc.nodes[feature_list].kind == toml::Kind.Array && doc.nodes[feature_list].count <= 256, "dependency features must be an array of at most 256 names");
            var item = doc.nodes[feature_list].first;
            while item >= 0 {
                platform::require(doc.nodes[item].kind == toml::Kind.String, "dependency feature names must be strings");
                let feature = toml::text(doc, item);
                platform::require(package_name(feature), "invalid dependency feature name");
                features.push(str(feature)); item = doc.nodes[item].next;
            }
        }
        let dep = if registry_source {
            Dependency { name: str(name), dev: dev, requirement: string(doc, id, "version"), registry: string(doc, id, "registry", nest::DEFAULT_REGISTRY), package: string(doc, id, "package", name), optional: optional, features: copy(features), default_features: default_features, .. }
        } else {
            platform::require(toml::find(doc, id, "registry") < 0 && toml::find(doc, id, "package") < 0, "Git/path dependencies cannot specify registry/package");
            Dependency { name: str(name), path: string(doc, id, "path"), git: string(doc, id, "git"), rev: string(doc, id, "rev"), dev: dev, requirement: string(doc, id, "version"), optional: optional, features: copy(features), default_features: default_features, .. }
        };
        validate_dependency(dep);
        for prior in project.dependencies {
            if prior.name != name { continue; }
            platform::require(isolated && dev && !prior.dev, "duplicate dependency across dependency tables");
            platform::require(prior.path == dep.path && prior.git == dep.git && prior.rev == dep.rev && prior.registry == dep.registry && prior.package == dep.package && prior.requirement == dep.requirement, "shared isolated production and development aliases require identical source and version requirements");
        }
        platform::require(project.dependencies.len < 256, "dependency limit is 256");
        project.dependencies.push(copy(dep)); id = doc.nodes[id].next;
    }
}
fn feature_index(project: Project&, name: u8[:]) -> i64 {
    for feature, i in project.features { if feature.name == name { return i; } }
    return -1;
}
fn read_features(doc: toml::Document&, table: i64, project: Project&) {
    platform::require(doc.nodes[table].kind == toml::Kind.Table, "features must be a table");
    var id = doc.nodes[table].first;
    while id >= 0 {
        let name = toml::key(doc, id);
        platform::require(package_name(name) && project.features.len < 256, "invalid feature name or feature limit exceeded");
        platform::require(doc.nodes[id].kind == toml::Kind.Array && doc.nodes[id].count <= 256, "feature must be an array of at most 256 items");
        var items: u8[][>..] = [];
        var item = doc.nodes[id].first;
        while item >= 0 {
            platform::require(doc.nodes[item].kind == toml::Kind.String, "feature items must be strings");
            items.push(str(toml::text(doc, item)));
            item = doc.nodes[item].next;
        }
        project.features.push(Feature { name: str(name), items: copy(items) });
        id = doc.nodes[id].next;
    }
    for feature in project.features {
        for item in feature.items {
            if item.len > 4 && item[..4] == "dep:" {
                var found = false;
                for dep in project.dependencies { if dep.optional && dep.name == item[4..] { found = true; } }
                platform::require(found, str("unknown optional dependency in feature: ", item));
            } else {
                let alias, name, weak = nest::forwarded_feature(item);
                if alias.len > 0 {
                    var found = false;
                    for dep in project.dependencies { if !dep.dev && dep.name == alias && (!weak || dep.optional) { found = true; break; } }
                    platform::require(found && nest::feature_name(name), str("invalid dependency feature reference: ", item));
                } else {
                    platform::require(feature_index(project, item) >= 0, str("unknown feature reference: ", item));
                }
            }
        }
    }
}
fn load(root: u8[:], project: Project&, isolated: bool = false) {
    project.root = platform::absolute(root);
    let input = platform::load(str(project.root, "/Honk.toml"));
    parse(input, project, isolated);
}
fn parse(input: u8[:], project: Project&, isolated: bool = false) {
    var doc = toml::Document { .. }; let error = toml::parse_into(input, doc);
    platform::require(error.len == 0, error);
    keys(doc, 0, ["package", "dependencies", "dev-dependencies", "toolchain", "workspace", "features"]);
    let package = toml::find(doc, 0, "package");
    if package >= 0 {
        keys(doc, package, ["name", "version", "entry", "kind", "description", "license"]);
        project.description = string(doc, package, "description"); project.license = string(doc, package, "license");
        project.name = string(doc, package, "name"); project.version = string(doc, package, "version", "0.1.0");
        project.kind = string(doc, package, "kind", "bin");
        platform::require(package_name(project.name), "invalid package name (lowercase ASCII, digits, hyphen, underscore)");
        platform::require(version(project.version), "version must be strict SemVer (limit 64 bytes)");
        platform::require(project.kind == "bin" || project.kind == "lib", "kind must be bin or lib");
        project.entry = string(doc, package, "entry", if project.kind == "bin" { "src/main.goose" } else { "src/lib.goose" });
        platform::require(source_entry(project.entry), "entry must be a safe relative .goose path");
        if project.kind == "lib" { platform::require(module_entry(project.entry), "library entry path components must be Goose identifiers (not keywords)"); }
    }
    let toolchain = toml::find(doc, 0, "toolchain");
    if toolchain >= 0 {
        keys(doc, toolchain, ["revision"]); project.revision = string(doc, toolchain, "revision");
        platform::require(commit(project.revision), "toolchain revision must be a full lowercase commit hash");
    }
    let workspace = toml::find(doc, 0, "workspace");
    if workspace >= 0 {
        keys(doc, workspace, ["members"]); let members = toml::find(doc, workspace, "members");
        platform::require(members >= 0 && doc.nodes[members].kind == toml::Kind.Array, "workspace needs a members array");
        var id = doc.nodes[members].first;
        while id >= 0 {
            platform::require(doc.nodes[id].kind == toml::Kind.String, "workspace members must be strings");
            let member = toml::text(doc, id); platform::require(relative(member), "unsafe workspace member path");
            for m in project.members { platform::require(m != member, "duplicate workspace member"); }
            platform::require(project.members.len < 256, "workspace member limit is 256");
            project.members.push(str(member)); id = doc.nodes[id].next;
        }
    }
    platform::require(package >= 0 || project.members.len > 0, "manifest needs a package or nonempty workspace");
    read_dependencies(doc, "dependencies", false, project, isolated);
    read_dependencies(doc, "dev-dependencies", true, project, isolated);
    let features = toml::find(doc, 0, "features");
    if features >= 0 {
        platform::require(isolated && package >= 0, "features require an isolated package manifest");
        read_features(doc, features, project);
    }
}
fn quoted(out: u8[>..]&, s: u8[:]) { json::format_string(out, s); }
fn serialize(project: Project&) -> u8[>..] {
    var out: u8[>..] = [];
    if project.name.len > 0 {
        out.append("[package]\nname = "); quoted(out, project.name); out.append("\nversion = "); quoted(out, project.version);
        out.append("\nkind = "); quoted(out, project.kind); out.append("\nentry = "); quoted(out, project.entry); out.push('\n');
        if project.description.len > 0 { out.append("description = "); quoted(out, project.description); out.push('\n'); }
        if project.license.len > 0 { out.append("license = "); quoted(out, project.license); out.push('\n'); }
    }
    if project.revision.len > 0 { out.append("\n[toolchain]\nrevision = "); quoted(out, project.revision); out.push('\n'); }
    if project.members.len > 0 {
        out.append("\n[workspace]\nmembers = ["); for m, i in project.members { if i > 0 { out.append(", "); } quoted(out, m); } out.append("]\n");
    }
    for dev in [false, true] {
        out.append(if dev { "\n[dev-dependencies]\n" } else { "\n[dependencies]\n" });
        for dep in project.dependencies {
            if dep.dev != dev { continue; } out.append(dep.name); out.append(" = { ");
            if dep.path.len > 0 { out.append("path = "); quoted(out, dep.path); }
            else if dep.registry.len > 0 { out.append("package = "); quoted(out, dep.package); out.append(", registry = "); quoted(out, dep.registry); out.append(", version = "); quoted(out, dep.requirement); }
            else { out.append("git = "); quoted(out, dep.git); out.append(if dep.requirement.len > 0 { ", version = " } else { ", rev = " }); quoted(out, if dep.requirement.len > 0 { dep.requirement[..] } else { dep.rev[..] }); }
            out.append(" }\n");
        }
    }
    return out;
}

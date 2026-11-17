// SPDX-License-Identifier: Apache-2.0
namespace registry;
import std;
import toml;
import semver;
import nest;
import argparse;
import .platform;
import .toolchain;
fn discover(cmd: u8[:], options: const argparse::Result&) {
    platform::require(options.positionals.len <= 1 && (cmd != "info" || options.positionals.len == 1), "search accepts one query; info requires one package name");
    let registry = options.get("registry", nest::DEFAULT_REGISTRY);
    platform::require(nest::registry_url(registry), "invalid registry index URL");
    let offline = options.has("offline") || options.has("frozen");
    let cache = str(toolchain::home(), "/nest");
    let query = if options.positionals.len > 0 { options.positionals[0] } else { "" };
    platform::require(query.len <= 64, "registry query exceeds 64 bytes");
    let package = if cmd == "search" { "_catalog" } else { query };
    platform::require(cmd == "search" || nest::package_name(package), "invalid registry package name");
    var input: u8[>..] = []; input.resize(1048576, 0);
    let size = nest::native_index(registry, package, str(cache, "/index"), offline, !offline, input[..]);
    platform::require(size >= 0, nest::last_error()); input.resize(size);
    if cmd == "info" {
        var records: nest::Record[>..] = [];
        let error = nest::parse_index(input, registry, package, records); platform::require(error.len == 0, error);
        for record in records {
            print(record.package, " ", record.version, if record.yanked { " (yanked)" } else { "" });
            print("  entry: ", record.entry, "\n  sha256: ", record.sha256);
            for dep in record.dependencies { print("  ", dep.alias, " -> ", dep.package, " ", dep.requirement); }
        }
        return;
    }
    var doc = toml::Document { .. }; let error = toml::parse_into(input, doc); platform::require(error.len == 0, error);
    platform::require(nest::keys(doc, 0, ["schema", "packages"]), "invalid registry catalog");
    let schema = toml::find(doc, 0, "schema"); let array = toml::find(doc, 0, "packages");
    platform::require(schema >= 0 && doc.nodes[schema].kind == toml::Kind.Integer && doc.nodes[schema].integer == 1 && array >= 0 && doc.nodes[array].kind == toml::Kind.Array && doc.nodes[array].count <= 4096, "unsupported registry catalog");
    var id = doc.nodes[array].first;
    while id >= 0 {
        let name = nest::string(doc, id, "name"); let version = nest::string(doc, id, "version");
        let parsed, version_error = semver::parse(version);
        platform::require(nest::package_name(name) && version_error.kind == semver::ErrorKind.None, "invalid catalog package");
        if query.len == 0 || find(name, query) >= 0 { print(name, " ", version); }
        id = doc.nodes[id].next;
    }
}

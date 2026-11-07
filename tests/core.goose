// SPDX-License-Identifier: Apache-2.0
import watch from "../vendor/goose-watch";
import glob from "../vendor/goose-glob";
import crypto from "../vendor/goose-crypto";
import http from "../vendor/goose-http";
import honk_metadata from "../vendor/honk-metadata";
import process from "../vendor/goose-process";
import semver from "../vendor/goose-semver";
import text from "../vendor/goose-text";
import toml_edit from "../vendor/goose-toml-edit";
import toml from "../vendor/goose-toml";
import argparse from "../vendor/goose-argparse";
import logger from "../vendor/goose-log";
import time from "../vendor/goose-time";
import utc from "../vendor/goose-log/examples/utc";
import posix from "../vendor/goose-terminal";
import task from "../vendor/goose-task";
import honk from "..";
import std;
fn main() {
    var cache_graph = deps::Graph { .. };
    var generated: u8[>..] = [];
    // Generated declarations can exceed original-file limits; cache eligibility
    // must reject conservatively without the fatal source requirements parser.
    for i in 257 { generated.append(str("import alias", i, " from \"/stage/app\";\n")); }
    assert(!build_cache::pure(generated, cache_graph, false, "/stage/app"));
    assert(build_cache::pure("import local from \"/stage/app\"; import local.mod;", cache_graph, false, "/stage/app"));
    assert(!build_cache::pure("import local from \"/external\";", cache_graph, false, "/stage/app"));

    assert(manifest::identifier("json_codec"));
    assert(!manifest::identifier("json-codec"));
    assert(!manifest::identifier("std"));
    assert(manifest::relative("src/main.goose"));
    assert(!manifest::relative("../main.goose"));
    assert(!manifest::relative("src/../main.goose"));
    assert(!manifest::relative("target/main.goose"));
    assert(manifest::module_entry("Src/from.goose"));
    assert(manifest::module_entry("src/std.goose"));
    assert(!manifest::module_entry("src/fn.goose"));
    assert(!manifest::module_entry("src/lib-entry.goose"));
    assert(!manifest::source_entry("src/main.txt"));
    assert(manifest::commit(toolchain::REVISION));
    assert(!manifest::commit("main"));
    assert(source::requirements("/* nested /* import bad from \"x\"; */ */ fn main() {}").len == 0);
    let text = "import sample from \"../sample\"; import sample.other;";
    let reqs = source::requirements(text);
    assert(reqs.len == 1);
    for req in reqs { assert(req.name == "sample" && req.source == "../sample"); assert(text[req.start..req.end] == "from \"../sample\""); }
    assert(source::requirements("let s = \"\"\"import bad from \"x\";\"\"\";").len == 0);
    print("core contracts passed");
}

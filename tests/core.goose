// SPDX-License-Identifier: Apache-2.0
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
import honk from "..";
import std;
fn main() {
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

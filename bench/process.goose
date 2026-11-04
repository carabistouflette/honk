// SPDX-License-Identifier: Apache-2.0
import logger from "../vendor/goose-log";
import http from "../vendor/goose-http";
import honk_metadata from "../vendor/honk-metadata";
import process from "../vendor/goose-process";
import semver from "../vendor/goose-semver";
import text from "../vendor/goose-text";
import toml from "../vendor/goose-toml";
import argparse from "../vendor/goose-argparse";
import honk from "..";
import std;
fn main() {
    let argv = args();
    let mode = argv[1];
    for i in 200 {
        if mode == "inherit" { let out, code = platform::command(["/bin/true"], "."); assert(code == 0 && out.len == 0); }
        else if mode == "tiny" { let out, code = platform::command(["/bin/echo", "tiny"], ".", true); assert(code == 0 && out == "tiny\n"); }
        else { let out, code = platform::command(["/usr/bin/head", "-c", "65536", "/dev/zero"], ".", true); assert(code == 0 && out.len == 65536); for c in out { assert(c == 0); } }
    }
}

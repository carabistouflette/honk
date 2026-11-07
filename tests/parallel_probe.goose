// SPDX-License-Identifier: Apache-2.0
import task from "../vendor/goose-task";
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
import honk from "..";
import std;
import os;
extern fn verify() -> bool = "hp_parallel_verify";
fn main() {
    var mode: u8[>..] = []; assert(env("HONK_PARALLEL_FAULT", mode));
    let launch = mode == "launch";
    let programs:  (const u8[:])[2] = ["/bin/sleep", if launch { "/does/not/exist/parallel-test" } else { "/bin/sleep" }];
    let arguments: (const u8[:])[1] = [if mode == "success" || mode == "close" { "0.01" } else { "2" }];
    var display = presentation::Output { .. };
    let result = parallel_tests::run(programs, arguments, "/", 2, 1000, display);
    if mode == "success" { assert(result.code == 0 && result.failure == parallel_tests::Failure.None); }
    else {
        assert(result.code == 125);
        if launch { assert(result.failure == parallel_tests::Failure.Launch && result.target == 1); }
        else { assert(result.failure == parallel_tests::Failure.Supervision); }
    }
    assert(verify());
    print("parallel fault probe passed");
}

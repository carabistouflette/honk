// SPDX-License-Identifier: Apache-2.0
import glob from "../vendor/goose-glob";
import crypto from "../vendor/goose-crypto";
import toml_edit from "../vendor/goose-toml-edit";
import logger from "../vendor/goose-log";
import time from "../vendor/goose-time";
import utc from "../vendor/goose-log/examples/utc";
import http from "../vendor/goose-http";
import honk_metadata from "../vendor/honk-metadata";
import process from "../vendor/goose-process";
import semver from "../vendor/goose-semver";
import text from "../vendor/goose-text";
import toml from "../vendor/goose-toml";
import argparse from "../vendor/goose-argparse";
import posix from "../vendor/goose-terminal";
import honk from "..";
import std;
import os;
extern fn ignore_chld() = "honk_test_ignore_chld";
extern fn verify() = "honk_test_process_verify";
fn main() {
    let argv = args(); ignore_chld();
    let lock = platform::lock(argv[1]); assert(lock >= 0);
    let out, code = platform::command(["/bin/sleep", "30"], ".", true);
    let expected = if argv.len > 2 { 125 } else { 143 }; assert(code == expected);
    verify(); platform::unlock(lock);
}

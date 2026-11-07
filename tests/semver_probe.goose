// SPDX-License-Identifier: Apache-2.0
import watch from "../vendor/goose-watch";
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
fn main() {
    let argv = args();
    if argv.len < 3 { exit(2); }
    let version, error = version_policy::parse_tag(argv[2]);
    if error.kind != semver::ErrorKind.None { exit(2); }
    if argv[1] == "tag" { print(semver::format(version)); return; }
    if argv[1] != "match" || argv.len != 4 { exit(2); }
    let requirement, req_error = semver::parse_requirement(argv[3]);
    if req_error.kind != semver::ErrorKind.None { exit(2); }
    if !semver::matches(requirement, version) { exit(1); }
}

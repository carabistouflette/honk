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
fn checkpoint(label: const u8[:]) {
    print("\n@@QUAL ", label);
    assert(platform::flush_stdout());
    var line: u8[>..] = [];
    assert(read_line(line) && line == "continue");
}
fn main() {
    let argv = args(); assert(argv.len == 7);
    let mode = argv[1];
    var display = presentation::Output { .. };
    let empty: (const u8[:])[0] = [];
    checkpoint("baseline");
    if mode == "endurance" {
        var programs: (const u8[:])[>..] = [];
        for i in 64 { programs.push(argv[2 + i % 4]); }
        for round in 8 {
            let result = parallel_tests::run(programs, empty, ".", 4, 30000, display);
            assert(result.code == 0 && result.failure == parallel_tests::Failure.None);
            checkpoint("round");
        }
    } else if mode == "failure" {
        let programs: (const u8[:])[12] = [argv[2], argv[3], argv[4], argv[5], argv[2], "/bin/false", argv[4], argv[5], argv[2], argv[3], argv[4], argv[5]];
        let result = parallel_tests::run(programs, empty, ".", 4, 30000, display);
        assert(result.code == 1 && result.failure == parallel_tests::Failure.None && result.target == 5);
        checkpoint("failure");
    } else if mode == "timeout" || mode == "cancel" {
        let programs:  (const u8[:])[2] = ["/bin/sleep", "/bin/sleep"];
        let arguments: (const u8[:])[1] = ["2"];
        let result = parallel_tests::run(programs, arguments, ".", 2, if mode == "timeout" { 100 } else { 5000 }, display);
        if mode == "timeout" { assert(result.code == 125 && result.failure == parallel_tests::Failure.TimedOut); }
        else { assert(result.code == 143 && result.failure == parallel_tests::Failure.None); }
        checkpoint(mode);
    } else {
        let programs:  (const u8[:])[2] = [argv[2], argv[6]];
        let arguments: (const u8[:])[1] = [mode];
        let result = parallel_tests::run(programs, arguments, ".", 2, 30000, display);
        if mode == "pressure" { assert(result.code == 0 && result.failure == parallel_tests::Failure.None); }
        else { assert(mode == "overflow" && result.code == 125 && result.failure == parallel_tests::Failure.OutputLimit); }
        checkpoint(mode);
    }
}

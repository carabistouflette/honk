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
import posix from "../vendor/goose-terminal";
import honk from "..";
import std;
import os;
extern fn close(fd: i32) -> i32;
fn main() {
    let argv = args();
    if argv.len > 1 && argv[1] == "deadline" {
        assert(argv.len == 3);
        var packed: u8[>..] = []; platform::pack(packed, "/usr/bin/python3"); platform::pack(packed, "-I"); platform::pack(packed, "-c");
        platform::pack(packed, "import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text('started');time.sleep(30)"); platform::pack(packed, argv[2]);
        var out: u8[>..] = []; let status = platform::spawn(packed, ".", true, out, 1000);
        assert(status == 125 && out.len == 0); return;
    }
    if argv.len > 1 && argv[1] == "streams" {
        let out, code = platform::command(["/usr/bin/python3", "-c", "import sys;sys.stdout.buffer.write(b'a\\x00b');sys.stderr.write('live-stderr')"], ".", true);
        assert(code == 0 && out == "a\0b"); return;
    }
    if argv.len > 1 && argv[1] == "stdin" {
        let out, code = platform::command(["/bin/cat"], ".", true); assert(code == 0 && out == "inherited stdin\n"); return;
    }
    if argv.len > 1 && argv[1] == "exact" {
        let out, code = platform::command(["/usr/bin/head", "-c", "1048576", "/dev/zero"], ".", true);
        assert(code == 0 && out.len == 1048576); for c in out { assert(c == 0); } return;
    }
    if argv.len > 1 && argv[1] == "arguments" {
        var many: (const u8[:])[>..] = []; many.push("/bin/true"); for i in 4095 { many.push("x"); }
        let out, code = platform::command(many[..], ".", true); assert(code == 0);
        many.push("x"); let overflow, overflow_code = platform::command(many[..], ".", true); assert(overflow_code == 125);
        var buffer: u8[>..] = [];
        assert(platform::spawn("/bin/true\0bad", ".", true, buffer) == 125);
        return;
    }
    if argv.len > 1 && argv[1] == "overflow" {
        let text, status = platform::command(["/usr/bin/python3", "-c", "import sys;sys.stdout.buffer.write(b'x'*1048577)"], ".", true);
        assert(status == 125 && text.len <= 1048576); return;
    }
    if argv.len > 1 && argv[1] == "signal" {
        let text, status = platform::command(["/usr/bin/python3", "-c", "import os,signal;os.kill(os.getpid(),signal.SIGTERM)"], ".", true);
        assert(status == 143); return;
    }
    if argv.len > 1 && argv[1] == "missing" {
        let text, status = platform::command(["/definitely/missing/honk-test-command"], ".", true);
        assert(status == 127); return;
    }
    if argv.len > 1 && argv[1] == "closed" { close(0); close(1); }
    let text, status = platform::command(["/bin/echo", "captured"], ".", true);
    if status != 0 || text != "captured\n" { write_stderr("capture failed\n"); exit(1); }
}

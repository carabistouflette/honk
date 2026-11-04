// SPDX-License-Identifier: Apache-2.0
import text from "../vendor/goose-text";
import toml from "../vendor/goose-toml";
import argparse from "../vendor/goose-argparse";
import honk from "..";
import std;
import os;
extern fn close(fd: i32) -> i32;
fn main() {
    let argv = args();
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

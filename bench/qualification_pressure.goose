// SPDX-License-Identifier: Apache-2.0
import std;
import os;
fn main() {
    let argv = args(); assert(argv.len == 2);
    var bytes: u8[>..] = [];
    for i in 65536 { bytes.push('x'); }
    if argv[1] == "overflow" { bytes.push('x'); }
    write_stdout(bytes);
    write_stderr(bytes);
}

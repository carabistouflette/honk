// SPDX-License-Identifier: Apache-2.0
// Exercise the real consumer and POSIX adapter with test-only libc write faults.
import posix from "../vendor/goose-terminal";
import presentation from "../src";
import std;
import os;
extern fn select_mode(mode: i64) = "honk_test_write_mode";
extern fn calls() -> i64 = "honk_test_write_calls";
fn main() {
    assert(arg_count() == 2);
    var text: u8[>..] = []; arg(1, text);
    let mode, ok = parse_int(text); assert(ok && mode >= 0 && mode <= 3);
    select_mode(mode);
    var output = presentation::Output { mode: presentation::Mode.Always, .. };
    presentation::summary(output, "first");
    presentation::summary(output, "second");
    let expected_calls = [6, 7, 2, 64];
    assert(calls() == expected_calls[mode]);
    assert(output.failed == (mode >= 2));
    print("application success");
}

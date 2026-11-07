// SPDX-License-Identifier: Apache-2.0
// Exercise the actual diagnostics path using deterministic application callbacks.
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

// Unrelated consumer hooks cannot change fixed events, numeric fields or UTC.
fn format(out: u8[>..]&, value: i64) { out.append("hostile signed"); }
fn format(out: u8[>..]&, value: u64) { out.append("hostile unsigned"); }
fn format(out: u8[>..]&, value: const u8[:]) { out.append("hostile text"); }

fn initial_unconfigured() {
    assert(!diagnostics::active());
    var clocks = 0;
    var sinks = 0;
    fn clock() -> i64 { clocks++; 0 }
    fn sink(line: const u8[:]) -> bool { sinks++; false }
    assert(diagnostics::write_with(diagnostics::Event.Started, 0, 0, clock, sink));
    assert(diagnostics::write_with(diagnostics::Event.Failed, 1, 1, clock, sink));
    assert(clocks == 0 && sinks == 0 && !diagnostics::active());
}
fn levels_and_events() {
    let minimums = [log::Level.Trace, log::Level.Debug, log::Level.Info,
                    log::Level.Warn, log::Level.Error, log::Level.Fatal, log::Level.Off];
    let events = [diagnostics::Event.Started, diagnostics::Event.ItemCompleted,
                  diagnostics::Event.Returned, diagnostics::Event.Failed, diagnostics::Event.ChildFailed];
    let names = ["started", "item_completed", "returned", "failed", "child_failed"];
    for minimum, mi in minimums {
        assert(diagnostics::configure("/not-opened/private-marker-value", minimum));
        assert(diagnostics::active() == (mi != 6));
        for event, ei in events {
            var clocks = 0;
            var sinks = 0;
            var expected: u8[>..] = [];
            expected.append(if ei < 3 { "[INFO]" } else { "[ERROR]" });
            expected.append(" timestamp=\"1970-01-01T00:00:00Z\" ");
            expected.append(names[ei]); expected.append(" duration_ns=123 outcome=7\n");
            fn clock() -> i64 { clocks++; 0 }
            fn sink(line: const u8[:]) -> bool { sinks++; assert(line == expected); true }
            assert(diagnostics::write_with(event, 123, 7, clock, sink));
            let enabled = mi < 3 || ((mi == 3 || mi == 4) && ei >= 3);
            assert(clocks == (if enabled { 1 } else { 0 }));
            assert(sinks == clocks && diagnostics::active() == (mi != 6));
        }
    }
}
struct Sample { nanoseconds: i64, expected: const u8[:] }
fn exact_samples_and_owned_output() {
    let samples = [
        Sample { -9223372036854775808, "1677-09-21T00:12:43.145224192Z" },
        Sample { 9223372036854775807, "2262-04-11T23:47:16.854775807Z" },
        Sample { -1, "1969-12-31T23:59:59.999999999Z" },
        Sample { -1000000000, "1969-12-31T23:59:59Z" },
        Sample { 1, "1970-01-01T00:00:00.000000001Z" },
        Sample { 123400000, "1970-01-01T00:00:00.1234Z" },
        Sample { 0, "1970-01-01T00:00:00Z" },
    ];
    assert(diagnostics::configure("/not-opened/diagnostics"));
    var clocks = 0;
    var sinks = 0;
    var retained: u8[>..] = [];
    for sample, index in samples {
        var expected: u8[>..] = [];
        expected.append("[INFO] timestamp=\""); expected.append(sample.expected);
        expected.append("\" returned duration_ns=18446744073709551615 outcome=4294967295\n");
        fn clock() -> i64 { clocks++; sample.nanoseconds }
        fn sink(line: const u8[:]) -> bool {
            sinks++;
            assert(line == expected);
            retained.clear(); retained.append(line);
            true
        }
        assert(diagnostics::write_with(diagnostics::Event.Returned, 18446744073709551615, 4294967295, clock, sink));
        assert(clocks == index + 1 && sinks == index + 1);
        assert(retained == expected);
    }
    // Owned copies survive later emissions using separate lexical line storage.
    let saved = copy(retained);
    fn epoch() -> i64 { 0 }
    fn discard(line: const u8[:]) -> bool { true }
    assert(diagnostics::write_with(diagnostics::Event.Started, 0, 0, epoch, discard));
    assert(retained == saved);
}
fn failure_and_configuration_reset() {
    assert(diagnostics::configure("/not-opened/first"));
    var clocks = 0;
    var sinks = 0;
    fn clock() -> i64 { clocks++; -1 }
    fn fail(line: const u8[:]) -> bool {
        sinks++;
        assert(line == "[INFO] timestamp=\"1969-12-31T23:59:59.999999999Z\" started duration_ns=0 outcome=0\n");
        false
    }
    assert(!diagnostics::write_with(diagnostics::Event.Started, 0, 0, clock, fail));
    assert(clocks == 1 && sinks == 1 && !diagnostics::active());
    assert(!diagnostics::write_with(diagnostics::Event.Started, 0, 0, clock, fail));
    assert(!diagnostics::write_with(diagnostics::Event.Failed, 7, 1, clock, fail));
    assert(clocks == 1 && sinks == 1);
    assert(!diagnostics::configure(""));
    assert(!diagnostics::write_with(diagnostics::Event.Started, 0, 0, clock, fail));
    assert(!diagnostics::configure("private\0marker"));
    assert(!diagnostics::active());
    var oversized: u8[>..] = []; oversized.resize(4096, 'a');
    assert(!diagnostics::configure(oversized));
    assert(!diagnostics::write_with(diagnostics::Event.Started, 0, 0, clock, fail));
    assert(clocks == 1 && sinks == 1);
    assert(diagnostics::configure("/not-opened/reset", log::Level.Off));
    assert(diagnostics::write_with(diagnostics::Event.Started, 0, 0, clock, fail));
    assert(clocks == 1 && sinks == 1 && !diagnostics::active());
    assert(diagnostics::configure("/not-opened/reset", log::Level.Info));
    fn recover(line: const u8[:]) -> bool {
        sinks++;
        assert(line == "[INFO] timestamp=\"1969-12-31T23:59:59.999999999Z\" returned duration_ns=9 outcome=0\n");
        true
    }
    assert(diagnostics::write_with(diagnostics::Event.Returned, 9, 0, clock, recover));
    assert(clocks == 2 && sinks == 2 && diagnostics::active());
}
fn lexical_output_and_caller_borrow() {
    assert(diagnostics::configure("/not-opened/borrowed"));
    var caller_storage: u8[>..] = []; caller_storage.append("caller-owned manifest bytes");
    let borrowed: const u8[:] = caller_storage;
    var clocks = 0;
    var sinks = 0;
    fn clock() -> i64 { clocks++; 0 }
    fn sink(line: const u8[:]) -> bool {
        sinks++;
        assert(line == "[INFO] timestamp=\"1970-01-01T00:00:00Z\" started duration_ns=0 outcome=0\n");
        true
    }
    for i in 3 {
        assert(diagnostics::write_with(diagnostics::Event.Started, 0, 0, clock, sink));
        assert(borrowed == "caller-owned manifest bytes");
    }
    assert(clocks == 3 && sinks == 3 && diagnostics::active());
}
fn main() {
    initial_unconfigured();
    levels_and_events();
    exact_samples_and_owned_output();
    failure_and_configuration_reset();
    lexical_output_and_caller_borrow();
}

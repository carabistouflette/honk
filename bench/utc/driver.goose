// SPDX-License-Identifier: Apache-2.0
// Root imports are rebound to an immutable export by the measurement runner.
import http from "../../vendor/goose-http";
import honk_metadata from "../../vendor/honk-metadata";
import process from "../../vendor/goose-process";
import semver from "../../vendor/goose-semver";
import text from "../../vendor/goose-text";
import toml_edit from "../../vendor/goose-toml-edit";
import toml from "../../vendor/goose-toml";
import argparse from "../../vendor/goose-argparse";
import logger from "../../vendor/goose-log";
import time from "../../vendor/goose-time";
import utc from "../../vendor/goose-log/examples/utc";
import honk from "../..";
import std;
import os;
import binary;

const EVENTS = [diagnostics::Event.Started, diagnostics::Event.ItemCompleted, diagnostics::Event.Returned,
                diagnostics::Event.Failed, diagnostics::Event.ChildFailed];
struct Work { event: i64 = 0, duration: u64 = 0, outcome: u32 = 0, sample: i64 = 0 }
extern fn prepare(size: i64, real_sink: bool) -> bool = "utc_bench_prepare";
extern fn sink_calls() -> i64 = "utc_bench_calls";
extern fn sink_bytes() -> i64 = "utc_bench_bytes";
extern fn sink_checksum() -> i64 = "utc_bench_checksum";
extern fn dump(path: const u8[:]) -> bool = "utc_bench_dump";
var current_sample: i64      = 0;
var stage:          i64      = 0;
var clocks:         i64      = 0;
var samples:        i64[>..] = [];
var destination:    u8[>..]  = [];
fn sampled_clock() -> i64 {
    let value = if stage == 4 || stage == 5 { diagnostics::wall_clock() } else { current_sample };
    samples[clocks] = value; clocks++;
    value
}
fn counted_sink(line: const u8[:]) -> bool { diagnostics::append(destination, line) }
// BEGIN_WRITE
fn actual_write(event: diagnostics::Event, duration: u64, outcome: u32) -> bool {
    diagnostics::write_with(event, duration, outcome, sampled_clock, counted_sink)
}
// END_WRITE
fn batch(items: const Work[:], count: i64) -> i64 {
    var successful = 0;
    for i in count {
        let item = items[i % items.len];
        current_sample = item.sample;
        let event = if stage == 2 { diagnostics::Event.Started } else { EVENTS[item.event] };
        if actual_write(event, item.duration, item.outcome) { successful++; }
    }
    successful
}
fn number(text: const u8[:], maximum: i64) -> i64 {
    let value, ok = parse_int(text); assert(ok && value >= 0 && value <= maximum); value
}
fn main() {
    let argv = args(); assert(argv.len == 9);
    stage = number(argv[1], 5);
    let count = number(argv[3], 1000000); assert(count > 0);
    let warmup = number(argv[4], 1024);
    destination.append(argv[5]);
    var input: u8[>..] = []; assert(read_file(argv[2], input));
    assert(input.len == 8 * 21);
    var items: Work[8] = [Work { .. }; 8];
    for i in 8 {
        let at = i * 21;
        let duration, a = binary::read_u64le(input, at + 1);
        let outcome, b = binary::read_u32le(input, at + 9);
        let sample, c = binary::read_i64le(input, at + 13);
        assert(a && b && c && input[at] < 5);
        items[i] = Work { input[at], duration, outcome, sample };
    }
    if stage != 0 {
        let minimum = if stage == 1 { log::Level.Off } else if stage == 2 { log::Level.Warn } else { log::Level.Info };
        assert(diagnostics::configure(destination, minimum));
    }
    samples.resize(count + warmup, 0);
    assert(prepare((count + warmup) * 256, stage == 5));
    assert(batch(items, warmup) == warmup);
    let before_clocks = clocks;
    let before_sinks = sink_calls();
    let before_bytes = sink_bytes();
    let before_checksum = sink_checksum();
    let started = clock_ns();
    let successful = batch(items, count);
    let elapsed = clock_ns() - started;
    let measured_clocks = clocks - before_clocks;
    let measured_sinks = sink_calls() - before_sinks;
    let measured_bytes = sink_bytes() - before_bytes;
    let measured_checksum = sink_checksum() - before_checksum;
    assert(successful == count && dump(argv[6]));
    // Trace serialization and filesystem I/O are outside the measured loop.
    var trace: u8[>..] = [];
    for sample in samples[..clocks] {
        let bits = sample as! u64;
        for j in 8 { trace.push(((bits >> (8 * j)) & 255) as! u8); }
    }
    assert(write_file(argv[7], trace));
    print("{\"elapsed_ns\":", elapsed, ",\"iterations\":", count,
          ",\"successful\":", successful, ",\"clocks\":", measured_clocks,
          ",\"sinks\":", measured_sinks, ",\"bytes\":", measured_bytes,
          ",\"checksum\":", measured_checksum, "}");
}

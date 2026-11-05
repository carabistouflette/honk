// SPDX-License-Identifier: Apache-2.0
// Application adapter, not part of the goose-log core interface.
// Root entrypoints declare the logger and pinned time dependencies.
import std;
namespace utc_log;

// Inputs cannot borrow either output; timestamp and scratch must be distinct.
// Clock returns Unix nanoseconds. Filtering precedes clock/buffer/message work.
fn emit<Clock, Sink>(config: log::Logger, level: log::Level, message: const u8[:],
                    timestamp: u8[>..]&, scratch: u8[>..]&) -> log::Status {
    if !log::enabled(config, level) { return log::Status.Filtered; }
    let sampled_ns: i64 = Clock();
    let stamp = time::from_unix_nanoseconds(sampled_ns);
    timestamp.clear();
    // Every signed i64 nanosecond sample is a valid supported Timestamp.
    assert(time::append_rfc3339(timestamp, stamp) == time::Error.None);
    let record = log::Record { level: level, message: message, timestamp: timestamp };
    return log::emit_record(config, record, scratch, Sink);
}

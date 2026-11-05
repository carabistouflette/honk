// SPDX-License-Identifier: Apache-2.0
// Unsupported internal implementation; callers use only the documented time interface.
namespace time_detail;
import std;

// Check before evaluating arithmetic, including in release builds.
fn checked_add(a: i64, b: i64) -> i64, time::Error {
    if (b > 0 && a > 9223372036854775807 - b) ||
       (b < 0 && a < -9223372036854775808 - b) { return 0, time::Error.Overflow; }
    return a + b, time::Error.None;
}

fn checked_subtract(a: i64, b: i64) -> i64, time::Error {
    if (b > 0 && a < -9223372036854775808 + b) ||
       (b < 0 && a > 9223372036854775807 + b) { return 0, time::Error.Overflow; }
    return a - b, time::Error.None;
}

fn valid(value: time::Timestamp) -> bool {
    value.seconds >= time::MIN_SECONDS && value.seconds <= time::MAX_SECONDS &&
        value.nanoseconds >= 0 && value.nanoseconds < time::NANOSECONDS_PER_SECOND
}

// Requires normalized nanos. Bound the final result before multiplication;
// at i64.min, seconds * 1e9 alone would overflow.
fn pair_nanoseconds(seconds: i64, nanos: i64) -> i64, time::Error {
    if seconds < -9223372037 || seconds > 9223372036 ||
       (seconds == -9223372037 && nanos < 145224192) ||
       (seconds == 9223372036 && nanos > 854775807) { return 0, time::Error.Overflow; }
    if seconds < 0 { return (seconds + 1) * time::NANOSECONDS_PER_SECOND + (nanos - time::NANOSECONDS_PER_SECOND), time::Error.None; }
    return seconds * time::NANOSECONDS_PER_SECOND + nanos, time::Error.None;
}

fn shift(value: time::Timestamp, delta: time::Duration, subtracting: bool) -> time::Timestamp, time::Error {
    if !valid(value) { return time::Timestamp { .. }, time::Error.Invalid; }
    // Bounded calendar seconds plus at most ~9.3e9 seconds cannot overflow i64.
    let ds = delta.nanoseconds / time::NANOSECONDS_PER_SECOND;
    let dn = rem(delta.nanoseconds, time::NANOSECONDS_PER_SECOND);
    var seconds = value.seconds;
    var nanos = value.nanoseconds;
    if subtracting { seconds -= ds; nanos -= dn; }
    else { seconds += ds; nanos += dn; }
    if nanos < 0 { seconds -= 1; nanos += time::NANOSECONDS_PER_SECOND; }
    else if nanos >= time::NANOSECONDS_PER_SECOND { seconds += 1; nanos -= time::NANOSECONDS_PER_SECOND; }
    if seconds < time::MIN_SECONDS || seconds > time::MAX_SECONDS { return time::Timestamp { .. }, time::Error.Overflow; }
    return time::Timestamp { seconds, nanos }, time::Error.None;
}

fn leap(year: i64) -> bool { year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) }

// Prefix day counts in a common year; callers validate month before indexing.
const MONTH_START: i64[12] = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];

fn month_days(year: i64, month: i64) -> i64 {
    if month == 2 { return if leap(year) { 29 } else { 28 }; }
    if month == 4 || month == 6 || month == 9 || month == 11 { return 30; }
    return 31;
}

fn digit(byte: u8) -> bool { byte >= '0' && byte <= '9' }

// Requires a bounded slice (at most nine bytes); -1 means a non-digit.
fn decimal(bytes: const u8[:]) -> i64 {
    var value: i64 = 0;
    for byte in bytes {
        if !digit(byte) { return -1; }
        value = value * 10 + byte - '0';
    }
    return value;
}

// Requires nonnegative, representable value and an exactly sized digit slice.
fn write_decimal(out: u8[:], value: i64) {
    var remaining = value;
    var at = out.len;
    while at > 0 {
        at -= 1;
        out[at] = ('0' + remaining % 10) as u8;
        remaining /= 10;
    }
}

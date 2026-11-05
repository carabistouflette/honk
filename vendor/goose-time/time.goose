// SPDX-License-Identifier: Apache-2.0
import std;
import .detail;
namespace time;

const NANOSECONDS_PER_SECOND: i64 = 1000000000;
const MIN_SECONDS:            i64 = -62135596800;
const MAX_SECONDS:            i64 = 253402300799;
const MAX_INPUT_BYTES = 35;

enum Error { None, Invalid, Overflow, Syntax, Unsupported, TooLong }
enum Unit { Nanosecond, Microsecond, Millisecond, Second, Minute, Hour, Day }
struct Duration { nanoseconds: i64 = 0 }
struct Instant { nanoseconds: i64 = 0 }
struct Timestamp { seconds: i64 = 0, nanoseconds: i64 = 0 }
struct Calendar {
    year: i64 = 0, month: i64 = 0, day: i64 = 0,
    hour: i64 = 0, minute: i64 = 0, second: i64 = 0, nanosecond: i64 = 0,
}

fn duration(value: i64, unit: Unit) -> Duration, Error {
    var scale: i64 = 1;
    if unit == Unit.Microsecond { scale = 1000; }
    else if unit == Unit.Millisecond { scale = 1000000; }
    else if unit == Unit.Second { scale = NANOSECONDS_PER_SECOND; }
    else if unit == Unit.Minute { scale = 60000000000; }
    else if unit == Unit.Hour { scale = 3600000000000; }
    else if unit == Unit.Day { scale = 86400000000000; }
    if value > 9223372036854775807 / scale || value < -9223372036854775808 / scale {
        return Duration { .. }, Error.Overflow;
    }
    return Duration { value * scale }, Error.None;
}
fn add(a: Duration, b: Duration) -> Duration, Error {
    let n, error = time_detail::checked_add(a.nanoseconds, b.nanoseconds);
    return Duration { n }, error;
}
fn subtract(a: Duration, b: Duration) -> Duration, Error {
    let n, error = time_detail::checked_subtract(a.nanoseconds, b.nanoseconds);
    return Duration { n }, error;
}
fn add(a: Instant, b: Duration) -> Instant, Error {
    let n, error = time_detail::checked_add(a.nanoseconds, b.nanoseconds);
    return Instant { n }, error;
}
fn subtract(a: Instant, b: Duration) -> Instant, Error {
    let n, error = time_detail::checked_subtract(a.nanoseconds, b.nanoseconds);
    return Instant { n }, error;
}
fn difference(a: Instant, b: Instant) -> Duration, Error {
    let n, error = time_detail::checked_subtract(a.nanoseconds, b.nanoseconds);
    return Duration { n }, error;
}

fn from_unix_nanoseconds(value: i64) -> Timestamp {
    var seconds = value / NANOSECONDS_PER_SECOND;
    var nanos = rem(value, NANOSECONDS_PER_SECOND);
    if nanos < 0 { seconds -= 1; nanos += NANOSECONDS_PER_SECOND; }
    return Timestamp { seconds, nanos };
}

fn to_unix_nanoseconds(value: Timestamp) -> i64, Error {
    if !time_detail::valid(value) { return 0, Error.Invalid; }
    return time_detail::pair_nanoseconds(value.seconds, value.nanoseconds);
}

fn add(value: Timestamp, delta: Duration) -> Timestamp, Error { return time_detail::shift(value, delta, false); }
fn subtract(value: Timestamp, delta: Duration) -> Timestamp, Error { return time_detail::shift(value, delta, true); }
fn difference(a: Timestamp, b: Timestamp) -> Duration, Error {
    if !time_detail::valid(a) || !time_detail::valid(b) { return Duration { .. }, Error.Invalid; }
    var seconds = a.seconds - b.seconds;
    var nanos = a.nanoseconds - b.nanoseconds;
    if nanos < 0 { seconds -= 1; nanos += NANOSECONDS_PER_SECOND; }
    let n, error = time_detail::pair_nanoseconds(seconds, nanos);
    return Duration { n }, error;
}

fn from_calendar(value: Calendar) -> Timestamp, Error {
    if value.year < 1 || value.year > 9999 || value.month < 1 || value.month > 12 ||
       value.day < 1 || value.day > time_detail::month_days(value.year, value.month) ||
       value.hour < 0 || value.hour > 23 || value.minute < 0 || value.minute > 59 ||
       value.second < 0 || value.second > 59 || value.nanosecond < 0 ||
       value.nanosecond >= NANOSECONDS_PER_SECOND { return Timestamp { .. }, Error.Invalid; }
    let y = value.year - 1;
    var days = 365 * y + y / 4 - y / 100 + y / 400 + value.day - 1 +
        time_detail::MONTH_START[value.month - 1];
    if value.month > 2 && time_detail::leap(value.year) { days += 1; }
    return Timestamp { (days - 719162) * 86400 + value.hour * 3600 + value.minute * 60 + value.second,
                       value.nanosecond }, Error.None;
}
fn to_calendar(value: Timestamp) -> Calendar, Error {
    if !time_detail::valid(value) { return Calendar { .. }, Error.Invalid; }
    var days = value.seconds / 86400;
    var daytime = rem(value.seconds, 86400);
    if daytime < 0 { days -= 1; daytime += 86400; }
    days += 719162;
    let era = days / 146097;
    let day_of_era = days % 146097;
    let year_of_era = (day_of_era - day_of_era / 1460 + day_of_era / 36524 - day_of_era / 146096) / 365;
    let year = era * 400 + year_of_era + 1;
    var day = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    var month = 1;
    while month < 12 {
        let count = time_detail::month_days(year, month);
        if day < count { break; }
        day -= count;
        month += 1;
    }
    return Calendar { year, month, day + 1, daytime / 3600, (daytime / 60) % 60,
                      daytime % 60, value.nanoseconds }, Error.None;
}

fn parse_rfc3339(source: const u8[:]) -> Timestamp, Error {
    if source.len > MAX_INPUT_BYTES { return Timestamp { .. }, Error.TooLong; }
    if source.len < 20 { return Timestamp { .. }, Error.Syntax; }
    if source[4] != '-' || source[7] != '-' || (source[10] != 'T' && source[10] != 't') ||
       source[13] != ':' || source[16] != ':' { return Timestamp { .. }, Error.Syntax; }
    var calendar = Calendar { time_detail::decimal(source[..4]), time_detail::decimal(source[5..7]), time_detail::decimal(source[8..10]),
                              time_detail::decimal(source[11..13]), time_detail::decimal(source[14..16]), time_detail::decimal(source[17..19]), 0 };
    if calendar.year < 0 || calendar.month < 0 || calendar.day < 0 ||
       calendar.hour < 0 || calendar.minute < 0 || calendar.second < 0 { return Timestamp { .. }, Error.Syntax; }
    var at = 19;
    if source[at] == '.' {
        at += 1;
        let start = at;
        while at < source.len && time_detail::digit(source[at]) { at += 1; }
        let width = at - start;
        if width == 0 { return Timestamp { .. }, Error.Syntax; }
        if width > 9 { return Timestamp { .. }, Error.Unsupported; }
        calendar.nanosecond = time_detail::decimal(source[start..at]);
        for i in width..9 { calendar.nanosecond *= 10; }
    }
    if at == source.len { return Timestamp { .. }, Error.Syntax; }
    var offset: i64 = 0;
    if source[at] == 'Z' || source[at] == 'z' {
        if at + 1 != source.len { return Timestamp { .. }, Error.Syntax; }
    } else {
        if (source[at] != '+' && source[at] != '-') || source.len - at != 6 {
            return Timestamp { .. }, Error.Syntax;
        }
        if source[at + 3] != ':' { return Timestamp { .. }, Error.Syntax; }
        let hour = time_detail::decimal(source[at + 1..at + 3]);
        let minute = time_detail::decimal(source[at + 4..at + 6]);
        if hour < 0 || minute < 0 { return Timestamp { .. }, Error.Syntax; }
        if hour > 23 || minute > 59 { return Timestamp { .. }, Error.Invalid; }
        offset = hour * 3600 + minute * 60;
        if source[at] == '-' {
            if offset == 0 { return Timestamp { .. }, Error.Unsupported; }
            offset = -offset;
        }
    }
    let local, error = from_calendar(calendar);
    if error != Error.None { return Timestamp { .. }, error; }
    let seconds = local.seconds - offset;
    if seconds < MIN_SECONDS || seconds > MAX_SECONDS { return Timestamp { .. }, Error.Overflow; }
    return Timestamp { seconds, local.nanoseconds }, Error.None;
}

fn append_rfc3339(out: u8[>..]&, value: Timestamp) -> Error {
    let calendar, error = to_calendar(value);
    if error != Error.None { return error; }
    // Fixed stack storage, then one append. No consumer formatting dispatch.
    var bytes: u8[30] = ['0'; 30];
    time_detail::write_decimal(bytes[..4], calendar.year);
    bytes[4] = '-'; time_detail::write_decimal(bytes[5..7], calendar.month);
    bytes[7] = '-'; time_detail::write_decimal(bytes[8..10], calendar.day);
    bytes[10] = 'T'; time_detail::write_decimal(bytes[11..13], calendar.hour);
    bytes[13] = ':'; time_detail::write_decimal(bytes[14..16], calendar.minute);
    bytes[16] = ':'; time_detail::write_decimal(bytes[17..19], calendar.second);
    var length = 19;
    if calendar.nanosecond != 0 {
        bytes[19] = '.';
        time_detail::write_decimal(bytes[20..29], calendar.nanosecond);
        length = 29;
        while bytes[length - 1] == '0' { length -= 1; }
    }
    bytes[length] = 'Z';
    out.append(bytes[..length + 1]);
    return Error.None;
}

// SPDX-License-Identifier: Apache-2.0
import glob from "../vendor/goose-glob";
import crypto from "../vendor/goose-crypto";
import http from "../vendor/goose-http";
import honk_metadata from "../vendor/honk-metadata";
import process from "../vendor/goose-process";
import semver from "../vendor/goose-semver";
import text from "../vendor/goose-text";
import toml from "../vendor/goose-toml";
import toml_edit from "../vendor/goose-toml-edit";
import argparse from "../vendor/goose-argparse";
import logger from "../vendor/goose-log";
import time from "../vendor/goose-time";
import utc from "../vendor/goose-log/examples/utc";
import honk from "..";
import std;
const FIRST = "1111111111111111111111111111111111111111";
const SECOND = "2222222222222222222222222222222222222222";
fn expect_error(requirement: const u8[:], tags: const tag_select::Tag[:], expected: tag_select::Error) {
    let selected, error = tag_select::select(requirement, tags);
    assert(error == expected);
    assert(selected.reference.len == 0 && selected.commit.len == 0 && selected.version.len == 0);
}
fn ephemeral() -> tag_select::Selection, tag_select::Error {
    var reference: u8[>..] = []; reference.append("refs/tags/v1.2.3");
    var commit:    u8[>..] = []; commit.append(FIRST);
    let tags = [tag_select::Tag { reference, commit }];
    return tag_select::select("=1.2.3", tags[..]);
}
// Consumer overloads must not change the library's owned requirement targets.
fn copy(value: const semver::Version&) -> semver::Version {
    return semver::Version { major: tag_select::owned("99"), minor: tag_select::owned("0"), patch: tag_select::owned("0"), prerelease: [], build: [] };
}
fn copy(value: const semver::Comparator[:]) -> semver::Comparator[] { return []; }
fn main() {
    let tags = [tag_select::Tag { "refs/tags/1.10.0", SECOND }, tag_select::Tag { "refs/tags/1.2.3", FIRST },
                tag_select::Tag { "refs/tags/notes", FIRST }, tag_select::Tag { "refs/tags/v2.0.0-alpha.1", SECOND }];
    let selected, error = tag_select::select("^1.2.3", tags[..]);
    assert(error == tag_select::Error.None && selected.reference == "refs/tags/1.10.0" && selected.commit == SECOND && selected.version == "1.10.0");
    let pre, pre_error = tag_select::select(">=2.0.0-alpha.0,<2.0.0", tags[..]);
    assert(pre_error == tag_select::Error.None && pre.version == "2.0.0-alpha.1");
    let owned, owned_error = ephemeral();
    assert(owned_error == tag_select::Error.None && owned.reference == "refs/tags/v1.2.3" && owned.version == "1.2.3" && owned.commit == FIRST);
    let none: tag_select::Tag[0] = [];
    expect_error("*", none[..], tag_select::Error.NoMatch);
    for requirement in ["", "1.2", "v1.2.3", "^1.2", "1.2.3 || 2.0.0"] { expect_error(requirement, tags[..], tag_select::Error.InvalidRequirement); }
    expect_error("=9.0.0", tags[..], tag_select::Error.NoMatch);
    let ties = [tag_select::Tag { "refs/tags/1.2.3+one", FIRST }, tag_select::Tag { "refs/tags/1.2.3+two", FIRST }];
    expect_error("=1.2.3", ties[..], tag_select::Error.Ambiguous);
    let aliases = [tag_select::Tag { "refs/tags/1.2.3", FIRST }, tag_select::Tag { "refs/tags/v1.2.3", FIRST }];
    expect_error("=1.2.3", aliases[..], tag_select::Error.Ambiguous);
    let duplicate = [tag_select::Tag { "refs/tags/v1.2.3", FIRST }, tag_select::Tag { "refs/tags/v1.2.3", FIRST }];
    let repeated, repeated_error = tag_select::select("*", duplicate[..]);
    assert(repeated_error == tag_select::Error.None && repeated.commit == FIRST);
    let conflict = [tag_select::Tag { "refs/tags/v1.2.3", FIRST }, tag_select::Tag { "refs/tags/v1.2.3", SECOND }];
    expect_error("=9.0.0", conflict[..], tag_select::Error.InvalidCatalog);
    let unsorted = [tag_select::Tag { "refs/tags/v2.0.0", SECOND }, tag_select::Tag { "refs/tags/v1.2.3", FIRST }];
    expect_error("*", unsorted[..], tag_select::Error.InvalidCatalog);
    let branch = [tag_select::Tag { "refs/heads/1.2.3", FIRST }];
    expect_error("*", branch[..], tag_select::Error.InvalidCatalog);
    let bad_sha = [tag_select::Tag { "refs/tags/v1.2.3", "main" }];
    expect_error("*", bad_sha[..], tag_select::Error.InvalidCatalog);
    let malformed_tail = [tag_select::Tag { "refs/tags/v1.2.3", FIRST }, tag_select::Tag { "refs/tags/v9.0.0", "bad" }];
    expect_error("=1.2.3", malformed_tail[..], tag_select::Error.InvalidCatalog);
    var excessive: tag_select::Tag[>..] = [];
    for i in 4097 { excessive.push(tag_select::Tag { "refs/tags/v1.2.3", FIRST }); }
    expect_error("*", excessive[..], tag_select::Error.TooManyTags);
    excessive.clear();
    for i in 4096 { excessive.push(tag_select::Tag { "refs/tags/v1.2.3", FIRST }); }
    let capped, cap_error = tag_select::select("*", excessive[..]);
    assert(cap_error == tag_select::Error.None && capped.version == "1.2.3");
    var long_ref = tag_select::owned("refs/tags/"); long_ref.resize(4096, 'x');
    var short_ref = tag_select::owned("refs/tags/"); short_ref.resize(2128, 'x');
    var bytes: tag_select::Tag[>..] = []; bytes.push(tag_select::Tag { short_ref[..], FIRST });
    for i in 253 { bytes.push(tag_select::Tag { long_ref[..], FIRST }); }
    expect_error("*", bytes[..], tag_select::Error.NoMatch);
    bytes.push(tag_select::Tag { long_ref[..], FIRST });
    expect_error("*", bytes[..], tag_select::Error.CatalogTooLarge);
    let higher = [tag_select::Tag { "refs/tags/1.2.3+one", FIRST }, tag_select::Tag { "refs/tags/1.2.3+two", SECOND },
                  tag_select::Tag { "refs/tags/2.0.0", SECOND }];
    let unambiguous, higher_error = tag_select::select("*", higher[..]);
    assert(higher_error == tag_select::Error.None && unambiguous.version == "2.0.0");
    var version64 = tag_select::owned("refs/tags/1.0.0-"); for i in 58 { version64.push('a'); }
    let length_tags = [tag_select::Tag { version64[..], FIRST }];
    let limit, limit_error = tag_select::select(">=1.0.0-a,<1.0.0", length_tags[..]);
    assert(limit_error == tag_select::Error.None && limit.version.len == 64);
    var version65 = tag_select::owned(version64[..]); version65.push('a');
    let overlength = [tag_select::Tag { version65[..], FIRST }];
    expect_error(">=1.0.0-a,<1.0.0", overlength[..], tag_select::Error.NoMatch);
    var over_ref = tag_select::owned(long_ref[..]); over_ref.push('x');
    let over_ref_tags = [tag_select::Tag { over_ref[..], FIRST }];
    expect_error("*", over_ref_tags[..], tag_select::Error.InvalidCatalog);
    let numeric = [tag_select::Tag { "refs/tags/2.0.0", FIRST }, tag_select::Tag { "refs/tags/999999999999999999999.0.0", SECOND }];
    let large, large_error = tag_select::select("*", numeric[..]);
    assert(large_error == tag_select::Error.None && large.commit == SECOND);
    print("tag selection contracts passed");
}

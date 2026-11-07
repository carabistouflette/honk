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
import posix from "../vendor/goose-terminal";
import honk from "..";
import std;
const FIRST = "1111111111111111111111111111111111111111";
const SECOND = "2222222222222222222222222222222222222222";
fn bad(input: const u8[:], expected: tag_select::Error = tag_select::Error.InvalidCatalog) {
    let selected, error = tag_catalog::select("*", input);
    assert(error == expected && selected.reference.len == 0 && selected.commit.len == 0 && selected.version.len == 0);
}
fn main() {
    let input = str(FIRST, "\trefs/tags/v1.2.3\n", FIRST, "\trefs/tags/v1.2.3-alpha\n", SECOND, "\trefs/tags/v1.2.3^{}\n");
    let selected, error = tag_catalog::select("*", input);
    assert(error == tag_select::Error.None && selected.commit == SECOND && selected.version == "1.2.3");
    let duplicate = str(FIRST, "\trefs/tags/v1.2.3\n", FIRST, "\trefs/tags/v1.2.3\n");
    let repeated, repeated_error = tag_catalog::select("*", duplicate);
    assert(repeated_error == tag_select::Error.None && repeated.commit == FIRST);
    bad(str(FIRST, "\trefs/tags/v1.2.3\n", SECOND, "\trefs/tags/v1.2.3\n"));
    bad(str(FIRST, "\trefs/tags/v1.2.3^{}\n"));
    bad(str(FIRST, "\trefs/tags/v1.2.3\n", FIRST, "\trefs/tags/v1.2.3^{}\n", SECOND, "\trefs/tags/v1.2.3^{}\n"));
    bad(str(FIRST, "\trefs/tags/v2.0.0\n", FIRST, "\trefs/tags/v1.2.3\n"));
    for ref in ["refs/heads/v1.2.3", "refs/tags/.hidden", "refs/tags/x.lock", "refs/tags/x.lock/y", "refs/tags/x..y", "refs/tags/x@{y", "refs/tags/x//y", "refs/tags/x.", "refs/tags/x/", "refs/tags/x y", "refs/tags/x~y", "refs/tags/x^y", "refs/tags/x:y", "refs/tags/x?y", "refs/tags/x*y", "refs/tags/x[y", "refs/tags/x\\y"] { bad(str(FIRST, "\t", ref, "\n")); }
    for text in ["bad\n", "", "0000000000000000000000000000000000000000\trefs/tags/1.2.3\n", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\trefs/tags/1.2.3\n"] {
        if text.len > 0 { bad(text); }
    }
    bad(str(FIRST, "\trefs/tags/v1.2.3")); bad(str(FIRST, "\trefs/tags/v1.2.3\r\n"));
    bad(str(FIRST, "\trefs/tags/v1.2.3\ntruncated"));
    var rows: u8[>..] = []; for i in 8192 { rows.append(str(FIRST, "\trefs/tags/v1.2.3\n")); }
    let capped, cap_error = tag_catalog::select("*", rows);
    assert(cap_error == tag_select::Error.None && capped.commit == FIRST);
    rows.append(str(FIRST, "\trefs/tags/v1.2.3\n")); bad(rows, tag_select::Error.TooManyTags);
    rows.resize(1048577, 'x'); bad(rows, tag_select::Error.CatalogTooLarge);
    var unique: u8[>..] = [];
    for i in 4096 {
        unique.append(FIRST); unique.append("\trefs/tags/x");
        for shift in [12, 8, 4, 0] { unique.push("0123456789abcdef"[(i >> shift) & 15]); } unique.push('\n');
    }
    bad(unique, tag_select::Error.NoMatch); unique.append(str(FIRST, "\trefs/tags/z\n")); bad(unique, tag_select::Error.TooManyTags);
    var long_ref = tag_select::owned("refs/tags/z"); long_ref.resize(4096, 'z');
    var first_ref = tag_select::owned("refs/tags/a"); first_ref.resize(1620, 'a');
    var exact: u8[>..] = []; exact.append(str(FIRST, "\t", first_ref, "\n"));
    for i in 253 { exact.append(str(FIRST, "\t", long_ref, "\n")); }
    assert(exact.len == 1048576); bad(exact, tag_select::Error.NoMatch); exact.push('\n'); bad(exact, tag_select::Error.CatalogTooLarge);
    long_ref.push('z'); bad(str(FIRST, "\t", long_ref, "\n"));
    print("tag advertisement contracts passed");
}

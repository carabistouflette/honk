// SPDX-License-Identifier: Apache-2.0
// Pure selection from enumerated Git tags. Transport and locking stay with deps.
namespace tag_select;
import semver;
import .version_policy;
import .manifest;

const MAX_TAGS = 4096;
const MAX_CATALOG_BYTES = 1048576;
const MAX_REF_BYTES = 4096;
const MAX_TAG_VERSION_BYTES = 64;
struct Tag { reference: const u8[:], commit: const u8[:] }
struct Selection { reference: u8[] = [], commit: u8[] = [], version: u8[] = [] }
enum Error { None, InvalidRequirement, InvalidCatalog, TooManyTags, CatalogTooLarge, NoMatch, Ambiguous }

fn owned(value: const u8[:]) -> u8[>..] { var out: u8[>..] = []; out.append(value); return out; }
fn snapshot(value: const semver::Version&) -> semver::Version {
    return semver::Version { major: tag_select::owned(value.major), minor: tag_select::owned(value.minor),
        patch: tag_select::owned(value.patch), prerelease: tag_select::owned(value.prerelease), build: tag_select::owned(value.build) };
}
fn spelling(reference: const u8[:]) -> const u8[:] {
    let tag = reference[10..];
    return if tag.len > 0 && tag[0] == 'v' { tag[1..] } else { tag };
}
fn compare_refs(a: const u8[:], b: const u8[:]) -> i64 {
    let common = if a.len < b.len { a.len } else { b.len };
    for i in common { if a[i] < b[i] { return -1; } if a[i] > b[i] { return 1; } }
    return if a.len < b.len { -1 } else if a.len > b.len { 1 } else { 0 };
}
fn select(requirement: const u8[:], tags: const Tag[:]) -> Selection, Error {
    let requested, error = semver::parse_requirement(requirement);
    if error.kind != semver::ErrorKind.None { return Selection { .. }, Error.InvalidRequirement; }
    if tags.len > MAX_TAGS { return Selection { .. }, Error.TooManyTags; }
    // Validate the complete catalog before choosing; an early match must not
    // hide malformed rows or truncation. Bytes include the supplied refs/SHA.
    var bytes: i64 = 0;
    for tag, i in tags {
        if tag.reference.len <= 10 || tag.reference.len > MAX_REF_BYTES || tag.reference[..10] != "refs/tags/" || !manifest::commit(tag.commit) {
            return Selection { .. }, Error.InvalidCatalog;
        }
        if tag.reference.len + tag.commit.len > MAX_CATALOG_BYTES - bytes { return Selection { .. }, Error.CatalogTooLarge; }
        bytes += tag.reference.len + tag.commit.len;
        if i > 0 {
            let order = tag_select::compare_refs(tags[i - 1].reference, tag.reference);
            if order > 0 || (order == 0 && tags[i - 1].commit != tag.commit) { return Selection { .. }, Error.InvalidCatalog; }
        }
    }
    var best: i64 = -1; var ambiguous = false;
    // A growable container permits replacing an immutable owned Version.
    // At most one snapshot is live; comparisons allocate nothing.
    var saved: semver::Version[>..] = [];
    for tag, i in tags {
        let text = tag_select::spelling(tag.reference);
        if text.len > MAX_TAG_VERSION_BYTES { continue; }
        let version, parse_error = version_policy::parse_tag(tag.reference);
        if parse_error.kind != semver::ErrorKind.None || !semver::matches(requested, version) { continue; }
        var order: i64 = 1;
        for previous in saved { order = semver::compare(version, previous); }
        if best < 0 || order > 0 {
            saved.clear(); saved.push(tag_select::snapshot(version)); best = i; ambiguous = false;
        } else if order == 0 && (tag.reference != tags[best].reference || tag.commit != tags[best].commit) {
            ambiguous = true;
        }
    }
    if best < 0 { return Selection { .. }, Error.NoMatch; }
    if ambiguous { return Selection { .. }, Error.Ambiguous; }
    return Selection { reference: tag_select::owned(tags[best].reference), commit: tag_select::owned(tags[best].commit),
        version: tag_select::owned(tag_select::spelling(tags[best].reference)) }, Error.None;
}

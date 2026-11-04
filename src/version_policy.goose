// SPDX-License-Identifier: Apache-2.0
// Only enumerated full refs/tags names belong here; dependency refs stay exact.
namespace version_policy;
import semver;
fn parse_tag(reference: const u8[:]) -> semver::Version, semver::Error {
    let prefix = "refs/tags/";
    if reference.len <= prefix.len || reference[..prefix.len] != prefix { return semver::Version { .. }, semver::Error { semver::ErrorKind.Syntax, 0 }; }
    let tag = reference[prefix.len..];
    let value = if tag.len > 0 && tag[0] == 'v' { tag[1..] } else { tag };
    return semver::parse(value);
}

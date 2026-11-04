// SPDX-License-Identifier: Apache-2.0
// Strict byte parser for complete, refname-sorted Git tag advertisements.
namespace tag_catalog;
import .tag_select;
import .manifest;

const MAX_ROWS = 8192;
fn reference(value: const u8[:]) -> bool {
    if value.len <= 10 || value.len > tag_select::MAX_REF_BYTES || value[..10] != "refs/tags/" || value[value.len - 1] == '/' || value[value.len - 1] == '.' { return false; }
    var start = 0;
    for c, i in value {
        if c <= 32 || c == 127 || c == '~' || c == '^' || c == ':' || c == '?' || c == '*' || c == '[' || c == '\\' { return false; }
        if i > 0 && ((c == '.' && value[i - 1] == '.') || (c == '{' && value[i - 1] == '@')) { return false; }
        if i == start && c == '.' { return false; }
        if c == '/' {
            if i == start || (i - start >= 5 && value[i - 5..i] == ".lock") { return false; }
            start = i + 1;
        }
    }
    return !(value.len - start >= 5 && value[value.len - 5..] == ".lock");
}
fn object(value: const u8[:]) -> bool {
    if !manifest::commit(value) { return false; }
    for c in value { if c != '0' { return true; } }
    return false;
}
fn select(requirement: const u8[:], input: const u8[:]) -> tag_select::Selection, tag_select::Error {
    if input.len > tag_select::MAX_CATALOG_BYTES { return tag_select::Selection { .. }, tag_select::Error.CatalogTooLarge; }
    if input.len > 0 && input[input.len - 1] != '\n' { return tag_select::Selection { .. }, tag_select::Error.InvalidCatalog; }
    var tags: tag_select::Tag[>..] = []; var peels: tag_select::Tag[>..] = [];
    var start = 0; var rows = 0;
    var previous_start = -1; var previous_end = 0;
    for c, end in input {
        if c != '\n' { continue; }
        rows++; if rows > MAX_ROWS { return tag_select::Selection { .. }, tag_select::Error.TooManyTags; }
        let begin = start; let row = input[begin..end]; start = end + 1;
        if row.len < 52 || row[40] != '\t' || !tag_catalog::object(row[..40]) { return tag_select::Selection { .. }, tag_select::Error.InvalidCatalog; }
        let raw = row[41..]; let peeled = raw.len > 3 && raw[raw.len - 3..] == "^{}";
        let name = if peeled { raw[..raw.len - 3] } else { raw };
        if !tag_catalog::reference(name) { return tag_select::Selection { .. }, tag_select::Error.InvalidCatalog; }
        if previous_start >= 0 {
            let order = tag_select::compare_refs(input[previous_start + 41..previous_end], raw);
            if order > 0 || (order == 0 && input[previous_start..previous_start + 40] != row[..40]) { return tag_select::Selection { .. }, tag_select::Error.InvalidCatalog; }
            if order == 0 { continue; }
        }
        previous_start = begin; previous_end = end;
        if peeled { peels.push(tag_select::Tag { name, row[..40] }); }
        else {
            if tags.len == tag_select::MAX_TAGS { return tag_select::Selection { .. }, tag_select::Error.TooManyTags; }
            tags.push(tag_select::Tag { name, row[..40] });
        }
    }
    // Peeled rows are not necessarily adjacent to their base in raw ref order.
    // Non-peeled names remain sorted, allowing bounded binary lookup.
    for peel in peels {
        var low = 0; var high = tags.len; var found = -1;
        while low < high {
            let middle = low + (high - low) / 2;
            let order = tag_select::compare_refs(tags[middle].reference, peel.reference);
            if order < 0 { low = middle + 1; } else if order > 0 { high = middle; } else { found = middle; break; }
        }
        if found < 0 { return tag_select::Selection { .. }, tag_select::Error.InvalidCatalog; }
        tags[found].commit = peel.commit;
    }
    return tag_select::select(requirement, tags[..]);
}

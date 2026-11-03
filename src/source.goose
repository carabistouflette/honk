// SPDX-License-Identifier: Apache-2.0
// Minimal lexical scan for sourced imports; this is not a Goose parser.
namespace source;
import std;
import .platform;
struct Token { start: i64 = 0, end: i64 = 0, quoted: bool = false }
struct Reader { text: const u8[:], pos: i64 = 0 }
struct Requirement { name: u8[], source: u8[], start: i64, end: i64 }
fn alpha(c: u8) -> bool { (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || (c >= '0' && c <= '9') }
fn token(r: Reader&) -> Token {
    let s = r.text;
    loop {
        while r.pos < s.len && s[r.pos] <= 32 { r.pos++; }
        if r.pos + 1 < s.len && s[r.pos..r.pos + 2] == "//" {
            while r.pos < s.len && s[r.pos] != '\n' { r.pos++; } continue;
        }
        if r.pos + 1 < s.len && s[r.pos..r.pos + 2] == "/*" {
            var depth = 1; r.pos += 2;
            while r.pos < s.len && depth > 0 {
                if r.pos + 1 < s.len && s[r.pos..r.pos + 2] == "/*" { depth++; r.pos += 2; }
                else if r.pos + 1 < s.len && s[r.pos..r.pos + 2] == "*/" { depth--; r.pos += 2; }
                else { r.pos++; }
            }
            platform::require(depth == 0, "unterminated source comment"); continue;
        }
        break;
    }
    let start = r.pos;
    if r.pos == s.len { return Token { start, start, false }; }
    if r.pos + 2 < s.len && s[r.pos..r.pos + 3] == "\"\"\"" {
        r.pos += 3;
        while r.pos + 2 < s.len && s[r.pos..r.pos + 3] != "\"\"\"" { r.pos++; }
        platform::require(r.pos + 2 < s.len, "unterminated raw source string"); r.pos += 3;
        return Token { start, r.pos, true };
    }
    let c = s[r.pos]; r.pos++;
    if c == '"' || c == '\'' {
        var closed = false;
        while r.pos < s.len {
            let ch = s[r.pos]; r.pos++;
            if ch == '\\' && r.pos < s.len { r.pos++; }
            else if ch == c { closed = true; break; }
        }
        platform::require(closed, "unterminated source string"); return Token { start, r.pos, true };
    }
    if alpha(c) { while r.pos < s.len && alpha(s[r.pos]) { r.pos++; } }
    return Token { start, r.pos, false };
}
fn requirements(text: u8[:]) -> Requirement[>..] {
    var r = Reader { text: text }; var out: Requirement[>..] = [];
    loop {
        let t = token(r); if t.start == t.end { break; }
        if t.quoted || text[t.start..t.end] != "import" { continue; }
        let name = token(r); let from = token(r);
        if from.quoted || text[from.start..from.end] != "from" { continue; }
        let value = token(r); platform::require(value.quoted && value.end - value.start >= 2 && text[value.start] == '"', "expected quoted import source");
        let s = text[value.start + 1..value.end - 1];
        for c in s { platform::require(c >= 32 && c != 127 && c != '\\' && c != '"', "import sources must be plain strings without escapes"); }
        platform::require(out.len < 256, "source import limit is 256 per file");
        out.push(Requirement { name: str(text[name.start..name.end]), source: str(s), start: from.start, end: value.end });
    }
    return out;
}

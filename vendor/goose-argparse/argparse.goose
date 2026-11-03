// Pure argument parsing: no process arguments, output, or exits.
import std;
namespace argparse;

struct Option {
    name:       const u8[:],
    short:      u8          = 0,
    help:       const u8[:] = "",
    value_name: const u8[:] = "",
}

fn flag(name: const u8[:], short: u8 = 0, help: const u8[:] = "") -> Option {
    Option { name: name, short: short, help: help }
}

fn option(name: const u8[:], short: u8 = 0, help: const u8[:] = "", value_name: const u8[:] = "VALUE") -> Option {
    Option { name: name, short: short, help: help, value_name: value_name }
}

enum Error { None, InvalidSpec, UnknownOption, MissingValue, UnexpectedValue }
struct Entry { name: const u8[:], value: const u8[:] }
struct Result {
    error:       Error = Error.None,
    message:     u8[],
    entries:     Entry[],
    positionals: const u8[:][],
}

fn has(result: Result&, name: const u8[:]) -> bool {
    for e in result.entries { if e.name == name { return true; } }
    false
}

// Repeated options are retained in entries; get returns the last value.
fn get(result: Result&, name: const u8[:], fallback: const u8[:] = "") -> const u8[:] {
    var last = -1;
    for i in result.entries.len { if result.entries[i].name == name { last = i; } }
    if last < 0 { fallback } else { result.entries[last].value }
}

fn ascii_letter(c: u8) -> bool {
    (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
}

// An empty string means the specification is valid.
fn validate(spec: Option[:]) -> u8[>..] {
    for i in spec.len {
        let s = spec[i];
        if s.name.len == 0 { return str("option name must not be empty"); }
        if !ascii_letter(s.name[0]) { return str("invalid option name: ", s.name); }
        for c in s.name {
            if !ascii_letter(c) && !(c >= '0' && c <= '9') && c != '-' {
                return str("invalid option name: ", s.name);
            }
        }
        if s.short != 0 && !ascii_letter(s.short) {
            return str("short alias must be an ASCII letter: --", s.name);
        }
        for j in i {
            if spec[j].name == s.name { return str("duplicate option: --", s.name); }
            if s.short != 0 && spec[j].short == s.short {
                return str("duplicate short alias for --", s.name);
            }
        }
    }
    str("")
}

fn lookup_long(spec: Option[:], name: const u8[:]) -> i64 {
    for i in spec.len { if spec[i].name == name { return i; } }
    -1
}
fn lookup_short(spec: Option[:], name: u8) -> i64 {
    if name == 0 { return -1; }
    for i in spec.len { if spec[i].short == name { return i; } }
    -1
}

// argv excludes the executable name. Returned slices borrow argv and spec.
// A failure may contain partial entries; inspect error before using them.
fn parse<T>(spec: Option[:], argv: T[:]) -> Result {
    var entries:     Entry[>..]       = [];
    var positionals: const u8[:][>..] = [];
    fn finish(error: Error = Error.None, message: const u8[:] = "") -> Result {
        Result { error: error, message: str(message), entries: copy(entries), positionals: copy(positionals) }
    }
    let problem = validate(spec);
    if problem.len > 0 {
        return finish(Error.InvalidSpec, problem);
    }
    var literal = false;
    var i = 0;
    while i < argv.len {
        let token = argv[i];
        i += 1;
        if literal || token.len < 2 || token[0] != '-' {
            positionals.push(token);
            continue;
        }
        if token == "--" { literal = true; continue; }
        if token[1] == '-' {
            let equal = find(token, "=");
            let end = if equal < 0 { token.len } else { equal };
            let index = lookup_long(spec, token[2..end]);
            if index < 0 {
                return finish(Error.UnknownOption, str("unknown option: ", token[..end]));
            }
            let s = spec[index];
            if s.value_name.len == 0 {
                if equal >= 0 {
                    return finish(Error.UnexpectedValue, str("flag does not take a value: --", s.name));
                }
                entries.push(Entry { s.name, "" });
            } else if equal >= 0 {
                entries.push(Entry { s.name, token[equal + 1..] });
            } else {
                if i == argv.len {
                    return finish(Error.MissingValue, str("missing value for --", s.name));
                }
                entries.push(Entry { s.name, argv[i] });
                i += 1;
            }
        } else {
            var j = 1;
            while j < token.len {
                let index = lookup_short(spec, token[j]);
                if index < 0 {
                    return finish(Error.UnknownOption, str("unknown option: -", token[j..j + 1]));
                }
                let s = spec[index];
                j += 1;
                if s.value_name.len > 0 {
                    if j < token.len { entries.push(Entry { s.name, token[j..] }); }
                    else {
                        if i == argv.len {
                            return finish(Error.MissingValue, str("missing value for --", s.name));
                        }
                        entries.push(Entry { s.name, argv[i] });
                        i += 1;
                    }
                    j = token.len;
                } else {
                    entries.push(Entry { s.name, "" });
                }
            }
        }
    }
    finish()
}

// No implicit help option: declare a flag and decide when to show this.
fn help(spec: Option[:], program: const u8[:], description: const u8[:] = "") -> u8[>..] {
    var out: u8[>..] = [];
    format(out, "Usage: ", program, " [options] [--] [args...]\n");
    if description.len > 0 { format(out, "\n", description, "\n"); }
    if spec.len > 0 { format(out, "\nOptions:\n"); }
    for s in spec {
        format(out, "  ");
        if s.short != 0 {
            format(out, "-");
            out.push(s.short);
            format(out, ", ");
        }
        format(out, "--", s.name);
        if s.value_name.len > 0 { format(out, " <", s.value_name, ">"); }
        if s.help.len > 0 { format(out, "  ", s.help); }
        format(out, "\n");
    }
    out
}

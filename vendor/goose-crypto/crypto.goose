// SPDX-License-Identifier: Apache-2.0
namespace crypto;
import std;

enum Error { None, InvalidInput, InvalidState, InvalidSignature, BackendFailure, LimitExceeded }
const SHA256_BYTES = 32;
const ED25519_PUBLIC_KEY_BYTES = 32;
const ED25519_SIGNATURE_BYTES = 64;
const MAX_SHA256_BYTES: i64 = 2305843009213693951;
// Process-local implementation storage. Copying intentionally forks a hash.
// Never modify or persist _state; it can contain original input bytes.
struct Sha256 { _state: u8[128] = [0; 128] }

extern fn native_sha256(message: const u8[:], digest: u8[:]) -> i64 = "gc_sha256";
extern fn native_init(state: u8[:]) -> i64 = "gc_sha256_init";
extern fn native_update(state: u8[:], message: const u8[:]) -> i64 = "gc_sha256_update";
extern fn native_finish(state: u8[:], digest: u8[:]) -> i64 = "gc_sha256_finish";
extern fn native_verify(message: const u8[:], signature: const u8[:], public_key: const u8[:]) -> i64 = "gc_verify_ed25519";
extern fn native_disjoint(input: const u8[:], output: u8[:]) -> i64 = "gc_disjoint";

fn error_from_native(code: i64) -> Error {
    if code == 0 { return Error.None; }
    if code == 1 { return Error.InvalidInput; }
    if code == 2 { return Error.InvalidState; }
    if code == 3 { return Error.InvalidSignature; }
    if code == 5 { return Error.LimitExceeded; }
    return Error.BackendFailure;
}
fn sha256(message: const u8[:], digest: u8[:]) -> Error {
    if digest.len != SHA256_BYTES { return Error.InvalidInput; }
    if message.len > MAX_SHA256_BYTES { return Error.LimitExceeded; }
    return error_from_native(native_sha256(message, digest));
}
fn init(state: Sha256&) -> Error { return error_from_native(native_init(state._state[..])); }
fn update(state: Sha256&, message: const u8[:]) -> Error {
    return error_from_native(native_update(state._state[..], message));
}
fn finish(state: Sha256&, digest: u8[:]) -> Error {
    if digest.len != SHA256_BYTES { return Error.InvalidInput; }
    return error_from_native(native_finish(state._state[..], digest));
}
fn verify_ed25519(message: const u8[:], signature: const u8[:], public_key: const u8[:]) -> Error {
    if signature.len != ED25519_SIGNATURE_BYTES || public_key.len != ED25519_PUBLIC_KEY_BYTES { return Error.InvalidInput; }
    return error_from_native(native_verify(message, signature, public_key));
}
fn hex_value(c: u8) -> i64 {
    if c >= '0' && c <= '9' { return c - '0'; }
    if c >= 'a' && c <= 'f' { return c - 'a' + 10; }
    if c >= 'A' && c <= 'F' { return c - 'A' + 10; }
    return -1;
}
// Exact-sized caller storage, lowercase output, no allocations. Aliases rejected.
fn hex_encode(input: const u8[:], output: u8[:]) -> Error {
    if output.len % 2 != 0 || output.len / 2 != input.len || native_disjoint(input, output) != 0 { return Error.InvalidInput; }
    let digits = "0123456789abcdef";
    for i in input.len {
        output[i * 2] = digits[input[i] / 16];
        output[i * 2 + 1] = digits[input[i] % 16];
    }
    return Error.None;
}
fn hex_decode(input: const u8[:], output: u8[:]) -> Error {
    if input.len % 2 != 0 || input.len / 2 != output.len || native_disjoint(input, output) != 0 { return Error.InvalidInput; }
    for c in input { if hex_value(c) < 0 { return Error.InvalidInput; } }
    for i in output.len { output[i] = (hex_value(input[i * 2]) * 16 + hex_value(input[i * 2 + 1])) as u8; }
    return Error.None;
}

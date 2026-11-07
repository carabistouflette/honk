// SPDX-License-Identifier: Apache-2.0
import crypto from "..";
import std;

fn digest(message: const u8[:], expected: const u8[:]) {
    var out: u8[32] = [0; 32];
    var hex: u8[64] = [0; 64];
    assert(crypto::sha256(message, out) == crypto::Error.None);
    assert(crypto::hex_encode(out, hex) == crypto::Error.None);
    assert(hex == expected);
    // Exercise every split across the SHA-256 padding boundaries.
    for split in 0..message.len + 1 {
        var state = crypto::Sha256 { .. };
        assert(crypto::init(state) == crypto::Error.None);
        assert(crypto::update(state, message[..split]) == crypto::Error.None);
        assert(crypto::update(state, "") == crypto::Error.None);
        assert(crypto::update(state, message[split..]) == crypto::Error.None);
        var streamed: u8[32] = [0; 32];
        assert(crypto::finish(state, streamed) == crypto::Error.None);
        assert(streamed == out);
        let consumed = state;
        assert(crypto::finish(state, streamed) == crypto::Error.InvalidState);
        assert(state._state == consumed._state && streamed == out);
        assert(crypto::update(state, "x") == crypto::Error.InvalidState);
        assert(state._state == consumed._state);
    }
}
fn hashing() {
    digest("", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    digest("abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    digest("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
    var short: u8[31] = [42; 31];
    var long:  u8[33] = [43; 33];
    assert(crypto::sha256("abc", short) == crypto::Error.InvalidInput);
    assert(short == [42 as! u8; 31]);
    assert(crypto::sha256("abc", long) == crypto::Error.InvalidInput);
    assert(long == [43 as! u8; 33]);
    var state = crypto::Sha256 { .. };
    var out: u8[32] = [99; 32];
    assert(crypto::update(state, "abc") == crypto::Error.InvalidState);
    assert(crypto::finish(state, out) == crypto::Error.InvalidState);
    assert(out == [99 as! u8; 32]);
    assert(crypto::init(state) == crypto::Error.None);
    assert(crypto::update(state, "ab") == crypto::Error.None);
    let before = state;
    assert(crypto::finish(state, short) == crypto::Error.InvalidInput);
    assert(short == [42 as! u8; 31] && state._state == before._state);
    var fork = state;
    assert(crypto::update(state, "c") == crypto::Error.None);
    assert(crypto::finish(state, out) == crypto::Error.None);
    var forked: u8[32] = [0; 32];
    assert(crypto::update(fork, "d") == crypto::Error.None);
    assert(crypto::finish(fork, forked) == crypto::Error.None);
    assert(out != forked);
    assert(crypto::sha256("abd", out) == crypto::Error.None);
    assert(out == forked);
    // Reset works both while active and after finalization.
    assert(crypto::init(state) == crypto::Error.None);
    assert(crypto::update(state, "discard") == crypto::Error.None);
    assert(crypto::init(state) == crypto::Error.None);
    assert(crypto::finish(state, out) == crypto::Error.None);
    assert(crypto::sha256("", forked) == crypto::Error.None);
    assert(out == forked);
}
fn encodings() {
    var binary: u8[256] = [0; 256];
    for i in 256 { binary[i] = i as! u8; }
    var encoded: u8[512] = [0; 512];
    var decoded: u8[256] = [0; 256];
    assert(crypto::hex_encode(binary, encoded) == crypto::Error.None);
    assert(crypto::hex_decode(encoded, decoded) == crypto::Error.None);
    assert(binary == decoded);
    for i in encoded.len {
        if encoded[i] >= 'a' && encoded[i] <= 'f' { encoded[i] -= 32; }
    }
    assert(crypto::hex_decode(encoded, decoded) == crypto::Error.None);
    assert(binary == decoded);
    var empty: u8[0] = [];
    assert(crypto::hex_encode("", empty) == crypto::Error.None);
    assert(crypto::hex_decode("", empty) == crypto::Error.None);
    var out: u8[2] = [91; 2];
    for invalid in ["", "0", "000", "00000", "0x00", " 000", "000 ", "00\n0", "00\0f", "00gg", "00é"] {
        assert(crypto::hex_decode(invalid, out) == crypto::Error.InvalidInput);
        assert(out == [91 as! u8; 2]);
    }
    // Every nonhex byte, including invalid UTF-8, rejects atomically at each position.
    for n in 256 {
        let c = n as! u8;
        if (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F') { continue; }
        for position in 4 {
            var invalid: u8[4] = ['0'; 4];
            invalid[position] = c;
            assert(crypto::hex_decode(invalid, out) == crypto::Error.InvalidInput);
            assert(out == [91 as! u8; 2]);
        }
    }
    var wrong: u8[3] = [71; 3];
    assert(crypto::hex_encode("a", wrong) == crypto::Error.InvalidInput);
    assert(wrong == [71 as! u8; 3]);
}
fn signatures() {
    // RFC 8032 section 7.1, TEST 1 and TEST 2; pure Ed25519.
    var key: u8[32] = [0; 32];
    var sig: u8[64] = [0; 64];
    assert(crypto::hex_decode("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", key) == crypto::Error.None);
    assert(crypto::hex_decode("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b", sig) == crypto::Error.None);
    assert(crypto::verify_ed25519("", sig, key) == crypto::Error.None);
    assert(crypto::verify_ed25519("\0", sig, key) == crypto::Error.InvalidSignature);
    assert(crypto::hex_decode("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", key) == crypto::Error.None);
    assert(crypto::hex_decode("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00", sig) == crypto::Error.None);
    assert(crypto::verify_ed25519("\x72", sig, key) == crypto::Error.None);
    for i in sig.len {
        var damaged = sig;
        damaged[i] ^= 1;
        assert(crypto::verify_ed25519("\x72", damaged, key) == crypto::Error.InvalidSignature);
    }
    for i in key.len {
        var damaged = key;
        damaged[i] ^= 1;
        assert(crypto::verify_ed25519("\x72", sig, damaged) == crypto::Error.InvalidSignature);
    }
    for n in 256 {
        if n == 0x72 { continue; }
        var message: u8[1] = [n as! u8];
        assert(crypto::verify_ed25519(message, sig, key) == crypto::Error.InvalidSignature);
    }
    assert(crypto::verify_ed25519("\x72", sig[..63], key) == crypto::Error.InvalidInput);
    assert(crypto::verify_ed25519("\x72", sig, key[..31]) == crypto::Error.InvalidInput);
    var oversig: u8[65] = [0; 65];
    var overkey: u8[33] = [0; 33];
    assert(crypto::verify_ed25519("\x72", oversig, key) == crypto::Error.InvalidInput);
    assert(crypto::verify_ed25519("\x72", sig, overkey) == crypto::Error.InvalidInput);
    // Reject noncanonical scalar and small-order/zero key encodings.
    var noncanonical = sig;
    noncanonical[63] |= 0x80;
    assert(crypto::verify_ed25519("\x72", noncanonical, key) == crypto::Error.InvalidSignature);
    var zero: u8[32] = [0; 32];
    assert(crypto::verify_ed25519("\x72", sig, zero) == crypto::Error.InvalidSignature);
}
fn aliases() {
    var storage: u8[128] = [17; 128];
    assert(crypto::sha256(storage[..32], storage[..32]) == crypto::Error.InvalidInput);
    assert(storage == [17 as! u8; 128]);
    assert(crypto::sha256(storage[16..48], storage[..32]) == crypto::Error.InvalidInput);
    assert(storage == [17 as! u8; 128]);
    assert(crypto::hex_encode(storage[..16], storage[..32]) == crypto::Error.InvalidInput);
    assert(storage == [17 as! u8; 128]);
    // Valid hex input makes overlap rejection independently observable.
    var hex_storage: u8[64] = ['0'; 64];
    assert(crypto::hex_decode(hex_storage[..32], hex_storage[..16]) == crypto::Error.InvalidInput);
    assert(hex_storage == ['0' as! u8; 64]);
    assert(crypto::hex_decode(hex_storage[..32], hex_storage[16..32]) == crypto::Error.InvalidInput);
    assert(hex_storage == ['0' as! u8; 64]);
    assert(crypto::hex_decode(hex_storage[16..48], hex_storage[..16]) == crypto::Error.None);
    assert(hex_storage[..16] == [0 as! u8; 16]);
    // Adjacent ranges are permitted; rejection must test ranges, not allocation identity.
    assert(crypto::sha256(storage[32..64], storage[..32]) == crypto::Error.None);
    var state = crypto::Sha256 { .. };
    assert(crypto::init(state) == crypto::Error.None);
    let before = state;
    assert(crypto::update(state, state._state[..8]) == crypto::Error.InvalidInput);
    assert(state._state == before._state);
    assert(crypto::finish(state, state._state[..32]) == crypto::Error.InvalidInput);
    assert(state._state == before._state);
}
fn main() {
    hashing(); encodings(); signatures(); aliases();
    print("crypto public interface regressions passed");
}

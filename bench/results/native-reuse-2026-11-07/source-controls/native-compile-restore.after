/* SPDX-License-Identifier: Apache-2.0 */
#include "crypto.h"
#include <pthread.h>
#include <stddef.h>
#include <string.h>
#include <sodium.h>

/* No native pointer or allocator-owned resource is stored in a Goose value.
 * Metadata is private, native-endian and deliberately not a wire format. */
enum { STATE_OFFSET = 16 };
_Static_assert(sizeof(crypto_hash_sha256_state) <= GC_STATE_BYTES - STATE_OFFSET,
               "libsodium SHA-256 state no longer fits caller storage");
_Static_assert(crypto_hash_sha256_BYTES == GC_SHA256_BYTES, "SHA-256 size mismatch");
_Static_assert(crypto_sign_ed25519_PUBLICKEYBYTES == GC_ED25519_PUBLICKEY_BYTES,
               "Ed25519 public key size mismatch");
_Static_assert(crypto_sign_ed25519_BYTES == GC_ED25519_SIGNATURE_BYTES,
               "Ed25519 signature size mismatch");
static const uint8_t marker[8] = { 'G', 'C', 'S', '2', '5', '6', 1, 0 };
static pthread_once_t once = PTHREAD_ONCE_INIT;
static int init_result = -1;
static void initialize(void) { init_result = sodium_init(); }
static int ready(void) {
    return pthread_once(&once, initialize) == 0 && init_result >= 0;
}
static int valid(const void *p, int64_t n) {
    return n >= 0 && (uint64_t)n <= SIZE_MAX &&
           (n == 0 || (p != NULL && (uintptr_t)p <= UINTPTR_MAX - (uint64_t)n));
}
static int exact(gc_output s, int64_t n) {
    return s.len == n && valid(s.data, s.len);
}
static int overlap(const void *a, int64_t an, const void *b, int64_t bn) {
    if (!an || !bn) return 0;
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    return x <= y ? y - x < (uint64_t)an : x - y < (uint64_t)bn;
}
static const uint8_t empty = 0;
static const uint8_t *bytes(gc_input in) { return in.len ? in.data : &empty; }
static void save(uint8_t *out, const crypto_hash_sha256_state *state, uint64_t total) {
    memset(out, 0, GC_STATE_BYTES);
    memcpy(out, marker, sizeof marker);
    memcpy(out + 8, &total, sizeof total);
    memcpy(out + STATE_OFFSET, state, sizeof *state);
}
static int load(const uint8_t *in, crypto_hash_sha256_state *state, uint64_t *total) {
    if (memcmp(in, marker, sizeof marker)) return 0;
    memcpy(total, in + 8, sizeof *total);
    if (*total > GC_SHA256_MAX_BYTES) return 0;
    memcpy(state, in + STATE_OFFSET, sizeof *state);
    /* Count is in bits. Validate before giving caller-owned bytes to libsodium;
     * all buffered block positions are derived from this count. */
    return state->count == *total * UINT64_C(8);
}
int64_t gc_sha256(gc_input message, gc_output digest) {
    if (!valid(message.data, message.len) || !exact(digest, GC_SHA256_BYTES) ||
        overlap(message.data, message.len, digest.data, digest.len)) return GC_INVALID_INPUT;
    if ((uint64_t)message.len > GC_SHA256_MAX_BYTES) return GC_LIMIT_EXCEEDED;
    if (!ready()) return GC_BACKEND_FAILURE;
    uint8_t result[GC_SHA256_BYTES];
    if (crypto_hash_sha256(result, bytes(message), (unsigned long long)message.len))
        return GC_BACKEND_FAILURE;
    memcpy(digest.data, result, sizeof result);
    return GC_OK;
}
int64_t gc_sha256_init(gc_output state) {
    if (!exact(state, GC_STATE_BYTES)) return GC_INVALID_INPUT;
    if (!ready()) return GC_BACKEND_FAILURE;
    crypto_hash_sha256_state local;
    memset(&local, 0, sizeof local);
    if (crypto_hash_sha256_init(&local)) return GC_BACKEND_FAILURE;
    save(state.data, &local, 0);
    return GC_OK;
}
int64_t gc_sha256_update(gc_output state, gc_input message) {
    if (!exact(state, GC_STATE_BYTES) || !valid(message.data, message.len) ||
        overlap(state.data, state.len, message.data, message.len)) return GC_INVALID_INPUT;
    crypto_hash_sha256_state local;
    uint64_t total;
    if (!load(state.data, &local, &total)) return GC_INVALID_STATE;
    if ((uint64_t)message.len > GC_SHA256_MAX_BYTES - total) return GC_LIMIT_EXCEEDED;
    if (!ready()) return GC_BACKEND_FAILURE;
    if (crypto_hash_sha256_update(&local, bytes(message), (unsigned long long)message.len))
        return GC_BACKEND_FAILURE;
    save(state.data, &local, total + (uint64_t)message.len);
    return GC_OK;
}
int64_t gc_sha256_finish(gc_output state, gc_output digest) {
    if (!exact(state, GC_STATE_BYTES) || !exact(digest, GC_SHA256_BYTES) ||
        overlap(state.data, state.len, digest.data, digest.len)) return GC_INVALID_INPUT;
    crypto_hash_sha256_state local;
    uint64_t total;
    if (!load(state.data, &local, &total)) return GC_INVALID_STATE;
    if (!ready()) return GC_BACKEND_FAILURE;
    uint8_t result[GC_SHA256_BYTES];
    if (crypto_hash_sha256_final(&local, result)) return GC_BACKEND_FAILURE;
    memset(state.data, 0, GC_STATE_BYTES);
    memcpy(digest.data, result, sizeof result);
    return GC_OK;
}
int64_t gc_verify_ed25519(gc_input message, gc_input signature, gc_input public_key) {
    if (!valid(message.data, message.len) ||
        signature.len != GC_ED25519_SIGNATURE_BYTES || !valid(signature.data, signature.len) ||
        public_key.len != GC_ED25519_PUBLICKEY_BYTES || !valid(public_key.data, public_key.len))
        return GC_INVALID_INPUT;
    if (!ready()) return GC_BACKEND_FAILURE;
    return crypto_sign_ed25519_verify_detached(signature.data, bytes(message),
               (unsigned long long)message.len, public_key.data) == 0
               ? GC_OK : GC_INVALID_SIGNATURE;
}

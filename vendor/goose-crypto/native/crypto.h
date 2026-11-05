/* SPDX-License-Identifier: Apache-2.0 */
#ifndef GOOSE_CRYPTO_NATIVE_H
#define GOOSE_CRYPTO_NATIVE_H
#include <stdint.h>

typedef struct { const uint8_t *data; int64_t len; } gc_input;
typedef struct { uint8_t *data; int64_t len; } gc_output;
enum { GC_OK, GC_INVALID_INPUT, GC_INVALID_STATE, GC_INVALID_SIGNATURE,
       GC_BACKEND_FAILURE, GC_LIMIT_EXCEEDED };
enum { GC_SHA256_BYTES = 32, GC_STATE_BYTES = 128,
       GC_ED25519_PUBLICKEY_BYTES = 32, GC_ED25519_SIGNATURE_BYTES = 64 };
#define GC_SHA256_MAX_BYTES UINT64_C(2305843009213693951)

int64_t gc_disjoint(gc_input input, gc_output output);
int64_t gc_sha256(gc_input message, gc_output digest);
int64_t gc_sha256_init(gc_output state);
int64_t gc_sha256_update(gc_output state, gc_input message);
int64_t gc_sha256_finish(gc_output state, gc_output digest);
int64_t gc_verify_ed25519(gc_input message, gc_input signature, gc_input public_key);
#endif

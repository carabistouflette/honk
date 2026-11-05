// SPDX-License-Identifier: Apache-2.0
// Benchmark-only sink interposition. Production native source is unmodified.
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
typedef struct { const uint8_t *data; int64_t len; } Bytes;
static uint8_t *capture;
static int64_t capacity, used, calls, checksum;
static uint8_t deliver;
extern uint8_t __real_goose_cli_log_append(Bytes, Bytes);
uint8_t utc_bench_prepare(int64_t size, uint8_t real_sink) {
    if(size < 0 || size > 256262144) return 0;
    free(capture); capture = NULL;
    capacity = size; used = calls = checksum = 0; deliver = real_sink;
    if(size) { capture = malloc((size_t)size); if(!capture) return 0; memset(capture, 0, (size_t)size); }
    return 1;
}
uint8_t __wrap_goose_cli_log_append(Bytes path, Bytes line) {
    if(line.len <= 0 || line.len > 256 || line.len > capacity - used || !line.data) return 0;
    if(deliver && !__real_goose_cli_log_append(path, line)) return 0;
    memcpy(capture + used, line.data, (size_t)line.len);
    used += line.len; calls++; checksum += line.len;
    for(int64_t i = 0; i < line.len; i++) checksum += line.data[i] * (i + 1);
    return 1;
}
int64_t utc_bench_calls(void) { return calls; }
int64_t utc_bench_bytes(void) { return used; }
int64_t utc_bench_checksum(void) { return checksum; }
uint8_t utc_bench_dump(Bytes path) {
    char name[4096];
    if(path.len <= 0 || path.len >= (int64_t)sizeof name || !path.data || memchr(path.data, 0, (size_t)path.len)) return 0;
    memcpy(name, path.data, (size_t)path.len); name[path.len] = 0;
    FILE *out = fopen(name, "wb"); if(!out) return 0;
    size_t written = fwrite(capture, 1, (size_t)used, out);
    int closed = fclose(out);
    return written == (size_t)used && closed == 0;
}

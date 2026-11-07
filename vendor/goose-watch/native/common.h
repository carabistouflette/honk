/* SPDX-License-Identifier: Apache-2.0 */
#ifndef GOOSE_WATCH_COMMON_H
#define GOOSE_WATCH_COMMON_H
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdint.h>
#include <string.h>
#include <sys/inotify.h>
#include <unistd.h>

/* Private Goose ABI. state: fd+1, wd, cursor, used, ended, poisoned, reserved*2.
 * meta: errno, cleanup_errno, ready, mask, cookie, name_length. */
typedef struct {
    uint8_t *data;
    int64_t len;
} gw_bytes;
typedef struct {
    const uint8_t *data;
    int64_t len;
} gw_const_bytes;
typedef struct {
    int64_t *data;
    int64_t len;
} gw_ints;
typedef struct {
    const int64_t *data;
    int64_t len;
} gw_const_ints;
enum { GW_OK, GW_INPUT, GW_STATE, GW_INTERRUPTED, GW_SYSTEM, GW_END, GW_CORRUPT };
enum { GW_BUFFER = 65536, GW_NAME = 256, GW_PATH = 4095 };
#ifndef GW_INIT
#define GW_INIT inotify_init1
#define GW_ADD inotify_add_watch
#define GW_READ read
#define GW_POLL poll
#define GW_CLOSE close
#endif
static inline int gw_args(gw_ints state, gw_ints meta) {
    if (meta.len != 6 || !meta.data)
        return 0;
    memset(meta.data, 0, 6 * sizeof(int64_t));
    return state.len == 8 && state.data;
}
static inline int gw_active(gw_ints state) {
    return state.data[0] > 0 && state.data[0] <= (int64_t)INT_MAX + 1;
}
static inline int gw_failure(int error, gw_ints meta) {
    meta.data[0] = error;
    return error == EINTR ? GW_INTERRUPTED : GW_SYSTEM;
}
static inline int gw_path(gw_const_bytes path) {
    if (!path.data || path.len < 1 || path.len > GW_PATH || path.data[0] != '/' ||
        memchr(path.data, 0, (size_t)path.len))
        return 0;
    if (path.len == 1)
        return 1;
    size_t start = 1;
    for (size_t i = 1; i <= (size_t)path.len; ++i) {
        if (i != (size_t)path.len && path.data[i] != '/')
            continue;
        size_t n = i - start;
        if (!n || (n == 1 && path.data[start] == '.') ||
            (n == 2 && path.data[start] == '.' && path.data[start + 1] == '.'))
            return 0;
        start = i + 1;
    }
    return 1;
}
/* Byte-buffer offsets need not be aligned. Validate before exposing output. */
static inline int gw_decode(const uint8_t *data, size_t size, int64_t wd, gw_bytes name,
                            gw_ints meta, size_t *consumed) {
    struct inotify_event event;
    if (size < sizeof event)
        return GW_CORRUPT;
    memcpy(&event, data, sizeof event);
    if (event.len > GW_NAME || event.len > size - sizeof event ||
        (event.wd != wd && !(event.wd == -1 && (event.mask & IN_Q_OVERFLOW))))
        return GW_CORRUPT;
    size_t length = 0;
    if (event.len) {
        const uint8_t *start = data + sizeof event;
        const uint8_t *end = memchr(start, 0, event.len);
        if (!end)
            return GW_CORRUPT;
        length = (size_t)(end - start);
        if (memchr(start, '/', length))
            return GW_CORRUPT;
        memcpy(name.data, start, length);
    }
    meta.data[2] = 1;
    meta.data[3] = event.mask;
    meta.data[4] = event.cookie;
    meta.data[5] = (int64_t)length;
    *consumed = sizeof event + event.len;
    return GW_OK;
}

#endif

/* SPDX-License-Identifier: Apache-2.0 */
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
enum { GW_OK, GW_INPUT, GW_STATE, GW_INTERRUPTED, GW_SYSTEM, GW_END, GW_CORRUPT };
enum { GW_BUFFER = 65536, GW_NAME = 256, GW_PATH = 4095 };
#ifndef GW_INIT
#define GW_INIT inotify_init1
#define GW_ADD inotify_add_watch
#define GW_READ read
#define GW_POLL poll
#define GW_CLOSE close
#endif
static int gw_args(gw_ints state, gw_ints meta) {
    if (meta.len != 6 || !meta.data)
        return 0;
    memset(meta.data, 0, 6 * sizeof(int64_t));
    return state.len == 8 && state.data;
}
static int gw_active(gw_ints state) {
    return state.data[0] > 0 && state.data[0] <= (int64_t)INT_MAX + 1;
}
static int gw_failure(int error, gw_ints meta) {
    meta.data[0] = error;
    return error == EINTR ? GW_INTERRUPTED : GW_SYSTEM;
}
static int gw_path(gw_const_bytes path) {
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
int64_t gw_open(gw_ints state, gw_const_bytes path, gw_ints meta) {
    if (!gw_args(state, meta))
        return GW_INPUT;
    if (state.data[0])
        return GW_STATE;
    if (!gw_path(path))
        return GW_INPUT;
    char name[GW_PATH + 1];
    memcpy(name, path.data, (size_t)path.len);
    name[path.len] = 0;
    int fd = GW_INIT(IN_NONBLOCK | IN_CLOEXEC);
    if (fd < 0)
        return gw_failure(errno, meta);
    uint32_t mask = IN_CREATE | IN_MODIFY | IN_CLOSE_WRITE | IN_ATTRIB | IN_DELETE | IN_MOVED_FROM |
                    IN_MOVED_TO | IN_DELETE_SELF | IN_MOVE_SELF | IN_ONLYDIR | IN_DONT_FOLLOW;
    int wd = GW_ADD(fd, name, mask);
    if (wd < 0) {
        int error = errno;
        if (GW_CLOSE(fd) < 0)
            meta.data[1] = errno;
        return gw_failure(error, meta);
    }
    memset(state.data, 0, 8 * sizeof(int64_t));
    state.data[0] = (int64_t)fd + 1;
    state.data[1] = wd;
    return GW_OK;
}
/* Byte-buffer offsets need not be aligned. Validate before exposing output. */
static int gw_decode(const uint8_t *data, size_t size, int64_t wd, gw_bytes name, gw_ints meta,
                     size_t *consumed) {
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
int64_t gw_next(gw_ints state, gw_bytes buffer, int64_t timeout_ms, gw_bytes name, gw_ints meta) {
    if (!gw_args(state, meta))
        return GW_INPUT;
    if (buffer.len != GW_BUFFER || !buffer.data || name.len != GW_NAME || !name.data ||
        timeout_ms < 0 || timeout_ms > 60000)
        return GW_INPUT;
    if (!gw_active(state))
        return GW_STATE;
    if (state.data[5])
        return GW_CORRUPT;
    int64_t cursor = state.data[2], used = state.data[3];
    if (cursor < 0 || used < cursor || used > GW_BUFFER) {
        state.data[5] = 1;
        return GW_CORRUPT;
    }
    if (cursor == used) {
        if (state.data[4])
            return GW_END;
        int fd = (int)(state.data[0] - 1);
        struct pollfd item = {.fd = fd, .events = POLLIN, .revents = 0};
        int ready = GW_POLL(&item, 1, (int)timeout_ms);
        if (ready < 0)
            return gw_failure(errno, meta);
        if (!ready)
            return GW_OK;
        if (item.revents & (POLLNVAL | POLLERR | POLLHUP)) {
            meta.data[0] = item.revents & POLLNVAL ? EBADF : EIO;
            return GW_SYSTEM;
        }
        if (!(item.revents & POLLIN))
            return GW_OK;
        ssize_t count = GW_READ(fd, buffer.data, GW_BUFFER);
        if (count < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK)
                return GW_OK;
            return gw_failure(errno, meta);
        }
        if (!count) {
            state.data[5] = 1;
            return GW_CORRUPT;
        }
        cursor = 0;
        used = count;
        state.data[2] = 0;
        state.data[3] = used;
    }
    size_t consumed = 0;
    int code = gw_decode(buffer.data + cursor, (size_t)(used - cursor), state.data[1], name, meta,
                         &consumed);
    if (code != GW_OK) {
        state.data[5] = 1;
        return code;
    }
    state.data[2] += (int64_t)consumed;
    if (meta.data[3] & IN_IGNORED)
        state.data[4] = 1;
    return GW_OK;
}
int64_t gw_close(gw_ints state, gw_ints meta) {
    if (!gw_args(state, meta))
        return GW_INPUT;
    if (!state.data[0])
        return GW_OK;
    if (!gw_active(state))
        return GW_STATE;
    int fd = (int)(state.data[0] - 1);
    memset(state.data, 0, 8 * sizeof(int64_t));
    /* Linux releases the fd even on EINTR. Never retry close. */
    if (GW_CLOSE(fd) < 0)
        return gw_failure(errno, meta);
    return GW_OK;
}

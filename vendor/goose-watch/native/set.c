/* SPDX-License-Identifier: Apache-2.0 */
#include "common.h"
/* state: fd+1,count,cursor,used,ended,poisoned,reserved*2.
 * map: sorted pairs (wd,request index). meta: legacy6,directory,failed_directory. */
enum { GW_SET_MAX = 256, GW_SET_MAP = 512, GW_SET_PACKED = 1048576 };
int64_t gw_close(gw_ints state, gw_ints meta);
static int gs_args(gw_ints state, gw_ints map, gw_ints meta) {
    if (meta.len != 8 || !meta.data)
        return 0;
    memset(meta.data, 0, 8 * sizeof(int64_t));
    meta.data[6] = -1;
    meta.data[7] = -1;
    return state.len == 8 && state.data && map.len == GW_SET_MAP && map.data;
}
static int64_t gs_lookup(gw_ints map, int64_t count, int64_t wd) {
    int64_t lo = 0, hi = count;
    while (lo < hi) {
        int64_t mid = lo + (hi - lo) / 2;
        if (map.data[mid * 2] < wd)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo < count && map.data[lo * 2] == wd ? map.data[lo * 2 + 1] : -1;
}
static inline int gs_rollback(int fd, int error, gw_ints meta) {
    if (GW_CLOSE(fd) < 0)
        meta.data[1] = errno;
    return gw_failure(error, (gw_ints){meta.data, 6});
}
int64_t gw_set_open(gw_ints state, gw_ints map, gw_const_bytes packed, gw_ints offsets,
                    gw_ints meta) {
    if (!gs_args(state, map, meta))
        return GW_INPUT;
    if (state.data[0])
        return GW_STATE;
    if (offsets.len < 2 || offsets.len > GW_SET_MAP || offsets.len % 2 || !offsets.data ||
        packed.len < 1 || packed.len > GW_SET_PACKED || !packed.data)
        return GW_INPUT;
    int64_t count = offsets.len / 2, end = 0;
    for (int64_t i = 0; i < count; ++i) {
        int64_t start = offsets.data[i * 2], length = offsets.data[i * 2 + 1];
        meta.data[7] = i;
        if (start != end || length < 1 || length > GW_PATH || start < 0 || start >= packed.len ||
            length >= packed.len - start || packed.data[start + length] != 0 ||
            !gw_path((gw_const_bytes){packed.data + start, length}))
            return GW_INPUT;
        for (int64_t j = 0; j < i; ++j)
            if (offsets.data[j * 2 + 1] == length &&
                !memcmp(packed.data + offsets.data[j * 2], packed.data + start, (size_t)length))
                return GW_INPUT;
        end = start + length + 1;
    }
    meta.data[7] = -1;
    if (end != packed.len)
        return GW_INPUT;
#if defined(IN_MASK_CREATE) && !defined(GW_SET_NO_MASK_CREATE)
    int fd = GW_INIT(IN_NONBLOCK | IN_CLOEXEC);
    if (fd < 0)
        return gw_failure(errno, (gw_ints){meta.data, 6});
    int64_t pending[GW_SET_MAP] = {0};
    uint32_t mask = IN_CREATE | IN_MODIFY | IN_CLOSE_WRITE | IN_ATTRIB | IN_DELETE | IN_MOVED_FROM |
                    IN_MOVED_TO | IN_DELETE_SELF | IN_MOVE_SELF | IN_ONLYDIR | IN_DONT_FOLLOW |
                    IN_MASK_CREATE;
    for (int64_t i = 0; i < count; ++i) {
        meta.data[7] = i;
        int wd = GW_ADD(fd, (const char *)packed.data + offsets.data[i * 2], mask);
        if (wd < 0)
            return gs_rollback(fd, errno, meta);
        int64_t pos = i;
        while (pos > 0 && pending[(pos - 1) * 2] > wd) {
            pending[pos * 2] = pending[(pos - 1) * 2];
            pending[pos * 2 + 1] = pending[(pos - 1) * 2 + 1];
            --pos;
        }
        if ((pos > 0 && pending[(pos - 1) * 2] == wd) || (pos < i && pending[pos * 2] == wd))
            return gs_rollback(fd, EEXIST, meta);
        pending[pos * 2] = wd;
        pending[pos * 2 + 1] = i;
    }
    memcpy(map.data, pending, sizeof pending);
    memset(state.data, 0, 8 * sizeof(int64_t));
    state.data[0] = (int64_t)fd + 1;
    state.data[1] = count;
    meta.data[7] = -1;
    return GW_OK;
#else
    meta.data[0] = ENOTSUP;
    return GW_SYSTEM;
#endif
}
static int gs_decode(const uint8_t *data, size_t size, gw_ints map, int64_t count, gw_bytes name,
                     gw_ints meta, size_t *consumed) {
    struct inotify_event header;
    if (size < sizeof header)
        return GW_CORRUPT;
    memcpy(&header, data, sizeof header);
    int64_t directory;
    if (header.mask & IN_Q_OVERFLOW) {
        if (header.wd != -1 || header.len != 0 || header.cookie != 0 ||
            header.mask != IN_Q_OVERFLOW)
            return GW_CORRUPT;
        directory = -1;
    } else {
        directory = gs_lookup(map, count, header.wd);
        if (directory < 0 || directory >= count)
            return GW_CORRUPT;
    }
    int64_t scratch[6] = {0};
    size_t used = 0;
    int code = gw_decode(data, size, header.wd, name, (gw_ints){scratch, 6}, &used);
    if (code != GW_OK)
        return code;
    memcpy(meta.data, scratch, sizeof scratch);
    meta.data[6] = directory;
    *consumed = used;
    return GW_OK;
}
int64_t gw_set_next(gw_ints state, gw_ints map, gw_bytes buffer, int64_t timeout_ms, gw_bytes name,
                    gw_ints meta) {
    if (!gs_args(state, map, meta))
        return GW_INPUT;
    if (buffer.len != GW_BUFFER || !buffer.data || name.len != GW_NAME || !name.data ||
        timeout_ms < 0 || timeout_ms > 60000)
        return GW_INPUT;
    if (!gw_active(state))
        return GW_STATE;
    if (state.data[5])
        return GW_CORRUPT;
    if (state.data[4])
        return GW_END;
    int64_t count = state.data[1], cursor = state.data[2], used = state.data[3];
    if (count < 1 || count > GW_SET_MAX || cursor < 0 || used < cursor || used > GW_BUFFER) {
        state.data[5] = 1;
        return GW_CORRUPT;
    }
    if (cursor == used) {
        int fd = (int)(state.data[0] - 1);
        struct pollfd item = {.fd = fd, .events = POLLIN, .revents = 0};
        int ready = GW_POLL(&item, 1, (int)timeout_ms);
        if (ready < 0)
            return gw_failure(errno, (gw_ints){meta.data, 6});
        if (!ready)
            return GW_OK;
        if (item.revents & (POLLNVAL | POLLERR | POLLHUP)) {
            meta.data[0] = item.revents & POLLNVAL ? EBADF : EIO;
            return GW_SYSTEM;
        }
        if (!(item.revents & POLLIN))
            return GW_OK;
        ssize_t got = GW_READ(fd, buffer.data, GW_BUFFER);
        if (got < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK)
                return GW_OK;
            return gw_failure(errno, (gw_ints){meta.data, 6});
        }
        if (!got) {
            state.data[5] = 1;
            return GW_CORRUPT;
        }
        cursor = 0;
        used = got;
        state.data[2] = 0;
        state.data[3] = used;
    }
    size_t consumed = 0;
    int code =
        gs_decode(buffer.data + cursor, (size_t)(used - cursor), map, count, name, meta, &consumed);
    if (code != GW_OK) {
        state.data[5] = 1;
        return code;
    }
    state.data[2] += (int64_t)consumed;
    if (meta.data[3] & (IN_IGNORED | IN_Q_OVERFLOW))
        state.data[4] = 1;
    return GW_OK;
}
int64_t gw_set_close(gw_ints state, gw_ints map, gw_ints meta) {
    if (!gs_args(state, map, meta))
        return GW_INPUT;
    int64_t code = gw_close(state, (gw_ints){meta.data, 6});
    if (!state.data[0])
        memset(map.data, 0, GW_SET_MAP * sizeof(int64_t));
    return code;
}

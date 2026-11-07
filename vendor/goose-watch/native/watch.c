/* SPDX-License-Identifier: Apache-2.0 */
#include "common.h"

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

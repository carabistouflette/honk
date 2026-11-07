/* SPDX-License-Identifier: Apache-2.0 */
/* Test-only libc-write wrapper. Production adapter/guard code stays intact. */
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
#include <unistd.h>

static int64_t mode;
static int64_t calls;
ssize_t __real_write(int fd, const void *bytes, size_t count);
void honk_test_write_mode(int64_t selected) { mode = selected; calls = 0; }
int64_t honk_test_write_calls(void) { return calls; }
ssize_t __wrap_write(int fd, const void *bytes, size_t count) {
    if (fd != STDERR_FILENO) return __real_write(fd, bytes, count);
    ++calls;
    if ((mode == 1 && calls == 1) || mode == 3) { errno = EINTR; return -1; }
    if (mode == 2 && calls > 1) { errno = EAGAIN; return -1; }
    return __real_write(fd, bytes, count < 3 ? count : 3);
}

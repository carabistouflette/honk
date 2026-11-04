// SPDX-License-Identifier: Apache-2.0
// Linux application adapter, independent of the goose-log core. A false
// result can follow partial output; no retry, rollback, rotation or fsync.
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct { const uint8_t *data; int64_t len; } cli_log_bytes;
enum { CLI_LOG_PATH_LIMIT = 4096, CLI_LOG_LINE_LIMIT = 16417 };
static const off_t cli_log_file_limit = (off_t)16 * 1024 * 1024;

static int cli_log_openat(int directory, const char *name, int flags, mode_t mode) {
    int fd;
    do { fd = openat(directory, name, flags, mode); } while (fd < 0 && errno == EINTR);
    return fd;
}

static int cli_log_stat(int fd, struct stat *status) {
    int result;
    do { result = fstat(fd, status); } while (result < 0 && errno == EINTR);
    return result;
}

static int cli_log_private_mode(int fd) {
    int result;
    do { result = fchmod(fd, S_IRUSR | S_IWUSR); } while (result < 0 && errno == EINTR);
    return result;
}

static int cli_log_finish(int fd, int success) {
    // Linux closes the descriptor even when close reports EINTR. Retrying
    // could close a descriptor reused by another part of the application.
    return close(fd) == 0 && success;
}

static int cli_log_valid(const struct stat *status) {
    return S_ISREG(status->st_mode) && status->st_uid == geteuid() &&
        (status->st_mode & 07777) == (S_IRUSR | S_IWUSR) && status->st_nlink == 1;
}

uint8_t goose_cli_log_append(cli_log_bytes path, cli_log_bytes line) {
    if (path.len <= 0 || path.len >= CLI_LOG_PATH_LIMIT ||
        line.len <= 0 || line.len > CLI_LOG_LINE_LIMIT ||
        !path.data || !line.data || memchr(path.data, 0, (size_t)path.len)) return 0;
    char name[CLI_LOG_PATH_LIMIT];
    memcpy(name, path.data, (size_t)path.len);
    name[path.len] = 0;
    if (name[path.len - 1] == '/') return 0;

    const int directory_flags = O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC;
    int directory = cli_log_openat(AT_FDCWD, name[0] == '/' ? "/" : ".", directory_flags, 0);
    if (directory < 0) return 0;
    char *component = name;
    while (*component == '/') ++component;
    for (;;) {
        char *separator = strchr(component, '/');
        if (!separator) break;
        *separator = 0;
        int next = cli_log_openat(directory, component, directory_flags, 0);
        if (next < 0) return (uint8_t)cli_log_finish(directory, 0);
        if (!cli_log_finish(directory, 1)) return (uint8_t)cli_log_finish(next, 0);
        directory = next;
        component = separator + 1;
        while (*component == '/') ++component;
    }

    const int file_flags = O_WRONLY | O_APPEND | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC | O_NOCTTY;
    int fd = cli_log_openat(directory, component, file_flags | O_CREAT | O_EXCL, S_IRUSR | S_IWUSR);
    int created = fd >= 0;
    if (fd < 0 && errno == EEXIST) fd = cli_log_openat(directory, component, file_flags, 0);
    if (fd < 0) return (uint8_t)cli_log_finish(directory, 0);
    if (!cli_log_finish(directory, 1)) return (uint8_t)cli_log_finish(fd, 0);
    // Exclusive creation prevents changing an existing file's permissions.
    // fchmod gives a new file exactly 0600 even when the umask removed bits.
    if (created && cli_log_private_mode(fd) < 0) return (uint8_t)cli_log_finish(fd, 0);
    struct stat status;
    if (cli_log_stat(fd, &status) < 0 || !cli_log_valid(&status))
        return (uint8_t)cli_log_finish(fd, 0);
    int locked;
    do { locked = flock(fd, LOCK_EX | LOCK_NB); } while (locked < 0 && errno == EINTR);
    if (locked < 0) return (uint8_t)cli_log_finish(fd, 0);
    // Cooperating writers hold the lock across quota checking and all writes.
    // Recheck metadata after acquiring it.
    if (cli_log_stat(fd, &status) < 0 || !cli_log_valid(&status) || status.st_size < 0 ||
        status.st_size > cli_log_file_limit || line.len > cli_log_file_limit - status.st_size)
        return (uint8_t)cli_log_finish(fd, 0);
    size_t written = 0, length = (size_t)line.len;
    while (written < length) {
        ssize_t result = write(fd, line.data + written, length - written);
        if (result < 0 && errno == EINTR) continue;
        if (result <= 0) return (uint8_t)cli_log_finish(fd, 0);
        written += (size_t)result;
    }
    // close releases flock and its error is part of this delivery result.
    return (uint8_t)cli_log_finish(fd, 1);
}

uint8_t example_log_stdout_ok(void) {
    int flushed = fflush(stdout);
    return (uint8_t)(flushed == 0 && !ferror(stdout));
}

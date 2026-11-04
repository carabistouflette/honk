/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include "../vendor/goose-process/native/process.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
static pid_t owned;
static bool fail_clock;
static volatile sig_atomic_t pipe_handled;
static struct sigaction original_pipe, expected_pipe, original_chld;
static sigset_t original_mask;
static bool pipe_blocked, pipe_pending;
static void pipe_handler(int number) { (void)number; ++pipe_handled; }
static int pidfd_denials, kill_denials, transfers, recovery_waits, forwards;
static bool fault(void) { return getenv("HONK_TEST_TRANSFER") != NULL; }
int __real_clock_gettime(clockid_t clock, struct timespec *value);
int __wrap_clock_gettime(clockid_t clock, struct timespec *value) {
    if (fail_clock && clock == CLOCK_MONOTONIC) { fail_clock = false; errno = EIO; return -1; }
    return __real_clock_gettime(clock, value);
}
long __real_syscall(long number, ...);
long __wrap_syscall(long number, ...) {
    va_list args; va_start(args, number); long result;
    if (number == SYS_pidfd_open) {
        int pid = va_arg(args, int), flags = va_arg(args, int);
        result = __real_syscall(number, pid, flags);
    } else {
        assert(number == SYS_pidfd_send_signal);
        int fd = va_arg(args, int), signal = va_arg(args, int);
        void *info = va_arg(args, void *); int flags = va_arg(args, int);
        if (fault() && !pidfd_denials) { ++pidfd_denials; errno = EPERM; result = -1; }
        else { if (signal == SIGTERM) ++forwards; result = __real_syscall(number, fd, signal, info, flags); }
    }
    va_end(args); return result;
}
int __real_kill(pid_t pid, int number);
int __wrap_kill(pid_t pid, int number) {
    assert(fault()); /* Ordinary forwarding must never signal a numeric PID. */
    assert(pid == owned);
    if (!kill_denials) { ++kill_denials; errno = EPERM; return -1; }
    return __real_kill(pid, number);
}
pid_t __real_waitpid(pid_t pid, int *status, int options);
pid_t __wrap_waitpid(pid_t pid, int *status, int options) {
    if (transfers && pid == owned && recovery_waits < 2) {
        struct sigaction action; assert(sigaction(SIGCHLD, NULL, &action) == 0);
        assert(action.sa_handler == SIG_DFL && !(action.sa_flags & SA_NOCLDWAIT));
        const char *lock = getenv("HONK_TEST_LOCK"); assert(lock);
        int fd = open(lock, O_RDWR | O_CLOEXEC); assert(fd >= 0);
        assert(flock(fd, LOCK_EX | LOCK_NB) < 0 && (errno == EWOULDBLOCK || errno == EAGAIN));
        assert(close(fd) == 0); ++recovery_waits; errno = EPERM; return -1;
    }
    return __real_waitpid(pid, status, options);
}
bool __real_honk_process_guard_begin(void);
bool __wrap_honk_process_guard_begin(void) {
    bool ok = __real_honk_process_guard_begin();
    if (ok && getenv("HONK_TEST_PRESTART")) assert(__real_kill(getpid(), SIGTERM) == 0);
    return ok;
}
int64_t __real_gp_start(gp_input packed, gp_input cwd, gp_input sets, gp_input removes,
    int64_t input, gp_metadata config, gp_metadata state, gp_metadata meta);
int64_t __wrap_gp_start(gp_input packed, gp_input cwd, gp_input sets, gp_input removes,
    int64_t input, gp_metadata config, gp_metadata state, gp_metadata meta) {
    assert(!getenv("HONK_TEST_PRESTART"));
    assert(config.len == 11 && config.data[0] == 0 && config.data[2] == 2 && config.data[3] == 1);
    assert(config.data[9] == 1048576 && config.data[8] == 1);
    int64_t result = __real_gp_start(packed, cwd, sets, removes, input, config, state, meta);
    assert(result == 0); owned = (pid_t)gp_id(state); assert(owned > 0);
    const char *record = getenv("HONK_TEST_CHILD");
    if (record) {
        struct sigaction action; sigset_t mask;
        assert(sigaction(SIGPIPE, NULL, &action) == 0 && sigprocmask(SIG_SETMASK, NULL, &mask) == 0);
        int fd = open(record, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600); assert(fd >= 0);
        char text[96]; int length = snprintf(text, sizeof text, "%ld %d %d\n", (long)owned, action.sa_handler == SIG_DFL, sigismember(&mask, SIGPIPE));
        assert(length > 0 && (size_t)length < sizeof text && write(fd, text, (size_t)length) == length && close(fd) == 0);
    }
    if (fault()) fail_clock = true;
    else assert(__real_kill(getpid(), SIGTERM) == 0);
    return result;
}
int64_t __real_gp_wait(gp_metadata state, gp_input input, gp_output out, gp_output err,
    int64_t slice, int64_t step, gp_metadata meta, int64_t *done);
int64_t __wrap_gp_wait(gp_metadata state, gp_input input, gp_output out, gp_output err,
    int64_t slice, int64_t step, gp_metadata meta, int64_t *done) {
    assert(slice == 20 && step == 1);
    int64_t result = __real_gp_wait(state, input, out, err, slice, step, meta, done);
    if (meta.data[5]) { assert(meta.data[5] == owned && !transfers); ++transfers; }
    return result;
}
int64_t __real_gp_close(gp_metadata state, gp_metadata meta);
int64_t __wrap_gp_close(gp_metadata state, gp_metadata meta) {
    int64_t result = __real_gp_close(state, meta); assert(meta.data[5] == 0); return result;
}
void honk_test_ignore_chld(void) {
    assert(sigaction(SIGCHLD, NULL, &original_chld) == 0);
    struct sigaction action = {0}; action.sa_handler = SIG_IGN;
    assert(sigemptyset(&action.sa_mask) == 0 && sigaction(SIGCHLD, &action, NULL) == 0);
    assert(sigaction(SIGPIPE, NULL, &original_pipe) == 0 && sigprocmask(SIG_SETMASK, NULL, &original_mask) == 0);
    const char *mode = getenv("HONK_TEST_PIPE");
    if (mode && (!strcmp(mode, "ignored") || !strcmp(mode, "handler"))) {
        memset(&action, 0, sizeof action); assert(sigemptyset(&action.sa_mask) == 0);
        action.sa_handler = !strcmp(mode, "ignored") ? SIG_IGN : pipe_handler;
        action.sa_flags = SA_RESTART; assert(sigaddset(&action.sa_mask, SIGUSR1) == 0);
        assert(sigaction(SIGPIPE, &action, NULL) == 0);
    }
    pipe_blocked = mode && (!strcmp(mode, "blocked") || !strcmp(mode, "pending"));
    pipe_pending = mode && !strcmp(mode, "pending");
    if (pipe_blocked) {
        sigset_t one; assert(sigemptyset(&one) == 0 && sigaddset(&one, SIGPIPE) == 0);
        assert(sigprocmask(SIG_BLOCK, &one, NULL) == 0);
        if (pipe_pending) assert(raise(SIGPIPE) == 0);
    }
    assert(sigaction(SIGPIPE, NULL, &expected_pipe) == 0);
}
void honk_test_process_verify(void) {
    struct sigaction action; assert(sigaction(SIGCHLD, NULL, &action) == 0 && action.sa_handler == SIG_IGN);
    if (getenv("HONK_TEST_PRESTART")) {
        assert(!owned && !forwards && !transfers);
        assert(sigaction(SIGCHLD, &original_chld, NULL) == 0); return;
    }
    int status; assert(__real_waitpid(owned, &status, WNOHANG) == -1 && errno == ECHILD);
    if (fault()) assert(pidfd_denials == 1 && kill_denials == 1 && transfers == 1 && recovery_waits == 2);
    else assert(forwards == 1 && !pidfd_denials && !kill_denials && !transfers);
    struct sigaction pipe; sigset_t mask, pending;
    assert(sigaction(SIGPIPE, NULL, &pipe) == 0 && sigprocmask(SIG_SETMASK, NULL, &mask) == 0 && sigpending(&pending) == 0);
    assert(pipe.sa_handler == expected_pipe.sa_handler && (pipe.sa_flags & SA_RESTART) == (expected_pipe.sa_flags & SA_RESTART));
    assert(sigismember(&pipe.sa_mask, SIGUSR1) == sigismember(&expected_pipe.sa_mask, SIGUSR1) && !pipe_handled);
    assert(sigismember(&mask, SIGPIPE) == (pipe_blocked ? 1 : sigismember(&original_mask, SIGPIPE)));
    assert(sigismember(&pending, SIGPIPE) == (pipe_pending ? 1 : 0));
    if (pipe_pending) {
        sigset_t one; struct timespec immediate = {0, 0};
        assert(sigemptyset(&one) == 0 && sigaddset(&one, SIGPIPE) == 0 && sigtimedwait(&one, NULL, &immediate) == SIGPIPE);
    }
    assert(sigaction(SIGPIPE, &original_pipe, NULL) == 0 && sigprocmask(SIG_SETMASK, &original_mask, NULL) == 0);
    // Restoration was asserted above. Leave the fixture's original waitable
    // policy for LeakSanitizer's own post-main tracing child.
    assert(sigaction(SIGCHLD, &original_chld, NULL) == 0);
}

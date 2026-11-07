/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include "../vendor/goose-process/native/process.h"
#include <assert.h>
#include <errno.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
static pid_t pids[2];
static int starts, closes, recoveries, pidfd_denials, kill_denials;
static bool fail_clock;
static struct sigaction original[4];
static sigset_t original_mask;
static const int signals[4] = {SIGINT, SIGTERM, SIGCHLD, SIGPIPE};
static bool mode(const char *wanted) {
  const char *actual = getenv("HONK_PARALLEL_FAULT");
  return actual && !strcmp(actual, wanted);
}
__attribute__((constructor)) static void remember_signals(void) {
  for (int i = 0; i < 4; ++i) assert(sigaction(signals[i], NULL, &original[i]) == 0);
  assert(sigprocmask(SIG_SETMASK, NULL, &original_mask) == 0);
}
int __real_clock_gettime(clockid_t, struct timespec *);
int __wrap_clock_gettime(clockid_t clock, struct timespec *value) {
  if (fail_clock && clock == CLOCK_MONOTONIC) {
    fail_clock = false; errno = EIO; return -1;
  }
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
    int fd = va_arg(args, int), sig = va_arg(args, int);
    void *info = va_arg(args, void *); int flags = va_arg(args, int);
    if (mode("transfer") && !pidfd_denials) {
      ++pidfd_denials; errno = EPERM; result = -1;
    } else result = __real_syscall(number, fd, sig, info, flags);
  }
  va_end(args); return result;
}
int __real_kill(pid_t, int);
int __wrap_kill(pid_t pid, int sig) {
  if (mode("transfer") && pid == pids[0] && !kill_denials) {
    ++kill_denials; errno = EPERM; return -1;
  }
  return __real_kill(pid, sig);
}
int64_t __real_gp_start(gp_input, gp_input, gp_input, gp_input, int64_t, gp_metadata, gp_metadata, gp_metadata);
int64_t __wrap_gp_start(gp_input packed, gp_input cwd, gp_input sets, gp_input removes,
                       int64_t input, gp_metadata config, gp_metadata state, gp_metadata meta) {
  assert(starts < 2);
  int64_t result = __real_gp_start(packed, cwd, sets, removes, input, config, state, meta);
  pids[starts++] = result == 0 ? (pid_t)gp_id(state) : 0;
  if (mode("transfer") && starts == 2) fail_clock = true;
  return result;
}
int64_t __real_gp_close(gp_metadata, gp_metadata);
int64_t __wrap_gp_close(gp_metadata state, gp_metadata meta) {
  int64_t result = __real_gp_close(state, meta);
  ++closes;
  if (mode("close") && closes == 1) { meta.data[0] = EIO; return 3; }
  return result;
}
void __real_honk_process_recover(int64_t);
void __wrap_honk_process_recover(int64_t pid) {
  assert(mode("transfer") && pid == pids[0]);
  assert(closes == 2 && recoveries == 0); /* All other owners closed first. */
  ++recoveries;
  __real_honk_process_recover(pid);
}
bool hp_parallel_verify(void) {
  assert(starts == 2 && closes == 2);
  for (int i = 0; i < 2; ++i) {
    if (!pids[i]) continue;
    int status;
    assert(waitpid(pids[i], &status, WNOHANG) == -1 && errno == ECHILD);
  }
  if (mode("transfer")) assert(recoveries == 1 && pidfd_denials == 1 && kill_denials == 1);
  else assert(!recoveries && !pidfd_denials && !kill_denials);
  sigset_t mask; assert(sigprocmask(SIG_SETMASK, NULL, &mask) == 0);
  for (int i = 0; i < 4; ++i) {
    struct sigaction current; assert(sigaction(signals[i], NULL, &current) == 0);
    assert(current.sa_handler == original[i].sa_handler);
    assert(sigismember(&mask, signals[i]) == sigismember(&original_mask, signals[i]));
  }
  return true;
}

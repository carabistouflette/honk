/* SPDX-License-Identifier: Apache-2.0 */
/* Test-only linker seam. Production builds never include this file. */
#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
typedef struct {
  int64_t *data;
  int64_t len;
} ints;
typedef struct {
  uint8_t *data;
  int64_t len;
} bytes;
/* CMake probes link this object without the watch package. Real Honk links it.
 */
static int clock_sequence;
static int64_t clock_step;
static int clock_quiet;
static int overflow_injected;
int64_t __real_honk_watch_clock_ms(void) __attribute__((weak));
int64_t __wrap_honk_watch_clock_ms(void) {
  if (overflow_injected && getenv("WATCH_FAULT_CLOCK_AFTER_OVERFLOW"))
    return -1;
  if (clock_sequence == 2) {
    clock_sequence = 3;
    if (clock_step == 1000 && getenv("WATCH_FAULT_CANCEL_AT_CAP"))
      raise(SIGINT);
    return clock_step;
  }
  if (clock_quiet && clock_sequence == 3) {
    clock_sequence = 4;
    return 500;
  }
  if (clock_quiet && clock_sequence == 4) {
    clock_sequence = 5;
    const char *done = getenv("WATCH_FAULT_CLOCK_DONE");
    if (done)
      unlink(done);
    return 700;
  }
  if (clock_sequence >= 3)
    return -1;
  const char *mode = getenv("WATCH_FAULT_MODE");
  const char *trigger = getenv("WATCH_FAULT_TRIGGER");
  if (mode && strncmp(mode, "clock", 5) == 0 && trigger &&
      unlink(trigger) == 0) {
    if (strcmp(mode, "clock-backwards") == 0) {
      clock_sequence = 2;
      clock_step = 9;
      return 10;
    }
    if (strcmp(mode, "clock-cap") == 0 || strcmp(mode, "clock-ignored") == 0 ||
        strcmp(mode, "clock-quiet") == 0) {
      clock_sequence = 1;
      clock_quiet = strcmp(mode, "clock-quiet") == 0;
      clock_step = clock_quiet                      ? 200
                   : strcmp(mode, "clock-cap") == 0 ? 1000
                                                    : 500;
      return 0;
    }
    return -1;
  }
  return __real_honk_watch_clock_ms ? __real_honk_watch_clock_ms() : -1;
}
int64_t __real_gw_set_next(ints, ints, bytes, int64_t, bytes, ints)
    __attribute__((weak));
int64_t __wrap_gw_set_next(ints state, ints map, bytes buffer, int64_t timeout,
                           bytes name, ints meta) {
  static int ignored_remaining = 0;
  static int64_t *first_owner;
  if (!first_owner)
    first_owner = state.data;
  const char *target = getenv("WATCH_FAULT_TARGET");
  bool selected_owner =
      !target || strcmp(target, "data") != 0 || state.data != first_owner;
  if (clock_sequence == 1 && meta.len == 8 && meta.data && name.len >= 9 &&
      name.data) {
    clock_sequence = 2;
    memset(meta.data, 0, 8 * sizeof(int64_t));
    meta.data[2] = 1;
    meta.data[3] = 8;
    meta.data[5] = 9;
    memcpy(name.data, clock_step != 500 ? "cap.goose" : "ignored.o", 9);
    return 0;
  }
  const char *mode = getenv("WATCH_FAULT_MODE");
  const char *trigger = getenv("WATCH_FAULT_TRIGGER");
  if ((!mode ||
       (strncmp(mode, "clock", 5) != 0 && strncmp(mode, "tree", 4) != 0)) &&
      selected_owner && trigger && meta.len == 8 && meta.data && unlink(trigger) == 0) {
    memset(meta.data, 0, 8 * sizeof(int64_t));
    if (mode && strcmp(mode, "overflow") == 0) {
      meta.data[2] = 1;
      meta.data[3] = 16384;
      overflow_injected = 1;
      meta.data[6] = -1;
      if (state.len != 8 || !state.data)
        return 4;
      state.data[4] = 1;
      return 0;
    }
    if (mode && strcmp(mode, "ignored") == 0) {
      ignored_remaining = 256;
    } else {
      if (state.len != 8 || !state.data)
        return 4;
      /* Match the real decoder: permanent poison until close. */
      state.data[5] = 1;
      return 6; /* CorruptEvent, without exposing partial data. */
    }
  }
  if (ignored_remaining > 0 && meta.len == 8 && meta.data && name.len >= 9 &&
      name.data) {
    --ignored_remaining;
    memset(meta.data, 0, 8 * sizeof(int64_t));
    meta.data[2] = 1;
    meta.data[3] = 8;
    meta.data[5] = 9;
    memcpy(name.data, "ignored.o", 9);
    return 0;
  }
  if (!__real_gw_set_next)
    return 4;
  return __real_gw_set_next(state, map, buffer, timeout, name, meta);
}

int64_t __real_honk_tree_scan_step(ints) __attribute__((weak));
int64_t __real_honk_tree_verify_step(ints) __attribute__((weak));
static void tree_hook(const char *phase) {
  const char *mode = getenv("WATCH_FAULT_MODE");
  const char *trigger = getenv("WATCH_FAULT_TRIGGER");
  const char *root = getenv("WATCH_TREE_ROOT");
  if (!mode || strncmp(mode, "tree", 4) || !trigger || !root)
    return;
  if (!strcmp(mode, "tree-retry") && !strcmp(phase, "verify") &&
      access(trigger, F_OK) == 0) {
    char path[4096];
    int n = snprintf(path, sizeof path, "%s/churn", root);
    if (n > 0 && (size_t)n < sizeof path) {
      if (mkdir(path, 0700) == 0)
        rmdir(path);
    }
    return;
  }
  bool selected =
      (!strcmp(mode, "tree-aba") && !strcmp(phase, "scan")) ||
      (!strcmp(mode, "tree-verify-aba") && !strcmp(phase, "verify")) ||
      (!strcmp(mode, "tree-cancel") && !strcmp(phase, "scan"));
  if (!selected || unlink(trigger) != 0)
    return;
  if (!strcmp(mode, "tree-cancel")) {
    raise(SIGINT);
    return;
  }
  char moved[4096];
  int n = snprintf(moved, sizeof moved, "%s-moved", root);
  if (n > 0 && (size_t)n < sizeof moved && rename(root, moved) == 0)
    rename(moved, root);
}
int64_t __wrap_honk_tree_scan_step(ints tree) {
  tree_hook("scan");
  return __real_honk_tree_scan_step ? __real_honk_tree_scan_step(tree) : -1;
}
int64_t __wrap_honk_tree_verify_step(ints tree) {
  tree_hook("verify");
  return __real_honk_tree_verify_step ? __real_honk_tree_verify_step(tree) : -1;
}

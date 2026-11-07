/* SPDX-License-Identifier: Apache-2.0 */
/* Test-only linker seam. Production builds never include this file. */
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
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
int64_t __real_gw_next(ints, bytes, int64_t, bytes, ints) __attribute__((weak));
int64_t __wrap_gw_next(ints state, bytes buffer, int64_t timeout, bytes name,
                       ints meta) {
  static int ignored_remaining = 0;
  const char *trigger = getenv("WATCH_FAULT_TRIGGER");
  if (trigger && meta.len == 6 && meta.data && unlink(trigger) == 0) {
    memset(meta.data, 0, 6 * sizeof(int64_t));
    const char *mode = getenv("WATCH_FAULT_MODE");
    if (mode && strcmp(mode, "overflow") == 0) {
      meta.data[2] = 1;
      meta.data[3] = 16384;
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
  if (ignored_remaining > 0 && meta.len == 6 && meta.data && name.len >= 9 &&
      name.data) {
    --ignored_remaining;
    memset(meta.data, 0, 6 * sizeof(int64_t));
    meta.data[2] = 1;
    meta.data[3] = 8;
    meta.data[5] = 9;
    memcpy(name.data, "ignored.o", 9);
    return 0;
  }
  if (!__real_gw_next)
    return 4;
  return __real_gw_next(state, buffer, timeout, name, meta);
}

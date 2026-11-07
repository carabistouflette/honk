/* SPDX-License-Identifier: Apache-2.0 */
#include "../../native/watch_tree.c"
#include <assert.h>
#include <stdio.h>
#include <time.h>
int honk_watch_cancelled(void) { return 0; }
static int64_t clock_ns(void) {
  struct timespec t;
  assert(!clock_gettime(CLOCK_MONOTONIC, &t));
  assert(t.tv_sec >= 0 && t.tv_sec < INT64_MAX / 1000000000);
  return (int64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
int main(int argc, char **argv) {
  assert(argc == 2);
  int64_t state[2] = {0};
  tree_words owner = {state, 2};
  int64_t start = clock_ns();
  assert(!honk_tree_begin(owner));
  assert(!honk_tree_root(
      owner, (tree_bytes){(uint8_t *)argv[1], (int64_t)strlen(argv[1])}));
  int result;
  do {
    result = (int)honk_tree_scan_step(owner);
  } while (result > 0);
  assert(!result);
  int64_t scan = clock_ns() - start;
  int64_t count = honk_tree_count(owner);
  assert(count >= 2);
  start = clock_ns();
  assert(!honk_tree_verify_begin(owner));
  do {
    result = (int)honk_tree_verify_step(owner);
  } while (result > 0);
  assert(!result);
  int64_t verify = clock_ns() - start;
  start = clock_ns();
  for (int i = 0; i < 1000; ++i)
    assert(!honk_tree_roots_valid(owner));
  int64_t root_checks = clock_ns() - start;
  assert(!honk_tree_close(owner));
  printf("%lld %lld %lld %lld\n", (long long)count, (long long)scan,
         (long long)verify, (long long)root_checks);
}

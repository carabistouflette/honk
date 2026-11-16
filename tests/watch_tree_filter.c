/* SPDX-License-Identifier: Apache-2.0 */
#include "../native/watch_tree.c"
#include <assert.h>
#include <stdio.h>
int honk_watch_cancelled(void) { return 0; }
static int count_fds(void) {
  DIR *d = opendir("/proc/self/fd");
  assert(d);
  int n = 0;
  while (readdir(d))
    ++n;
  assert(!closedir(d));
  return n;
}
static void walk(tree_words owner, bool verify) {
  int64_t result;
  while ((result = verify ? honk_tree_verify_step(owner)
                          : honk_tree_scan_step(owner)) > 0) {
    if (result != 2)
      continue;
    uint8_t path[4096];
    int64_t length = honk_tree_path(owner, -1, (tree_bytes){0},
                                    (tree_bytes){path, sizeof path});
    assert(length > 0 && length < 4096);
    path[length] = 0;
    assert(!honk_tree_decide(owner, strcmp((char *)path, "ignored") != 0));
  }
  assert(result == 0);
}
int main(void) {
  char base[] = "/tmp/honk-filter-XXXXXX";
  assert(mkdtemp(base));
  char root[4096], ignored[4096], included[4096], nested[4096];
  snprintf(root, sizeof root, "%s/root", base);
  assert(!mkdir(root, 0700));
  snprintf(ignored, sizeof ignored, "%s/root/ignored", base);
  assert(!mkdir(ignored, 0700));
  snprintf(included, sizeof included, "%s/root/included", base);
  assert(!mkdir(included, 0700));
  snprintf(nested, sizeof nested, "%s/root/included/nested", base);
  assert(!mkdir(nested, 0700));
  int baseline = count_fds();
  int64_t state[2] = {0};
  tree_words owner = {state, 2};
  assert(!honk_tree_begin(owner));
  assert(!honk_tree_root(owner,
                         (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
  assert(!honk_tree_filter(owner));
  walk(owner, false);
  assert(honk_tree_count(owner) == 4);
  assert(!honk_tree_verify_begin(owner));
  walk(owner, true);
  assert(!honk_tree_close(owner));
  assert(count_fds() == baseline);
  /* Verification owns the same cursor and must clean an undecided entry. */
  assert(!honk_tree_begin(owner));
  assert(!honk_tree_root(owner,
                         (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
  assert(!honk_tree_filter(owner));
  walk(owner, false);
  assert(!honk_tree_verify_begin(owner));
  assert(honk_tree_verify_step(owner) == 2);
  assert(!honk_tree_close(owner));
  assert(count_fds() == baseline);
  /* A suspended cursor closes even if its decision was never supplied. */
  assert(!honk_tree_begin(owner));
  assert(!honk_tree_root(owner,
                         (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
  assert(!honk_tree_filter(owner));
  assert(honk_tree_scan_step(owner) == 2);
  assert(honk_tree_scan_step(owner) == -1);
  assert(!honk_tree_close(owner));
  assert(count_fds() == baseline);
  /* Opened identity must still match the yielded candidate. */
  assert(!honk_tree_begin(owner));
  assert(!honk_tree_root(owner,
                         (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
  assert(!honk_tree_filter(owner));
  for (;;) {
    assert(honk_tree_scan_step(owner) == 2);
    uint8_t path[4096];
    int64_t length = honk_tree_path(owner, -1, (tree_bytes){0},
                                    (tree_bytes){path, sizeof path});
    assert(length > 0);
    path[length] = 0;
    if (!strcmp((char *)path, "included"))
      break;
    assert(!honk_tree_decide(owner, 0));
  }
  char moved[4096];
  snprintf(moved, sizeof moved, "%s/root/moved", base);
  assert(!rename(included, moved));
  assert(!mkdir(included, 0700));
  assert(honk_tree_decide(owner, 1) == -1);
  assert(!honk_tree_close(owner));
  assert(count_fds() == baseline);
  assert(!rmdir(included));
  assert(!rename(moved, included));
  assert(!rmdir(nested));
  assert(!rmdir(included));
  assert(!rmdir(ignored));
  assert(!rmdir(root));
  assert(!rmdir(base));
  puts("filter pruning, relative paths, verification, pending cleanup and "
       "identity races passed");
}

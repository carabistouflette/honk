#define _GNU_SOURCE
/* SPDX-License-Identifier: Apache-2.0 */
// clang-format off
#include "../vendor/goose-watch/native/set.c"
#include "../vendor/goose-watch/native/watch.c"
#include "../native/watch_tree.c"
// clang-format on
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int honk_watch_cancelled(void) { return 0; }
int main(void) {
  char temp[] = "/tmp/honk-tree-guard-XXXXXX";
  assert(mkdtemp(temp));
  char root[4096], moved[4096];
  snprintf(root, sizeof root, "%s/root", temp);
  snprintf(moved, sizeof moved, "%s/moved", temp);
  assert(!mkdir(root, 0700));
  int64_t native[2] = {0};
  tree_words tree_owner = {native, 2};
  assert(!honk_tree_begin(tree_owner));
  assert(!honk_tree_root(tree_owner,
                         (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
  int64_t fds[256], state[8] = {0}, map[512] = {0}, meta[8];
  int64_t count = honk_tree_fds(tree_owner, (tree_words){fds, 256});
  assert(count == 2);
  gw_ints owner = {state, 8}, mapping = {map, 512}, info = {meta, 8};
  assert(gw_set_open_fds(owner, mapping, (gw_const_ints){fds, count}, info) ==
         GW_OK);
  // A root ABA is fatal even though final path/inode validation succeeds.
  for (int i = 0; i < 200; ++i) {
    char name[32];
    snprintf(name, sizeof name, "noise-%d.o", i);
    int fd = openat((int)fds[1], name, O_CREAT | O_WRONLY | O_CLOEXEC, 0600);
    assert(fd >= 0);
    assert(write(fd, "x", 1) == 1 && !close(fd));
  }
  assert(!rename(root, moved) && !rename(moved, root));
  assert(!honk_tree_roots_valid(tree_owner));
  uint8_t buffer[65536], name[256];
  int records = 0;
  bool fatal = false;
  for (int i = 0; i < 4096; ++i) {
    assert(gw_set_next(owner, mapping, (gw_bytes){buffer, 65536}, 0,
                       (gw_bytes){name, 256}, info) == GW_OK);
    if (!meta[2])
      break;
    ++records;
    if (honk_tree_guard_event(tree_owner, meta[6], (tree_bytes){name, meta[5]},
                              meta[3]) < 0) {
      fatal = true;
      break;
    }
  }
  assert(fatal && records > 256);
  assert(gw_set_close(owner, mapping, info) == GW_OK);
  for (int i = 0; i < 200; ++i) {
    char text[32];
    snprintf(text, sizeof text, "noise-%d.o", i);
    assert(!unlinkat((int)fds[1], text, 0));
  }
  assert(!honk_tree_close(tree_owner) && !rmdir(root) && !rmdir(temp));
  puts("session-long guard catches root ABA behind more than256 irrelevant "
       "records");
}

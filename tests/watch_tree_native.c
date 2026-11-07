/* SPDX-License-Identifier: Apache-2.0 */
#include "../native/watch_tree.c"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
static int cancelled;
int honk_watch_cancelled(void) { return cancelled; }
static int fd_count(void) {
  DIR *d = opendir("/proc/self/fd");
  assert(d);
  int n = 0;
  while (readdir(d))
    ++n;
  assert(!closedir(d));
  return n;
}
static bool scan(tree_words owner) {
  int result;
  do {
    result = (int)honk_tree_scan_step(owner);
  } while (result > 0);
  return result == 0;
}
static bool verify(tree_words owner) {
  assert(!honk_tree_verify_begin(owner));
  int result;
  do {
    result = (int)honk_tree_verify_step(owner);
  } while (result > 0);
  return result == 0;
}
int main(void) {
  char temp[] = "/tmp/honk-tree-XXXXXX";
  assert(mkdtemp(temp));
  char root[4096], nested[4096], excluded_path[4096], link[4096], moved[4096];
  assert(snprintf(root, sizeof root, "%s/root", temp) < (int)sizeof root);
  assert(snprintf(nested, sizeof nested, "%s/root/nested", temp) <
         (int)sizeof nested);
  assert(snprintf(excluded_path, sizeof excluded_path, "%s/root/target", temp) <
         (int)sizeof excluded_path);
  assert(snprintf(link, sizeof link, "%s/root/link", temp) < (int)sizeof link);
  assert(snprintf(moved, sizeof moved, "%s/moved", temp) < (int)sizeof moved);
  assert(!mkdir(root, 0700) && !mkdir(nested, 0700) &&
         !mkdir(excluded_path, 0700));
  assert(!symlink(temp, link));
  int64_t state[2] = {0};
  tree_words owner = {state, 2};
  int initial = fd_count();
  for (int i = 0; i < 32; ++i) {
    assert(!honk_tree_begin(owner));
    assert(honk_tree_begin(owner) < 0);
    assert(!honk_tree_root(
        owner, (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
    assert(scan(owner));
    assert(honk_tree_count(owner) == 3);
    assert(verify(owner));
    assert(honk_tree_event(owner, 1, (tree_bytes){NULL, 0}, 4) == 0);
    assert(honk_tree_event(owner, 0, (tree_bytes){NULL, 0}, 4) == 2);
    assert(honk_tree_event(owner, 1, (tree_bytes){(const uint8_t *)"target", 6},
                           0x40000100) == 2);
    assert(honk_tree_event(owner, 0,
                           (tree_bytes){(const uint8_t *)"outside.goose", 13},
                           8) == 2);
    int64_t fds[256];
    assert(honk_tree_fds(owner, (tree_words){fds, 256}) == 3);
    for (int j = 0; j < 3; ++j)
      assert(fcntl((int)fds[j], F_GETFD) & FD_CLOEXEC);
    assert(!honk_tree_close(owner) && !state[0]);
    assert(fd_count() == initial);
  }
  assert(!honk_tree_begin(owner));
  assert(honk_tree_root(
             owner, (tree_bytes){(uint8_t *)link, (int64_t)strlen(link)}) < 0);
  assert(!honk_tree_close(owner));
  assert(!honk_tree_begin(owner));
  assert(!honk_tree_root(owner,
                         (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
  assert(scan(owner));
  assert(!rename(root, moved));
  assert(honk_tree_roots_valid(owner) < 0);
  assert(!rename(moved, root));
  assert(!honk_tree_roots_valid(owner));
  char added[4096];
  assert(snprintf(added, sizeof added, "%s/root/added", temp) <
         (int)sizeof added);
  assert(!mkdir(added, 0700));
  assert(!verify(owner));
  assert(!rmdir(added));
  assert(verify(owner));
  assert(!rmdir(nested));
  assert(!verify(owner));
  assert(!honk_tree_close(owner));
  assert(!honk_tree_begin(owner));
  assert(!honk_tree_root(owner,
                         (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
  cancelled = 1;
  assert(!scan(owner));
  cancelled = 0;
  assert(!honk_tree_close(owner));
  // Every entry counts, including ordinary files and excluded-name entries.
  int rootfd = open(root, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  assert(rootfd >= 0);
  for (int i = 0; i < 8193; ++i) {
    char name[32];
    snprintf(name, sizeof name, "entry-%d", i);
    int fd = openat(rootfd, name, O_CREAT | O_WRONLY | O_CLOEXEC, 0600);
    assert(fd >= 0 && !close(fd));
  }
  assert(!honk_tree_begin(owner));
  assert(!honk_tree_root(owner,
                         (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
  assert(!scan(owner));
  assert(!honk_tree_close(owner));
  for (int i = 0; i < 8193; ++i) {
    char name[32];
    snprintf(name, sizeof name, "entry-%d", i);
    assert(!unlinkat(rootfd, name, 0));
  }
  assert(!close(rootfd));
  assert(!unlink(link) && !rmdir(excluded_path));
  assert(!honk_tree_begin(owner));
  assert(!honk_tree_root(owner,
                         (tree_bytes){(uint8_t *)root, (int64_t)strlen(root)}));
  assert(scan(owner));
  assert(!rmdir(root));
  assert(honk_tree_roots_valid(owner) < 0);
  assert(!honk_tree_close(owner));
  assert(fd_count() == initial && !rmdir(temp));
  puts("nofollow, identities, held-root deletion, topology verification, "
       "cancellation and fd cleanup passed");
}

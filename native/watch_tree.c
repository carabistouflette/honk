/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
extern int honk_watch_cancelled(void);
/* Bounded native allocation, owned only by the Goose root Tree. */
typedef struct {
  int64_t *data;
  int64_t len;
} tree_words;
typedef struct {
  const uint8_t *data;
  int64_t len;
} tree_bytes;
enum { TREE_CAP = 256, TREE_WORDS = 2, TREE_ENTRIES = 8192, TREE_DEPTH = 32 };
typedef struct {
  int fd;
  int parent, depth, roles;
  dev_t dev;
  ino_t ino;
  char name[256];
} tree_entry;
typedef struct {
  uint64_t magic;
  int count, roots, visited, cursor;
  tree_entry entries[TREE_CAP];
  bool filtering, pending, verifying;
  DIR *directory;
  int scan_index, scan_fd;
  bool seen[TREE_CAP];
  char candidate[256];
  struct stat candidate_info;
  int root_indices[8];
  char root_paths[8][4096];
} tree;
_Static_assert(sizeof(tree) <= 131072, "bounded native tree storage");
static const uint64_t TREE_MAGIC = UINT64_C(0x7761746368747265);
static tree *owned(tree_words words) {
  if (!words.data || words.len != TREE_WORDS)
    return NULL;
  if (!words.data[0])
    return NULL;
  tree *t = (tree *)(uintptr_t)words.data[0];
  return t->magic == TREE_MAGIC ? t : NULL;
}
static bool identity(const struct stat *s, const tree_entry *entry) {
  return S_ISDIR(s->st_mode) && s->st_dev == entry->dev &&
         s->st_ino == entry->ino && s->st_nlink > 0;
}
static bool excluded(const char *name) {
  return !strcmp(name, ".git") || !strcmp(name, ".honk") ||
         !strcmp(name, "target") || !strcmp(name, ".build") ||
         !strcmp(name, ".toolchain");
}
/* Transfer fd only on success. Shared parent sentinels may be reused. */
static int insert(tree *t, int fd, int parent, const char *name, int depth,
                  int roles) {
  struct stat s;
  if (fstat(fd, &s) < 0 || !S_ISDIR(s.st_mode) || !s.st_nlink)
    return -1;
  for (int i = 0; i < t->count; ++i)
    if (t->entries[i].dev == s.st_dev && t->entries[i].ino == s.st_ino) {
      if (roles == 2 && t->entries[i].roles == 2) {
        close(fd);
        return i;
      }
      return -1; /* overlapping roots/aliases are deliberately unsupported */
    }
  if (t->count == TREE_CAP || depth > TREE_DEPTH || strlen(name) > 255)
    return -1;
  int index = t->count++;
  tree_entry *e = &t->entries[index];
  memset(e, 0, sizeof *e);
  e->fd = fd;
  e->parent = parent;
  e->depth = depth;
  e->roles = roles;
  e->dev = s.st_dev;
  e->ino = s.st_ino;
  strcpy(e->name, name);
  return index;
}
int64_t honk_tree_close(tree_words words) {
  tree *t = owned(words);
  if (!t)
    return -1;
  bool ok = true;
  if (t->directory && closedir(t->directory) < 0) ok = false;
  for (int i = 0; i < t->count; ++i) {
    int fd = t->entries[i].fd;
    t->entries[i].fd = -1;
    if (close(fd) < 0)
      ok = false;
  }
  memset(t, 0, sizeof *t);
  free(t);
  words.data[0] = 0;
  words.data[1] = 0;
  return ok ? 0 : -1;
}
int64_t honk_tree_begin(tree_words words) {
  if (!words.data || words.len != TREE_WORDS)
    return -1;
  if (words.data[0] || words.data[1])
    return -1;
  tree *t = calloc(1, sizeof *t);
  if (!t)
    return -1;
  t->magic = TREE_MAGIC;
  words.data[0] = (int64_t)(uintptr_t)t;
  return 0;
}
/* Component traversal never follows untrusted symlinks. Root '/' is excluded.
 */
int64_t honk_tree_root(tree_words words, tree_bytes path) {
  tree *t = owned(words);
  if (!t || t->roots == 8 || path.len < 2 || path.len > 4095 || !path.data ||
      path.data[0] != '/' || memchr(path.data, 0, (size_t)path.len))
    return -1;
  char text[4096];
  memcpy(text, path.data, (size_t)path.len);
  text[path.len] = 0;
  int fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  if (fd < 0)
    return -1;
  char *part = text + 1;
  for (;;) {
    char *slash = strchr(part, '/');
    if (slash)
      *slash = 0;
    if (!*part || !strcmp(part, ".") || !strcmp(part, "..") ||
        strlen(part) > 255) {
      close(fd);
      return -1;
    }
    int child =
        openat(fd, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (child < 0) {
      close(fd);
      return -1;
    }
    if (!slash) {
      int parent = insert(t, fd, -1, "", 0, 2);
      if (parent < 0) {
        close(fd);
        close(child);
        return -1;
      }
      int root = insert(t, child, parent, part, 0, 1 | 4);
      if (root < 0) {
        close(child);
        return -1;
      }
      t->root_indices[t->roots] = root;
      memcpy(t->root_paths[t->roots], path.data, (size_t)path.len);
      t->root_paths[t->roots][path.len] = 0;
      ++t->roots;
      return 0;
    }
    close(fd);
    fd = child;
    part = slash + 1;
  }
}
/* Optional filtering keeps one cursor and one undecided directory candidate. */
int64_t honk_tree_filter(tree_words words) {
  tree *t = owned(words);
  if (!t || t->cursor || t->directory)
    return -1;
  t->filtering = true;
  return 0;
}
int64_t honk_tree_path(tree_words words, int64_t index, tree_bytes name,
                       tree_bytes output) {
  tree *t = owned(words);
  if (!t || !output.data || output.len != 4096)
    return -1;
  if (index == -1) {
    if (!t->pending)
      return -1;
    index = t->scan_index;
    name.data = (const uint8_t *)t->candidate;
    name.len = (int64_t)strlen(t->candidate);
  }
  if (index < 0 || index >= t->count || !(t->entries[index].roles & 1) ||
      name.len <= 0 || name.len > 255 || !name.data ||
      memchr(name.data, 0, (size_t)name.len) ||
      memchr(name.data, '/', (size_t)name.len))
    return -1;
  uint8_t *out = (uint8_t *)output.data;
  size_t at = 4095;
  at -= (size_t)name.len;
  memcpy(out + at, name.data, (size_t)name.len);
  int depth = 0;
  while (!(t->entries[index].roles & 4)) {
    tree_entry *e = &t->entries[index];
    size_t n = strlen(e->name);
    if (++depth > TREE_DEPTH || e->parent < 0 || at < n + 1)
      return -1;
    out[--at] = '/';
    at -= n;
    memcpy(out + at, e->name, n);
    index = e->parent;
  }
  size_t length = 4095 - at;
  memmove(out, out + at, length);
  return (int64_t)length;
}
int64_t honk_tree_decide(tree_words words, int64_t include) {
  tree *t = owned(words);
  if (!t || !t->pending || !t->directory || (include != 0 && include != 1))
    return -1;
  t->pending = false;
  if (!include)
    return 0;
  int fd = t->scan_fd;
  struct stat info;
  if (fstatat(fd, t->candidate, &info, AT_SYMLINK_NOFOLLOW) < 0 ||
      !S_ISDIR(info.st_mode) || info.st_dev != t->candidate_info.st_dev ||
      info.st_ino != t->candidate_info.st_ino)
    return -1;
  if (t->verifying) {
    for (int j = 0; j < t->count; ++j)
      if (t->entries[j].parent == t->scan_index &&
          !strcmp(t->entries[j].name, t->candidate) &&
          identity(&info, &t->entries[j])) {
        t->seen[j] = true;
        return 0;
      }
    return -1;
  }
  int child =
      openat(fd, t->candidate, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (child < 0)
    return -1;
  struct stat actual;
  if (fstat(child, &actual) < 0 || actual.st_dev != info.st_dev ||
      actual.st_ino != info.st_ino ||
      insert(t, child, t->scan_index, t->candidate,
             t->entries[t->scan_index].depth + 1, 1) < 0) {
    close(child);
    return -1;
  }
  return 0;
}
static int filtered_step(tree *t, bool verify) {
  if (t->pending)
    return -1;
  if (!t->directory) {
    while (t->cursor < t->count && !(t->entries[t->cursor].roles & 1))
      ++t->cursor;
    if (t->cursor == t->count)
      return 0;
    t->scan_index = t->cursor++;
    tree_entry *e = &t->entries[t->scan_index];
    struct stat info;
    if (verify &&
        (fstat(e->fd, &info) < 0 || !identity(&info, e) ||
         (e->parent >= 0 && (fstatat(t->entries[e->parent].fd, e->name, &info,
                                     AT_SYMLINK_NOFOLLOW) < 0 ||
                             !identity(&info, e)))))
      return -1;
    int fd =
        openat(e->fd, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0)
      return -1;
    t->directory = fdopendir(fd);
    if (!t->directory) {
      close(fd);
      return -1;
    }
    t->scan_fd = fd;
    t->verifying = verify;
    memset(t->seen, 0, sizeof t->seen);
  }
  for (;;) {
    if (honk_watch_cancelled())
      return -1;
    errno = 0;
    struct dirent *item = readdir(t->directory);
    if (!item) {
      bool ok = errno == 0;
      if (verify)
        for (int j = 0; j < t->count; ++j)
          if (t->entries[j].parent == t->scan_index &&
              !(t->entries[j].roles & 4) && !t->seen[j])
            ok = false;
      if (closedir(t->directory) < 0)
        ok = false;
      t->directory = NULL;
      t->scan_fd = -1;
      return ok ? 1 : -1;
    }
    if (!strcmp(item->d_name, ".") || !strcmp(item->d_name, ".."))
      continue;
    if (++t->visited > TREE_ENTRIES)
      return -1;
    if (fstatat(t->scan_fd, item->d_name, &t->candidate_info,
                AT_SYMLINK_NOFOLLOW) < 0)
      return -1;
    if (!S_ISDIR(t->candidate_info.st_mode) || excluded(item->d_name))
      continue;
    if (strlen(item->d_name) > 255)
      return -1;
    strcpy(t->candidate, item->d_name);
    t->pending = true;
    return 2;
  }
}
/* One directory per call; count every entry, including excluded names/files. */
int64_t honk_tree_scan_step(tree_words words) {
  tree *t = owned(words);
  if (!t || !t->roots)
    return -1;
  if (t->filtering) return filtered_step(t, false);
  while (t->cursor < t->count && !(t->entries[t->cursor].roles & 1))
    ++t->cursor;
  if (t->cursor == t->count)
    return 0;
  int index = t->cursor++;
  tree_entry *entry = &t->entries[index];
  int fd =
      openat(entry->fd, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (fd < 0)
    return -1;
  DIR *dir = fdopendir(fd);
  if (!dir) {
    close(fd);
    return -1;
  }
  bool ok = true;
  struct dirent *item;
  for (;;) {
    if (honk_watch_cancelled()) {
      ok = false;
      break;
    }
    errno = 0;
    item = readdir(dir);
    if (!item) {
      if (errno)
        ok = false;
      break;
    }
    if (!strcmp(item->d_name, ".") || !strcmp(item->d_name, ".."))
      continue;
    if (++t->visited > TREE_ENTRIES) {
      ok = false;
      break;
    }
    struct stat info;
    if (fstatat(fd, item->d_name, &info, AT_SYMLINK_NOFOLLOW) < 0) {
      ok = false;
      break;
    }
    if (!S_ISDIR(info.st_mode) || excluded(item->d_name))
      continue;
    int child = openat(fd, item->d_name,
                       O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (child < 0) {
      ok = false;
      break;
    }
    struct stat actual;
    if (fstat(child, &actual) < 0 || actual.st_dev != info.st_dev ||
        actual.st_ino != info.st_ino ||
        insert(t, child, index, item->d_name, entry->depth + 1, 1) < 0) {
      close(child);
      ok = false;
      break;
    }
  }
  if (closedir(dir) < 0)
    ok = false;
  return ok ? 1 : -1;
}
int64_t honk_tree_count(tree_words words) {
  tree *t = owned(words);
  return t ? t->count : -1;
}
int64_t honk_tree_fds(tree_words words, tree_words output) {
  tree *t = owned(words);
  if (!t || output.len != TREE_CAP || !output.data)
    return -1;
  for (int i = 0; i < t->count; ++i)
    output.data[i] = t->entries[i].fd;
  return t->count;
}
/* Exact configured root bindings checked even when old inotify coverage ended.
 */
int64_t honk_tree_roots_valid(tree_words words) {
  tree *t = owned(words);
  if (!t)
    return -1;
  for (int i = 0; i < t->count; ++i)
    if (t->entries[i].roles & 4) {
      tree_entry *e = &t->entries[i];
      struct stat info;
      if (fstat(e->fd, &info) < 0 || !identity(&info, e) ||
          fstatat(t->entries[e->parent].fd, e->name, &info,
                  AT_SYMLINK_NOFOLLOW) < 0 ||
          !identity(&info, e))
        return -1;
    }
  for (int i = 0; i < t->roots; ++i) {
    char text[4096];
    strcpy(text, t->root_paths[i]);
    int fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0)
      return -1;
    char *part = text + 1;
    for (;;) {
      char *slash = strchr(part, '/');
      if (slash)
        *slash = 0;
      int next =
          openat(fd, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
      close(fd);
      if (next < 0)
        return -1;
      fd = next;
      if (!slash)
        break;
      part = slash + 1;
    }
    struct stat info;
    bool ok = fstat(fd, &info) == 0 &&
              identity(&info, &t->entries[t->root_indices[i]]);
    if (close(fd) < 0)
      ok = false;
    if (!ok)
      return -1;
  }
  return 0;
}
int64_t honk_tree_verify_begin(tree_words words) {
  tree *t = owned(words);
  if (!t || t->directory || t->pending)
    return -1;
  t->cursor = 0;
  t->visited = 0;
  return 0;
}
/* Verify membership under installed watches, using retained anchors. */
int64_t honk_tree_verify_step(tree_words words) {
  tree *t = owned(words);
  if (!t)
    return -1;
  if (t->filtering) return filtered_step(t, true);
  while (t->cursor < t->count && !(t->entries[t->cursor].roles & 1))
    ++t->cursor;
  if (t->cursor == t->count)
    return 0;
  int index = t->cursor++;
  tree_entry *e = &t->entries[index];
  struct stat info;
  if (fstat(e->fd, &info) < 0 || !identity(&info, e))
    return -1;
  if (e->parent >= 0 && (fstatat(t->entries[e->parent].fd, e->name, &info,
                                 AT_SYMLINK_NOFOLLOW) < 0 ||
                         !identity(&info, e)))
    return -1;
  int fd = openat(e->fd, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (fd < 0)
    return -1;
  DIR *dir = fdopendir(fd);
  if (!dir) {
    close(fd);
    return -1;
  }
  bool ok = true;
  bool seen[TREE_CAP] = {0};
  struct dirent *item;
  for (;;) {
    if (honk_watch_cancelled()) {
      ok = false;
      break;
    }
    errno = 0;
    item = readdir(dir);
    if (!item) {
      if (errno)
        ok = false;
      break;
    }
    if (!strcmp(item->d_name, ".") || !strcmp(item->d_name, ".."))
      continue;
    if (++t->visited > TREE_ENTRIES) {
      ok = false;
      break;
    }
    if (fstatat(fd, item->d_name, &info, AT_SYMLINK_NOFOLLOW) < 0) {
      ok = false;
      break;
    }
    if (!S_ISDIR(info.st_mode) || excluded(item->d_name))
      continue;
    int found = -1;
    for (int j = 0; j < t->count; ++j)
      if (t->entries[j].parent == index &&
          !strcmp(t->entries[j].name, item->d_name) &&
          identity(&info, &t->entries[j])) {
        found = j;
        break;
      }
    if (found < 0) {
      ok = false;
      break;
    }
    seen[found] = true;
  }
  for (int j = 0; j < t->count; ++j)
    if (t->entries[j].parent == index && !(t->entries[j].roles & 4) && !seen[j])
      ok = false;
  if (closedir(dir) < 0)
    ok = false;
  return ok ? 1 : -1;
}
/* -1 explicit binding lost, 1 included topology changed, 0 irrelevant sentinel.
 */
int64_t honk_tree_event(tree_words words, int64_t index, tree_bytes name,
                        int64_t mask) {
  tree *t = owned(words);
  if (!t || index < 0 || index >= t->count || name.len < 0 || name.len > 255 ||
      (!name.data && name.len))
    return -1;
  tree_entry *e = &t->entries[index];
  if (mask & (0x400 | 0x800 | 0x2000 | 0x8000))
    return (e->roles & (2 | 4)) ? -1 : 1;
  if (e->roles & 2)
    for (int j = 0; j < t->count; ++j)
      if (name.len > 0 && (t->entries[j].roles & 4) &&
          t->entries[j].parent == index &&
          strlen(t->entries[j].name) == (size_t)name.len &&
          !memcmp(t->entries[j].name, name.data, (size_t)name.len) &&
          (mask & (0x40 | 0x80 | 0x100 | 0x200)))
        return -1;
  if (!(e->roles & 1))
    return 2; // Sentinel-only records never become source changes.
  char basename[256];
  if (name.len > 0)
    memcpy(basename, name.data, (size_t)name.len);
  basename[name.len] = 0;
  if (excluded(basename))
    return 2;
  return (e->roles & 1) && (mask & 0x40000000) &&
                 (mask & (0x40 | 0x80 | 0x100 | 0x200))
             ? 1
             : 0;
}

/* A session-long guard covers explicit roots/parents independently of
 * generations. */
int64_t honk_tree_guard_event(tree_words words, int64_t index, tree_bytes name,
                              int64_t mask) {
  int64_t kind = honk_tree_event(words, index, name, mask);
  return kind < 0 ? -1 : 0;
}

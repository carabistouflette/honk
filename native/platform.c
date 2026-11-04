// SPDX-License-Identifier: Apache-2.0
// POSIX operations missing from the pinned Goose standard library. No shell.
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#define _POSIX_C_SOURCE 200809L
#define _XOPEN_SOURCE 700
#include "goose.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

typedef struct {
  const uint8_t *data;
  int64_t len;
} hs;
#define HPATH 4096
#define HCAP (1024 * 1024)
static bool path(hs s, char out[HPATH]) {
  if (s.len <= 0 || s.len >= HPATH || memchr(s.data, 0, (size_t)s.len))
    return false;
  memcpy(out, s.data, (size_t)s.len);
  out[s.len] = 0;
  return true;
}
bool honk_real(hs s, gs_rref out) {
  char p[HPATH], r[HPATH];
  if (!path(s, p) || !realpath(p, r))
    return false;
  gs_bld_append(out, r, (int64_t)strlen(r));
  return true;
}
int64_t honk_kind(hs s) {
  char p[HPATH];
  struct stat st;
  if (!path(s, p) || lstat(p, &st) < 0)
    return 0;
  return S_ISREG(st.st_mode) ? 1 : S_ISDIR(st.st_mode) ? 2 : -1;
}
static struct dirent *read_entry(DIR *dir, bool *ok) {
  errno = 0;
  struct dirent *entry = readdir(dir);
  if (!entry && errno)
    *ok = false;
  return entry;
}
static int name_order(const void *a, const void *b) {
  return strcmp(*(const char *const *)a, *(const char *const *)b);
}
bool honk_list(hs s, gs_rref out) {
  char p[HPATH];
  if (!path(s, p))
    return false;
  int fd = open(p, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (fd < 0)
    return false;
  DIR *dir = fdopendir(fd);
  if (!dir) {
    close(fd);
    return false;
  }
  char **names = NULL;
  size_t count = 0, capacity = 0, bytes = 0;
  bool ok = true;
  struct dirent *entry;
  while (ok && (entry = read_entry(dir, &ok))) {
    const char *name = entry->d_name;
    if (!strcmp(name, ".") || !strcmp(name, ".."))
      continue;
    size_t length = strlen(name);
    if (count >= 100000 || length + 1 > HCAP - bytes || strchr(name, '\n') ||
        strchr(name, '\r')) {
      ok = false;
      break;
    }
    if (count == capacity) {
      size_t next = capacity ? capacity * 2 : 32;
      char **grown = realloc(names, next * sizeof *names);
      if (!grown) {
        ok = false;
        break;
      }
      names = grown;
      capacity = next;
    }
    names[count] = strdup(name);
    if (!names[count]) {
      ok = false;
      break;
    }
    count++;
    bytes += length + 1;
  }
  closedir(dir);
  if (ok) {
    if (count > 1)
      qsort(names, count, sizeof *names, name_order);
    for (size_t i = 0; i < count; i++) {
      gs_bld_append(out, names[i], (int64_t)strlen(names[i]));
      gs_bld_append(out, "\n", 1);
    }
  }
  for (size_t i = 0; i < count; i++)
    free(names[i]);
  free(names);
  return ok;
}
bool honk_mkdir(hs s) {
  char p[HPATH];
  if (!path(s, p))
    return false;
  // Refuse symlinks in every existing component.
  for (char *q = p + 1;; q++) {
    if (*q != '/' && *q)
      continue;
    char end = *q;
    *q = 0;
    struct stat st;
    if (mkdir(p, 0700) < 0 && errno != EEXIST)
      return false;
    if (lstat(p, &st) < 0 || !S_ISDIR(st.st_mode))
      return false;
    *q = end;
    if (!end)
      break;
  }
  return true;
}
static bool read_bounded(hs s, gs_rref out, size_t limit) {
  char p[HPATH];
  if (!path(s, p))
    return false;
  int fd = open(p, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
  if (fd < 0)
    return false;
  struct stat st;
  bool ok = fstat(fd, &st) == 0 && S_ISREG(st.st_mode) &&
            (uint64_t)st.st_size <= limit;
  char b[16384];
  size_t total = 0;
  while (ok) {
    ssize_t n = read(fd, b, sizeof b);
    if (n < 0 && errno == EINTR)
      continue;
    if (n < 0) {
      ok = false;
      break;
    }
    if (!n)
      break;
    total += (size_t)n;
    if (total > limit) {
      ok = false;
      break;
    }
    gs_bld_append(out, b, n);
  }
  close(fd);
  return ok;
}
bool honk_read(hs s, gs_rref out) { return read_bounded(s, out, HCAP); }

static bool write_atomic(hs s, hs data, bool executable, bool exclusive,
                         bool durable) {
  char p[HPATH], t[HPATH];
  if (!path(s, p) || snprintf(t, sizeof t, "%s.tmp-XXXXXX", p) >= (int)sizeof t)
    return false;
  struct stat st;
  bool exists = lstat(p, &st) == 0;
  if (exists && !S_ISREG(st.st_mode))
    return false;
  mode_t mode = executable ? 0755 : exists ? st.st_mode & 0777 : 0600;
  int fd = mkstemp(t);
  if (fd < 0)
    return false;
  bool ok = fchmod(fd, mode) == 0;
  size_t off = 0;
  while (ok && off < (size_t)data.len) {
    ssize_t n = write(fd, data.data + off, (size_t)data.len - off);
    if (n < 0 && errno == EINTR)
      continue;
    if (n <= 0) {
      ok = false;
      break;
    }
    off += (size_t)n;
  }
  if (ok && durable)
    ok = fsync(fd) == 0;
  if (close(fd) < 0)
    ok = false;
  if (ok) {
    if (exclusive)
      ok = link(t, p) == 0;
    else
      ok = rename(t, p) == 0;
  }
  unlink(t);
  return ok;
}
bool honk_write(hs s, hs data, bool executable, bool exclusive) {
  return write_atomic(s, data, executable, exclusive, true);
}
bool honk_write_scratch(hs s, hs data) {
  return write_atomic(s, data, false, false, false);
}
int64_t honk_lock(hs s) {
  char p[HPATH];
  if (!path(s, p))
    return -1;
  int fd = open(p, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0600);
  if (fd < 0)
    return -1;
  if (fd <= STDERR_FILENO) {
    int moved = fcntl(fd, F_DUPFD_CLOEXEC, STDERR_FILENO + 1);
    close(fd);
    fd = moved;
    if (fd < 0)
      return -1;
  }
  struct stat st;
  if (fstat(fd, &st) < 0 || !S_ISREG(st.st_mode) ||
      flock(fd, LOCK_EX | LOCK_NB) < 0) {
    close(fd);
    return -1;
  }
  return fd;
}
void honk_unlock(int64_t fd) {
  if (fd >= 0)
    close((int)fd);
}
// A synchronous runner retains its project/cache locks until the direct child
// has exited. Block cancellation across fork so a signal cannot land before the
// child PID is registered.
static volatile sig_atomic_t waiting_child = 0;
static volatile sig_atomic_t interrupted = 0;
typedef struct {
  struct sigaction old_int, old_term;
  sigset_t mask, blocked;
} signal_guard;
static void forward_signal(int number) {
  int saved = errno;
  interrupted = number;
  if (waiting_child > 0)
    kill((pid_t)waiting_child, number);
  errno = saved;
}
static bool guard_begin(signal_guard *guard) {
  sigemptyset(&guard->blocked);
  sigaddset(&guard->blocked, SIGINT);
  sigaddset(&guard->blocked, SIGTERM);
  if (sigprocmask(SIG_BLOCK, &guard->blocked, &guard->mask) < 0)
    return false;
  if (sigaction(SIGINT, NULL, &guard->old_int) < 0 ||
      sigaction(SIGTERM, NULL, &guard->old_term) < 0) {
    sigprocmask(SIG_SETMASK, &guard->mask, NULL);
    return false;
  }
  struct sigaction action;
  memset(&action, 0, sizeof action);
  sigemptyset(&action.sa_mask);
  action.sa_handler = forward_signal;
  if (sigaction(SIGINT, &action, NULL) < 0) {
    sigprocmask(SIG_SETMASK, &guard->mask, NULL);
    return false;
  }
  if (sigaction(SIGTERM, &action, NULL) < 0) {
    sigaction(SIGINT, &guard->old_int, NULL);
    sigprocmask(SIG_SETMASK, &guard->mask, NULL);
    return false;
  }
  waiting_child = 0;
  interrupted = 0;
  return true;
}
static int guard_end(signal_guard *guard) {
  waiting_child = 0;
  sigprocmask(SIG_BLOCK, &guard->blocked, NULL);
  int received = interrupted;
  sigaction(SIGINT, &guard->old_int, NULL);
  sigaction(SIGTERM, &guard->old_term, NULL);
  sigprocmask(SIG_SETMASK, &guard->mask, NULL);
  return received;
}
// packed argv consists of nonempty NUL-terminated arguments. User empty args
// are supported.
int64_t honk_spawn(hs packed, hs cwd, bool capture, gs_rref out) {
  char dir[HPATH];
  if (!path(cwd, dir) || packed.len < 2 || packed.len > HCAP ||
      packed.data[packed.len - 1] != 0)
    return 125;
  size_t count = 0;
  for (int64_t i = 0; i < packed.len; i++)
    if (!packed.data[i])
      count++;
  if (count > 4096 || packed.data[0] == 0)
    return 125;
  char *buf = malloc((size_t)packed.len);
  char **argv = calloc(count + 1, sizeof *argv);
  if (!buf || !argv) {
    free(buf);
    free(argv);
    return 125;
  }
  memcpy(buf, packed.data, (size_t)packed.len);
  size_t k = 0;
  argv[k++] = buf;
  for (int64_t i = 0; i < packed.len - 1; i++)
    if (!buf[i])
      argv[k++] = buf + i + 1;
  int fds[2] = {-1, -1};
  if (capture && pipe(fds) < 0) {
    free(buf);
    free(argv);
    return 125;
  }
  if (capture) {
    if (fcntl(fds[0], F_SETFD, FD_CLOEXEC) < 0 ||
        fcntl(fds[1], F_SETFD, FD_CLOEXEC) < 0) {
      close(fds[0]);
      close(fds[1]);
      free(buf);
      free(argv);
      return 125;
    }
  }
  signal_guard guard;
  if (!guard_begin(&guard)) {
    if (capture) {
      close(fds[0]);
      close(fds[1]);
    }
    free(buf);
    free(argv);
    return 125;
  }
  pid_t pid = fork();
  if (pid < 0) {
    guard_end(&guard);
    if (capture) {
      close(fds[0]);
      close(fds[1]);
    }
    free(buf);
    free(argv);
    return 125;
  }
  if (pid == 0) {
    guard_end(&guard);
    if (chdir(dir) < 0)
      _exit(125);
    if (capture) {
      close(fds[0]);
      if (fds[1] != STDOUT_FILENO) {
        if (dup2(fds[1], STDOUT_FILENO) < 0)
          _exit(125);
        close(fds[1]);
      } else if (fcntl(STDOUT_FILENO, F_SETFD, 0) < 0) {
        _exit(125);
      }
    }
    // Disable implicit Git configuration, interactive prompts, and repository
    // hooks.
    if (strcmp(argv[0], "git") == 0) {
      if (setenv("GIT_CONFIG_NOSYSTEM", "1", 1) ||
          setenv("GIT_CONFIG_GLOBAL", "/dev/null", 1) ||
          setenv("GIT_TERMINAL_PROMPT", "0", 1) ||
          setenv("GIT_ALLOW_PROTOCOL", "https", 1))
        _exit(125);
      const char *context[] = {"GIT_TEMPLATE_DIR",
                               "GIT_DIR",
                               "GIT_WORK_TREE",
                               "GIT_COMMON_DIR",
                               "GIT_INDEX_FILE",
                               "GIT_OBJECT_DIRECTORY",
                               "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                               "GIT_NAMESPACE",
                               "GIT_SHALLOW_FILE",
                               "GIT_CONFIG_COUNT",
                               "GIT_CONFIG_PARAMETERS",
                               "GIT_CONFIG",
                               "GIT_REPLACE_REF_BASE"};
      for (size_t i = 0; i < sizeof context / sizeof context[0]; i++)
        if (unsetenv(context[i]))
          _exit(125);
    }
    // Archive options are application policy, not inherited executable hooks or
    // compressor flags.
    if (strcmp(argv[0], "tar") == 0) {
      if (unsetenv("TAR_OPTIONS") || unsetenv("GZIP"))
        _exit(125);
    }
    execvp(argv[0], argv);
    _exit(errno == ENOENT ? 127 : 126);
  }
  waiting_child = (sig_atomic_t)pid;
  sigprocmask(SIG_SETMASK, &guard.mask, NULL);
  free(buf);
  free(argv);
  bool overflow = false;
  if (capture) {
    close(fds[1]);
    char b[16384];
    size_t total = 0;
    for (;;) {
      ssize_t n = read(fds[0], b, sizeof b);
      if (n < 0 && errno == EINTR)
        continue;
      if (n < 0) {
        overflow = true;
        kill(pid, SIGKILL);
        break;
      }
      if (!n)
        break;
      total += (size_t)n;
      if (total > HCAP) {
        overflow = true;
        kill(pid, SIGKILL);
        break;
      }
      gs_bld_append(out, b, n);
    }
    close(fds[0]);
  }
  // Observe completion without reaping first. A zombie reserves its PID until
  // cancellation is blocked, preventing a handler from signalling a reused PID.
  siginfo_t completion;
  while (waitid(P_PID, (id_t)pid, &completion, WEXITED | WNOWAIT) < 0) {
    if (errno != EINTR) {
      guard_end(&guard);
      return 125;
    }
  }
  sigprocmask(SIG_BLOCK, &guard.blocked, NULL);
  waiting_child = 0;
  int status;
  while (waitpid(pid, &status, 0) < 0) {
    if (errno != EINTR) {
      guard_end(&guard);
      return 125;
    }
  }
  int cancellation = guard_end(&guard);
  if (cancellation)
    return 128 + cancellation;
  if (overflow)
    return 125;
  return WIFEXITED(status)     ? WEXITSTATUS(status)
         : WIFSIGNALED(status) ? 128 + WTERMSIG(status)
                               : 125;
}
// Tree walks use descriptors and never follow source or destination symlinks.
// Resource caps bound work even for unexpectedly large dependency trees.
static bool skip(const char *n) {
  return !strcmp(n, ".git") || !strcmp(n, "target") || !strcmp(n, ".honk") ||
         !strcmp(n, ".toolchain") || !strcmp(n, ".build");
}
static bool copy_regular(int srcdir, int dstdir, const char *name,
                         uint64_t *bytes) {
  int src =
      openat(srcdir, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
  if (src < 0)
    return false;
  struct stat st;
  bool ok = fstat(src, &st) == 0 && S_ISREG(st.st_mode) && st.st_size >= 0 &&
            (uint64_t)st.st_size <= 268435456 - *bytes;
  if (!ok) {
    close(src);
    return false;
  }
  *bytes += (uint64_t)st.st_size;
  int dst =
      openat(dstdir, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC,
             st.st_mode & 0111 ? 0755 : 0644);
  if (dst < 0) {
    close(src);
    return false;
  }
  // Staging parents are private. Normalize archived modes independently of
  // caller umask.
  ok = fchmod(dst, st.st_mode & 0111 ? 0755 : 0644) == 0;
  char buf[65536];
  uint64_t actual = 0;
#if defined(__linux__) && !defined(HONK_PORTABLE_COPY)
  // Large files can use kernel-assisted copying, including CoW on supporting
  // filesystems. Both paths retain the same descriptor, file-type,
  // logical-byte, and exact-length checks.
  if (ok && (uint64_t)st.st_size >= sizeof buf) {
    while (actual < (uint64_t)st.st_size) {
      ssize_t count = copy_file_range(
          src, NULL, dst, NULL, (size_t)((uint64_t)st.st_size - actual), 0);
      if (count < 0 && errno == EINTR)
        continue;
      if (count < 0) {
        if (errno != EXDEV && errno != ENOSYS && errno != EOPNOTSUPP &&
            errno != EINVAL && errno != EPERM)
          ok = false;
        break;
      }
      if (!count)
        break;
      actual += (uint64_t)count;
    }
  }
#endif

  while (ok) {
    ssize_t count = read(src, buf, sizeof buf);
    if (count < 0 && errno == EINTR)
      continue;
    if (count < 0) {
      ok = false;
      break;
    }
    if (!count)
      break;
    actual += (uint64_t)count;
    if (actual > (uint64_t)st.st_size) {
      ok = false;
      break;
    }
    ssize_t offset = 0;
    while (offset < count) {
      ssize_t written = write(dst, buf + offset, (size_t)(count - offset));
      if (written < 0 && errno == EINTR)
        continue;
      if (written <= 0) {
        ok = false;
        break;
      }
      offset += written;
    }
  }
  ok = ok && actual == (uint64_t)st.st_size;
  close(src);
  if (close(dst) < 0)
    ok = false;
  return ok;
}
// Copy a caller-validated NUL-delimited file set without traversing symlinks.
// Each path is checked again at the native boundary and walked relative to held
// descriptors.
static int relative_directory(int base, char *relative, bool create) {
  int current = fcntl(base, F_DUPFD_CLOEXEC, 0);
  if (current < 0)
    return -1;
  if (!*relative)
    return current;
  char *part = relative;
  unsigned depth = 0;
  for (;;) {
    char *slash = strchr(part, '/');
    if (slash)
      *slash = 0;
    if (!*part || !strcmp(part, ".") || !strcmp(part, "..") || ++depth > 64) {
      close(current);
      return -1;
    }
    if (create && mkdirat(current, part, 0700) < 0 && errno != EEXIST) {
      close(current);
      return -1;
    }
    int next =
        openat(current, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    close(current);
    if (next < 0)
      return -1;
    current = next;
    if (!slash)
      return current;
    *slash = '/';
    part = slash + 1;
  }
}
bool honk_directory(hs base, hs relative) {
  char p[HPATH], q[HPATH];
  if (!path(base, p) || !path(relative, q) || q[0] == '/')
    return false;
  int root = open(p, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (root < 0)
    return false;
  int directory = relative_directory(root, q, false);
  close(root);
  if (directory < 0)
    return false;
  close(directory);
  return true;
}
static bool copy_selected_path(int source, int destination, char *path,
                               uint64_t *bytes) {
  char *name = strrchr(path, '/');
  char *parents = path;
  if (name) {
    *name = 0;
    name++;
  } else {
    name = path;
    parents = "";
  }
  if (!*name || !strcmp(name, ".") || !strcmp(name, ".."))
    return false;
  int src = relative_directory(source, parents, false);
  if (src < 0)
    return false;
  int dst = relative_directory(destination, parents, true);
  bool ok = dst >= 0 && copy_regular(src, dst, name, bytes);
  close(src);
  if (dst >= 0)
    close(dst);
  return ok;
}

bool honk_copy_files(hs from, hs to, hs packed) {
  char p[HPATH], q[HPATH];
  if (!path(from, p) || !path(to, q) || packed.len < 1 || packed.len > HCAP ||
      packed.data[packed.len - 1] != 0)
    return false;
  int src = open(p, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  int dst = open(q, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (src < 0 || dst < 0) {
    if (src >= 0)
      close(src);
    if (dst >= 0)
      close(dst);
    return false;
  }
  bool ok = true;
  uint64_t bytes = 0;
  size_t files = 0, start = 0;
  for (size_t i = 0; ok && i < (size_t)packed.len; i++) {
    if (packed.data[i])
      continue;
    hs entry = {packed.data + start, (int64_t)(i - start)};
    char relative[HPATH];
    ok = ++files <= 100000 && path(entry, relative) && relative[0] != '/' &&
         copy_selected_path(src, dst, relative, &bytes);
    start = i + 1;
  }
  close(src);
  close(dst);
  return ok;
}
static bool tree_copy(int src, int dst, size_t *files, uint64_t *bytes,
                      int depth) {
  if (depth > 64)
    return false;
  int duplicate = fcntl(src, F_DUPFD_CLOEXEC, 0);
  if (duplicate < 0)
    return false;
  DIR *d = fdopendir(duplicate);
  if (!d) {
    close(duplicate);
    return false;
  }
  bool ok = true;
  struct dirent *e;
  while (ok && (e = read_entry(d, &ok))) {
    const char *n = e->d_name;
    if (!strcmp(n, ".") || !strcmp(n, "..") || skip(n))
      continue;
    if (++*files > 100000 || strchr(n, '\n') || strchr(n, '\r')) {
      ok = false;
      break;
    }
    struct stat st;
    if (fstatat(src, n, &st, AT_SYMLINK_NOFOLLOW) < 0) {
      ok = false;
      break;
    }
    if (S_ISDIR(st.st_mode)) {
      if (mkdirat(dst, n, 0700) < 0 && errno != EEXIST) {
        ok = false;
        break;
      }
      int a = openat(src, n, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC),
          b = openat(dst, n, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
      ok = a >= 0 && b >= 0 && tree_copy(a, b, files, bytes, depth + 1);
      if (a >= 0)
        close(a);
      if (b >= 0)
        close(b);
    } else if (S_ISREG(st.st_mode)) {
      ok = copy_regular(src, dst, n, bytes);
    } else
      ok = false;
  }
  closedir(d);
  return ok;
}
bool honk_copy(hs from, hs to) {
  char p[HPATH], q[HPATH];
  if (!path(from, p) || !path(to, q))
    return false;
  int a = open(p, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC),
      b = open(q, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  size_t files = 0;
  uint64_t bytes = 0;
  bool ok = a >= 0 && b >= 0 && tree_copy(a, b, &files, &bytes, 0);
  if (a >= 0)
    close(a);
  if (b >= 0)
    close(b);
  return ok;
}
static bool remove_at(int parent, const char *name, int depth) {
  // Source depth is 64; private staging/package verification adds wrappers and
  // a final regular-file level. Cleanup must accept every tree we can create.
  if (depth > 80)
    return false;
  struct stat st;
  if (fstatat(parent, name, &st, AT_SYMLINK_NOFOLLOW) < 0)
    return errno == ENOENT;
  if (!S_ISDIR(st.st_mode))
    return unlinkat(parent, name, 0) == 0;
  int fd =
      openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (fd < 0)
    return false;
  DIR *d = fdopendir(fd);
  if (!d) {
    close(fd);
    return false;
  }
  bool ok = true;
  struct dirent *e;
  while (ok && (e = read_entry(d, &ok))) {
    if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, ".."))
      continue;
    ok = remove_at(fd, e->d_name, depth + 1);
  }
  closedir(d);
  return ok && unlinkat(parent, name, AT_REMOVEDIR) == 0;
}
// User-selected installation prefixes may contain . or .., but no component may
// be a symlink.
static int directory_path(const char *path) {
  char components[HPATH];
  size_t length = strlen(path);
  if (length >= sizeof components)
    return -1;
  memcpy(components, path, length + 1);
  int directory =
      open(path[0] == '/' ? "/" : ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  if (directory < 0)
    return -1;
  char *part = components;
  for (;;) {
    char *slash = strchr(part, '/');
    if (slash)
      *slash = 0;
    if (*part && strcmp(part, ".")) {
      int next = openat(directory, part,
                        O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
      close(directory);
      if (next < 0)
        return -1;
      directory = next;
    }
    if (!slash)
      return directory;
    part = slash + 1;
  }
}
bool honk_unlink_regular(hs input) {
  char pathbuf[HPATH];
  if (!path(input, pathbuf))
    return false;
  char *name = strrchr(pathbuf, '/');
  char *parent = pathbuf;
  if (name) {
    *name = 0;
    name++;
    if (!*parent)
      parent = "/";
  } else {
    name = pathbuf;
    parent = ".";
  }
  if (!*name || !strcmp(name, ".") || !strcmp(name, ".."))
    return false;
  int directory = directory_path(parent);
  if (directory < 0)
    return false;
  struct stat st;
  bool ok = fstatat(directory, name, &st, AT_SYMLINK_NOFOLLOW) == 0 &&
            S_ISREG(st.st_mode) && unlinkat(directory, name, 0) == 0;
  close(directory);
  return ok;
}

bool honk_remove(hs s) {
  char p[HPATH];
  if (!path(s, p))
    return false;
  char *slash = strrchr(p, '/');
  if (!slash || slash == p || !slash[1] || !strcmp(slash + 1, ".") ||
      !strcmp(slash + 1, ".."))
    return false;
  *slash = 0;
  int fd = open(p, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (fd < 0)
    return errno == ENOENT;
  bool ok = remove_at(fd, slash + 1, 0);
  close(fd);
  return ok;
}

// Stream executable installation with bounded memory and atomic publication.
bool honk_install(hs from, hs to, bool force) {
  char p[HPATH], q[HPATH], temp[HPATH];
  if (!path(from, p) || !path(to, q) ||
      snprintf(temp, sizeof temp, "%s.tmp-XXXXXX", q) >= (int)sizeof temp)
    return false;
  struct stat st;
  if (lstat(q, &st) == 0 && !S_ISREG(st.st_mode))
    return false;
  int src = open(p, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
  if (src < 0)
    return false;
  bool ok = fstat(src, &st) == 0 && S_ISREG(st.st_mode) && st.st_size >= 0 &&
            st.st_size <= 268435456;
  int dst = ok ? mkstemp(temp) : -1;
  if (dst < 0) {
    close(src);
    return false;
  }
  char buf[65536];
  uint64_t total = 0;
  while (ok) {
    ssize_t n = read(src, buf, sizeof buf);
    if (n < 0 && errno == EINTR)
      continue;
    if (n < 0) {
      ok = false;
      break;
    }
    if (!n)
      break;
    total += (uint64_t)n;
    if (total > 268435456) {
      ok = false;
      break;
    }
    ssize_t offset = 0;
    while (offset < n) {
      ssize_t written = write(dst, buf + offset, (size_t)(n - offset));
      if (written < 0 && errno == EINTR)
        continue;
      if (written <= 0) {
        ok = false;
        break;
      }
      offset += written;
    }
  }
  close(src);
  if (ok)
    ok = fchmod(dst, 0755) == 0 && fsync(dst) == 0;
  if (close(dst) < 0)
    ok = false;
  if (ok)
    ok = force ? rename(temp, q) == 0 : link(temp, q) == 0;
  unlink(temp);
  return ok;
}

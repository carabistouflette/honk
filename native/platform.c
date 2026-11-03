// SPDX-License-Identifier: Apache-2.0
// POSIX operations missing from the pinned Goose standard library. No shell.
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

bool honk_write(hs s, hs data, bool executable, bool exclusive) {
  char p[HPATH], t[HPATH];
  if (!path(s, p) || snprintf(t, sizeof t, "%s.tmp-XXXXXX", p) >= (int)sizeof t)
    return false;
  struct stat st;
  if (lstat(p, &st) == 0 && !S_ISREG(st.st_mode))
    return false;
  int fd = mkstemp(t);
  if (fd < 0)
    return false;
  bool ok = fchmod(fd, executable ? 0755 : 0644) == 0;
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
  if (ok)
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
int64_t honk_lock(hs s) {
  char p[HPATH];
  if (!path(s, p))
    return -1;
  int fd = open(p, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0600);
  if (fd < 0)
    return -1;
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
    fcntl(fds[0], F_SETFD, FD_CLOEXEC);
    fcntl(fds[1], F_SETFD, FD_CLOEXEC);
  }
  pid_t pid = fork();
  if (pid < 0) {
    if (capture) {
      close(fds[0]);
      close(fds[1]);
    }
    free(buf);
    free(argv);
    return 125;
  }
  if (pid == 0) {
    if (chdir(dir) < 0)
      _exit(125);
    if (capture) {
      close(fds[0]);
      if (dup2(fds[1], STDOUT_FILENO) < 0)
        _exit(125);
      close(fds[1]);
    }
    // Disable implicit Git configuration, interactive prompts, and repository
    // hooks.
    if (strcmp(argv[0], "git") == 0) {
      setenv("GIT_CONFIG_NOSYSTEM", "1", 1);
      setenv("GIT_CONFIG_GLOBAL", "/dev/null", 1);
      setenv("GIT_TERMINAL_PROMPT", "0", 1);
      setenv("GIT_ALLOW_PROTOCOL", "https", 1);
      unsetenv("GIT_TEMPLATE_DIR");
      unsetenv("GIT_DIR");
      unsetenv("GIT_WORK_TREE");
      unsetenv("GIT_CONFIG_COUNT");
      unsetenv("GIT_CONFIG_PARAMETERS");
    }
    execvp(argv[0], argv);
    _exit(errno == ENOENT ? 127 : 126);
  }
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
      if (n <= 0)
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
  int status;
  while (waitpid(pid, &status, 0) < 0) {
    if (errno != EINTR)
      return 125;
  }
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
static bool tree_copy(int src, int dst, size_t *files, uint64_t *bytes,
                      int depth) {
  if (depth > 64)
    return false;
  DIR *d = fdopendir(dup(src));
  if (!d)
    return false;
  bool ok = true;
  struct dirent *e;
  errno = 0;
  while (ok && (e = readdir(d))) {
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
      if (st.st_size < 0 || (uint64_t)st.st_size > 268435456 - *bytes) {
        ok = false;
        break;
      }
      *bytes += (uint64_t)st.st_size;
      int a = openat(src, n, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
      int b =
          openat(dst, n, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC,
                 st.st_mode & 0111 ? 0755 : 0644);
      ok = a >= 0 && b >= 0;
      char buf[65536];
      uint64_t actual = 0;
      while (ok) {
        ssize_t nr = read(a, buf, sizeof buf);
        if (nr < 0 && errno == EINTR)
          continue;
        if (nr < 0) {
          ok = false;
          break;
        }
        if (!nr)
          break;
        actual += (uint64_t)nr;
        if (actual > (uint64_t)st.st_size) {
          ok = false;
          break;
        }
        ssize_t off = 0;
        while (off < nr) {
          ssize_t nw = write(b, buf + off, (size_t)(nr - off));
          if (nw < 0 && errno == EINTR)
            continue;
          if (nw <= 0) {
            ok = false;
            break;
          }
          off += nw;
        }
      }
      if (a >= 0)
        close(a);
      if (b >= 0 && close(b) < 0)
        ok = false;
    } else
      ok = false;
    errno = 0;
  }
  if (errno)
    ok = false;
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
  if (depth > 64)
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
  errno = 0;
  while (ok && (e = readdir(d))) {
    if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, ".."))
      continue;
    ok = remove_at(fd, e->d_name, depth + 1);
    errno = 0;
  }
  if (errno)
    ok = false;
  closedir(d);
  return ok && unlinkat(parent, name, AT_REMOVEDIR) == 0;
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

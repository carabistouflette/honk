// SPDX-License-Identifier: Apache-2.0
// Linux/POSIX cache adapter. No shell, hooks, build scripts, or credential forwarding.
#include <archive.h>
#include <archive_entry.h>
#include <curl/curl.h>
#include <openssl/evp.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct { const uint8_t *data; int64_t len; } input;
typedef struct { uint8_t *data; int64_t len; } output;
#define PATH_CAP 4096
#define INDEX_CAP (1024 * 1024)
#define ARCHIVE_CAP (16 * 1024 * 1024)
#define TREE_CAP (64 * 1024 * 1024)
static char failure[256];
static bool fail(const char *message) { snprintf(failure, sizeof failure, "%s", message); return false; }
int64_t nest_error(output out) {
    size_t n = strlen(failure);
    if (out.len < 0 || n > (size_t)out.len) return -1;
    memcpy(out.data, failure, n); return (int64_t)n;
}
static bool string(input s, char *out, size_t cap) {
    if (s.len <= 0 || (uint64_t)s.len >= cap || !s.data) return fail("invalid or oversized native argument");
    for (int64_t i = 0; i < s.len; ++i) if (s.data[i] < 32 || s.data[i] == 127) return fail("control byte in native argument");
    memcpy(out, s.data, (size_t)s.len); out[s.len] = 0; return true;
}
static bool join(char *out, const char *a, const char *b) {
    if (snprintf(out, PATH_CAP, "%s/%s", a, b) >= PATH_CAP) return fail("cache path too long");
    return true;
}
static bool regular(const char *path, size_t cap) {
    struct stat st;
    return lstat(path, &st) == 0 && S_ISREG(st.st_mode) && st.st_uid == getuid() &&
        st.st_nlink == 1 && !(st.st_mode & 0022) && st.st_size >= 0 && (uint64_t)st.st_size <= cap;
}
static bool directory(const char *path) {
    struct stat st;
    return lstat(path, &st) == 0 && S_ISDIR(st.st_mode) && st.st_uid == getuid() && !(st.st_mode & 0022);
}
static bool directories(const char *path) {
    char copy[PATH_CAP];
    if (path[0] != '/' || strlen(path) >= sizeof copy) return fail("cache must be an absolute path");
    strcpy(copy, path);
    for (char *p = copy + 1; ; ++p) {
        if (*p && *p != '/') continue;
        char saved = *p; *p = 0;
        const char *component = strrchr(copy, '/'); component = component ? component + 1 : copy;
        if (!*component || !strcmp(component, ".") || !strcmp(component, "..")) return fail("noncanonical cache path");
        struct stat st;
        if (lstat(copy, &st) != 0) { if (errno != ENOENT || (mkdir(copy, 0700) != 0 && errno != EEXIST) || lstat(copy, &st) != 0 || !S_ISDIR(st.st_mode)) return fail("cannot create cache directory"); }
        else if (!S_ISDIR(st.st_mode)) return fail("cache ancestor is not a real directory");
        *p = saved; if (!saved) break;
    }
    return directory(path) || fail("cache directory must be owned and non-writable by other users");
}
static int cache_lock(const char *cache) {
    char path[PATH_CAP]; if (!directories(cache) || !join(path, cache, "lock")) return -1;
    int fd = open(path, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0 || !regular(path, 0) || flock(fd, LOCK_EX) != 0) { if (fd >= 0) close(fd); fail("cannot lock private registry cache"); return -1; }
    return fd;
}
static void hex(const unsigned char *bytes, size_t n, char *out) {
    for (size_t i = 0; i < n; ++i) { out[2*i] = "0123456789abcdef"[bytes[i] >> 4]; out[2*i+1] = "0123456789abcdef"[bytes[i] & 15]; } out[2*n] = 0;
}
static bool digest(const void *data, size_t n, char *out) {
    unsigned char value[32]; unsigned int size = 0;
    if (!EVP_Digest(data, n, value, &size, EVP_sha256(), NULL) || size != 32) return fail("SHA-256 failed");
    hex(value, 32, out); return true;
}
static int64_t read_file(const char *path, uint8_t *out, size_t cap) {
    if (!regular(path, cap)) { fail("missing, unsafe, or oversized cached file"); return -1; }
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC); if (fd < 0) { fail("cannot open cached file"); return -1; }
    size_t used = 0;
    while (used < cap) { ssize_t n = read(fd, out + used, cap - used); if (n < 0 && errno == EINTR) continue; if (n < 0) { close(fd); fail("cannot read cached file"); return -1; } if (!n) break; used += (size_t)n; }
    uint8_t extra; ssize_t tail = read(fd, &extra, 1); int closed = close(fd);
    if (tail != 0 || closed != 0) { fail("cached file changed or exceeded limit"); return -1; } return (int64_t)used;
}
static bool write_file(const char *path, const void *data, size_t n) {
    char tmp[PATH_CAP]; if (snprintf(tmp, sizeof tmp, "%s.tmp.XXXXXX", path) >= (int)sizeof tmp) return fail("temporary path too long");
    int fd = mkstemp(tmp); if (fd < 0) return fail("cannot create temporary cache file");
    size_t at = 0; bool ok = true;
    while (at < n) { ssize_t k = write(fd, (const uint8_t *)data + at, n - at); if (k < 0 && errno == EINTR) continue; if (k <= 0) { ok = false; break; } at += (size_t)k; }
    if (fsync(fd) != 0) ok = false;
    if (close(fd) != 0) ok = false;
    if (ok && rename(tmp, path) != 0) ok = false;
    if (!ok) { unlink(tmp); return fail("cannot publish cache file"); } return true;
}
typedef struct { uint8_t *data; size_t used, cap, header_bytes; char etag[256]; } transfer;
static size_t body(char *p, size_t a, size_t b, void *opaque) {
    transfer *t = opaque; if (a && b > SIZE_MAX / a) return 0; size_t n = a*b;
    if (n > t->cap - t->used) return 0;
    memcpy(t->data + t->used, p, n); t->used += n; return n;
}
static size_t headers(char *p, size_t a, size_t b, void *opaque) {
    transfer *t = opaque; if (a && b > SIZE_MAX / a) return 0; size_t n = a*b;
    if (n > 65536 - t->header_bytes) return 0;
    t->header_bytes += n;
    if (n >= 5 && !strncasecmp(p, "HTTP/", 5)) t->etag[0] = 0;
    if (n > 5 && !strncasecmp(p, "etag:", 5)) {
        size_t start = 5, end = n; while (start < end && (p[start] == ' ' || p[start] == '\t')) ++start;
        while (end > start && (p[end-1] == '\r' || p[end-1] == '\n')) --end;
        if (end-start < sizeof t->etag) {
            for (size_t i = start; i < end; ++i) if ((unsigned char)p[i] < 32 || p[i] == 127) return 0;
            memcpy(t->etag, p+start, end-start); t->etag[end-start] = 0;
        }
    }
    return n;
}
static bool url_allowed(const char *url) {
    // Cleartext is restricted to explicit IPv4 loopback fixtures, never enabled by an environment variable.
    return !strncmp(url, "https://", 8) || !strncmp(url, "http://127.0.0.1:", 17);
}
static bool fetch_options(CURL *c, const char *url, transfer *t, struct curl_slist *request_headers) {
    if (!url_allowed(url) || strchr(url, '@') || strchr(url, '#')) return fail("registry URLs require HTTPS without credentials or fragments");
    bool loopback = !strncmp(url, "http://127.0.0.1:", 17);
#define SET(k,v) do { if (curl_easy_setopt(c, k, v) != CURLE_OK) return fail("unsupported HTTP option"); } while (0)
    SET(CURLOPT_URL, url); SET(CURLOPT_PROTOCOLS_STR, loopback ? "http" : "https");
    SET(CURLOPT_REDIR_PROTOCOLS_STR, loopback ? "http" : "https");
    SET(CURLOPT_FOLLOWLOCATION, loopback ? 0L : 1L); SET(CURLOPT_MAXREDIRS, 5L);
    SET(CURLOPT_PROXY, ""); SET(CURLOPT_NETRC, CURL_NETRC_IGNORED);
    SET(CURLOPT_SSL_VERIFYPEER, 1L); SET(CURLOPT_SSL_VERIFYHOST, 2L);
    SET(CURLOPT_NOSIGNAL, 1L); SET(CURLOPT_CONNECTTIMEOUT_MS, 10000L); SET(CURLOPT_TIMEOUT_MS, 60000L);
    SET(CURLOPT_WRITEFUNCTION, body); SET(CURLOPT_WRITEDATA, t);
    SET(CURLOPT_HEADERFUNCTION, headers); SET(CURLOPT_HEADERDATA, t);
    SET(CURLOPT_HTTPHEADER, request_headers); SET(CURLOPT_ACCEPT_ENCODING, "identity");
    SET(CURLOPT_USERAGENT, "goose-nest/0.1.0-alpha.1");
#undef SET
    return true;
}
static bool fetch_result(CURL *c, CURLcode code, long *status) {
    if (code != CURLE_OK || curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, status) != CURLE_OK)
        return fail("HTTP transfer failed, timed out, or exceeded resource limits");
    return (*status == 200 || *status == 304) || fail("HTTP server returned an unexpected status");
}
static bool init_http(void) {
    static bool initialized;
    if (!initialized) {
        if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) return fail("cannot initialize TLS");
        initialized = true;
    }
    return true;
}
static bool fetch(const char *url, const char *etag, transfer *t, long *status) {
    static CURL *connection;
    if (!init_http()) return false;
    if (!connection) connection = curl_easy_init();
    if (!connection) return fail("cannot initialize HTTP connection");
    curl_easy_reset(connection);
    struct curl_slist *request_headers = NULL;
    char conditional[300];
    if (etag && *etag) { snprintf(conditional, sizeof conditional, "If-None-Match: %s", etag); request_headers = curl_slist_append(NULL, conditional); if (!request_headers) return fail("cannot allocate conditional header"); }
    bool ok = fetch_options(connection, url, t, request_headers)
        && fetch_result(connection, curl_easy_perform(connection), status);
    curl_slist_free_all(request_headers);
    return ok;
}
int64_t nest_index(input registry_in, input name_in, input cache_in, bool offline, bool refresh, output out) {
    char registry[PATH_CAP], name[65], cache[PATH_CAP], url[PATH_CAP], key[65], path[PATH_CAP], tag_path[PATH_CAP];
    if (!string(registry_in, registry, sizeof registry) || !string(name_in, name, sizeof name) || !string(cache_in, cache, sizeof cache) || out.len < INDEX_CAP) return -1;
    if (snprintf(url, sizeof url, "%s/%s.toml", registry, name) >= (int)sizeof url || !digest(url, strlen(url), key)) return -1;
    int lock = cache_lock(cache); if (lock < 0) return -1;
    int64_t result = -1;
    if (!join(path, cache, key) || snprintf(tag_path, sizeof tag_path, "%s.etag", path) >= (int)sizeof tag_path) goto done;
    if (!refresh && regular(path, INDEX_CAP)) { result = read_file(path, out.data, INDEX_CAP); goto done; }
    if (offline) { fail("registry index is not cached; offline mode forbids network access"); goto done; }
    char etag[256] = {0};
    if (regular(path, INDEX_CAP) && regular(tag_path, 255)) { int64_t n = read_file(tag_path, (uint8_t *)etag, 255); if (n < 0) goto done; etag[n] = 0; for (int64_t i = 0; i < n; ++i) if ((unsigned char)etag[i] < 32 || etag[i] == 127) { fail("invalid cached ETag"); goto done; } }
    transfer t = {.data=out.data, .cap=INDEX_CAP}; long status = 0;
    if (!fetch(url, etag, &t, &status)) goto done;
    if (status == 304) { result = read_file(path, out.data, INDEX_CAP); goto done; }
    if (!write_file(path, out.data, t.used) || !write_file(tag_path, t.etag, strlen(t.etag))) goto done;
    result = (int64_t)t.used;
done: close(lock); return result;
}
// Content verification uses sorted directory entries and length-delimited names.
// No file is trusted merely because its size/mtime matches a previous invocation.
static bool tree(EVP_MD_CTX *ctx, const char *path, size_t *bytes, size_t *files, int depth) {
    if (depth > 32 || !directory(path)) return fail("unsafe or deep source tree");
    struct dirent **names = NULL; int count = scandir(path, &names, NULL, alphasort); if (count < 0) return fail("cannot enumerate source tree");
    bool ok = true;
    for (int i = 0; i < count; ++i) {
        const char *name = names[i]->d_name;
        if (!strcmp(name, ".") || !strcmp(name, "..")) { free(names[i]); continue; }
        char child[PATH_CAP]; struct stat st;
        if (!join(child, path, name) || lstat(child, &st) != 0 || ++*files > 4096) ok = false;
        if (ok) {
            uint64_t length = strlen(name); unsigned char kind = S_ISDIR(st.st_mode) ? 'd' : 'f';
            if (!EVP_DigestUpdate(ctx, &kind, 1) || !EVP_DigestUpdate(ctx, &length, sizeof length) || !EVP_DigestUpdate(ctx, name, (size_t)length)) ok = false;
            if (ok && S_ISDIR(st.st_mode)) ok = tree(ctx, child, bytes, files, depth + 1);
            else if (ok) {
                if (!regular(child, INDEX_CAP) || *bytes > TREE_CAP - (size_t)st.st_size) ok = false;
                else {
                    *bytes += (size_t)st.st_size;
                    uint8_t *buffer = malloc(INDEX_CAP); int64_t n = buffer ? read_file(child, buffer, INDEX_CAP) : -1;
                    uint64_t size = n < 0 ? 0 : (uint64_t)n; unsigned int executable = (st.st_mode & 0111) ? 1 : 0;
                    if (n < 0 || !EVP_DigestUpdate(ctx, &size, sizeof size) || !EVP_DigestUpdate(ctx, &executable, sizeof executable) || !EVP_DigestUpdate(ctx, buffer, (size_t)size)) ok = false;
                    free(buffer);
                }
            }
            unsigned char end = 'e'; if (ok && !EVP_DigestUpdate(ctx, &end, 1)) ok = false;
        }
        free(names[i]); if (!ok) { for (++i; i < count; ++i) free(names[i]); break; }
    }
    free(names); return ok || fail("source tree is corrupt, unsafe, or exceeds limits");
}
static bool tree_digest(const char *path, char *out) {
    EVP_MD_CTX *ctx = EVP_MD_CTX_new(); if (!ctx) return fail("cannot allocate SHA-256 context");
    size_t bytes = 0, files = 0; unsigned char hash[32]; unsigned int n = 0;
    bool ok = EVP_DigestInit_ex(ctx, EVP_sha256(), NULL) && tree(ctx, path, &bytes, &files, 0) && EVP_DigestFinal_ex(ctx, hash, &n) && n == 32;
    EVP_MD_CTX_free(ctx); if (ok) hex(hash, 32, out); return ok;
}
static bool safe_relative(const char *name) {
    if (!name || !*name || *name == '/' || strlen(name) > 1024) return false;
    const char *start = name;
    for (const char *p = name; ; ++p) {
        if (*p == '\\' || *p == ':' || (*p && ((unsigned char)*p < 32 || *p == 127))) return false;
        if (!*p || *p == '/') {
            size_t n = (size_t)(p-start); if (!n || (n == 1 && *start == '.') || (n == 2 && start[0] == '.' && start[1] == '.')) return false;
            if (!*p) return true;
            start = p+1;
        }
    }
}
static bool unpack(const uint8_t *data, size_t n, const char *target, const char *label) {
    struct archive *a = archive_read_new(); if (!a) return fail("cannot create archive reader");
    archive_read_support_filter_gzip(a); archive_read_support_format_tar(a);
    bool ok = archive_read_open_memory(a, data, n) == ARCHIVE_OK;
    size_t files = 0, total = 0; struct archive_entry *entry; int status = ARCHIVE_FATAL;
    while (ok && (status = archive_read_next_header(a, &entry)) == ARCHIVE_OK) {
        const char *name = archive_entry_pathname(entry); size_t prefix = strlen(label);
        if (!name || strncmp(name, label, prefix) || name[prefix] != '/' || archive_entry_symlink(entry) || archive_entry_hardlink(entry) || ++files > 4096) { ok = false; break; }
        const char *relative = name + prefix + 1;
        // Directory entries are unnecessary: parents are created from validated file paths.
        if (archive_entry_filetype(entry) == AE_IFDIR) { if (*relative && relative[strlen(relative)-1] == '/') { char *trimmed = strdup(relative); if (!trimmed) { ok = false; break; } trimmed[strlen(trimmed)-1] = 0; ok = safe_relative(trimmed); free(trimmed); } else if (*relative) ok = safe_relative(relative); continue; }
        int64_t size = archive_entry_size(entry);
        if (archive_entry_filetype(entry) != AE_IFREG || !safe_relative(relative) || size < 0 || size > INDEX_CAP || total > TREE_CAP - (size_t)size) { ok = false; break; }
        total += (size_t)size;
        char path[PATH_CAP]; if (!join(path, target, relative)) { ok = false; break; }
        char *slash = strrchr(path, '/'); *slash = 0; ok = directories(path); *slash = '/'; if (!ok) break;
        int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, archive_entry_perm(entry) & 0111 ? 0700 : 0600);
        if (fd < 0) { ok = false; break; }
        uint8_t buffer[32768]; int64_t used = 0;
        while (ok) {
            la_ssize_t k = archive_read_data(a, buffer, sizeof buffer); if (k < 0 || used + k > size) { ok = false; break; } if (!k) break;
            size_t at = 0; while (at < (size_t)k) { ssize_t w = write(fd, buffer+at, (size_t)k-at); if (w < 0 && errno == EINTR) continue; if (w <= 0) { ok = false; break; } at += (size_t)w; } used += k;
        }
        int close_status = close(fd); if (used != size || close_status != 0) ok = false;
    }
    if (status != ARCHIVE_EOF) ok = false;
    archive_read_free(a); return ok || fail("archive rejected: invalid paths, links, duplicate files, truncation, or limits");
}
static void remove_private(const char *path) {
    DIR *d = opendir(path); if (!d) return;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        char child[PATH_CAP]; struct stat st;
        if (!join(child, path, e->d_name) || lstat(child, &st)) continue;
        if (S_ISDIR(st.st_mode)) remove_private(child); else unlink(child);
    }
    closedir(d); rmdir(path);
}
static bool valid_sha(const char *sha) {
    return strlen(sha) == 64 && strspn(sha, "0123456789abcdef") == 64;
}

#define PREFETCH_WIDTH 4
typedef struct {
    char sha[65], url[PATH_CAP], blob[PATH_CAP];
    transfer data;
    CURL *easy;
    CURLcode result;
    bool active;
} archive_job;

static bool prefetch_group(CURLM *multi, archive_job *jobs, size_t count) {
    bool ok = false;
    for (size_t i = 0; i < count; ++i) {
        archive_job *job = &jobs[i];
        job->data = (transfer){.data = malloc(ARCHIVE_CAP), .cap = ARCHIVE_CAP};
        job->easy = curl_easy_init();
        if (!job->data.data || !job->easy) { fail("cannot allocate archive transfer"); goto done; }
        if (!fetch_options(job->easy, job->url, &job->data, NULL)) goto done;
        if (curl_multi_add_handle(multi, job->easy) != CURLM_OK) { fail("cannot queue archive transfer"); goto done; }
        job->active = true;
        job->result = CURLE_FAILED_INIT;
    }
    int running;
    do {
        if (curl_multi_perform(multi, &running) != CURLM_OK ||
            (running && curl_multi_poll(multi, NULL, 0, 1000, NULL) != CURLM_OK)) {
            fail("cannot run archive transfers");
            goto done;
        }
    } while (running);
    int left;
    for (CURLMsg *message; (message = curl_multi_info_read(multi, &left));) {
        if (message->msg != CURLMSG_DONE) continue;
        for (size_t i = 0; i < count; ++i)
            if (jobs[i].easy == message->easy_handle) jobs[i].result = message->data.result;
    }
    for (size_t i = 0; i < count; ++i) {
        archive_job *job = &jobs[i];
        long status;
        char actual[65];
        if (!fetch_result(job->easy, job->result, &status)) goto done;
        if (status != 200) { fail("archive server did not return a package"); goto done; }
        if (!digest(job->data.data, job->data.used, actual)) goto done;
        if (strcmp(actual, job->sha)) { fail("package archive SHA-256 mismatch"); goto done; }
        if (!write_file(job->blob, job->data.data, job->data.used)) goto done;
    }
    ok = true;
done:
    for (size_t i = 0; i < count; ++i) {
        if (jobs[i].active) curl_multi_remove_handle(multi, jobs[i].easy);
        if (jobs[i].easy) curl_easy_cleanup(jobs[i].easy);
        free(jobs[i].data.data);
        jobs[i] = (archive_job){0};
    }
    return ok;
}

// Offsets delimit records consisting of a 64-byte digest followed by the URL.
typedef struct { const int64_t *data; int64_t len; } offsets;
bool nest_prefetch(input records, offsets starts, input cache_in) {
    if (!records.data || !starts.data || starts.len < 2 || starts.len > 257 ||
        starts.data[0] != 0 || starts.data[starts.len - 1] != records.len)
        return fail("invalid archive transfer list");
    char cache[PATH_CAP];
    if (!string(cache_in, cache, sizeof cache)) return false;
    int lock = cache_lock(cache);
    if (lock < 0) return false;
    CURLM *multi = NULL;
    archive_job jobs[PREFETCH_WIDTH] = {0};
    size_t count = 0;
    bool ok = false;
    for (int64_t i = 1; i < starts.len; ++i) {
        int64_t start = starts.data[i - 1], end = starts.data[i];
        if (start < 0 || end > records.len || end <= start || end - start <= 64) {
            fail("invalid archive transfer record");
            goto done;
        }
        archive_job *job = &jobs[count];
        if (!string((input){records.data + start, 64}, job->sha, sizeof job->sha) ||
            !string((input){records.data + start + 64, end - start - 64}, job->url, sizeof job->url))
            goto done;
        if (!valid_sha(job->sha)) { fail("invalid SHA-256"); goto done; }
        char target[PATH_CAP];
        if (!join(target, cache, job->sha) ||
            snprintf(job->blob, sizeof job->blob, "%s.tar.gz", target) >= (int)sizeof job->blob) {
            fail("archive cache path too long");
            goto done;
        }
        if (directory(target) || regular(job->blob, ARCHIVE_CAP)) continue;
        bool queued = false;
        for (size_t j = 0; j < count; ++j) if (!strcmp(jobs[j].sha, job->sha)) queued = true;
        if (queued) continue;
        if (!multi) {
            if (!init_http()) goto done;
            multi = curl_multi_init();
            if (!multi) { fail("cannot initialize archive transfers"); goto done; }
        }
        if (++count == PREFETCH_WIDTH) {
            if (!prefetch_group(multi, jobs, count)) goto done;
            count = 0;
        }
    }
    ok = count == 0 || prefetch_group(multi, jobs, count);
done:
    if (multi) curl_multi_cleanup(multi);
    close(lock);
    return ok;
}

bool nest_materialize(input url_in, input sha_in, input label_in, input cache_in, bool offline) {
    char url[PATH_CAP], sha[65], label[160], cache[PATH_CAP], target[PATH_CAP], ready[PATH_CAP], blob[PATH_CAP];
    if (!string(url_in, url, sizeof url) || !string(sha_in, sha, sizeof sha) || !string(label_in, label, sizeof label) || !string(cache_in, cache, sizeof cache)) return false;
    if (!safe_relative(label) || strchr(label, '/')) return fail("invalid package label");
    if (!valid_sha(sha)) return fail("invalid SHA-256");
    int lock = cache_lock(cache); if (lock < 0) return false;
    bool ok = false; uint8_t *data = NULL; char temporary[PATH_CAP] = {0};
    if (!join(target, cache, sha) || snprintf(ready, sizeof ready, "%s.ready", target) >= (int)sizeof ready || snprintf(blob, sizeof blob, "%s.tar.gz", target) >= (int)sizeof blob) goto done;
    if (directory(target)) {
        char expected[65] = {0}, actual[65];
        if (read_file(ready, (uint8_t *)expected, 64) != 64 || !tree_digest(target, actual) || strcmp(actual, expected)) { fail("cached package content changed; remove this package cache entry and fetch again"); goto done; }
        ok = true; goto done;
    }
    data = malloc(ARCHIVE_CAP); if (!data) { fail("cannot allocate bounded archive buffer"); goto done; }
    int64_t size = -1;
    if (regular(blob, ARCHIVE_CAP)) size = read_file(blob, data, ARCHIVE_CAP);
    else {
        if (offline) { fail("package archive is not cached; offline mode forbids network access"); goto done; }
        transfer t = {.data=data, .cap=ARCHIVE_CAP}; long status = 0;
        if (!fetch(url, NULL, &t, &status) || status != 200) goto done;
        size = (int64_t)t.used;
    }
    char actual[65]; if (size < 0 || !digest(data, (size_t)size, actual) || strcmp(actual, sha)) { fail("package archive SHA-256 mismatch"); goto done; }
    if (!regular(blob, ARCHIVE_CAP) && !write_file(blob, data, (size_t)size)) goto done;
    if (snprintf(temporary, sizeof temporary, "%s.unpack.XXXXXX", target) >= (int)sizeof temporary || !mkdtemp(temporary)) { temporary[0] = 0; fail("cannot create package staging directory"); goto done; }
    if (!unpack(data, (size_t)size, temporary, label) || !tree_digest(temporary, actual)) goto done;
    if (rename(temporary, target) != 0) { fail("cannot publish package sources"); goto done; } temporary[0] = 0;
    if (!write_file(ready, actual, 64)) goto done;
    ok = true;
done:
    if (temporary[0]) remove_private(temporary);
    free(data); close(lock); return ok;
}

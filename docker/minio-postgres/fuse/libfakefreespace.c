/*
 * LD_PRELOAD helper: when the underlying filesystem reports suspiciously low
 * free space / inodes (typical for Docker Desktop bind-mounts of SMB/UNC
 * shares), override statfs/statvfs results with a large fake capacity.
 *
 * Effective for libc-based programs (PostgreSQL). Go binaries (MinIO) bypass
 * libc syscalls — use fakefreespace-mount (FUSE) for those.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>
#include <sys/statfs.h>
#include <sys/statvfs.h>

#ifndef FAKE_FREE_BYTES_DEFAULT
#define FAKE_FREE_BYTES_DEFAULT (10ULL * 1024ULL * 1024ULL * 1024ULL * 1024ULL) /* 10 TiB */
#endif

/* If reported free bytes are below this, treat as "broken network stats". */
#ifndef SUSPICIOUS_FREE_BYTES
#define SUSPICIOUS_FREE_BYTES (512ULL * 1024ULL * 1024ULL) /* 512 MiB */
#endif

static unsigned long long fake_free_bytes(void) {
    const char *env = getenv("FAKE_FREE_BYTES");
    if (env && *env) {
        char *end = NULL;
        unsigned long long v = strtoull(env, &end, 10);
        if (end != env && v > 0) {
            return v;
        }
    }
    return FAKE_FREE_BYTES_DEFAULT;
}

static int looks_broken_statvfs(const struct statvfs *buf) {
    if (buf->f_frsize == 0 || buf->f_bsize == 0) {
        return 1;
    }
    unsigned long long avail =
        (unsigned long long)buf->f_bavail * (unsigned long long)buf->f_frsize;
    if (avail < SUSPICIOUS_FREE_BYTES) {
        return 1;
    }
    /* Network mounts often report 0 inodes. */
    if (buf->f_files == 0 || buf->f_ffree == 0) {
        return 1;
    }
    return 0;
}

static int looks_broken_statfs(const struct statfs *buf) {
    unsigned long bsize = buf->f_frsize ? buf->f_frsize : buf->f_bsize;
    if (bsize == 0) {
        return 1;
    }
    unsigned long long avail =
        (unsigned long long)buf->f_bavail * (unsigned long long)bsize;
    if (avail < SUSPICIOUS_FREE_BYTES) {
        return 1;
    }
    if (buf->f_files == 0 || buf->f_ffree == 0) {
        return 1;
    }
    return 0;
}

static void patch_statvfs(struct statvfs *buf) {
    unsigned long long fake = fake_free_bytes();
    unsigned long frsize = buf->f_frsize ? buf->f_frsize : 4096;
    unsigned long long blocks = fake / frsize;
    if (blocks < 1024) {
        blocks = 1024;
    }
    buf->f_bsize = frsize;
    buf->f_frsize = frsize;
    buf->f_blocks = blocks;
    buf->f_bfree = blocks;
    buf->f_bavail = blocks;
    buf->f_files = 10000000;
    buf->f_ffree = 9990000;
    buf->f_favail = 9990000;
    buf->f_namemax = buf->f_namemax ? buf->f_namemax : 255;
}

static void patch_statfs(struct statfs *buf) {
    unsigned long long fake = fake_free_bytes();
    unsigned long bsize = buf->f_frsize ? buf->f_frsize : (buf->f_bsize ? buf->f_bsize : 4096);
    unsigned long long blocks = fake / bsize;
    if (blocks < 1024) {
        blocks = 1024;
    }
    buf->f_type = buf->f_type ? buf->f_type : 0x65735546; /* FUSE_SUPER_MAGIC-ish */
    buf->f_bsize = bsize;
    buf->f_frsize = bsize;
    buf->f_blocks = blocks;
    buf->f_bfree = blocks;
    buf->f_bavail = blocks;
    buf->f_files = 10000000;
    buf->f_ffree = 9990000;
    buf->f_namelen = buf->f_namelen ? buf->f_namelen : 255;
}

int statvfs(const char *path, struct statvfs *buf) {
    static int (*real_statvfs)(const char *, struct statvfs *) = NULL;
    if (!real_statvfs) {
        real_statvfs = (int (*)(const char *, struct statvfs *))dlsym(RTLD_NEXT, "statvfs");
    }
    int rc = real_statvfs(path, buf);
    if (rc == 0 && looks_broken_statvfs(buf)) {
        patch_statvfs(buf);
    }
    return rc;
}

int fstatvfs(int fd, struct statvfs *buf) {
    static int (*real_fstatvfs)(int, struct statvfs *) = NULL;
    if (!real_fstatvfs) {
        real_fstatvfs = (int (*)(int, struct statvfs *))dlsym(RTLD_NEXT, "fstatvfs");
    }
    int rc = real_fstatvfs(fd, buf);
    if (rc == 0 && looks_broken_statvfs(buf)) {
        patch_statvfs(buf);
    }
    return rc;
}

int statfs(const char *path, struct statfs *buf) {
    static int (*real_statfs)(const char *, struct statfs *) = NULL;
    if (!real_statfs) {
        real_statfs = (int (*)(const char *, struct statfs *))dlsym(RTLD_NEXT, "statfs");
    }
    int rc = real_statfs(path, buf);
    if (rc == 0 && looks_broken_statfs(buf)) {
        patch_statfs(buf);
    }
    return rc;
}

int fstatfs(int fd, struct statfs *buf) {
    static int (*real_fstatfs)(int, struct statfs *) = NULL;
    if (!real_fstatfs) {
        real_fstatfs = (int (*)(int, struct statfs *))dlsym(RTLD_NEXT, "fstatfs");
    }
    int rc = real_fstatfs(fd, buf);
    if (rc == 0 && looks_broken_statfs(buf)) {
        patch_statfs(buf);
    }
    return rc;
}

/*
 * Minimal FUSE3 passthrough that proxies all file I/O to a backend directory
 * but reports a large fake free capacity via statfs.
 *
 * Needed for MinIO (Go): it issues raw syscalls, so LD_PRELOAD cannot help.
 */
#define FUSE_USE_VERSION 31

#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <fuse3/fuse.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static const char *backend_root = NULL;
static unsigned long long fake_bytes = 10ULL * 1024ULL * 1024ULL * 1024ULL * 1024ULL;

static void fullpath(char out[4096], const char *path) {
    if (strcmp(path, "/") == 0) {
        snprintf(out, 4096, "%s", backend_root);
        return;
    }
    snprintf(out, 4096, "%s%s", backend_root, path);
}

static int ff_getattr(const char *path, struct stat *stbuf, struct fuse_file_info *fi) {
    (void)fi;
    char fpath[4096];
    fullpath(fpath, path);
    int res = lstat(fpath, stbuf);
    return res == -1 ? -errno : 0;
}

static int ff_access(const char *path, int mask) {
    char fpath[4096];
    fullpath(fpath, path);
    int res = access(fpath, mask);
    return res == -1 ? -errno : 0;
}

static int ff_readdir(const char *path, void *buf, fuse_fill_dir_t filler, off_t offset,
                      struct fuse_file_info *fi, enum fuse_readdir_flags flags) {
    (void)offset;
    (void)fi;
    (void)flags;
    char fpath[4096];
    fullpath(fpath, path);
    DIR *dp = opendir(fpath);
    if (!dp) {
        return -errno;
    }
    filler(buf, ".", NULL, 0, 0);
    filler(buf, "..", NULL, 0, 0);
    struct dirent *de;
    while ((de = readdir(dp)) != NULL) {
        if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0) {
            continue;
        }
        struct stat st;
        memset(&st, 0, sizeof(st));
        st.st_ino = de->d_ino;
        st.st_mode = de->d_type << 12;
        if (filler(buf, de->d_name, &st, 0, 0)) {
            break;
        }
    }
    closedir(dp);
    return 0;
}

static int ff_mkdir(const char *path, mode_t mode) {
    char fpath[4096];
    fullpath(fpath, path);
    int res = mkdir(fpath, mode);
    return res == -1 ? -errno : 0;
}

static int ff_unlink(const char *path) {
    char fpath[4096];
    fullpath(fpath, path);
    int res = unlink(fpath);
    return res == -1 ? -errno : 0;
}

static int ff_rmdir(const char *path) {
    char fpath[4096];
    fullpath(fpath, path);
    int res = rmdir(fpath);
    return res == -1 ? -errno : 0;
}

static int ff_rename(const char *from, const char *to, unsigned int flags) {
    if (flags) {
        return -EINVAL;
    }
    char ffrom[4096], fto[4096];
    fullpath(ffrom, from);
    fullpath(fto, to);
    int res = rename(ffrom, fto);
    return res == -1 ? -errno : 0;
}

static int ff_chmod(const char *path, mode_t mode, struct fuse_file_info *fi) {
    (void)fi;
    char fpath[4096];
    fullpath(fpath, path);
    int res = chmod(fpath, mode);
    return res == -1 ? -errno : 0;
}

static int ff_chown(const char *path, uid_t uid, gid_t gid, struct fuse_file_info *fi) {
    (void)fi;
    char fpath[4096];
    fullpath(fpath, path);
    int res = lchown(fpath, uid, gid);
    return res == -1 ? -errno : 0;
}

static int ff_truncate(const char *path, off_t size, struct fuse_file_info *fi) {
    int res;
    if (fi) {
        res = ftruncate(fi->fh, size);
    } else {
        char fpath[4096];
        fullpath(fpath, path);
        res = truncate(fpath, size);
    }
    return res == -1 ? -errno : 0;
}

static int ff_open(const char *path, struct fuse_file_info *fi) {
    char fpath[4096];
    fullpath(fpath, path);
    int fd = open(fpath, fi->flags);
    if (fd == -1) {
        return -errno;
    }
    fi->fh = fd;
    return 0;
}

static int ff_create(const char *path, mode_t mode, struct fuse_file_info *fi) {
    char fpath[4096];
    fullpath(fpath, path);
    int fd = open(fpath, fi->flags, mode);
    if (fd == -1) {
        return -errno;
    }
    fi->fh = fd;
    return 0;
}

static int ff_read(const char *path, char *buf, size_t size, off_t offset,
                   struct fuse_file_info *fi) {
    (void)path;
    int res = pread(fi->fh, buf, size, offset);
    return res == -1 ? -errno : res;
}

static int ff_write(const char *path, const char *buf, size_t size, off_t offset,
                    struct fuse_file_info *fi) {
    (void)path;
    int res = pwrite(fi->fh, buf, size, offset);
    return res == -1 ? -errno : res;
}

static int ff_statfs(const char *path, struct statvfs *stbuf) {
    (void)path;
    unsigned long bsize = 4096;
    unsigned long long blocks = fake_bytes / bsize;
    memset(stbuf, 0, sizeof(*stbuf));
    stbuf->f_bsize = bsize;
    stbuf->f_frsize = bsize;
    stbuf->f_blocks = blocks;
    stbuf->f_bfree = blocks;
    stbuf->f_bavail = blocks;
    stbuf->f_files = 10000000;
    stbuf->f_ffree = 9990000;
    stbuf->f_favail = 9990000;
    stbuf->f_namemax = 255;
    return 0;
}

static int ff_release(const char *path, struct fuse_file_info *fi) {
    (void)path;
    close(fi->fh);
    return 0;
}

static int ff_fsync(const char *path, int isdatasync, struct fuse_file_info *fi) {
    (void)path;
    (void)isdatasync;
    int res = fsync(fi->fh);
    return res == -1 ? -errno : 0;
}

static int ff_utimens(const char *path, const struct timespec ts[2],
                      struct fuse_file_info *fi) {
    (void)fi;
    char fpath[4096];
    fullpath(fpath, path);
    int res = utimensat(0, fpath, ts, AT_SYMLINK_NOFOLLOW);
    return res == -1 ? -errno : 0;
}

static void *ff_init(struct fuse_conn_info *conn, struct fuse_config *cfg) {
    (void)conn;
    cfg->use_ino = 1;
    cfg->entry_timeout = 1.0;
    cfg->attr_timeout = 1.0;
    cfg->negative_timeout = 0.0;
    return NULL;
}

static const struct fuse_operations ff_ops = {
    .init = ff_init,
    .getattr = ff_getattr,
    .access = ff_access,
    .readdir = ff_readdir,
    .mkdir = ff_mkdir,
    .unlink = ff_unlink,
    .rmdir = ff_rmdir,
    .rename = ff_rename,
    .chmod = ff_chmod,
    .chown = ff_chown,
    .truncate = ff_truncate,
    .open = ff_open,
    .create = ff_create,
    .read = ff_read,
    .write = ff_write,
    .statfs = ff_statfs,
    .release = ff_release,
    .fsync = ff_fsync,
    .utimens = ff_utimens,
};

static void usage(const char *prog) {
    fprintf(stderr,
            "Usage: %s <backend_dir> <mountpoint> [fake_free_bytes]\n"
            "  Mounts backend_dir at mountpoint via FUSE and reports fake free space.\n",
            prog);
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        usage(argv[0]);
        return 1;
    }
    backend_root = realpath(argv[1], NULL);
    if (!backend_root) {
        perror("realpath(backend)");
        return 1;
    }
    if (argc >= 4) {
        fake_bytes = strtoull(argv[3], NULL, 10);
        if (fake_bytes == 0) {
            fake_bytes = 10ULL * 1024ULL * 1024ULL * 1024ULL * 1024ULL;
        }
    }
    const char *env = getenv("FAKE_FREE_BYTES");
    if (env && *env) {
        unsigned long long v = strtoull(env, NULL, 10);
        if (v > 0) {
            fake_bytes = v;
        }
    }

    char *fuse_argv[] = {
        argv[0],
        "-f",
        "-o",
        "allow_other,default_permissions,attr_timeout=1",
        argv[2],
        NULL,
    };
    return fuse_main(5, fuse_argv, &ff_ops, NULL);
}

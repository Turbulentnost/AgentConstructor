#!/bin/sh
# Runs inside the docker-desktop WSL distro.
# Mounts the SMB Files share via drvfs (full capacity, not the ~130MB virtiofs trap).
set -eu

MOUNT_POINT="${SMB_MOUNT_POINT:-/mnt/smbshare}"
UNC_SHARE="${SMB_UNC_SHARE:-\\\\192.168.1.198\\Files}"
TARGET_NAME="${SMB_TARGET_NAME:-MinioConstructor2}"
# ASCII-only path for Docker Compose on Windows (Cyrillic in .env gets corrupted).
STABLE_LINK="${SMB_STABLE_LINK:-/mnt/MinioConstructor2}"

mkdir -p "$MOUNT_POINT"
if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
  mount -t drvfs "$UNC_SHARE" "$MOUNT_POINT"
fi

TARGET="$(find "$MOUNT_POINT" -maxdepth 2 -type d -name "$TARGET_NAME" 2>/dev/null | head -n 1 || true)"
if [ -z "$TARGET" ]; then
  echo "ERROR: directory '$TARGET_NAME' not found under $MOUNT_POINT" >&2
  ls -la "$MOUNT_POINT" >&2 || true
  exit 1
fi

mkdir -p "$TARGET/minio"
ln -sfn "$TARGET" "$STABLE_LINK"
df -h "$STABLE_LINK" >&2
# Print ONLY the stable ASCII path on stdout for the caller.
printf '%s\n' "$STABLE_LINK"

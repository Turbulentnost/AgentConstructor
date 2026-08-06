#!/bin/sh
set -eu
mkdir -p /mnt/smbshare
if ! mountpoint -q /mnt/smbshare; then
  mount -t drvfs '\\\\192.168.1.198\\Files' /mnt/smbshare
fi
df -h /mnt/smbshare
TARGET=$(find /mnt/smbshare -maxdepth 2 -type d -name MinioConstructor2 | head -n 1)
echo "TARGET=$TARGET"
dd if=/dev/zero of="$TARGET/wsl_probe.bin" bs=1M count=300
ls -lh "$TARGET/wsl_probe.bin"
rm -f "$TARGET/wsl_probe.bin"
echo WSL_WRITE_OK

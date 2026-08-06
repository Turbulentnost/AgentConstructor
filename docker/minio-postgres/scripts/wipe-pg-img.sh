#!/bin/sh
set -eu
mkdir -p /mnt/smbshare
mountpoint -q /mnt/smbshare || mount -t drvfs '\\192.168.1.198\Files' /mnt/smbshare
TARGET=$(find /mnt/smbshare -maxdepth 2 -type d -name MinioConstructor2 | head -n 1)
ln -sfn "$TARGET" /mnt/MinioConstructor2
rm -f /mnt/MinioConstructor2/postgres.img
ls -la /mnt/MinioConstructor2
echo DONE

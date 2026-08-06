#!/bin/bash
set -euo pipefail
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cifs-utils smbclient >/dev/null
mkdir -p /mnt/smb

echo "== smbclient list =="
smbclient -L //192.168.1.198 -N || true
smbclient -L //192.168.1.198 -U guest% || true

OPTS_LIST=(
  "guest,vers=3.0,iocharset=utf8,nobrl,actimeo=0"
  "username=guest,password=,vers=3.0,iocharset=utf8,nobrl,actimeo=0"
  "vers=3.0,iocharset=utf8,nobrl,sec=none,actimeo=0"
  "guest,vers=2.0,iocharset=utf8,nobrl"
)

for opts in "${OPTS_LIST[@]}"; do
  echo "== TRY mount -o ${opts} =="
  if mount -t cifs //192.168.1.198/Files /mnt/smb -o "${opts}"; then
    echo "MOUNTED OK"
    df -h /mnt/smb
    df -i /mnt/smb
    ls -la /mnt/smb | head -30
    # find MinioConstructor2
    find /mnt/smb -maxdepth 2 -type d -name 'MinioConstructor2' 2>/dev/null || true
    # write test beyond 130MB
    target="$(find /mnt/smb -maxdepth 2 -type d -name 'MinioConstructor2' | head -1)"
    if [[ -n "${target}" ]]; then
      echo "Writing 300MB into ${target}"
      dd if=/dev/zero of="${target}/cifs_write_test.bin" bs=1M count=300 status=progress
      ls -lh "${target}/cifs_write_test.bin"
      rm -f "${target}/cifs_write_test.bin"
      echo "WRITE_OK"
    fi
    umount /mnt/smb
    exit 0
  else
    echo "mount failed: $?"
    dmesg | tail -n 5 || true
  fi
done

echo "ALL MOUNT ATTEMPTS FAILED"
exit 1

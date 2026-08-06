#Requires -Version 5.1
<#
.SYNOPSIS
  Wipe MinIO objects and recreate the Postgres loop image on the network share.
#>
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Push-Location $ScriptDir
try {
    Write-Host "==> Stopping container..."
    docker compose --env-file .env down 2>$null
    docker rm -f agent-minio-postgres 2>$null | Out-Null

    $wipe = @'
mkdir -p /mnt/smbshare
mountpoint -q /mnt/smbshare || mount -t drvfs '\\192.168.1.198\Files' /mnt/smbshare
TARGET=$(find /mnt/smbshare -maxdepth 2 -type d -name MinioConstructor2 | head -n 1)
ln -sfn "$TARGET" /mnt/MinioConstructor2
rm -rf /mnt/MinioConstructor2/minio
rm -f /mnt/MinioConstructor2/postgres.img
mkdir -p /mnt/MinioConstructor2/minio
ls -la /mnt/MinioConstructor2
echo DONE
'@
    $wipe = $wipe -replace "`r", ""
    Write-Host "==> Wiping data on network share via docker-desktop WSL..."
    $wipe | wsl -d docker-desktop -e sh -c "tr -d '\r' | sh"
    Write-Host "Data wiped. Start again with .\start.ps1"
} finally {
    Pop-Location
}

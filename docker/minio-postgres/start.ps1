#Requires -Version 5.1
<#
.SYNOPSIS
  Build and start the single MinIO+PostgreSQL container.

.DESCRIPTION
  Data directory on the LAN share:
    \\192.168.1.198\Files\<archive>\MinioConstructor2

  Docker Desktop cannot bind-mount that share directly (fake ~130MB disk +
  ENOSPC). This script mounts the share inside the docker-desktop WSL distro
  via drvfs (reports full TB free), then bind-mounts that Linux path.

  Ports: 9000 MinIO API, 9001 Console, POSTGRES_HOST_PORT (default 5432; often 5433)
#>
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnsureScript = Join-Path $ScriptDir "scripts\ensure-smb-mount.sh"

function ConvertTo-UnixLf([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $text = [System.IO.File]::ReadAllText($Path)
    $normalized = $text -replace "`r`n", "`n" -replace "`r", "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $normalized, $utf8NoBom)
}

ConvertTo-UnixLf (Join-Path $ScriptDir "entrypoint.sh")
ConvertTo-UnixLf $EnsureScript

Write-Host "==> Mounting SMB share inside docker-desktop (drvfs)..."
# Pipe script into WSL; strip CR so bash never sees CRLF.
$ensureBody = ([System.IO.File]::ReadAllText($EnsureScript) -replace "`r", "")
$mountOut = $ensureBody | wsl -d docker-desktop -e sh -c "tr -d '\r' > /tmp/ensure-smb-mount.sh && chmod +x /tmp/ensure-smb-mount.sh && sh /tmp/ensure-smb-mount.sh 2>/tmp/ensure-smb-mount.err; ec=`$?; cat /tmp/ensure-smb-mount.err >&2; exit `$ec"
$mountExit = $LASTEXITCODE
$dataHostPath = @($mountOut | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ -match '^/mnt/' } | Select-Object -Last 1)
if (-not $dataHostPath) {
    throw "Failed to mount SMB share in docker-desktop WSL (exit=$mountExit). Is Docker Desktop running?`nOutput:`n$mountOut"
}
Write-Host "==> DATA_HOST_PATH=$dataHostPath"

# Merge DATA_HOST_PATH into .env (preserve other keys).
$envFile = Join-Path $ScriptDir ".env"
$lines = @()
if (Test-Path -LiteralPath $envFile) {
    $lines = Get-Content -LiteralPath $envFile
}
$updated = $false
$newLines = foreach ($line in $lines) {
    if ($line -match '^\s*DATA_HOST_PATH=') {
        $updated = $true
        "DATA_HOST_PATH=$dataHostPath"
    } else {
        $line
    }
}
if (-not $updated) {
    $newLines = @("DATA_HOST_PATH=$dataHostPath") + $newLines
}
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($envFile, $newLines, $utf8NoBom)

# Also keep Windows M: mapped for convenience / Explorer access.
$shareUncProbe = @"
set -eu
mp=/mnt/smbshare
t=`$(find "`$mp" -maxdepth 2 -type d -name MinioConstructor2 | head -n 1)
# Print Windows-style UNC by asking WSL to keep the Linux path only; mapping is optional.
printf '%s\n' "`$t"
"@
try {
    if (-not (Get-PSDrive -Name M -ErrorAction SilentlyContinue)) {
        $shareRoot = "\\192.168.1.198\Files"
        if (Test-Path -LiteralPath $shareRoot) {
            $parent = Get-ChildItem -LiteralPath $shareRoot -Directory -ErrorAction SilentlyContinue |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "MinioConstructor2") } |
                Select-Object -First 1
            if ($parent) {
                $unc = Join-Path $parent.FullName "MinioConstructor2"
                cmd /c "net use M: `"$unc`" /persistent:yes" | Out-Null
            }
        }
    }
} catch {
    Write-Host "==> Optional M: mapping skipped: $($_.Exception.Message)"
}

Push-Location $ScriptDir
try {
    Write-Host "==> Building and starting container agent-minio-postgres..."
    docker compose --env-file .env up -d --build
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE"
    }
    Write-Host ""
    docker compose ps
    Write-Host ""
    Write-Host "MinIO API:      http://localhost:9000"
    Write-Host "MinIO Console:  http://localhost:9001"
    $pgHostPort = if ($env:POSTGRES_HOST_PORT) { $env:POSTGRES_HOST_PORT } else { "5432" }
    if (Test-Path ".env") {
        Get-Content ".env" | ForEach-Object {
            if ($_ -match '^\s*POSTGRES_HOST_PORT\s*=\s*(.+)$') { $pgHostPort = $Matches[1].Trim() }
        }
    }
    Write-Host "PostgreSQL:     localhost:$pgHostPort  (see .env POSTGRES_HOST_PORT)"
    Write-Host "Data (Linux):   $dataHostPath"
    Write-Host "Logs:           docker logs -f agent-minio-postgres"
} finally {
    Pop-Location
}

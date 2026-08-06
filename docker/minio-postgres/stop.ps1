#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $ScriptDir
try {
    docker compose --env-file .env down
    Write-Host "Container stopped. Data on the network share was kept."
} finally {
    Pop-Location
}

#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Node.js install check and npm verification

.DESCRIPTION
    This script verifies that Node.js and npm are available on the system.
    If not found, it guides the user to install Node.js from the official source.
    Optionally installs dependencies from a package.json in the client directory.

.PARAMETER SkipInstall
    Skip running npm install even if a package.json is found.

.EXAMPLE
    .\get-npm.ps1
    Checks for Node.js/npm and installs client dependencies if package.json exists.

.EXAMPLE
    .\get-npm.ps1 -SkipInstall
    Checks for Node.js/npm only, does not run npm install.
#>

param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$ClientDir = Join-Path $ProjectRoot "client"

# ── check node ────────────────────────────────────────────────────────────────

$NodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $NodeCmd) {
    Write-Host "error: node.js not found on PATH" -ForegroundColor Red
    Write-Host ""
    Write-Host "install node.js from: https://nodejs.org/en/download" -ForegroundColor Cyan
    Write-Host "  - recommended: use the LTS release" -ForegroundColor Gray
    Write-Host "  - or use a version manager like nvm-windows: https://github.com/coreybutler/nvm-windows" -ForegroundColor Gray
    exit 1
}

$NodeVersion = & node --version
Write-Host "node.js found: $NodeVersion" -ForegroundColor Green

# ── check npm ─────────────────────────────────────────────────────────────────

$NpmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $NpmCmd) {
    Write-Host "error: npm not found on PATH (should ship with node.js)" -ForegroundColor Red
    exit 1
}

$NpmVersion = & npm --version
Write-Host "npm found: v$NpmVersion" -ForegroundColor Green

# ── install dependencies ───────────────────────────────────────────────────────

if ($SkipInstall) {
    Write-Host ""
    Write-Host "skipping npm install (-SkipInstall)" -ForegroundColor Yellow
    exit 0
}

$PackageJson = Join-Path $ClientDir "package.json"
if (-not (Test-Path $PackageJson)) {
    Write-Host ""
    Write-Host "no package.json found in client/ — skipping npm install" -ForegroundColor Yellow
    Write-Host "add a package.json to client/ to set up your frontend." -ForegroundColor Gray
    exit 0
}

Write-Host ""
Write-Host "installing client dependencies..." -ForegroundColor Cyan
Push-Location $ClientDir
try {
    & npm install
    if ($LASTEXITCODE -ne 0) {
        throw "npm install failed - err: $LASTEXITCODE"
    }
    Write-Host "client dependencies installed" -ForegroundColor Green
}
finally {
    Pop-Location
}

exit 0

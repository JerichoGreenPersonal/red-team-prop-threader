#Requires -Version 5.1
<#
.SYNOPSIS
    Build review-prep-worker.exe (console) and review-prep.exe (windowed) via PyInstaller.

.DESCRIPTION
    Runs from the repository root. Prefers ./uv.exe when present, otherwise `uv` on PATH.
    Outputs land in packaging/dist/.

.EXAMPLE
    .\packaging\build.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$Uv = Join-Path $RepoRoot "uv.exe"
if (-not (Test-Path $Uv)) {
    $UvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $UvCmd) {
        throw "uv not found. Run .\bin\setup\get-uv.ps1 or put uv on PATH."
    }
    $Uv = $UvCmd.Source
}

$Spec = Join-Path $PSScriptRoot "review_prep.spec"
$WorkPath = Join-Path $PSScriptRoot "build"
$DistPath = Join-Path $PSScriptRoot "dist"

Write-Host "Building with PyInstaller (spec: $Spec)"
Write-Host "  workpath: $WorkPath"
Write-Host "  distpath: $DistPath"

& $Uv run --group packaging pyinstaller `
    --noconfirm `
    --clean `
    --workpath $WorkPath `
    --distpath $DistPath `
    $Spec

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$Worker = Join-Path $DistPath "review-prep-worker.exe"
$Dash = Join-Path $DistPath "review-prep.exe"

if (-not (Test-Path $Worker)) { throw "Missing $Worker" }
if (-not (Test-Path $Dash)) { throw "Missing $Dash" }

Write-Host ""
Write-Host "Build OK:"
Write-Host "  $Worker"
Write-Host "  $Dash"
Write-Host ""
Write-Host "Install with: .\packaging\install.ps1"

#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Complete build pipeline for the project package

.DESCRIPTION
    This script runs the full build process:
    1. Synchronizes version from version.toml to VERSION file
    2. Builds package distributions using uv build
    3. Installs package in editable mode for cli usage

    The script ensures version coherence across all build artifacts.

.PARAMETER SkipPackage
    Skip package build step

.EXAMPLE
    .\build.ps1
    Full build with wheel package distributions

#>

param(
    [Parameter()]
    [switch]$SkipPackage
)

# set error action preference
$ErrorActionPreference = "Stop"

# get project root (parent of bin directory)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ScriptsDir = Join-Path $ProjectRoot "scripts"
$DistDir = Join-Path $ProjectRoot "dist"
$UvPath = Join-Path $ProjectRoot "uv.exe"
if (-not (Test-Path $UvPath)) {
    throw "uv executable not found: $UvPath"
}

Write-Host "starting package build" -ForegroundColor Cyan
Write-Host ""

# step 1: version synchronization
Write-Host "(1:3) synchronizing version..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    $VersionScript = Join-Path $ScriptsDir "version.py"
    if (-not (Test-Path $VersionScript)) {
        throw "version script not found: $VersionScript"
    }

    & $UvPath run python $VersionScript
    if ($LASTEXITCODE -ne 0) {
        throw "version synchronization failed - err: $LASTEXITCODE"
    }

    # read and display the updated version
    $VersionFile = Join-Path $ProjectRoot "VERSION"
    if (Test-Path $VersionFile) {
        $Version = (Get-Content $VersionFile -Raw).Trim()
        Write-Host "version synchronized: $Version" -ForegroundColor Green
    }
}
finally {
    Pop-Location
}

Write-Host ""

# step 2: package build
if (-not $SkipPackage) {
    Write-Host "(2:3) building package distributions..." -ForegroundColor Yellow

    Push-Location $ProjectRoot
    try {
        # clean previous distributions
        if (Test-Path $DistDir) {
            Remove-Item -Path $DistDir -Recurse -Force
            Write-Host "cleaned previous distributions" -ForegroundColor Gray
        }

        # build package
        & $UvPath build
        if ($LASTEXITCODE -ne 0) {
            throw "package build failed - err: $LASTEXITCODE"
        }

        # list built artifacts
        if (Test-Path $DistDir) {
            $Artifacts = Get-ChildItem -Path $DistDir -File
            Write-Host "package build finished" -ForegroundColor Green
            Write-Host "built artifacts:" -ForegroundColor Cyan
            foreach ($Artifact in $Artifacts) {
                $Size = [math]::Round($Artifact.Length / 1KB, 1)
                Write-Host "  - $($Artifact.Name) (${Size}KB)" -ForegroundColor Gray
            }
        }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "(2:3) skipping package build" -ForegroundColor Yellow
}

Write-Host ""

# step 3: install package
Write-Host "(3:3) installing package in editable mode..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    & $UvPath pip install -e .

    if ($LASTEXITCODE -ne 0) {
        throw "package installation failed - err: $LASTEXITCODE"
    }

    Write-Host "package installed successfully" -ForegroundColor Green
}
finally {
    Pop-Location
}

# show output summary
Write-Host ""
Write-Host "output summary:" -ForegroundColor Cyan

if (-not $SkipPackage -and (Test-Path $DistDir)) {
    Write-Host "dist: $DistDir" -ForegroundColor Gray
}

Write-Host ""
Write-Host "build pipeline completed successfully" -ForegroundColor Green

exit 0

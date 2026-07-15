#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Initialize a new Python package project using uv

.DESCRIPTION
    This script bootstraps a new Python package project:
    1. Validates that the project is not already initialized (pyproject.toml)
    2. Vendors uv.exe if not already present (runs bin/setup/get-uv.ps1)
    3. Runs uv init --package in the repo root to scaffold the project
    4. Adds dev dependencies (ruff, ty, pytest)
    5. Creates a virtual environment

.PARAMETER Name
    The project name. Must not contain spaces.

.PARAMETER Python
    The Python version to use. Defaults to 3.11.

.EXAMPLE
    .\init_project.ps1 -Name my-tool
    Initialize with default Python 3.11

.EXAMPLE
    .\init_project.ps1 -Name my-tool -Python 3.11.8
    Initialize with a specific Python version
#>

param(
    [Parameter(Mandatory = $false)]
    [string]$Name,

    [string]$Python = "3.11"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

# ── validation ────────────────────────────────────────────────────────────────

# auto-detect project name from parent folder if not provided
if (-not $Name) {
    $Name = Split-Path -Leaf $ProjectRoot
    Write-Host "auto-detected project name from folder: $Name" -ForegroundColor Cyan
}

# reject names with spaces
if ($Name -match '\s') {
    Write-Host "error: project name must not contain spaces: '$Name'" -ForegroundColor Red
    exit 1
}

# early-exit if the project is already initialized
$PyprojectPath = Join-Path $ProjectRoot "pyproject.toml"
if (Test-Path $PyprojectPath) {
    Write-Host "this project is already set up (pyproject.toml exists)" -ForegroundColor Yellow
    exit 0
}

# ── create init branch ────────────────────────────────────────────────────────

$GitAvailable = Get-Command git -ErrorAction SilentlyContinue
if ($GitAvailable) {
    Push-Location $ProjectRoot
    try {
        git checkout -b init-project main 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "switched to new branch 'init-project'" -ForegroundColor Green
        }
        else {
            Write-Host "warning: could not create branch 'init-project' (may already exist)" -ForegroundColor Yellow
        }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "warning: git not found, skipping branch creation" -ForegroundColor Yellow
}

Write-Host ""

# ── resolve uv ────────────────────────────────────────────────────────────────

$UvPath = Join-Path $ProjectRoot "uv.exe"
if (-not (Test-Path $UvPath)) {
    Write-Host "uv.exe not found — running get-uv.ps1..." -ForegroundColor Yellow
    $GetUvScript = Join-Path $ScriptDir "get-uv.ps1"
    if (-not (Test-Path $GetUvScript)) {
        Write-Host "error: get-uv.ps1 not found at: $GetUvScript" -ForegroundColor Red
        exit 1
    }
    & $GetUvScript
    if (-not (Test-Path $UvPath)) {
        Write-Host "error: uv.exe still not found after get-uv.ps1" -ForegroundColor Red
        exit 1
    }
    Write-Host "uv.exe installed" -ForegroundColor Green
    Write-Host ""
}

Write-Host "project initialization" -ForegroundColor Cyan
Write-Host "  name:   $Name" -ForegroundColor Gray
Write-Host "  python: $Python" -ForegroundColor Gray
Write-Host ""

# ── step 1: uv init ──────────────────────────────────────────────────────────

Write-Host "(1/6) initializing project with uv..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    & $UvPath init --name $Name --package --python $Python
    if ($LASTEXITCODE -ne 0) {
        throw "uv init failed - err: $LASTEXITCODE"
    }
    Write-Host "project scaffolded" -ForegroundColor Green
}
finally {
    Pop-Location
}

Write-Host ""

# ── step 2: patch pyproject.toml for dynamic versioning ──────────────────────

Write-Host "(2/6) patching pyproject.toml for dynamic versioning..." -ForegroundColor Yellow

$PyprojectPath = Join-Path $ProjectRoot "pyproject.toml"
if (-not (Test-Path $PyprojectPath)) {
    throw "pyproject.toml not found after uv init"
}

$Content = Get-Content $PyprojectPath -Raw

# add dynamic = ["version"] after the version line
$Content = $Content -replace '(?m)^version\s*=\s*"[^"]*"\r?\n', "dynamic = [""version""]`n"

# replace build-system to use setuptools
$Content = $Content -replace '(?ms)\[build-system\].*?build-backend\s*=\s*"[^"]*"', @"
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"
"@

# append setuptools dynamic version config
if ($Content -notmatch '\[tool\.setuptools\.dynamic\]') {
    $Content = $Content.TrimEnd() + "`n`n[tool.setuptools.dynamic]`nversion = { file = ""VERSION"" }`n"
}

Set-Content -Path $PyprojectPath -Value $Content -NoNewline
Write-Host "dynamic versioning configured" -ForegroundColor Green

Write-Host ""

# ── step 3: patch ruff.toml and ty.toml ──────────────────────────────────────

Write-Host "(3/6) patching ruff.toml and ty.toml..." -ForegroundColor Yellow

# derive major.minor from the python flag (e.g. 3.11.8 -> 3.11, 3.12 -> 3.12)
$PythonParts = $Python -split '\.'
$MajorMinor = "$($PythonParts[0]).$($PythonParts[1])"
$RuffTarget = "py$($PythonParts[0])$($PythonParts[1])"  # e.g. py311, py312

$RuffTomlPath = Join-Path $ProjectRoot "ruff.toml"
if (Test-Path $RuffTomlPath) {
    $RuffContent = Get-Content $RuffTomlPath -Raw
    $RuffContent = $RuffContent -replace 'namespace-packages\s*=\s*\["[^"]*"\]', "namespace-packages = [""$Name""]"
    $RuffContent = $RuffContent -replace 'target-version\s*=\s*"py[0-9]+"', "target-version = ""$RuffTarget"""
    Set-Content -Path $RuffTomlPath -Value $RuffContent -NoNewline
    Write-Host "ruff.toml updated (namespace=$Name, target=$RuffTarget)" -ForegroundColor Green
}
else {
    Write-Host "warning: ruff.toml not found, skipping" -ForegroundColor Yellow
}

$TyTomlPath = Join-Path $ProjectRoot "ty.toml"
if (Test-Path $TyTomlPath) {
    $TyContent = Get-Content $TyTomlPath -Raw
    $TyContent = $TyContent -replace 'python-version\s*=\s*"[0-9]+\.[0-9]+"', "python-version = ""$MajorMinor"""
    Set-Content -Path $TyTomlPath -Value $TyContent -NoNewline
    Write-Host "ty.toml updated (python-version=$MajorMinor)" -ForegroundColor Green
}
else {
    Write-Host "warning: ty.toml not found, skipping" -ForegroundColor Yellow
}

Write-Host ""

# ── step 4: add dev dependencies ─────────────────────────────────────────────

Write-Host "(4/6) adding dev dependencies (ruff, ty, pytest)..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    & $UvPath add --dev ruff ty pytest
    if ($LASTEXITCODE -ne 0) {
        throw "uv add --dev failed - err: $LASTEXITCODE"
    }
    Write-Host "dev dependencies added" -ForegroundColor Green
}
finally {
    Pop-Location
}

Write-Host ""

# ── step 5: create virtual environment ────────────────────────────────────────

Write-Host "(5/6) creating virtual environment..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    & $UvPath venv
    if ($LASTEXITCODE -ne 0) {
        throw "uv venv failed - err: $LASTEXITCODE"
    }
    Write-Host "virtual environment created" -ForegroundColor Green
}
finally {
    Pop-Location
}

Write-Host ""

# ── step 6: rename workspace file ─────────────────────────────────────────────

Write-Host "(6/6) setting up code workspace..." -ForegroundColor Yellow

$FolderName = Split-Path -Leaf $ProjectRoot
$TemplateWorkspace = Join-Path $ProjectRoot "template-py-package.code-workspace"
$NewWorkspace = Join-Path $ProjectRoot "$FolderName.code-workspace"

if (Test-Path $TemplateWorkspace) {
    Copy-Item -Path $TemplateWorkspace -Destination $NewWorkspace -Force
    Remove-Item -Path $TemplateWorkspace -Force
    Write-Host "workspace renamed to $FolderName.code-workspace" -ForegroundColor Green
}
else {
    Write-Host "warning: template workspace file not found, skipping" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "project initialization complete" -ForegroundColor Green
Write-Host ""
Write-Host "next steps:" -ForegroundColor Cyan
Write-Host "  - build package:    .\bin\build.ps1" -ForegroundColor Gray
Write-Host "  - run checks:       .\uv run ruff check ." -ForegroundColor Gray

# ensure we are in the project root
Set-Location $ProjectRoot

# activate the virtual environment
$VenvActivate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    Write-Host ""
    Write-Host "activating virtual environment..." -ForegroundColor Cyan
    & $VenvActivate
}

exit 0

#!/usr/bin/env pwsh
<#
.SYNOPSIS
    uv install and venv setup script

.DESCRIPTION
    this script automates the uv install process:
    1. downloads and installs the appropriate uv binary for the current platform
    2. sets up a venv
    3. installs dependencies

.PARAMETER Version
    the version of uv to install. default: latest

.EXAMPLE
    .\get_uv.ps1
    installs the latest version of uv

.EXAMPLE
    .\get_uv.ps1 -Version 0.5.0
    installs version 0.5.0 of uv
#>

param(
    [string]$Version = "latest"
)

$ErrorActionPreference = "Stop"

# configuration
$GitHubRepo = "astral-sh/uv"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$TempDir = Join-Path $env:TEMP "uv_install_$(Get-Random)"

# create temp directory
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

# cleanup function
function Cleanup {
    if (Test-Path $TempDir) {
        Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# register cleanup on exit
trap { Cleanup; break }

# print colored message
function Write-ColorMessage {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host $Message -ForegroundColor $Color
}

# detect architecture
function Get-Architecture {
    $arch = $env:PROCESSOR_ARCHITECTURE

    switch ($arch) {
        "AMD64" { return "x86_64" }
        "ARM64" { return "aarch64" }
        "x86" { return "i686" }
        default {
            Write-ColorMessage "error: unsupported architecture: $arch" "Red"
            exit 1
        }
    }
}

# get latest version from GitHub
function Get-LatestVersion {
    try {
        $apiUrl = "https://api.github.com/repos/$GitHubRepo/releases/latest"
        $response = Invoke-RestMethod -Uri $apiUrl -Method Get
        return $response.tag_name
    }
    catch {
        Write-ColorMessage "error: failed to fetch latest version: $_" "Red"
        exit 1
    }
}

# download file with progress
function Get-DownloadedFile {
    param(
        [string]$Url,
        [string]$OutputPath
    )

    try {
        Write-ColorMessage "downloading from: $Url" "Yellow"

        # use WebClient for progress display
        $webClient = New-Object System.Net.WebClient

        # register progress event
        Register-ObjectEvent -InputObject $webClient -EventName DownloadProgressChanged -SourceIdentifier WebClient.DownloadProgressChanged -Action {
            $percent = $EventArgs.ProgressPercentage
            Write-Progress -Activity "Downloading" -Status "$percent% Complete" -PercentComplete $percent
        } | Out-Null

        # download file
        $webClient.DownloadFile($Url, $OutputPath)

        # cleanup
        Unregister-Event -SourceIdentifier WebClient.DownloadProgressChanged -ErrorAction SilentlyContinue
        $webClient.Dispose()
        Write-Progress -Activity "Downloading" -Completed

        return $true
    }
    catch {
        Write-ColorMessage "error: download failed: $_" "Red"
        return $false
    }
}

# extract zip file
function Expand-ZipArchive {
    param(
        [string]$ArchivePath,
        [string]$DestinationPath
    )

    try {
        Write-ColorMessage "extracting archive..." "Yellow"

        # use .NET to extract
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($ArchivePath, $DestinationPath)

        return $true
    }
    catch {
        Write-ColorMessage "error: extraction failed: $_" "Red"
        return $false
    }
}

# find binaries in extracted files
function Find-Binaries {
    param(
        [string]$SearchPath
    )

    # Look for uv.exe and uvx.exe
    $uvBinary = Get-ChildItem -Path $SearchPath -Filter "uv.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    $uvxBinary = Get-ChildItem -Path $SearchPath -Filter "uvx.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1

    return @{
        uv  = if ($uvBinary) { $uvBinary.FullName } else { $null }
        uvx = if ($uvxBinary) { $uvxBinary.FullName } else { $null }
    }
}

# check if user wants to overwrite existing binary
function Test-ShouldOverwrite {
    param(
        [string]$BinaryPath,
        [string]$BinaryName
    )

    if (-not (Test-Path $BinaryPath)) {
        return $true
    }

    Write-ColorMessage "`n$BinaryName already exists at: $BinaryPath" "Yellow"
    $response = Read-Host "Do you want to re-vendor (overwrite) it? (y/N)"

    return ($response -match '^[Yy]')
}

# main installation function
function Install-UV {
    Write-ColorMessage "uv installer" "Green"

    # detect architecture
    Write-ColorMessage "detecting platform..." "Yellow"
    $arch = Get-Architecture
    $platform = "$arch-pc-windows-msvc"
    Write-ColorMessage "platform: $platform" "Green"

    # get version
    if ($Version -eq "latest") {
        Write-ColorMessage "fetching latest version..." "Yellow"
        $Version = Get-LatestVersion
        if ([string]::IsNullOrEmpty($Version)) {
            Write-ColorMessage "error: failed to fetch latest version" "Red"
            exit 1
        }
    }
    Write-ColorMessage "version: $Version" "Green"

    # construct download URL
    $filename = "uv-$platform.zip"
    $downloadUrl = "https://github.com/$GitHubRepo/releases/download/$Version/$filename"
    $archivePath = Join-Path $TempDir $filename

    # download
    if (-not (Get-DownloadedFile -Url $downloadUrl -OutputPath $archivePath)) {
        Write-ColorMessage "error: failed to download uv" "Red"
        Cleanup
        exit 1
    }

    # verify download
    if (-not (Test-Path $archivePath)) {
        Write-ColorMessage "error: download failed - file not found" "Red"
        Cleanup
        exit 1
    }

    # extract
    $extractPath = Join-Path $TempDir "extracted"
    if (-not (Expand-ZipArchive -ArchivePath $archivePath -DestinationPath $extractPath)) {
        Write-ColorMessage "error: failed to extract archive" "Red"
        Cleanup
        exit 1
    }

    # find binaries
    $binaries = Find-Binaries -SearchPath $extractPath

    if ([string]::IsNullOrEmpty($binaries.uv) -or -not (Test-Path $binaries.uv)) {
        Write-ColorMessage "error: could not find uv.exe in archive" "Red"
        Cleanup
        exit 1
    }

    # install binaries to project root
    Write-ColorMessage "`ninstalling to project root: $ProjectRoot" "Yellow"

    $installedBinaries = @()

    # install uv.exe
    $uvTargetPath = Join-Path $ProjectRoot "uv.exe"
    if (Test-ShouldOverwrite -BinaryPath $uvTargetPath -BinaryName "uv.exe") {
        try {
            Copy-Item -Path $binaries.uv -Destination $uvTargetPath -Force
            Write-ColorMessage "installed uv.exe" "Green"
            $installedBinaries += "uv.exe"
        }
        catch {
            Write-ColorMessage "error: failed to copy uv.exe: $_" "Red"
            Cleanup
            exit 1
        }
    }
    else {
        Write-ColorMessage "skipped uv.exe" "Yellow"
    }

    # install uvx.exe if found
    if (-not [string]::IsNullOrEmpty($binaries.uvx) -and (Test-Path $binaries.uvx)) {
        $uvxTargetPath = Join-Path $ProjectRoot "uvx.exe"

        if (Test-ShouldOverwrite -BinaryPath $uvxTargetPath -BinaryName "uvx.exe") {
            try {
                Copy-Item -Path $binaries.uvx -Destination $uvxTargetPath -Force
                Write-ColorMessage "installed uvx.exe" "Green"
                $installedBinaries += "uvx.exe"
            }

            catch {
                Write-ColorMessage "error: failed to copy uvx.exe: $_" "Red"
                Cleanup
                exit 1
            }
        }
        else {
            Write-ColorMessage "skipped uvx.exe" "Yellow"
        }
    }

    # verify installation
    if ($installedBinaries.Count -gt 0) {
        Write-ColorMessage "`nsuccessfully installed uv $Version" "Green"
        Write-ColorMessage "installed binaries: $($installedBinaries -join ', ')" "Green"
        Write-ColorMessage "location: $ProjectRoot" "Green"

        # show version
        if (Test-Path $uvTargetPath) {
            try {
                $uvVersion = & $uvTargetPath --version 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-ColorMessage "version: $uvVersion" "Green"
                }
            }

            catch {
                # ignore version check errors
            }
        }
    }
    else {
        Write-ColorMessage "`nno binaries were installed (all skipped)" "Yellow"
    }

    # cleanup
    Cleanup

    Write-ColorMessage "`ninstallation complete" "Green"
}

# run installation
try {
    Install-UV
}
catch {
    Write-ColorMessage "error: installation failed: $_" "Red"
    Cleanup
    exit 1
}

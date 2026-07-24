#Requires -Version 5.1
<#
.SYNOPSIS
    Install Review Prep binaries under %LOCALAPPDATA%\ReviewPrep\app\, create a Start Menu
    shortcut, and register the daily + logon scheduled tasks.

.PARAMETER DistDir
    Folder containing review-prep-worker.exe and review-prep.exe (default: packaging/dist).

.PARAMETER ScheduleHour
    Local hour for daily prep (default 5).

.PARAMETER ScheduleMinute
    Local minute for daily prep (default 0).

.PARAMETER SkipSchedule
    Copy binaries and shortcut only; do not register Task Scheduler jobs.

.EXAMPLE
    .\packaging\install.ps1
#>
[CmdletBinding()]
param(
    [string]$DistDir = "",
    [int]$ScheduleHour = 5,
    [int]$ScheduleMinute = 0,
    [switch]$SkipSchedule
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $DistDir) {
    $DistDir = Join-Path $PSScriptRoot "dist"
}
$DistDir = Resolve-Path $DistDir

$WorkerSrc = Join-Path $DistDir "review-prep-worker.exe"
$DashSrc = Join-Path $DistDir "review-prep.exe"
if (-not (Test-Path $WorkerSrc)) { throw "Missing $WorkerSrc — run .\packaging\build.ps1 first." }
if (-not (Test-Path $DashSrc)) { throw "Missing $DashSrc — run .\packaging\build.ps1 first." }

$AppRoot = Join-Path $env:LOCALAPPDATA "ReviewPrep"
$AppDir = Join-Path $AppRoot "app"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null

$WorkerDst = Join-Path $AppDir "review-prep-worker.exe"
$DashDst = Join-Path $AppDir "review-prep.exe"
Copy-Item -Force $WorkerSrc $WorkerDst
Copy-Item -Force $DashSrc $DashDst
Write-Host "Installed:"
Write-Host "  $WorkerDst"
Write-Host "  $DashDst"

# Ship ShotGrid query stub under LOCALAPPDATA (filters remain a human checkpoint).
$ConfigsDir = Join-Path $AppRoot "configs"
New-Item -ItemType Directory -Force -Path $ConfigsDir | Out-Null
$QueryDst = Join-Path $ConfigsDir "default_shotgrid_query.json"
$QueryCandidates = @(
    (Join-Path $DistDir "configs\default_shotgrid_query.json"),
    (Join-Path $RepoRoot "configs\default_shotgrid_query.json")
)
$QuerySrc = $QueryCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($QuerySrc) {
    Copy-Item -Force $QuerySrc $QueryDst
    Write-Host "  $QueryDst"
} else {
    Write-Warning "ShotGrid query JSON not found next to dist or repo; skipping copy."
}

# Start Menu shortcut (per-user)
$Programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Item -ItemType Directory -Force -Path $Programs | Out-Null
$ShortcutPath = Join-Path $Programs "Review Prep.lnk"
$Wsh = New-Object -ComObject WScript.Shell
$Shortcut = $Wsh.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $DashDst
$Shortcut.WorkingDirectory = $AppDir
$Shortcut.Description = "Daily Review Prep Assistant"
$Shortcut.Save()
Write-Host "Start Menu shortcut: $ShortcutPath"

if ($SkipSchedule) {
    Write-Host "Skipped Task Scheduler registration (-SkipSchedule)."
    return
}

# Prefer package helpers when running from a checkout with a venv; else schtasks XML/CLI.
$Uv = Join-Path $RepoRoot "uv.exe"
$RegisteredViaPython = $false
if (Test-Path $Uv) {
    try {
        $Py = @"
from review_prep.scheduler_windows import register_daily_task, register_logon_trigger
register_daily_task(r'$($WorkerDst.Replace("'", "''"))', hour=$ScheduleHour, minute=$ScheduleMinute)
register_logon_trigger(r'$($DashDst.Replace("'", "''"))')
print('registered')
"@
        & $Uv run python -c $Py
        if ($LASTEXITCODE -eq 0) {
            $RegisteredViaPython = $true
            Write-Host "Registered ReviewPrep\DailyPrep and ReviewPrep\OpenDashboard via scheduler_windows."
        }
    } catch {
        Write-Warning "Python registration failed; falling back to schtasks. $_"
    }
}

if (-not $RegisteredViaPython) {
    $User = $env:USERNAME
    $StartBoundary = "2000-01-01T{0:D2}:{1:D2}:00" -f $ScheduleHour, $ScheduleMinute
    $Xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$StartBoundary</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$User</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT72H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$([System.Security.SecurityElement]::Escape($WorkerDst))</Command>
    </Exec>
  </Actions>
</Task>
"@
    $XmlPath = Join-Path $env:TEMP ("review-prep-daily-{0}.xml" -f [guid]::NewGuid().ToString("N"))
    # Task Scheduler XML is UTF-16 LE
    [System.IO.File]::WriteAllText($XmlPath, $Xml, [System.Text.Encoding]::Unicode)
    try {
        & schtasks /Create /TN "ReviewPrep\DailyPrep" /XML $XmlPath /F | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "schtasks DailyPrep failed: $LASTEXITCODE" }
        & schtasks /Create /F /TN "ReviewPrep\OpenDashboard" /SC ONLOGON /RL LIMITED /TR "`"$DashDst`"" /RU $User | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "schtasks OpenDashboard failed: $LASTEXITCODE" }
        Write-Host "Registered ReviewPrep\DailyPrep and ReviewPrep\OpenDashboard via schtasks."
    } finally {
        Remove-Item -Force $XmlPath -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Install complete. Launch Review Prep from the Start Menu or:"
Write-Host "  & `"$DashDst`""

<#
.SYNOPSIS
    Start local RED Team Prop Threader web + worker processes with an optional tunnel.

.PARAMETER Test
    Run pytest, Ruff, and ty before starting services.

.PARAMETER SkipTunnel
    Skip tunnel start/validation even when TUNNEL_COMMAND is configured.
#>
[CmdletBinding()]
param(
    [switch]$Test,
    [switch]$SkipTunnel
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

. (Join-Path $PSScriptRoot "load-env.ps1")

$localDir = Join-Path $repoRoot "local"
$logDir = Join-Path $localDir "logs"
$pidDir = Join-Path $localDir "pids"
New-Item -ItemType Directory -Force -Path $localDir, $logDir, $pidDir | Out-Null

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "required command not found on PATH: $Name"
    }
}

function Stop-OwnedProcess([string]$Name) {
    $pidFile = Join-Path $pidDir "$Name.pid"
    if (-not (Test-Path $pidFile)) { return }
    $procId = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($procId -match '^\d+$') {
        $proc = Get-Process -Id ([int]$procId) -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping owned $Name process tree $($proc.Id)" -ForegroundColor DarkYellow
            # kill the powershell wrapper and all child uv/python processes
            & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

function Stop-OrphanPropThreaderProcesses {
    $patterns = @(
        'prop-threader-web',
        'prop-threader-worker',
        'prop-threader-web.exe',
        'prop-threader-worker.exe'
    )
    $orphans = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $cmd = [string]$_.CommandLine
        $name = [string]$_.Name
        foreach ($pattern in $patterns) {
            if ($name -like "*$pattern*" -or $cmd -like "*$pattern*") {
                return $true
            }
        }
        return $false
    }
    foreach ($orphan in $orphans) {
        Write-Host "Stopping orphan $($orphan.Name) pid $($orphan.ProcessId)" -ForegroundColor DarkYellow
        & taskkill.exe /PID $orphan.ProcessId /T /F 2>$null | Out-Null
    }
}

function Start-OwnedProcess([string]$Name, [string]$Command) {
    $logFile = Join-Path $logDir "$Name.log"
    $pidFile = Join-Path $pidDir "$Name.pid"
    # replace prior log so stale socket-mode crashes are not mistaken for current failures
    if (Test-Path $logFile) {
        Remove-Item $logFile -Force -ErrorAction SilentlyContinue
    }
    $proc = Start-Process -FilePath "powershell" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "`$host.UI.RawUI.WindowTitle = 'prop-threader-$Name'; $Command *>> '$logFile'"
    ) -PassThru -WindowStyle Normal
    Set-Content -Path $pidFile -Value $proc.Id
    Write-Host "Started $Name (pid $($proc.Id)), log: $logFile" -ForegroundColor Green
}

Assert-Command "uv"
if (-not $env:SLACK_APP_TOKEN) {
    throw "SLACK_APP_TOKEN must be set in .env (Socket Mode app-level token, xapp-...)"
}
if ($env:TUNNEL_COMMAND -and -not $SkipTunnel) {
    $tunnelBinary = ($env:TUNNEL_COMMAND -split '\s+')[0]
    Assert-Command $tunnelBinary
}

Stop-OwnedProcess "web"
Stop-OwnedProcess "worker"
Stop-OwnedProcess "tunnel"
Stop-OrphanPropThreaderProcesses

if ($Test) {
    Write-Host "Running local verification..." -ForegroundColor Cyan
    & .\uv run pytest
    if ($LASTEXITCODE -ne 0) { throw "pytest failed" }
    & .\uv run ruff check .
    if ($LASTEXITCODE -ne 0) { throw "ruff failed" }
    & .\uv run ty check
    if ($LASTEXITCODE -ne 0) { throw "ty failed" }
}

Write-Host "Running Alembic migrations..." -ForegroundColor Cyan
& .\uv run alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }

Start-OwnedProcess "web" "Set-Location '$repoRoot'; . '$PSScriptRoot\load-env.ps1'; .\uv run prop-threader-web"
Start-OwnedProcess "worker" "Set-Location '$repoRoot'; . '$PSScriptRoot\load-env.ps1'; .\uv run prop-threader-worker"

if ($env:TUNNEL_COMMAND -and -not $SkipTunnel) {
    Start-OwnedProcess "tunnel" "Set-Location '$repoRoot'; $($env:TUNNEL_COMMAND)"
    if ($env:TUNNEL_HEALTH_URL) {
        $ok = $false
        for ($i = 0; $i -lt 15; $i++) {
            try {
                $response = Invoke-WebRequest -Uri $env:TUNNEL_HEALTH_URL -UseBasicParsing -TimeoutSec 3
                if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                    $ok = $true
                    break
                }
            } catch {
                Start-Sleep -Seconds 1
            }
        }
        if (-not $ok) {
            Write-Warning "Tunnel health URL did not become ready: $($env:TUNNEL_HEALTH_URL)"
        }
    }
}

$webHost = if ($env:WEB_HOST) { $env:WEB_HOST } else { "127.0.0.1" }
$webPort = if ($env:WEB_PORT) { $env:WEB_PORT } else { "3000" }

Write-Host ""
Write-Host "RED Team Prop Threader local stack is starting." -ForegroundColor Green
Write-Host "Slack inbound mode: Socket Mode (no public Request URL required)"
Write-Host "Local health: http://${webHost}:${webPort}/healthz"

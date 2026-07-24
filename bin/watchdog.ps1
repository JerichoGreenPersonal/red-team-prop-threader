<#
.SYNOPSIS
    Poll localhost /healthz and post Slack down/recovery/daily heartbeat messages.

.DESCRIPTION
    Intended to run every 5 minutes via Task Scheduler on the always-on host.
    Uses SLACK_BOT_TOKEN from .env and posts to WATCHDOG_CHANNEL_ID (default C0B4GJSA1G8).
    State is stored in local/watchdog-state.json so alerts are not spammed.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

. (Join-Path $PSScriptRoot "load-env.ps1")

$localDir = Join-Path $repoRoot "local"
$logDir = Join-Path $localDir "logs"
$statePath = Join-Path $localDir "watchdog-state.json"
New-Item -ItemType Directory -Force -Path $localDir, $logDir | Out-Null
$logPath = Join-Path $logDir "watchdog.log"

function Write-WatchdogLog([string]$Message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $Message
    Add-Content -Path $logPath -Value $line -Encoding utf8
}

function Get-WatchdogConfig {
    $webHost = if ($env:WEB_HOST) { $env:WEB_HOST.Trim() } else { "127.0.0.1" }
    $webPort = if ($env:WEB_PORT) { $env:WEB_PORT.Trim() } else { "3000" }
    $defaultHealth = "http://${webHost}:${webPort}/healthz"
    $failThreshold = 2
    if ($env:WATCHDOG_FAIL_THRESHOLD -match '^\d+$') {
        $failThreshold = [int]$env:WATCHDOG_FAIL_THRESHOLD
    }
    $heartbeatHour = 9
    if ($env:WATCHDOG_HEARTBEAT_HOUR -match '^\d+$') {
        $heartbeatHour = [int]$env:WATCHDOG_HEARTBEAT_HOUR
    }
    return [pscustomobject]@{
        BotToken       = if ($env:SLACK_BOT_TOKEN) { $env:SLACK_BOT_TOKEN.Trim() } else { "" }
        ChannelId      = if ($env:WATCHDOG_CHANNEL_ID) { $env:WATCHDOG_CHANNEL_ID.Trim() } else { "C0B4GJSA1G8" }
        HealthUrl      = if ($env:WATCHDOG_HEALTH_URL) { $env:WATCHDOG_HEALTH_URL.Trim() } else { $defaultHealth }
        FailThreshold  = $failThreshold
        HeartbeatHour  = $heartbeatHour
        Hostname       = $env:COMPUTERNAME
    }
}

function Read-WatchdogState {
    if (-not (Test-Path $statePath)) {
        return [pscustomobject]@{
            status            = "unknown"
            failCount         = 0
            lastHeartbeatDate = ""
            alertedDown       = $false
        }
    }
    try {
        $raw = Get-Content -Path $statePath -Raw -Encoding utf8
        $obj = $raw | ConvertFrom-Json
        return [pscustomobject]@{
            status            = if ($obj.status) { [string]$obj.status } else { "unknown" }
            failCount         = if ($null -ne $obj.failCount) { [int]$obj.failCount } else { 0 }
            lastHeartbeatDate = if ($obj.lastHeartbeatDate) { [string]$obj.lastHeartbeatDate } else { "" }
            alertedDown       = [bool]$obj.alertedDown
        }
    }
    catch {
        Write-WatchdogLog "failed to read state file: $($_.Exception.Message)"
        return [pscustomobject]@{
            status            = "unknown"
            failCount         = 0
            lastHeartbeatDate = ""
            alertedDown       = $false
        }
    }
}

function Write-WatchdogState($State) {
    $json = (@{
            status            = $State.status
            failCount         = $State.failCount
            lastHeartbeatDate = $State.lastHeartbeatDate
            alertedDown       = $State.alertedDown
        } | ConvertTo-Json -Compress)
    Set-Content -Path $statePath -Value $json -Encoding utf8
}

function Test-Healthz([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
    }
    catch {
        return $false
    }
}

function Send-SlackMessage([string]$Token, [string]$ChannelId, [string]$Text) {
    $body = @{
        channel = $ChannelId
        text    = $Text
    } | ConvertTo-Json -Compress
    $headers = @{
        Authorization  = "Bearer $Token"
        "Content-Type" = "application/json; charset=utf-8"
    }
    try {
        $response = Invoke-RestMethod -Method Post -Uri "https://slack.com/api/chat.postMessage" -Headers $headers -Body $body
        if (-not $response.ok) {
            $err = if ($response.error) { $response.error } else { "unknown_error" }
            Write-WatchdogLog "chat.postMessage failed: $err"
            return $false
        }
        return $true
    }
    catch {
        Write-WatchdogLog "chat.postMessage request failed: $($_.Exception.Message)"
        return $false
    }
}

$config = Get-WatchdogConfig
if (-not $config.BotToken) {
    Write-WatchdogLog "SLACK_BOT_TOKEN missing; aborting"
    throw "SLACK_BOT_TOKEN must be set in .env"
}

$state = Read-WatchdogState
$healthy = Test-Healthz $config.HealthUrl
$now = Get-Date
$today = $now.ToString("yyyy-MM-dd")

if ($healthy) {
    $state.failCount = 0
    $state.status = "up"

    if ($state.alertedDown) {
        $msg = "RED Team Prop Threader UP on $($config.Hostname) - /healthz OK again"
        if (Send-SlackMessage -Token $config.BotToken -ChannelId $config.ChannelId -Text $msg) {
            Write-WatchdogLog "posted recovery alert"
            $state.alertedDown = $false
        }
    }

    if ($now.Hour -ge $config.HeartbeatHour -and $state.lastHeartbeatDate -ne $today) {
        $msg = "RED Team Prop Threader heartbeat OK on $($config.Hostname)"
        if (Send-SlackMessage -Token $config.BotToken -ChannelId $config.ChannelId -Text $msg) {
            Write-WatchdogLog "posted daily heartbeat"
            $state.lastHeartbeatDate = $today
        }
    }
}
else {
    $state.failCount = [int]$state.failCount + 1
    $state.status = "down"
    Write-WatchdogLog "health check failed (failCount=$($state.failCount)) url=$($config.HealthUrl)"

    if (-not $state.alertedDown -and $state.failCount -ge $config.FailThreshold) {
        $msg = "RED Team Prop Threader DOWN on $($config.Hostname) - /healthz failed"
        if (Send-SlackMessage -Token $config.BotToken -ChannelId $config.ChannelId -Text $msg) {
            Write-WatchdogLog "posted down alert"
            $state.alertedDown = $true
        }
    }
}

Write-WatchdogState $state
Write-WatchdogLog "done status=$($state.status) failCount=$($state.failCount) alertedDown=$($state.alertedDown)"

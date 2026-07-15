<#
.SYNOPSIS
    Loads the repository-root .env and optional .shell.env into the current
    PowerShell session, then prepends local dev directories to PATH.

.DESCRIPTION
    Parses each KEY=VALUE line from <repo-root>/.env, skipping blank lines and
    comments (#).  Surrounding quotes on values are stripped automatically.
    Variables are set for the current process only.

    After .env, the script looks for .shell.env in the same directory.  If
    found it is loaded the same way (later values override earlier ones).

    Finally, the repo-root, bin/, and .venv/Scripts/ directories are prepended
    to PATH so that project scripts and the virtualenv are immediately usable.

    Resolution order:
      1. $PSScriptRoot/../.env  (dot-sourced directly)
      2. $PWD/.env              (invoked via PATH or from repo root)

.USAGE
    . bin\load-env.ps1          # dot-source from the repo root
    . $PSScriptRoot\load-env.ps1  # dot-source from anywhere
#>

$repoRoot = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { $PWD.Path }

# --- helper: parse a KEY=VALUE file into process-level env vars -----------
function _LoadEnvFile([string]$Path) {
    $count = 0
    Get-Content $Path | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*?)\s*=\s*(.*)\s*$') {
            $key = $Matches[1].Trim()
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($key, $value)
            $count++
        }
    }
    Write-Host "  .env $count vars loaded from $Path" -ForegroundColor DarkGray
}

# --- locate and load .env ------------------------------------------------
$envFile = $null
$candidate = Join-Path $repoRoot '.env'
if (Test-Path $candidate) { $envFile = $candidate }
if (-not $envFile) {
    $candidate = Join-Path $PWD '.env'
    if (Test-Path $candidate) { $envFile = $candidate }
}
if ($envFile) {
    _LoadEnvFile $envFile
}
else {
    Write-Warning "load-env: .env not found — skipping."
}

# --- locate and load .shell.env (optional) --------------------------------
$shellEnv = Join-Path $repoRoot '.shell.env'
if (Test-Path $shellEnv) {
    _LoadEnvFile $shellEnv
}

# --- prepend local dev directories to PATH --------------------------------
$devPaths = @(
    $repoRoot
    (Join-Path $repoRoot 'bin')
    (Join-Path $repoRoot '.venv' 'Scripts')
)
$env:PATH = ($devPaths -join ';') + ";$env:PATH"

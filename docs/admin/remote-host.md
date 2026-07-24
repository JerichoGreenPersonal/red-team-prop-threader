# Remote host setup — RED Team Prop Threader

Run the bot on an always-on Windows machine (for example via Remote Desktop) so it does not depend on your laptop staying awake.

Socket Mode is the primary inbound path: the host needs outbound HTTPS to Slack and ShotGrid. No public Request URL or tunnel is required.

## Rule: one live instance

Only one web+worker pair may use the same Slack app tokens at a time.

1. On your laptop, stop any running stack before starting on the remote host.
2. After the remote host is the canonical instance, do not run `.\bin\run-local.ps1` on the laptop unless you first stop the remote stack.

## One-time setup on the remote machine

### 1. Prerequisites

- Windows account that stays logged in, or a boot-time task that can run whether or not you are in an RDP session
- Python 3.11 available to the repo `uv` workflow (same as laptop)
- Outbound HTTPS to Slack and `respawn.shotgunstudio.com`

### 2. Get the code

Clone or copy the repo to a stable path, for example:

```text
C:\Apps\red-team-prop-threader
```

Prefer git clone so you can pull updates later:

```powershell
cd C:\Apps
git clone <your-repo-url> red-team-prop-threader
cd red-team-prop-threader
git checkout feature/red-team-prop-threader
```

### 3. Install dependencies

```powershell
cd C:\Apps\red-team-prop-threader
.\uv.exe sync --all-groups
```

If `uv.exe` is missing, use the same install path you use on the laptop (`bin\setup\get-uv.ps1` or copy `uv.exe` into the repo root).

### 4. Create `.env`

```powershell
Copy-Item .env.example .env
```

Fill at least:

| Variable | Notes |
| --- | --- |
| `SLACK_BOT_TOKEN` | `xoxb-...` |
| `SLACK_SIGNING_SECRET` | App signing secret |
| `SLACK_APP_TOKEN` | Socket Mode app-level token `xapp-...` with `connections:write` |
| `SHOTGRID_SCRIPT_NAME` | ShotGrid Script user name |
| `SHOTGRID_SCRIPT_KEY` | ShotGrid Script API key |
| `SHOTGRID_URL` | Keep `https://respawn.shotgunstudio.com` |
| `DATABASE_URL` | Start with `sqlite:///local/prop-threader.db` for pilot |
| `CANVAS_TIMEZONE` | e.g. `America/Los_Angeles` |
| `WEB_HOST` / `WEB_PORT` | Keep `127.0.0.1` / `3000` unless you change health checks |

Leave `TUNNEL_COMMAND` empty for Socket Mode.

Do not commit `.env`. Do not reuse a second live copy of these tokens on another machine.

### 5. First start (manual)

```powershell
cd C:\Apps\red-team-prop-threader
.\bin\run-local.ps1
```

Verify:

```powershell
Invoke-WebRequest http://127.0.0.1:3000/healthz -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:3000/readyz -UseBasicParsing
```

Both should return HTTP 200. Then try `/create-prop-threads` in the pilot channel from the EA workspace.

Logs:

```text
local\logs\web.log
local\logs\worker.log
```

## Auto-start on boot (recommended)

Use Task Scheduler so the stack comes back after reboot without an interactive RDP session.

1. Open **Task Scheduler** → **Create Task** (not "Create Basic Task").
2. **General**
   - Name: `RED Team Prop Threader`
   - Run whether user is logged on or not
   - Run with highest privileges (optional; only if policy requires it)
   - Configure for: Windows 10/11
3. **Triggers** → New → At startup (or At log on for your service account)
4. **Actions** → New → Start a program
   - Program: `powershell.exe`
   - Arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "C:\Apps\red-team-prop-threader\bin\run-local.ps1"
```

5. **Conditions**: uncheck "Start only if on AC power" if this is a desktop/server that may report battery falsely.
6. **Settings**: allow task to run on demand; if it fails, restart every 1 minute up to 3 times.

After creating the task, reboot once and confirm `/healthz` is 200 without manually starting anything.

## Slack health watchdog (recommended)

`/healthz` is localhost-only, so external uptime monitors cannot reach it. A same-machine watchdog posts down/recovery alerts and a daily heartbeat to Slack using the bot token.

Defaults (override in `.env`):

| Variable | Default |
| --- | --- |
| `WATCHDOG_CHANNEL_ID` | `C0B4GJSA1G8` |
| `WATCHDOG_HEALTH_URL` | `http://127.0.0.1:3000/healthz` |
| `WATCHDOG_FAIL_THRESHOLD` | `2` (~10 min at 5-minute schedule) |
| `WATCHDOG_HEARTBEAT_HOUR` | `9` (local machine clock; set the host to Pacific / `America/Los_Angeles`) |

Behavior:

- Polls `/healthz` every run
- Posts one DOWN message after consecutive failures reach the threshold
- Posts one UP message when health returns after a down alert
- Posts one daily heartbeat when healthy, local hour >= heartbeat hour, and no heartbeat yet today
- State: `local\watchdog-state.json`
- Log: `local\logs\watchdog.log`

The bot must already be in channel `C0B4GJSA1G8` (true for the pilot).

### Task Scheduler setup

Create this **after** the `run-local.ps1` auto-start task.

1. Open **Task Scheduler** → **Create Task**.
2. **General**
   - Name: `RED Team Prop Threader Watchdog`
   - Run whether user is logged on or not
   - Configure for: Windows 10/11
3. **Triggers** → New → Daily (or At startup), then set **Repeat task every: 5 minutes** for a duration of **Indefinitely**
4. **Actions** → New → Start a program
   - Program (prefer 64-bit PowerShell):

```text
C:\Windows\Sysnative\WindowsPowerShell\v1.0\powershell.exe
```

   If the task itself already runs as 64-bit, `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` is fine.

   - Arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "C:\Apps\red-team-prop-threader\bin\watchdog.ps1"
```

5. **Conditions**: uncheck "Start only if on AC power" if needed.
6. **Settings**: allow on-demand run; if the task is already running, do not start a new instance.

Manual smoke test:

```powershell
cd C:\Apps\red-team-prop-threader
.\bin\watchdog.ps1
```

## Day-2 operations

| Task | Command / action |
| --- | --- |
| Restart stack | `.\bin\run-local.ps1` (stops owned processes, then starts fresh) |
| Check health | `http://127.0.0.1:3000/healthz` |
| Watchdog once | `.\bin\watchdog.ps1` |
| Watchdog log | `local\logs\watchdog.log` |
| Update code | `git pull`, then `.\uv.exe sync --all-groups`, then `.\bin\run-local.ps1` |
| Retention cleanup | Periodically: `.\uv run prop-threader-retention` (or schedule a second daily task) |
| Rotate secrets | Update `.env`, then restart with `.\bin\run-local.ps1` |

## Migrating history from the laptop (optional)

If you already created threads while running on the laptop and want the same SQLite history on the remote host:

1. Stop both stacks.
2. Copy `local\prop-threader.db` from laptop → remote `local\prop-threader.db`.
3. Start only the remote stack.

If you are fine starting fresh on the remote host, skip the copy and let Alembic create a new DB on first start.

## Production note

This remote-host setup is the right **pilot / single-operator** path. Longer-term production still targets approved internal hosting, PostgreSQL, secret injection, and backups. Socket Mode can remain either way.

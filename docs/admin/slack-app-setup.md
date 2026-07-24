# Slack App Setup — RED Team Prop Threader

This runbook is for EA IT review and for the administrator who imports, installs, and maintains the Slack app.

## Manifest location

Importable YAML:

```text
slack-app-manifest.yaml
```

App display name: **RED Team Prop Threader**  
Slash command: `/create-prop-threads`  
Usage hint (confirm in the Slack UI if prompted): `[ShotGrid page URL]`

## Create the app from the manifest

1. Open [Slack API Apps](https://api.slack.com/apps) → **Create New App** → **From a manifest**.
2. Select the **Electronic Arts** workspace.
3. Paste the contents of `slack-app-manifest.yaml` (Socket Mode is enabled; no public Request URLs are required).
4. Confirm the Usage Hint is `[ShotGrid page URL]` if Slack prompts for it.
5. Create the app, then submit the scopes below for IT approval.
6. After approval, install the app to the EA workspace and copy secrets into approved storage:
   - **Bot User OAuth Token** → `SLACK_BOT_TOKEN` (`xoxb-...`)
   - **Signing Secret** → `SLACK_SIGNING_SECRET`
   - **App-Level Token** (Socket Mode, scope `connections:write`) → `SLACK_APP_TOKEN` (`xapp-...`)
7. Enable **Socket Mode** in the Slack app settings if the imported manifest did not already enable it.
8. Invite the bot to the private development channel `C0B4GJSA1G8`.
9. Verify `/create-prop-threads` while viewing that channel from the EA workspace (not only from a connected external workspace).

## Scope justification (method-by-method)

Only bot token scopes are requested. No user-token scopes, `chat:write.public`, file-write scopes, or channel-management scopes are used.

| Scope | Slack methods / capability | Why required |
| --- | --- | --- |
| `commands` | Slash command `/create-prop-threads` | Receive the prop-thread creation command and optional ShotGrid page URL. |
| `chat:write` | `chat.postMessage`, `chat.update`, `chat.getPermalink` | Post one root message per asset, update bot messages (progress/edit flows), and obtain permalinks for canvas indexing. The bot posts only in channels where it is a member. |
| `channels:read` | `conversations.info`, `conversations.members` | Read public-channel metadata and membership when the bot is invited to a public target channel. Membership is used to validate mentioned users. |
| `groups:read` | `conversations.info`, `conversations.members` | Same as above for private channels (development and production targets may be private). |
| `files:read` | `files.info` | Read the built-in channel-canvas file object so preflight can validate/create/rename the canvas title safely before writing. |
| `users:read` | `users.info` | Resolve display names for non-notifying mentions and busy-owner copy. |
| `im:write` | `conversations.open`, `chat.postMessage` / `chat.update` in the DM | Open and update a single private progress DM to the submitting user. |
| `canvases:read` | `canvases.sections.lookup` | Look up existing group/header sections before indexing so updates can replace in place instead of blindly appending. |
| `canvases:write` | `conversations.canvases.create`, `canvases.edit` | Create the channel canvas when missing and apply narrow one-operation edits to index threads. |

## Socket Mode

Inbound slash commands and interactivity are delivered over Socket Mode (WebSocket), not public HTTPS Request URLs. Local development therefore does not require an approved tunnel hostname.

Generate an App-Level Token with scope `connections:write` and store it as `SLACK_APP_TOKEN`. Keep `SLACK_SIGNING_SECRET` configured; Bolt still uses it for payload verification.

Optional: a Flask `POST /slack/events` route remains available for dual-mode debugging, but production/local primary path is Socket Mode via `prop-threader-web`.

## Secrets and rotation

Store at minimum:

- `SLACK_BOT_TOKEN` — Bot User OAuth Token (`xoxb-...`)
- `SLACK_SIGNING_SECRET` — used to verify Slack request signatures
- `SLACK_APP_TOKEN` — App-Level Token for Socket Mode (`xapp-...`)

Rotation:

1. Regenerate the signing secret and/or reinstall to obtain a new bot token in the Slack app settings.
2. Rotate the App-Level Token if Socket Mode credentials must change.
3. Update approved secrets storage.
4. Restart web and worker processes so they load the new values.
5. Re-verify `/create-prop-threads` in the development channel.

## Private-channel invitation

The bot cannot discover or join private channels by itself. An EA-workspace channel member must invite it (for example `/invite @RED Team Prop Threader`) before the command can run in that channel.

## IT review checklist

- [ ] Manifest YAML reviewed (`slack-app-manifest.yaml`)
- [ ] Socket Mode enabled with App-Level Token (`connections:write`)
- [ ] Only the scopes in the table above are granted
- [ ] No user-token scopes requested
- [ ] App installed to the Electronic Arts workspace
- [ ] Bot invited to development channel `C0B4GJSA1G8`
- [ ] Secrets stored outside the repository
- [ ] Post-install slash-command verification completed from the EA workspace

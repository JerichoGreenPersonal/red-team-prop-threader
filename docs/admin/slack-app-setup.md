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
3. Paste the contents of `slack-app-manifest.yaml`.
4. Before importing, replace every occurrence of:

   ```text
   https://prop-threader-dev.example.invalid
   ```

   with the approved stable HTTPS development hostname (same host for slash-command URL and interactivity request URL). The `.example.invalid` value is intentional and non-routable so an unedited import cannot receive live traffic.
5. Confirm the Usage Hint is `[ShotGrid page URL]` if Slack prompts for it.
6. Create the app, then submit the scopes below for IT approval.
7. After approval, install the app to the EA workspace and copy the **Bot User OAuth Token** and **Signing Secret** into approved secrets storage. Map them to `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET`.
8. Invite the bot to the private development channel `C0B4GJSA1G8`.
9. Verify `/create-prop-threads` while viewing that channel from the EA workspace (not only from a connected external workspace).
10. For production, replace the development request URLs with the production HTTPS base URL and rotate secrets if the development credentials must not be reused.

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
| `canvases:write` | `conversations.canvases.create`, `canvases.edit`, `canvases.sections.lookup` | Create the channel canvas when missing, look up existing group sections, and apply narrow one-operation edits to index threads. |

## Interactivity and request URLs

Both of these must point at the same HTTPS base + `/slack/events` path:

- Slash command Request URL
- Interactivity Request URL

Development uses the approved tunnel hostname. Production uses the approved internal HTTPS host. Socket Mode is disabled; the app expects signed HTTPS callbacks.

## Secrets and rotation

Store at minimum:

- `SLACK_BOT_TOKEN` — Bot User OAuth Token (`xoxb-...`)
- `SLACK_SIGNING_SECRET` — used to verify Slack request signatures
- `SLACK_PUBLIC_BASE_URL` — public HTTPS origin used in the manifest URLs

Rotation:

1. Regenerate the signing secret and/or reinstall to obtain a new bot token in the Slack app settings.
2. Update approved secrets storage.
3. Restart web and worker processes so they load the new values.
4. Re-verify `/create-prop-threads` in the development channel.

## Private-channel invitation

The bot cannot discover or join private channels by itself. An EA-workspace channel member must invite it (for example `/invite @RED Team Prop Threader`) before the command can run in that channel.

## IT review checklist

- [ ] Manifest YAML reviewed (`slack-app-manifest.yaml`)
- [ ] Request URLs use an approved HTTPS hostname (not `.example.invalid` in the imported app)
- [ ] Only the scopes in the table above are granted
- [ ] No user-token scopes requested
- [ ] App installed to the Electronic Arts workspace
- [ ] Bot invited to development channel `C0B4GJSA1G8`
- [ ] Secrets stored outside the repository
- [ ] Post-install slash-command verification completed from the EA workspace

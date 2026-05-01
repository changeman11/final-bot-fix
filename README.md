# Scrim Poll Bot

A Discord bot for esports teams to coordinate scrims. Every day at midnight Sydney time, it posts an availability poll in your team's channel — players react with the times they're free, and a live availability board shows which other teams (across every server using the bot) have a full 5 ready at each time slot.

## Features

- 📅 **Daily availability poll** — auto-posts at midnight (Sydney time) with 11 time slots from 5:00 PM to 10:00 PM
- 🌍 **Local timezones** — times in the poll automatically display in each player's own timezone
- 📋 **Live availability board** — shows which other teams have a full 5 free at each time slot, updates as reactions come in
- 🔔 **Custom ping** — set `@everyone`, `@here`, or a specific role to be pinged with each daily poll
- 🔄 **Catch-up logic** — if the bot is offline at midnight, it posts the missed poll as soon as it comes back online
- 🔒 **Opt-out matchmaking** — teams can hide themselves from the cross-server board with one command
- 🤝 **Multi-server** — one bot serves all teams; each server is configured independently

## Setup (server admins)

1. Click the bot's invite link and add it to your server.
2. Go to the channel where you want the daily poll posted.
3. Run `!setchannel` (requires the **Manage Server** permission).
4. (Optional) Set up a ping with `!setping @YourScrimRole`.
5. Done! The bot will post a poll there every day at midnight Sydney time.

## Commands

### Setup (admin only)

| Command | Description |
|---|---|
| `!setchannel` | Set the current channel for daily polls |
| `!unsetchannel` | Stop daily polls in this server |
| `!setping @Role` | Set a ping (`@everyone`, `@here`, or a role) shown above each poll |
| `!unsetping` | Remove the ping |
| `!matchmaking on` | Show this team on other servers' availability boards (default) |
| `!matchmaking off` | Hide this team from other servers' boards |
| `!matchmaking status` | Check current matchmaking visibility |

### Anyone can use

| Command | Description |
|---|---|
| `!scrim` | Post a poll right now (also counts toward today's catch-up) |
| `!scrimhelp` | Show the full command list |

## How matchmaking works

When **5+ of your players** react to the same time slot on the daily poll, your server name automatically appears on every other team's "Live Scrim Availability" board. Their server names appear on yours too, at any slot where they have a full 5.

The bot only displays availability — it doesn't pair teams or message anyone privately. **You DM the other team's captain (or your contact in their Discord) to arrange the scrim.** That way teams choose who they want to play based on skill, history, or whatever.

To disable cross-team visibility, run `!matchmaking off`. Your team's reactions still work normally — you just won't appear on or see other teams' boards.

## How the daily poll works

- Posts at midnight Sydney time (so you see "tonight's" scrims first thing in the morning)
- 11 time slots from 5:00 PM to 10:00 PM in 30-minute increments
- Each slot uses Discord's dynamic timestamp format, so times automatically convert to each viewer's local timezone
- Players react with **all** times they're available (multiple reactions encouraged)
- The bot adds the first reaction to each slot, so the threshold for a "full 5" is actually 6 total reactions (5 humans + bot)

## Self-hosting

If you want to run your own instance instead of using the shared bot:

### Requirements

- Python 3.10+ (3.13 needs `audioop-lts`)
- A Discord application with a bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- A host that runs 24/7 (Railway, Fly.io, a VPS, etc.)

### Files

- `scrim_bot.py` — main bot
- `requirements.txt` — dependencies
- `Procfile` — for Railway/Heroku-style hosts

### Environment variables

- `BOT_TOKEN` — your Discord bot token (required)

### Persistent storage

The bot stores config in JSON files (`channels.json`, `last_poll.json`, etc.). It looks for a `/data` directory first (a Railway Volume mount path), falling back to the working directory if `/data` doesn't exist. **On Railway, mount a volume at `/data`** or your config will be wiped on every redeploy.

### Discord bot permissions

The invite link should request these permissions (integer: `67648`):
- Send Messages
- Add Reactions
- Read Message History
- Embed Links
- Use External Emojis

For the `!setping @everyone` feature to actually notify people, the bot also needs **"Mention @everyone, @here, and All Roles"** in the channel.

### Required intents

Enable in the Developer Portal under your bot's settings:
- **Message Content Intent** (required for prefix commands like `!scrim`)
- Server Members Intent is **not** required

## Configuration

The top of `scrim_bot.py` has these knobs:

```python
HOST_TZ    = "Australia/Sydney"   # anchor timezone for time slots
POLL_HOUR  = 0                    # hour to post (0 = midnight)
POLL_MIN   = 0                    # minute to post
TEAM_SIZE  = 5                    # players needed for a full team
SLOT_TIMES = [...]                # the 11 time slots
```

Edit and redeploy if you want different defaults.

## Troubleshooting

**No poll posted at midnight** — check your hosting provider's logs for errors. The bot will catch up automatically the next time it comes online (look for `[CATCH-UP]` log lines).

**Pings aren't notifying people** — the bot needs the **Mention @everyone, @here, and All Roles** channel permission. Check Channel Settings → Permissions for your bot's role.

**Other teams aren't showing on the board** — confirm they ran `!setchannel` in their server, that they have 5+ reactions on a slot, and that they haven't disabled matchmaking with `!matchmaking off`.

**Config keeps disappearing on redeploy (Railway)** — you need a Volume mounted at `/data`. Settings → Volumes → New Volume → mount path `/data`.

## License & contributions

Open source. Feel free to fork, modify, or self-host. Issues and PRs welcome.

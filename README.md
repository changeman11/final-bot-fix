# Scrim Poll Bot

A Discord bot for esports teams to coordinate scrims across multiple servers. Every day at midnight Sydney time, it posts an availability poll in your team's channel — players react with the times they're free, and a live cross-server availability board shows which other teams have a full 5 ready at each time slot. Players can also flag themselves as available "fills" for any team, and managers can claim them with a single reaction.

## Features

- 📅 **Daily availability poll** — auto-posts at midnight (Sydney time) with 11 time slots from 5:00 PM to 10:00 PM
- 🌍 **Local timezones** — times in the poll automatically display in each player's own timezone
- 📋 **Live availability board** — shows which other teams have a full 5 free at each time slot, edits in place as reactions come in
- 🆘 **Cross-server fill pool** — players react with ✅ to flag themselves as available fills for any team; managers claim them with one click
- 🔔 **Custom ping** — set `@everyone`, `@here`, or a specific role to be pinged with each daily poll
- ⚡ **Slash commands** — every command works as both `/command` (with autocomplete) and `!command` (prefix)
- 🔄 **Catch-up logic** — if the bot is offline at midnight, it posts the missed poll as soon as it comes back online
- 🔒 **Opt-out matchmaking** — teams can hide themselves from the cross-server board with one command
- 🤝 **Multi-server** — one bot serves all teams; each server is configured independently

## Setup (server admins)

1. Click the bot's invite link and add it to your server (the link must include `applications.commands` scope for slash commands).
2. Go to the channel where you want the daily poll posted.
3. Run `/setchannel` (requires the **Manage Server** permission).
4. (Optional) Set up a ping with `/setping @YourScrimRole`.
5. Done! The bot will post a poll there every day at midnight Sydney time.

## Commands

All commands work as **both** slash commands (`/command`) and prefix commands (`!command`). Slash commands have autocomplete and parameter hints, so they're recommended.

### Setup (admin only — requires Manage Server permission)

| Command | Description |
|---|---|
| `/setchannel` | Set the current channel for daily polls |
| `/unsetchannel` | Stop daily polls in this server |
| `/setping @Role` | Set a ping (`@everyone`, `@here`, or a role) shown above each poll |
| `/unsetping` | Remove the ping |
| `/matchmaking on` | Show this team on other servers' availability boards (default) |
| `/matchmaking off` | Hide this team from other servers' boards |
| `/matchmaking status` | Check current matchmaking visibility |

### Anyone can use

| Command | Description |
|---|---|
| `/scrim` | Post a poll right now (skipped if today already has one) |
| `/scrimhelp` | Show the full command list |

### Fill claims (admin only)

| Command | Description |
|---|---|
| Click 🇦 / 🇧 / 🇨 reaction on the board | Claim that fill for **all** their available times |
| Remove the reaction | Release the fill back to the pool |
| `/claim @user 8pm` | Backup command — claim a fill for a specific time |
| `/unclaim @user 8pm` | Backup command — release a fill from a specific time |

### Reset (admin only — use sparingly)

| Command | Description |
|---|---|
| `/refreshboard` | Delete and recreate the availability board (cleans duplicates) |
| `/refreshpoll` | Delete and recreate today's poll (⚠️ erases all current reactions) |

## How matchmaking works

When **5+ of your players** react to the same time slot on the daily poll, your server name automatically appears on every other team's "Live Scrim Availability" board. Their server names appear on yours too, at any slot where they have a full 5.

The bot only displays availability — it doesn't pair teams or message anyone privately. **You DM the other team's captain (or your contact in their Discord) to arrange the scrim.** That way teams choose who they want to play based on skill, history, or whatever.

To disable cross-team visibility, run `/matchmaking off`. Your team's reactions still work normally — you just won't appear on or see other teams' boards.

## How the fill pool works

If you only have 4 players free for a slot, you can pick up a "fill" from another team to round out your roster.

**For players who want to fill:**
1. React to the daily poll with the time slots you're free for (same as normal)
2. **Also react with ✅** to flag that you're willing to fill for any team
3. Your home team still gets priority — you'll only appear in the fill pool when your home team doesn't have 5+ at a given slot

**For managers needing a fill:**
1. The availability board shows a 🆘 **Fills available** section listing all opted-in players from other servers
2. Each fill has a letter emoji next to their name (🇦, 🇧, 🇨, etc.)
3. Click the letter emoji on the board → bot claims that fill for **all** the time slots they're free for, and DMs them to let them know
4. Remove the reaction → fill is released back to the pool
5. The fill pool is shared across all servers — first come, first served

When you claim a fill, they count toward your team's "5+ ready" status, and they're removed from other teams' visible fill pool.

## How the daily poll works

- Posts at midnight Sydney time (so you see "tonight's" scrims first thing in the morning)
- 11 time slots from 5:00 PM to 10:00 PM in 30-minute increments
- Each slot uses Discord's dynamic timestamp format, so times automatically convert to each viewer's local timezone
- Players react with **all** times they're available (multiple reactions encouraged)
- Plus ✅ if they're willing to fill for other teams
- The bot adds the first reaction to each slot, so the threshold for a "full 5" is actually 6 total reactions (5 humans + bot)



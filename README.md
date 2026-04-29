# Scrim Poll Bot

A Discord bot that posts a daily scrim availability poll at 8:00 AM (Sydney time).

## Setup (server admins)

1. Add the bot to your server using the invite link.
2. Go to the channel where you want polls posted.
3. Type `!setchannel` (you need Manage Server permission).
4. That's it! The bot will post a poll there every day at 8:00 AM AEST.

## Commands

| Command | Description |
|---|---|
| `!setchannel` | Set the current channel for daily polls (admin) |
| `!unsetchannel` | Stop daily polls in this server (admin) |
| `!scrim` | Post a poll immediately |
| `!scrimhelp` | Show command list |

## How the poll works

The bot posts 11 time slots (5:00 PM through 10:00 PM, 30-min increments). Members react with the times they're available. Most reactions wins.

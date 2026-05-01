import discord
from discord.ext import commands
from discord import app_commands
import datetime
import pytz
import json
import os
import asyncio
import re

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN  = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
HOST_TZ    = "Australia/Sydney"   # The "home" timezone the time slots are anchored to
POLL_HOUR  = 0                    # 0 = midnight (in HOST_TZ) — when the daily poll is posted
POLL_MIN   = 0
TEAM_SIZE  = 5                    # Players needed for a full team (bot's own react not counted)

# Persistent storage location
# /data is a Railway Volume that survives redeploys
# Falls back to the local folder if /data doesn't exist (for local testing)
DATA_DIR = "/data" if os.path.isdir("/data") else "."
CONFIG_FILE       = os.path.join(DATA_DIR, "channels.json")
LAST_POLL_FILE    = os.path.join(DATA_DIR, "last_poll.json")
POLL_MSGS_FILE    = os.path.join(DATA_DIR, "poll_messages.json")
BOARD_MSGS_FILE   = os.path.join(DATA_DIR, "board_messages.json")
MATCHMAKING_FILE  = os.path.join(DATA_DIR, "matchmaking.json")
PINGS_FILE        = os.path.join(DATA_DIR, "pings.json")

# Time slots in HOST_TZ (24-hour format: hour, minute)
SLOT_TIMES = [
    (17, 0), (17, 30),
    (18, 0), (18, 30),
    (19, 0), (19, 30),
    (20, 0), (20, 30),
    (21, 0), (21, 30),
    (22, 0),
]

EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟", "🅰️"]


def emoji_to_label(emoji):
    """Convert reaction emoji to readable time string like '8:00 PM'."""
    if emoji not in EMOJIS:
        return emoji
    idx = EMOJIS.index(emoji)
    hour, minute = SLOT_TIMES[idx]
    period = "PM" if hour >= 12 else "AM"
    h12 = hour if hour <= 12 else hour - 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{minute:02d} {period}"
# ───────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ─── PERSISTENT STORAGE HELPERS ───────────────────────────────────────────────
def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default

def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def load_channels():             return _load_json(CONFIG_FILE, {})
def save_channels(d):            _save_json(CONFIG_FILE, d)
def load_last_poll_dates():      return _load_json(LAST_POLL_FILE, {})
def save_last_poll_dates(d):     _save_json(LAST_POLL_FILE, d)
def load_poll_messages():        return _load_json(POLL_MSGS_FILE, {})
def save_poll_messages(d):       _save_json(POLL_MSGS_FILE, d)
def load_board_messages():       return _load_json(BOARD_MSGS_FILE, {})
def save_board_messages(d):      _save_json(BOARD_MSGS_FILE, d)
def load_matchmaking_settings(): return _load_json(MATCHMAKING_FILE, {})
def save_matchmaking_settings(d):_save_json(MATCHMAKING_FILE, d)
def load_pings():                return _load_json(PINGS_FILE, {})
def save_pings(d):               _save_json(PINGS_FILE, d)

def is_matchmaking_enabled(guild_id):
    """Default ON — only OFF if explicitly disabled (opt-out model)."""
    return load_matchmaking_settings().get(str(guild_id), True)

def get_ping_for(guild_id):
    return load_pings().get(str(guild_id))

def mark_poll_sent(guild_id):
    dates = load_last_poll_dates()
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%Y-%m-%d")
    dates[str(guild_id)] = today
    save_last_poll_dates(dates)

def record_poll_message(guild_id, channel_id, message_id):
    msgs = load_poll_messages()
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%Y-%m-%d")
    msgs[str(guild_id)] = {"channel_id": str(channel_id), "message_id": str(message_id), "date": today}
    save_poll_messages(msgs)

def record_board_message(guild_id, channel_id, message_id):
    msgs = load_board_messages()
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%Y-%m-%d")
    msgs[str(guild_id)] = {"channel_id": str(channel_id), "message_id": str(message_id), "date": today}
    save_board_messages(msgs)


# ─── BUILD TIME SLOTS WITH DYNAMIC TIMESTAMPS ─────────────────────────────────
def build_time_slots():
    tz = pytz.timezone(HOST_TZ)
    now = datetime.datetime.now(tz)
    slots = []
    for emoji, (hour, minute) in zip(EMOJIS, SLOT_TIMES):
        slot_dt = tz.localize(datetime.datetime(now.year, now.month, now.day, hour, minute))
        if slot_dt < now:
            slot_dt += datetime.timedelta(days=1)
        unix = int(slot_dt.timestamp())
        slots.append((emoji, f"<t:{unix}:t>"))
    return slots


# ─── POLL POSTING ─────────────────────────────────────────────────────────────
async def post_poll(channel):
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%A, %B %d")
    slots = build_time_slots()
    lines = [f"{emoji}  {ts}" for emoji, ts in slots]
    poll_body = "\n".join(lines)

    embed = discord.Embed(
        title=f"📅 Scrim Availability — {today}",
        description=(
            "React with the time(s) you're **free to scrim** tonight.\n"
            "Times shown in **your local timezone** automatically.\n\n"
            + poll_body
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="React to ALL times you're available!")

    ping = get_ping_for(channel.guild.id)
    content = ping if ping else None
    allowed = discord.AllowedMentions(everyone=True, roles=True, users=False)

    msg = await channel.send(content=content, embed=embed, allowed_mentions=allowed)
    for emoji, _ in slots:
        await msg.add_reaction(emoji)

    record_poll_message(channel.guild.id, channel.id, msg.id)

    if is_matchmaking_enabled(channel.guild.id):
        await post_or_update_board(channel.guild.id, force_new=True)

    return msg


async def post_polls_to_all_servers(reason="scheduled"):
    channels = load_channels()
    today_str = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%Y-%m-%d")
    for guild_id, channel_id in channels.items():
        channel = bot.get_channel(int(channel_id))
        if channel:
            try:
                await post_poll(channel)
                mark_poll_sent(guild_id)
                print(f"[OK] Posted {reason} poll in guild {guild_id} for {today_str}")
            except Exception as e:
                print(f"[ERROR] Failed to post in {channel_id}: {e}")
        else:
            print(f"[WARN] Channel {channel_id} not found for guild {guild_id}")


# ─── CATCH-UP CHECK ───────────────────────────────────────────────────────────
async def check_missed_polls():
    tz = pytz.timezone(HOST_TZ)
    today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")
    channels = load_channels()
    last_polls = load_last_poll_dates()
    print(f"[CATCH-UP] Today is {today_str}. Found {len(channels)} configured server(s).")

    missed_any = False
    for guild_id, channel_id in channels.items():
        last_date = last_polls.get(str(guild_id))
        if last_date != today_str:
            channel = bot.get_channel(int(channel_id))
            if channel:
                try:
                    await post_poll(channel)
                    mark_poll_sent(guild_id)
                    print(f"[CATCH-UP] Posted missed poll for guild {guild_id} (last: {last_date or 'never'})")
                    missed_any = True
                except Exception as e:
                    print(f"[ERROR] Catch-up failed for {channel_id}: {e}")
            else:
                print(f"[WARN] Channel {channel_id} not found for guild {guild_id}")

    if not missed_any and channels:
        print("[CATCH-UP] All servers already have today's poll. No catch-up needed.")


# ─── DAILY SCHEDULER ──────────────────────────────────────────────────────────
async def daily_poll_loop():
    await bot.wait_until_ready()
    await check_missed_polls()
    tz = pytz.timezone(HOST_TZ)

    while not bot.is_closed():
        now = datetime.datetime.now(tz)
        target = tz.localize(datetime.datetime(now.year, now.month, now.day, POLL_HOUR, POLL_MIN))
        if target <= now:
            target += datetime.timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        print(f"[SCHEDULER] Next poll at {target.isoformat()} (in {wait_seconds:.0f}s)")
        try:
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            break
        await post_polls_to_all_servers(reason="scheduled")


# ─── AVAILABILITY BOARD ───────────────────────────────────────────────────────
async def get_full_team_slots(guild_id):
    poll_messages = load_poll_messages()
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%Y-%m-%d")
    info = poll_messages.get(str(guild_id))
    if not info or info.get("date") != today:
        return []

    channel = bot.get_channel(int(info["channel_id"]))
    if not channel:
        return []

    try:
        msg = await channel.fetch_message(int(info["message_id"]))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return []

    full_slots = []
    for reaction in msg.reactions:
        emoji_str = str(reaction.emoji)
        if emoji_str in EMOJIS and reaction.count >= TEAM_SIZE + 1:
            full_slots.append(emoji_str)
    return full_slots


async def build_board_embed(viewer_guild_id):
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%A, %B %d")
    channels = load_channels()
    slot_to_teams = {emoji: [] for emoji in EMOJIS}
    my_full_slots = []

    for gid in channels.keys():
        if not is_matchmaking_enabled(gid):
            continue
        full_slots = await get_full_team_slots(gid)
        guild_obj = bot.get_guild(int(gid))
        guild_name = guild_obj.name if guild_obj else f"Server {gid}"

        if str(gid) == str(viewer_guild_id):
            my_full_slots = full_slots
        else:
            for emoji in full_slots:
                slot_to_teams[emoji].append(guild_name)

    lines = []
    if my_full_slots:
        my_labels = ", ".join(emoji_to_label(e) for e in my_full_slots)
        lines.append(f"✅ **Your team has 5+ at:** {my_labels}")
    else:
        lines.append("⏳ **Your team needs more reactions to show up here.**")

    lines.append("")
    lines.append("🌐 **Other teams with 5+ players free tonight:**")

    any_others = False
    for emoji in EMOJIS:
        teams = slot_to_teams[emoji]
        if teams:
            any_others = True
            label = emoji_to_label(emoji)
            team_list = ", ".join(teams)
            lines.append(f"• **{label}** — {team_list}")

    if not any_others:
        lines.append("_No other teams have a full 5 yet. Check back as reactions come in!_")

    lines.append("")
    lines.append("_DM the team's captain or your contact in their Discord to set up a match._")
    lines.append("_Use `/matchmaking off` to hide your team from this board._")

    embed = discord.Embed(
        title=f"📋 Live Scrim Availability — {today}",
        description="\n".join(lines),
        color=discord.Color.green(),
    )
    embed.set_footer(text="Updates live as teams react to today's poll")
    return embed


async def post_or_update_board(guild_id, force_new=False):
    if not is_matchmaking_enabled(guild_id):
        return

    channels = load_channels()
    channel_id = channels.get(str(guild_id))
    if not channel_id:
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        return

    embed = await build_board_embed(guild_id)
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%Y-%m-%d")
    boards = load_board_messages()
    info = boards.get(str(guild_id))

    if info and info.get("date") == today and not force_new:
        try:
            board_channel = bot.get_channel(int(info["channel_id"]))
            if board_channel:
                msg = await board_channel.fetch_message(int(info["message_id"]))
                await msg.edit(embed=embed)
                return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    try:
        msg = await channel.send(embed=embed)
        record_board_message(guild_id, channel.id, msg.id)
    except discord.HTTPException as e:
        print(f"[ERROR] Failed to post board for guild {guild_id}: {e}")


async def update_all_boards():
    channels = load_channels()
    for gid in channels.keys():
        if is_matchmaking_enabled(gid):
            try:
                await post_or_update_board(gid, force_new=False)
            except Exception as e:
                print(f"[ERROR] Failed to update board for guild {gid}: {e}")


# ─── REACTION EVENTS ──────────────────────────────────────────────────────────
def is_today_poll_message(payload):
    if not payload.guild_id:
        return False
    poll_messages = load_poll_messages()
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%Y-%m-%d")
    info = poll_messages.get(str(payload.guild_id))
    if not info or info.get("date") != today:
        return False
    return str(payload.message_id) == info["message_id"]


@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    if not is_today_poll_message(payload):
        return
    if str(payload.emoji) not in EMOJIS:
        return
    await update_all_boards()


@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id:
        return
    if not is_today_poll_message(payload):
        return
    if str(payload.emoji) not in EMOJIS:
        return
    await update_all_boards()


# ─── HYBRID COMMANDS (both ! and / work) ──────────────────────────────────────
# hybrid_command = works as !command (prefix) AND /command (slash)

@bot.hybrid_command(name="setchannel", description="Set the current channel for daily scrim polls")
@commands.has_permissions(manage_guild=True)
async def setchannel(ctx):
    channels = load_channels()
    channels[str(ctx.guild.id)] = str(ctx.channel.id)
    save_channels(channels)
    await ctx.send(f"✅ Daily scrim polls will now post in {ctx.channel.mention} at {POLL_HOUR:02d}:{POLL_MIN:02d} {HOST_TZ}.")


@bot.hybrid_command(name="unsetchannel", description="Stop daily scrim polls in this server")
@commands.has_permissions(manage_guild=True)
async def unsetchannel(ctx):
    channels = load_channels()
    if str(ctx.guild.id) in channels:
        del channels[str(ctx.guild.id)]
        save_channels(channels)
        await ctx.send("🛑 Daily scrim polls disabled for this server.")
    else:
        await ctx.send("This server doesn't have a poll channel set.")


@bot.hybrid_command(name="scrim", description="Post a scrim availability poll right now")
async def scrim(ctx):
    await ctx.defer()  # acknowledge the slash command (avoids 'interaction failed')
    await post_poll(ctx.channel)
    mark_poll_sent(ctx.guild.id)
    await ctx.send("✅ Poll posted!", ephemeral=True)
    # Try to delete the original ! message if it was a prefix command
    if ctx.message and ctx.message.author != bot.user:
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass


@bot.hybrid_command(name="setping", description="Set a ping (@everyone, @here, or @Role) above each daily poll")
@app_commands.describe(ping="The ping to add: @everyone, @here, or a role mention")
@commands.has_permissions(manage_guild=True)
async def setping(ctx, *, ping: str = None):
    if ping is None:
        await ctx.send(
            "Usage: `/setping @everyone` or `/setping @here` or `/setping @YourRole`\n"
            "Use `/unsetping` to remove it.",
            ephemeral=True,
        )
        return

    ping = ping.strip()
    valid = False
    if ping in ("@everyone", "@here"):
        valid = True
    elif re.fullmatch(r"<@&\d+>", ping):
        role_id = int(ping[3:-1])
        if ctx.guild.get_role(role_id):
            valid = True

    if not valid:
        await ctx.send(
            "❌ That doesn't look like a valid ping. Use:\n"
            "• `/setping @everyone`\n"
            "• `/setping @here`\n"
            "• `/setping @YourRole` (the role must exist in this server)",
            ephemeral=True,
        )
        return

    pings = load_pings()
    pings[str(ctx.guild.id)] = ping
    save_pings(pings)
    await ctx.send(
        f"✅ Daily polls will now ping {ping} above the message.",
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.hybrid_command(name="unsetping", description="Remove the ping above daily polls")
@commands.has_permissions(manage_guild=True)
async def unsetping(ctx):
    pings = load_pings()
    gid = str(ctx.guild.id)
    if gid in pings:
        del pings[gid]
        save_pings(pings)
        await ctx.send("🛑 Daily polls will no longer ping anyone.")
    else:
        await ctx.send("This server doesn't have a ping set.")


@bot.hybrid_command(name="matchmaking", description="Enable/disable cross-server availability board")
@app_commands.describe(mode="on, off, or status")
@app_commands.choices(mode=[
    app_commands.Choice(name="on", value="on"),
    app_commands.Choice(name="off", value="off"),
    app_commands.Choice(name="status", value="status"),
])
@commands.has_permissions(manage_guild=True)
async def matchmaking(ctx, mode: str = None):
    settings = load_matchmaking_settings()
    gid = str(ctx.guild.id)

    if mode is None or mode.lower() == "status":
        enabled = is_matchmaking_enabled(gid)
        state = "ON ✅" if enabled else "OFF ❌"
        await ctx.send(
            f"**Matchmaking is currently {state}** for this server.\n"
            f"Use `/matchmaking on` or `/matchmaking off` to change."
        )
        return

    mode = mode.lower()
    if mode == "on":
        settings[gid] = True
        save_matchmaking_settings(settings)
        await ctx.send("✅ Matchmaking **enabled**. Your team will appear on other servers' boards when 5+ players react to a slot.")
        await post_or_update_board(ctx.guild.id, force_new=True)
    elif mode == "off":
        settings[gid] = False
        save_matchmaking_settings(settings)
        await ctx.send("❌ Matchmaking **disabled**. Your team is now hidden from other servers' boards.")
    else:
        await ctx.send("Usage: `/matchmaking on`, `/matchmaking off`, or `/matchmaking status`")


@bot.hybrid_command(name="scrimhelp", description="Show all available scrim bot commands")
async def scrimhelp(ctx):
    embed = discord.Embed(
        title="🎮 Scrim Bot Commands",
        description=(
            "All commands work as both `/command` (slash) and `!command` (prefix).\n\n"
            "**Setup (admin only):**\n"
            "• `/setchannel` — Use the current channel for daily polls\n"
            "• `/unsetchannel` — Stop daily polls\n"
            "• `/setping @Role` — Add a ping above each poll (`@everyone`, `@here`, or `@Role`)\n"
            "• `/unsetping` — Remove the ping\n"
            "• `/matchmaking on/off/status` — Toggle cross-server availability board\n\n"
            "**Anyone:**\n"
            "• `/scrim` — Post a poll right now\n"
            "• `/scrimhelp` — Show this message\n\n"
            f"📅 Daily polls auto-post at **{POLL_HOUR:02d}:{POLL_MIN:02d} {HOST_TZ}**.\n"
            "🌍 Times in the poll show in **each player's local timezone**.\n"
            f"📋 When your team has **{TEAM_SIZE}+ reactions** on a slot, your server name "
            "appears on other teams' availability boards (and theirs on yours)."
        ),
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed)


# ─── ERROR HANDLING ───────────────────────────────────────────────────────────
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need the **Manage Server** permission to use this command.")
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        print(f"[ERROR] {error}")


@bot.tree.error
async def on_app_command_error(interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need the **Manage Server** permission to use this command.",
            ephemeral=True,
        )
    else:
        print(f"[SLASH ERROR] {error}")
        try:
            await interaction.response.send_message(
                "❌ Something went wrong. Try again in a moment.",
                ephemeral=True,
            )
        except discord.InteractionResponded:
            pass


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} — serving {len(bot.guilds)} servers")
    print(f"Data directory: {DATA_DIR}")
    print(f"Daily poll scheduled for {POLL_HOUR:02d}:{POLL_MIN:02d} {HOST_TZ}")


# Start the scheduler & sync slash commands
async def setup_hook():
    bot.loop.create_task(daily_poll_loop())
    try:
        synced = await bot.tree.sync()
        print(f"[SLASH] Synced {len(synced)} slash command(s) globally.")
        print("[SLASH] Note: global slash commands can take up to 1 hour to appear in all servers.")
    except Exception as e:
        print(f"[SLASH] Failed to sync slash commands: {e}")

bot.setup_hook = setup_hook


bot.run(BOT_TOKEN)

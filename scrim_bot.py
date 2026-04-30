import discord
from discord.ext import commands
import datetime
import pytz
import json
import os
import asyncio

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN  = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
HOST_TZ    = "Australia/Sydney"   # The "home" timezone the time slots are anchored to
POLL_HOUR  = 0                    # 0 = midnight (in HOST_TZ) — when the daily poll is posted
POLL_MIN   = 0

# Persistent storage location
# /data is a Railway Volume that survives redeploys
# Falls back to the local folder if /data doesn't exist (for local testing)
DATA_DIR = "/data" if os.path.isdir("/data") else "."
CONFIG_FILE = os.path.join(DATA_DIR, "channels.json")
LAST_POLL_FILE = os.path.join(DATA_DIR, "last_poll.json")

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
# ───────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ─── PERSISTENT STORAGE ───────────────────────────────────────────────────────
def load_channels():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_channels(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_last_poll_dates():
    if not os.path.exists(LAST_POLL_FILE):
        return {}
    with open(LAST_POLL_FILE, "r") as f:
        return json.load(f)

def save_last_poll_dates(data):
    with open(LAST_POLL_FILE, "w") as f:
        json.dump(data, f, indent=2)

def mark_poll_sent(guild_id):
    """Record today's date (in HOST_TZ) as the last poll date for this guild."""
    dates = load_last_poll_dates()
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%Y-%m-%d")
    dates[str(guild_id)] = today
    save_last_poll_dates(dates)


# ─── BUILD TIME SLOTS WITH DYNAMIC TIMESTAMPS ─────────────────────────────────
def build_time_slots():
    """
    Returns a list of (emoji, discord_timestamp_string) for each slot.
    Discord's <t:UNIX:t> format auto-converts to each viewer's local timezone.
    """
    tz = pytz.timezone(HOST_TZ)
    now = datetime.datetime.now(tz)

    slots = []
    for emoji, (hour, minute) in zip(EMOJIS, SLOT_TIMES):
        # Build a datetime for tonight at this hour in the host timezone
        slot_dt = tz.localize(datetime.datetime(
            now.year, now.month, now.day, hour, minute
        ))
        # If we somehow generate a poll after this time, push it to tomorrow
        if slot_dt < now:
            slot_dt += datetime.timedelta(days=1)
        unix = int(slot_dt.timestamp())
        # <t:UNIX:t>  → "5:00 PM" in viewer's local timezone
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

    msg = await channel.send(embed=embed)
    for emoji, _ in slots:
        await msg.add_reaction(emoji)


async def post_polls_to_all_servers(reason="scheduled"):
    """Posts to every configured server and records the date."""
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
    """On startup: if today's poll hasn't been sent yet for a guild, send it now."""
    tz = pytz.timezone(HOST_TZ)
    now = datetime.datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    channels = load_channels()
    last_polls = load_last_poll_dates()
    print(f"[CATCH-UP] Today is {today_str}. Found {len(channels)} configured server(s).")

    missed_any = False

    for guild_id, channel_id in channels.items():
        last_date = last_polls.get(str(guild_id))
        if last_date != today_str:
            # Haven't posted today yet — catch up
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


# ─── DAILY SCHEDULED POLL (manual sleep loop — avoids clock drift bug) ───────
async def daily_poll_loop():
    """Sleeps until next POLL_HOUR:POLL_MIN in HOST_TZ, then posts polls."""
    await bot.wait_until_ready()

    # First: check for missed polls
    await check_missed_polls()

    tz = pytz.timezone(HOST_TZ)

    while not bot.is_closed():
        now = datetime.datetime.now(tz)
        # Build today's target time
        target = tz.localize(datetime.datetime(
            now.year, now.month, now.day, POLL_HOUR, POLL_MIN
        ))
        # If target already passed today, schedule for tomorrow
        if target <= now:
            target += datetime.timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        print(f"[SCHEDULER] Next poll at {target.isoformat()} (in {wait_seconds:.0f}s)")

        try:
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            break

        # Time to post the scheduled poll
        await post_polls_to_all_servers(reason="scheduled")


# ─── COMMANDS ─────────────────────────────────────────────────────────────────
@bot.command()
@commands.has_permissions(manage_guild=True)
async def setchannel(ctx):
    """Set the current channel as this server's scrim poll channel."""
    channels = load_channels()
    channels[str(ctx.guild.id)] = str(ctx.channel.id)
    save_channels(channels)
    await ctx.send(f"✅ Daily scrim polls will now post in {ctx.channel.mention} at {POLL_HOUR:02d}:{POLL_MIN:02d} {HOST_TZ}.")

@bot.command()
@commands.has_permissions(manage_guild=True)
async def unsetchannel(ctx):
    """Stop daily polls in this server."""
    channels = load_channels()
    if str(ctx.guild.id) in channels:
        del channels[str(ctx.guild.id)]
        save_channels(channels)
        await ctx.send("🛑 Daily scrim polls disabled for this server.")
    else:
        await ctx.send("This server doesn't have a poll channel set.")

@bot.command()
async def scrim(ctx):
    """Manually trigger the poll right now."""
    await post_poll(ctx.channel)
    mark_poll_sent(ctx.guild.id)  # Count manual polls toward today's quota
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

@bot.command()
async def scrimhelp(ctx):
    embed = discord.Embed(
        title="🎮 Scrim Bot Commands",
        description=(
            f"**!setchannel** — Set the current channel for daily polls (admin only)\n"
            f"**!unsetchannel** — Stop daily polls (admin only)\n"
            f"**!scrim** — Post a poll right now\n"
            f"**!scrimhelp** — Show this message\n\n"
            f"Daily polls auto-post at **{POLL_HOUR:02d}:{POLL_MIN:02d} {HOST_TZ}**.\n"
            f"Times in the poll display in **each player's local timezone**."
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


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} — serving {len(bot.guilds)} servers")
    print(f"Data directory: {DATA_DIR}")
    print(f"Daily poll scheduled for {POLL_HOUR:02d}:{POLL_MIN:02d} {HOST_TZ}")


# Start the scheduler as a background task (replaces the buggy tasks.loop)
async def setup_hook():
    bot.loop.create_task(daily_poll_loop())

bot.setup_hook = setup_hook


bot.run(BOT_TOKEN)

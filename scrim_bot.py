import discord
from discord.ext import commands, tasks
import datetime
import pytz
import json
import os

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN  = os.getenv("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
HOST_TZ    = "Australia/Sydney"   # The "home" timezone the time slots are anchored to
POLL_HOUR  = 0                    # 8 AM (in HOST_TZ) — when the daily poll is posted
POLL_MIN   = 0
CONFIG_FILE = "channels.json"

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


# ─── DAILY SCHEDULED POLL ─────────────────────────────────────────────────────
@tasks.loop(time=datetime.time(hour=POLL_HOUR, minute=POLL_MIN, tzinfo=pytz.timezone(HOST_TZ)))
async def daily_poll():
    channels = load_channels()
    for guild_id, channel_id in channels.items():
        channel = bot.get_channel(int(channel_id))
        if channel:
            try:
                await post_poll(channel)
            except Exception as e:
                print(f"[ERROR] Failed to post in {channel_id}: {e}")
        else:
            print(f"[WARN] Channel {channel_id} not found for guild {guild_id}")


# ─── COMMANDS ─────────────────────────────────────────────────────────────────
@bot.command()
@commands.has_permissions(manage_guild=True)
async def setchannel(ctx):
    """Set the current channel as this server's scrim poll channel."""
    channels = load_channels()
    channels[str(ctx.guild.id)] = str(ctx.channel.id)
    save_channels(channels)
    await ctx.send(f"✅ Daily scrim polls will now post in {ctx.channel.mention} at {POLL_HOUR}:00 {HOST_TZ}.")

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
            f"Daily polls auto-post at **{POLL_HOUR}:00 {HOST_TZ}**.\n"
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
    print(f"Daily poll scheduled for {POLL_HOUR:02d}:{POLL_MIN:02d} {HOST_TZ}")
    if not daily_poll.is_running():
        daily_poll.start()


bot.run(BOT_TOKEN)

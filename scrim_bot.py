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
HOST_TZ    = "Australia/Sydney"
POLL_HOUR  = 0                    # 0 = midnight Sydney time
POLL_MIN   = 0
TEAM_SIZE  = 5
MAX_FILL_REACTIONS = 20           # Discord's per-message reaction limit

DATA_DIR = "/data" if os.path.isdir("/data") else "."
CONFIG_FILE       = os.path.join(DATA_DIR, "channels.json")
LAST_POLL_FILE    = os.path.join(DATA_DIR, "last_poll.json")
POLL_MSGS_FILE    = os.path.join(DATA_DIR, "poll_messages.json")
BOARD_MSGS_FILE   = os.path.join(DATA_DIR, "board_messages.json")
MATCHMAKING_FILE  = os.path.join(DATA_DIR, "matchmaking.json")
PINGS_FILE        = os.path.join(DATA_DIR, "pings.json")
CLAIMS_FILE       = os.path.join(DATA_DIR, "claims.json")
FILL_REACTS_FILE  = os.path.join(DATA_DIR, "fill_reactions.json")  # maps board emoji -> fill info per guild

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
FILL_EMOJI = "✅"  # players react with this on the poll to flag themselves as a fill

# Regional indicator emojis A-T (20 of them) used as "claim" buttons on the board
CLAIM_EMOJIS = [
    "🇦", "🇧", "🇨", "🇩", "🇪", "🇫", "🇬", "🇭", "🇮", "🇯",
    "🇰", "🇱", "🇲", "🇳", "🇴", "🇵", "🇶", "🇷", "🇸", "🇹",
]


def emoji_to_label(emoji):
    if emoji not in EMOJIS:
        return emoji
    idx = EMOJIS.index(emoji)
    hour, minute = SLOT_TIMES[idx]
    period = "PM" if hour >= 12 else "AM"
    h12 = hour if hour <= 12 else hour - 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{minute:02d} {period}"


def label_to_emoji(label):
    """Convert a string like '8pm' or '8:30 PM' to the matching slot emoji. Returns None if no match."""
    if not label:
        return None
    s = label.strip().lower().replace(" ", "")
    m = re.match(r"^(\d{1,2})(?::?(\d{2}))?\s*(am|pm)?$", s)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm = m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    for emoji, (h, mm) in zip(EMOJIS, SLOT_TIMES):
        if h == hour and mm == minute:
            return emoji
    return None
# ───────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True  # needed to resolve usernames for fill players
bot = commands.Bot(command_prefix="!", intents=intents)

# Cache of resolved usernames for the current day, so we don't hammer the API
# Format: {user_id: display_name}
_username_cache = {}


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
def load_claims():               return _load_json(CLAIMS_FILE, {})
def save_claims(d):              _save_json(CLAIMS_FILE, d)
def load_fill_reacts():          return _load_json(FILL_REACTS_FILE, {})
def save_fill_reacts(d):         _save_json(FILL_REACTS_FILE, d)


def is_matchmaking_enabled(guild_id):
    return load_matchmaking_settings().get(str(guild_id), True)

def get_ping_for(guild_id):
    return load_pings().get(str(guild_id))

def today_str():
    return datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%Y-%m-%d")

def mark_poll_sent(guild_id):
    dates = load_last_poll_dates()
    dates[str(guild_id)] = today_str()
    save_last_poll_dates(dates)

def has_poll_today(guild_id):
    """Returns True if this guild already had a poll posted today."""
    return load_last_poll_dates().get(str(guild_id)) == today_str()

def record_poll_message(guild_id, channel_id, message_id):
    msgs = load_poll_messages()
    msgs[str(guild_id)] = {"channel_id": str(channel_id), "message_id": str(message_id), "date": today_str()}
    save_poll_messages(msgs)

def record_board_message(guild_id, channel_id, message_id):
    msgs = load_board_messages()
    msgs[str(guild_id)] = {"channel_id": str(channel_id), "message_id": str(message_id), "date": today_str()}
    save_board_messages(msgs)


# ─── CLAIMS ───────────────────────────────────────────────────────────────────
# claims.json structure (keyed by date so old data clears naturally):
# {
#   "2026-05-01": {
#     "<slot_emoji>": [
#       {"fill_user_id", "fill_user_name", "fill_home_guild_id",
#        "claimed_by_guild_id", "claimed_by_guild_name"}
#     ]
#   }
# }

def get_today_claims():
    return load_claims().get(today_str(), {})

def save_today_claims(today_claims):
    # Prune old days — only keep today's
    save_claims({today_str(): today_claims})

def add_claim(slot_emoji, fill_user_id, fill_user_name, fill_home_guild_id, claiming_guild_id, claiming_guild_name):
    today_claims = get_today_claims()
    today_claims.setdefault(slot_emoji, []).append({
        "fill_user_id": str(fill_user_id),
        "fill_user_name": fill_user_name,
        "fill_home_guild_id": str(fill_home_guild_id),
        "claimed_by_guild_id": str(claiming_guild_id),
        "claimed_by_guild_name": claiming_guild_name,
    })
    save_today_claims(today_claims)

def remove_claim(slot_emoji, fill_user_id, claiming_guild_id):
    today_claims = get_today_claims()
    arr = today_claims.get(slot_emoji, [])
    arr = [c for c in arr
           if not (c["fill_user_id"] == str(fill_user_id) and c["claimed_by_guild_id"] == str(claiming_guild_id))]
    today_claims[slot_emoji] = arr
    save_today_claims(today_claims)

def is_already_claimed_for_slot(slot_emoji, fill_user_id):
    """Returns the existing claim dict if this fill is already claimed by ANY team for this slot today."""
    for c in get_today_claims().get(slot_emoji, []):
        if c["fill_user_id"] == str(fill_user_id):
            return c
    return None


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
            f"{poll_body}\n\n"
            f"{FILL_EMOJI} **= I'm available as a FILL** for any team\n"
            "_(react ✅ AND time slot(s) — your home team still gets priority)_"
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
    await msg.add_reaction(FILL_EMOJI)

    record_poll_message(channel.guild.id, channel.id, msg.id)

    # Always post a fresh board with the new poll
    if is_matchmaking_enabled(channel.guild.id):
        await post_or_update_board(channel.guild.id, force_new=True)

    return msg


async def post_polls_to_all_servers(reason="scheduled"):
    channels = load_channels()
    today = today_str()
    for guild_id, channel_id in channels.items():
        # Don't double-post if today's poll already exists for this guild
        if has_poll_today(guild_id):
            print(f"[SKIP] Guild {guild_id} already has today's poll.")
            continue
        channel = bot.get_channel(int(channel_id))
        if channel:
            try:
                await post_poll(channel)
                mark_poll_sent(guild_id)
                print(f"[OK] Posted {reason} poll in guild {guild_id} for {today}")
            except Exception as e:
                print(f"[ERROR] Failed to post in {channel_id}: {e}")
        else:
            print(f"[WARN] Channel {channel_id} not found for guild {guild_id}")


# ─── CATCH-UP CHECK ───────────────────────────────────────────────────────────
async def check_missed_polls():
    today = today_str()
    channels = load_channels()
    last_polls = load_last_poll_dates()
    print(f"[CATCH-UP] Today is {today}. Found {len(channels)} configured server(s).")

    missed_any = False
    for guild_id, channel_id in channels.items():
        if last_polls.get(str(guild_id)) != today:
            channel = bot.get_channel(int(channel_id))
            if channel:
                try:
                    await post_poll(channel)
                    mark_poll_sent(guild_id)
                    print(f"[CATCH-UP] Posted missed poll for guild {guild_id}")
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


# ─── REACTION ANALYSIS ────────────────────────────────────────────────────────
async def resolve_username(user_id, guild_obj=None):
    """
    Best-effort username resolution with multiple fallbacks:
    1. In-process cache (fastest)
    2. Guild member cache (if Members Intent is enabled)
    3. Fetch member from guild API
    4. Fetch user globally (no guild context)
    5. Generic fallback
    """
    uid = int(user_id)
    if uid in _username_cache:
        return _username_cache[uid]

    name = None

    # Try guild member cache first (uses display_name which honours nicknames)
    if guild_obj:
        member = guild_obj.get_member(uid)
        if member:
            name = member.display_name

    # Fetch from guild API if not cached
    if not name and guild_obj:
        try:
            member = await guild_obj.fetch_member(uid)
            if member:
                name = member.display_name
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # Last resort: global user fetch
    if not name:
        try:
            user = await bot.fetch_user(uid)
            if user:
                name = user.display_name or user.name
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    if not name:
        name = f"User {uid}"

    _username_cache[uid] = name
    return name


async def fetch_today_poll_message(guild_id):
    info = load_poll_messages().get(str(guild_id))
    if not info or info.get("date") != today_str():
        return None
    channel = bot.get_channel(int(info["channel_id"]))
    if not channel:
        return None
    try:
        return await channel.fetch_message(int(info["message_id"]))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def analyze_guild_reactions(guild_id):
    """
    Returns a dict describing the poll's reactions:
      roster_count_per_slot: {emoji: count}  (humans only; everyone who reacted to that slot)
      fill_marked_user_ids:  set of user IDs who reacted with FILL_EMOJI
      user_slot_map:         {user_id: set of slot emojis they reacted to}
    """
    msg = await fetch_today_poll_message(guild_id)
    result = {
        "roster_count_per_slot": {e: 0 for e in EMOJIS},
        "fill_marked_user_ids": set(),
        "user_slot_map": {},
    }
    if not msg:
        return result

    for reaction in msg.reactions:
        emoji_str = str(reaction.emoji)
        if emoji_str == FILL_EMOJI:
            async for user in reaction.users():
                if user.id != bot.user.id:
                    result["fill_marked_user_ids"].add(user.id)
        elif emoji_str in EMOJIS:
            async for user in reaction.users():
                if user.id == bot.user.id:
                    continue
                result["roster_count_per_slot"][emoji_str] += 1
                result["user_slot_map"].setdefault(user.id, set()).add(emoji_str)

    return result


def effective_team_count(guild_id, slot_emoji, raw_roster_count, user_slot_map_for_guild):
    """
    Adjusts roster count for a slot based on claims:
    - Subtract any of OUR fills who got claimed by OTHER teams (they're not playing for us)
    - Add fills FROM other teams who were claimed BY us (they're playing for us)
    """
    count = raw_roster_count
    today_claims = get_today_claims()
    for claim in today_claims.get(slot_emoji, []):
        if claim["fill_home_guild_id"] == str(guild_id) and claim["claimed_by_guild_id"] != str(guild_id):
            uid = int(claim["fill_user_id"])
            if slot_emoji in user_slot_map_for_guild.get(uid, set()):
                count -= 1
        if claim["claimed_by_guild_id"] == str(guild_id) and claim["fill_home_guild_id"] != str(guild_id):
            count += 1
    return count


async def get_full_team_slots(guild_id, analysis=None):
    """Slots where this guild has TEAM_SIZE+ effective players (with claim adjustments)."""
    if analysis is None:
        analysis = await analyze_guild_reactions(guild_id)
    full_slots = []
    for emoji in EMOJIS:
        raw = analysis["roster_count_per_slot"][emoji]
        eff = effective_team_count(guild_id, emoji, raw, analysis["user_slot_map"])
        if eff >= TEAM_SIZE:
            full_slots.append(emoji)
    return full_slots


async def get_available_fills(analyses_by_guild):
    """
    Returns {slot_emoji: [fill_info_dicts]} of fills not yet 'consumed' by their home team
    and not already claimed by some team for this slot.
    """
    pool = {emoji: [] for emoji in EMOJIS}
    today_claims = get_today_claims()

    for gid, analysis in analyses_by_guild.items():
        guild_obj = bot.get_guild(int(gid))
        guild_name = guild_obj.name if guild_obj else f"Server {gid}"

        for fill_uid in analysis["fill_marked_user_ids"]:
            user_slots = analysis["user_slot_map"].get(fill_uid, set())
            user_name = await resolve_username(fill_uid, guild_obj)

            for emoji in user_slots:
                # Already claimed for this slot? Skip.
                if is_already_claimed_for_slot(emoji, fill_uid):
                    continue

                # Home-team-priority: if home team has 5+ at this slot, fill is busy
                raw = analysis["roster_count_per_slot"][emoji]
                eff = effective_team_count(gid, emoji, raw, analysis["user_slot_map"])
                if eff >= TEAM_SIZE:
                    continue

                pool[emoji].append({
                    "fill_user_id": str(fill_uid),
                    "fill_user_name": user_name,
                    "fill_home_guild_id": str(gid),
                    "fill_home_guild_name": guild_name,
                })

    return pool


# ─── AVAILABILITY BOARD ───────────────────────────────────────────────────────
async def build_board_embed_and_react_map(viewer_guild_id):
    """
    Returns (embed, react_map) where react_map is {claim_emoji: fill_info}
    for the fill claim reactions to be added to the message.
    """
    today = datetime.datetime.now(pytz.timezone(HOST_TZ)).strftime("%A, %B %d")
    channels = load_channels()

    # Pre-fetch all guild reaction analyses (one round trip per guild)
    analyses = {}
    for gid in channels.keys():
        if not is_matchmaking_enabled(gid):
            continue
        analyses[gid] = await analyze_guild_reactions(gid)

    slot_to_teams = {emoji: [] for emoji in EMOJIS}
    my_full_slots = []

    for gid, analysis in analyses.items():
        full_slots = await get_full_team_slots(gid, analysis=analysis)
        guild_obj = bot.get_guild(int(gid))
        guild_name = guild_obj.name if guild_obj else f"Server {gid}"

        if str(gid) == str(viewer_guild_id):
            my_full_slots = full_slots
        else:
            for emoji in full_slots:
                slot_to_teams[emoji].append(guild_name)

    fills_pool = await get_available_fills(analyses)

    # ─── Consolidate fills: one entry per unique player, listing ALL slots ───
    # fills_pool is {slot_emoji: [fill_info, ...]}
    # We want: {fill_user_id: {info..., "slots": [list of slot_emojis]}}
    consolidated = {}
    for slot_emoji, slot_fills in fills_pool.items():
        for fill in slot_fills:
            uid = fill["fill_user_id"]
            if uid not in consolidated:
                consolidated[uid] = {
                    "fill_user_id": uid,
                    "fill_user_name": fill["fill_user_name"],
                    "fill_home_guild_id": fill["fill_home_guild_id"],
                    "fill_home_guild_name": fill["fill_home_guild_name"],
                    "slots": [],
                }
            if slot_emoji not in consolidated[uid]["slots"]:
                consolidated[uid]["slots"].append(slot_emoji)

    # Sort slots within each fill in time order
    for fill in consolidated.values():
        fill["slots"].sort(key=lambda e: EMOJIS.index(e))

    # ─── Build the embed ──────────────────────────────────────────────────────
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
            lines.append(f"• **{emoji_to_label(emoji)}** — {', '.join(teams)}")
    if not any_others:
        lines.append("_No other teams have a full 5 yet._")

    # ─── Fill pool section + claim reactions map ──────────────────────────────
    lines.append("")
    lines.append("🆘 **Fills available for any team:**")

    # Show fills already claimed BY this viewer team (so they remember who they have)
    today_claims = get_today_claims()
    my_claims_by_player = {}  # {fill_user_id: {"name", "home_guild_name", "slots": [emoji]}}
    for slot_emoji, claims in today_claims.items():
        for c in claims:
            if c["claimed_by_guild_id"] == str(viewer_guild_id):
                uid = c["fill_user_id"]
                if uid not in my_claims_by_player:
                    home_g = bot.get_guild(int(c["fill_home_guild_id"]))
                    my_claims_by_player[uid] = {
                        "name": c["fill_user_name"],
                        "home": home_g.name if home_g else "unknown",
                        "slots": [],
                    }
                if slot_emoji not in my_claims_by_player[uid]["slots"]:
                    my_claims_by_player[uid]["slots"].append(slot_emoji)

    if my_claims_by_player:
        lines.append("**✓ Already claimed by your team:**")
        for uid, info in my_claims_by_player.items():
            info["slots"].sort(key=lambda e: EMOJIS.index(e))
            slot_labels = ", ".join(emoji_to_label(e) for e in info["slots"])
            lines.append(f"• **{info['name']}** _(from {info['home']})_ — {slot_labels}")
        lines.append("")

    # Build the available list — ONE emoji per UNIQUE PLAYER
    react_map = {}  # claim_emoji -> {fill_user_id, fill_user_name, fill_home_guild_id, fill_home_guild_name, slots: [emoji]}
    fill_lines = []
    claim_idx = 0

    # Sort fills by name for consistency
    sorted_fills = sorted(consolidated.values(), key=lambda f: f["fill_user_name"].lower())

    overflow_count = 0
    for fill in sorted_fills:
        if claim_idx >= MAX_FILL_REACTIONS:
            overflow_count += 1
            continue
        ce = CLAIM_EMOJIS[claim_idx]
        react_map[ce] = {
            "fill_user_id": fill["fill_user_id"],
            "fill_user_name": fill["fill_user_name"],
            "fill_home_guild_id": fill["fill_home_guild_id"],
            "fill_home_guild_name": fill["fill_home_guild_name"],
            "slots": fill["slots"],  # list of slot emojis they're available for
        }
        slot_labels = ", ".join(emoji_to_label(e) for e in fill["slots"])
        fill_lines.append(f"{ce}  **{fill['fill_user_name']}** _({fill['fill_home_guild_name']})_ — {slot_labels}")
        claim_idx += 1

    if overflow_count:
        fill_lines.append(f"_…and {overflow_count} more (use_ `/claim @user [time]` _to claim those)_")

    if fill_lines:
        lines.extend(fill_lines)
        lines.append("")
        lines.append("_Managers: click 🇦/🇧/🇨… below to claim that fill for **all** their available times._")
        lines.append("_Use `/unclaim @user [time]` to release a specific time, or remove the reaction to release all times._")
    else:
        lines.append("_No fills available right now._")

    lines.append("")
    lines.append("_DM the team's captain or your contact in their Discord to set up a match._")
    lines.append("_Use `/matchmaking off` to hide your team from this board._")

    embed = discord.Embed(
        title=f"📋 Live Scrim Availability — {today}",
        description="\n".join(lines),
        color=discord.Color.green(),
    )
    embed.set_footer(text="Updates live as teams react · Manager-only fill claims")
    return embed, react_map


async def post_or_update_board(guild_id, force_new=False):
    """
    Edit the existing board if one exists for today; only post a new one if no board
    exists yet today. Even when force_new=True, we still prefer editing if a board
    record exists for today — this prevents duplicate boards from redeploys or
    catch-up logic.
    """
    if not is_matchmaking_enabled(guild_id):
        return

    channels = load_channels()
    channel_id = channels.get(str(guild_id))
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return

    embed, react_map = await build_board_embed_and_react_map(guild_id)
    today = today_str()
    boards = load_board_messages()
    info = boards.get(str(guild_id))

    # Try to edit the existing board first — even if force_new=True, prefer editing
    # if today's board exists (defends against duplicate boards on redeploy/catch-up).
    if info and info.get("date") == today:
        try:
            board_channel = bot.get_channel(int(info["channel_id"]))
            if board_channel:
                msg = await board_channel.fetch_message(int(info["message_id"]))
                await msg.edit(embed=embed)
                # Sync claim reactions: add new ones (don't remove — Discord rate limits)
                existing = {str(r.emoji) for r in msg.reactions}
                for ce in react_map.keys():
                    if ce not in existing:
                        try:
                            await msg.add_reaction(ce)
                        except discord.HTTPException:
                            pass
                all_maps = load_fill_reacts()
                all_maps[str(guild_id)] = {"date": today, "map": react_map}
                save_fill_reacts(all_maps)
                return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass  # board record stale (msg deleted etc.) — fall through and post fresh

    # Post a fresh board (only reached if no board exists today, OR existing one is gone)
    try:
        msg = await channel.send(embed=embed)
        record_board_message(guild_id, channel.id, msg.id)
        for ce in react_map.keys():
            try:
                await msg.add_reaction(ce)
            except discord.HTTPException:
                pass
        all_maps = load_fill_reacts()
        all_maps[str(guild_id)] = {"date": today, "map": react_map}
        save_fill_reacts(all_maps)
    except discord.HTTPException as e:
        print(f"[ERROR] Failed to post board for guild {guild_id}: {e}")


async def update_all_boards():
    """Edit (don't repost) the board in every opted-in server."""
    channels = load_channels()
    for gid in channels.keys():
        if is_matchmaking_enabled(gid):
            try:
                await post_or_update_board(gid, force_new=False)
            except Exception as e:
                print(f"[ERROR] Failed to update board for guild {gid}: {e}")


# ─── REACTION EVENT HANDLERS ──────────────────────────────────────────────────
def is_today_poll_message(payload):
    if not payload.guild_id:
        return False
    info = load_poll_messages().get(str(payload.guild_id))
    if not info or info.get("date") != today_str():
        return False
    return str(payload.message_id) == info["message_id"]


def is_today_board_message(payload):
    if not payload.guild_id:
        return False
    info = load_board_messages().get(str(payload.guild_id))
    if not info or info.get("date") != today_str():
        return False
    return str(payload.message_id) == info["message_id"]


async def notify_fill_claimed(fill_user_id, claiming_guild_name, slot_label):
    """DM the fill player that they were claimed."""
    try:
        user = await bot.fetch_user(int(fill_user_id))
        await user.send(
            f"🎮 **You've been claimed as a fill!**\n"
            f"**{claiming_guild_name}** picked you for **{slot_label}** tonight.\n"
            f"Reach out to their captain to coordinate."
        )
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def notify_fill_unclaimed(fill_user_id, claiming_guild_name, slot_label):
    try:
        user = await bot.fetch_user(int(fill_user_id))
        await user.send(
            f"ℹ️ **{claiming_guild_name}** has released your fill claim for **{slot_label}**. "
            f"You're back in the available pool."
        )
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

    # ── Reaction on the daily POLL → refresh boards ──
    if is_today_poll_message(payload):
        if str(payload.emoji) in EMOJIS or str(payload.emoji) == FILL_EMOJI:
            await update_all_boards()
        return

    # ── Reaction on the BOARD → claim a fill ──
    if is_today_board_message(payload):
        emoji_str = str(payload.emoji)
        if emoji_str not in CLAIM_EMOJIS:
            return

        guild = bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.HTTPException:
                return

        # Permission check: only managers can claim
        if not member.guild_permissions.manage_guild:
            try:
                channel = bot.get_channel(payload.channel_id)
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction(payload.emoji, member)
            except discord.HTTPException:
                pass
            try:
                await member.send("❌ Only managers (with **Manage Server** permission) can claim fills.")
            except discord.HTTPException:
                pass
            return

        # Look up which fill this emoji corresponds to
        all_maps = load_fill_reacts()
        info = all_maps.get(str(payload.guild_id))
        if not info or info.get("date") != today_str():
            return
        react_map = info.get("map", {})
        fill_info = react_map.get(emoji_str)
        if not fill_info:
            return

        # The new format has "slots" (list) instead of "slot_emoji"
        target_slots = fill_info.get("slots", [])
        if not target_slots:
            # Backwards compatibility: old single-slot format
            old_slot = fill_info.get("slot_emoji")
            if old_slot:
                target_slots = [old_slot]
        if not target_slots:
            return

        # Try to claim every slot. Some may be already claimed by other guilds.
        claimed_slots = []
        skipped_slots = []
        for slot_emoji in target_slots:
            existing = is_already_claimed_for_slot(slot_emoji, fill_info["fill_user_id"])
            if existing:
                if existing["claimed_by_guild_id"] == str(payload.guild_id):
                    # Already ours, just skip silently
                    continue
                else:
                    skipped_slots.append((slot_emoji, existing["claimed_by_guild_name"]))
                    continue
            add_claim(
                slot_emoji=slot_emoji,
                fill_user_id=fill_info["fill_user_id"],
                fill_user_name=fill_info["fill_user_name"],
                fill_home_guild_id=fill_info["fill_home_guild_id"],
                claiming_guild_id=str(payload.guild_id),
                claiming_guild_name=guild.name,
            )
            claimed_slots.append(slot_emoji)

        if not claimed_slots and skipped_slots:
            # Couldn't claim anything — undo the reaction
            try:
                channel = bot.get_channel(payload.channel_id)
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction(payload.emoji, member)
                names = ", ".join(f"{emoji_to_label(s)} ({by})" for s, by in skipped_slots)
                await channel.send(
                    f"⚠️ {member.mention} — that fill is already claimed for: {names}.",
                    delete_after=12,
                )
            except discord.HTTPException:
                pass
            return

        if not claimed_slots:
            return  # nothing changed

        # DM the fill once with the full slot list
        slot_labels = ", ".join(emoji_to_label(s) for s in claimed_slots)
        dm_ok = await notify_fill_claimed(fill_info["fill_user_id"], guild.name, slot_labels)

        # Confirm in channel
        try:
            channel = bot.get_channel(payload.channel_id)
            msg_text = (
                f"✅ {member.mention} claimed **{fill_info['fill_user_name']}** "
                f"({fill_info['fill_home_guild_name']}) for **{slot_labels}**."
            )
            if skipped_slots:
                skip_names = ", ".join(emoji_to_label(s) for s, _ in skipped_slots)
                msg_text += f"\n_(Note: {skip_names} were already claimed by other teams.)_"
            if not dm_ok:
                msg_text += f"\n⚠️ Couldn't DM them — please notify directly."
            await channel.send(msg_text, delete_after=20)
        except discord.HTTPException:
            pass

        await update_all_boards()


@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id:
        return

    # ── Reaction removed from POLL → refresh boards ──
    if is_today_poll_message(payload):
        if str(payload.emoji) in EMOJIS or str(payload.emoji) == FILL_EMOJI:
            await update_all_boards()
        return

    # ── Reaction removed from BOARD → unclaim a fill (manager toggling off) ──
    if is_today_board_message(payload):
        emoji_str = str(payload.emoji)
        if emoji_str not in CLAIM_EMOJIS:
            return

        guild = bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.HTTPException:
                return

        if not member.guild_permissions.manage_guild:
            return

        all_maps = load_fill_reacts()
        info = all_maps.get(str(payload.guild_id))
        if not info or info.get("date") != today_str():
            return
        react_map = info.get("map", {})
        fill_info = react_map.get(emoji_str)
        if not fill_info:
            return

        # New format: release ALL slots this guild had claimed for this player
        target_slots = fill_info.get("slots", [])
        if not target_slots:
            old_slot = fill_info.get("slot_emoji")
            if old_slot:
                target_slots = [old_slot]

        released_slots = []
        for slot_emoji in target_slots:
            existing = is_already_claimed_for_slot(slot_emoji, fill_info["fill_user_id"])
            if existing and existing["claimed_by_guild_id"] == str(payload.guild_id):
                remove_claim(slot_emoji, fill_info["fill_user_id"], str(payload.guild_id))
                released_slots.append(slot_emoji)

        if not released_slots:
            return

        slot_labels = ", ".join(emoji_to_label(s) for s in released_slots)
        await notify_fill_unclaimed(fill_info["fill_user_id"], guild.name, slot_labels)

        try:
            channel = bot.get_channel(payload.channel_id)
            await channel.send(
                f"↩️ {member.mention} released **{fill_info['fill_user_name']}** from **{slot_labels}**.",
                delete_after=15,
            )
        except discord.HTTPException:
            pass

        await update_all_boards()


# ─── HYBRID COMMANDS ──────────────────────────────────────────────────────────
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


@bot.hybrid_command(name="scrim", description="Post a scrim availability poll right now (only if today doesn't have one)")
async def scrim(ctx):
    await ctx.defer(ephemeral=True)
    if has_poll_today(ctx.guild.id):
        await ctx.send(
            "ℹ️ Today's poll already exists — find it in this channel.\n"
            "_(The bot only posts one poll per day to keep the board synced.)_",
            ephemeral=True,
        )
        return
    await post_poll(ctx.channel)
    mark_poll_sent(ctx.guild.id)
    await ctx.send("✅ Poll posted!", ephemeral=True)


@bot.hybrid_command(name="setping", description="Set a ping (@everyone, @here, or @Role) above each daily poll")
@app_commands.describe(ping="The ping to add: @everyone, @here, or a role mention")
@commands.has_permissions(manage_guild=True)
async def setping(ctx, *, ping: str = None):
    if ping is None:
        await ctx.send(
            "Usage: `/setping @everyone` or `/setping @here` or `/setping @YourRole`",
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
            "❌ That doesn't look like a valid ping. Use `@everyone`, `@here`, or a role mention.",
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
        await ctx.send(f"**Matchmaking is currently {state}** for this server.")
        return

    mode = mode.lower()
    if mode == "on":
        settings[gid] = True
        save_matchmaking_settings(settings)
        await ctx.send("✅ Matchmaking **enabled**.")
        await post_or_update_board(ctx.guild.id, force_new=False)
    elif mode == "off":
        settings[gid] = False
        save_matchmaking_settings(settings)
        await ctx.send("❌ Matchmaking **disabled**.")
    else:
        await ctx.send("Usage: `/matchmaking on`, `/matchmaking off`, or `/matchmaking status`")


@bot.hybrid_command(name="claim", description="Claim a fill player for a time slot")
@app_commands.describe(user="The fill player to claim", time="Time slot, e.g. 8pm or 8:30pm")
@commands.has_permissions(manage_guild=True)
async def claim(ctx, user: discord.User, time: str):
    await ctx.defer(ephemeral=True)
    slot_emoji = label_to_emoji(time)
    if not slot_emoji:
        await ctx.send(f"❌ Couldn't parse time `{time}`. Try `8pm`, `8:30pm`, etc.", ephemeral=True)
        return

    # Verify they're actually a fill (reacted ✅ + this slot somewhere)
    found = False
    fill_home_guild_id = None
    fill_home_guild_name = None
    for gid in load_channels().keys():
        analysis = await analyze_guild_reactions(gid)
        if user.id in analysis["fill_marked_user_ids"] and slot_emoji in analysis["user_slot_map"].get(user.id, set()):
            found = True
            fill_home_guild_id = gid
            g = bot.get_guild(int(gid))
            fill_home_guild_name = g.name if g else f"Server {gid}"
            break

    if not found:
        await ctx.send(
            f"❌ {user.display_name} hasn't signed up as a fill for {emoji_to_label(slot_emoji)}.\n"
            f"_(They need to react ✅ AND the time slot emoji on the daily poll.)_",
            ephemeral=True,
        )
        return

    existing = is_already_claimed_for_slot(slot_emoji, user.id)
    if existing:
        await ctx.send(
            f"⚠️ {user.display_name} is already claimed by **{existing['claimed_by_guild_name']}** for {emoji_to_label(slot_emoji)}.",
            ephemeral=True,
        )
        return

    add_claim(
        slot_emoji=slot_emoji,
        fill_user_id=str(user.id),
        fill_user_name=user.display_name,
        fill_home_guild_id=fill_home_guild_id,
        claiming_guild_id=str(ctx.guild.id),
        claiming_guild_name=ctx.guild.name,
    )
    dm_ok = await notify_fill_claimed(user.id, ctx.guild.name, emoji_to_label(slot_emoji))
    msg = f"✅ Claimed **{user.display_name}** ({fill_home_guild_name}) for **{emoji_to_label(slot_emoji)}**."
    if not dm_ok:
        msg += "\n⚠️ Couldn't DM them — please notify directly."
    await ctx.send(msg, ephemeral=True)
    await update_all_boards()


@bot.hybrid_command(name="unclaim", description="Release a claimed fill back to the pool")
@app_commands.describe(user="The fill player to release", time="Time slot, e.g. 8pm or 8:30pm")
@commands.has_permissions(manage_guild=True)
async def unclaim(ctx, user: discord.User, time: str):
    await ctx.defer(ephemeral=True)
    slot_emoji = label_to_emoji(time)
    if not slot_emoji:
        await ctx.send(f"❌ Couldn't parse time `{time}`.", ephemeral=True)
        return

    existing = is_already_claimed_for_slot(slot_emoji, user.id)
    if not existing:
        await ctx.send(f"ℹ️ {user.display_name} isn't currently claimed for {emoji_to_label(slot_emoji)}.", ephemeral=True)
        return
    if existing["claimed_by_guild_id"] != str(ctx.guild.id):
        await ctx.send(
            f"❌ That fill is claimed by **{existing['claimed_by_guild_name']}**, not your team.",
            ephemeral=True,
        )
        return

    remove_claim(slot_emoji, str(user.id), str(ctx.guild.id))
    await notify_fill_unclaimed(user.id, ctx.guild.name, emoji_to_label(slot_emoji))
    await ctx.send(f"↩️ Released **{user.display_name}** from **{emoji_to_label(slot_emoji)}**.", ephemeral=True)
    await update_all_boards()


@bot.hybrid_command(name="refreshboard", description="Delete and recreate the availability board (admin)")
@commands.has_permissions(manage_guild=True)
async def refreshboard(ctx):
    """Nukes today's board record + recreates it fresh. Useful if the board got duplicated or stale."""
    await ctx.defer(ephemeral=True)

    # Find and delete ALL bot messages today that look like a board
    channels = load_channels()
    channel_id = channels.get(str(ctx.guild.id))
    if not channel_id:
        await ctx.send("❌ This server doesn't have a poll channel set. Run `/setchannel` first.", ephemeral=True)
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        await ctx.send("❌ Couldn't find your poll channel.", ephemeral=True)
        return

    # Delete tracked board message if it exists
    boards = load_board_messages()
    info = boards.get(str(ctx.guild.id))
    if info and info.get("date") == today_str():
        try:
            old_msg = await channel.fetch_message(int(info["message_id"]))
            await old_msg.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # Also scan recent messages for any other board-shaped messages from the bot today
    deleted_count = 0
    try:
        async for m in channel.history(limit=50):
            if m.author == bot.user and m.embeds:
                title = m.embeds[0].title or ""
                if title.startswith("📋 Live Scrim Availability"):
                    try:
                        await m.delete()
                        deleted_count += 1
                    except discord.HTTPException:
                        pass
    except discord.HTTPException:
        pass

    # Clear board record
    boards.pop(str(ctx.guild.id), None)
    save_board_messages(boards)

    # Post a fresh one
    if is_matchmaking_enabled(ctx.guild.id):
        await post_or_update_board(ctx.guild.id, force_new=True)

    await ctx.send(f"✅ Refreshed availability board (cleaned up {deleted_count} old message(s)).", ephemeral=True)


@bot.hybrid_command(name="refreshpoll", description="Delete and recreate today's poll (admin) — use sparingly!")
@commands.has_permissions(manage_guild=True)
async def refreshpoll(ctx):
    """Nukes today's poll + board, then recreates them. WARNING: erases all reactions/signups."""
    await ctx.defer(ephemeral=True)

    channels = load_channels()
    channel_id = channels.get(str(ctx.guild.id))
    if not channel_id:
        await ctx.send("❌ This server doesn't have a poll channel set. Run `/setchannel` first.", ephemeral=True)
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        await ctx.send("❌ Couldn't find your poll channel.", ephemeral=True)
        return

    # Delete tracked poll message
    poll_msgs = load_poll_messages()
    info = poll_msgs.get(str(ctx.guild.id))
    if info and info.get("date") == today_str():
        try:
            old = await channel.fetch_message(int(info["message_id"]))
            await old.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # Scan recent messages for any other poll-shaped messages from bot today
    poll_deleted = 0
    board_deleted = 0
    try:
        async for m in channel.history(limit=50):
            if m.author == bot.user and m.embeds:
                title = m.embeds[0].title or ""
                if title.startswith("📅 Scrim Availability"):
                    try:
                        await m.delete()
                        poll_deleted += 1
                    except discord.HTTPException:
                        pass
                elif title.startswith("📋 Live Scrim Availability"):
                    try:
                        await m.delete()
                        board_deleted += 1
                    except discord.HTTPException:
                        pass
    except discord.HTTPException:
        pass

    # Clear records
    poll_msgs.pop(str(ctx.guild.id), None)
    save_poll_messages(poll_msgs)
    boards = load_board_messages()
    boards.pop(str(ctx.guild.id), None)
    save_board_messages(boards)

    # Clear today's "poll sent" mark so the bot will repost
    last_polls = load_last_poll_dates()
    last_polls.pop(str(ctx.guild.id), None)
    save_last_poll_dates(last_polls)

    # Repost
    await post_poll(channel)
    mark_poll_sent(ctx.guild.id)

    await ctx.send(
        f"✅ Refreshed today's poll (cleaned up {poll_deleted} poll(s) + {board_deleted} board(s)).",
        ephemeral=True,
    )


@bot.hybrid_command(name="scrimhelp", description="Show all available scrim bot commands")
async def scrimhelp(ctx):
    embed = discord.Embed(
        title="🎮 Scrim Bot Commands",
        description=(
            "All commands work as `/command` (slash) and `!command` (prefix).\n\n"
            "**Setup (admin only):**\n"
            "• `/setchannel` — Use the current channel for daily polls\n"
            "• `/unsetchannel` — Stop daily polls\n"
            "• `/setping @Role` / `/unsetping` — Add/remove ping above poll\n"
            "• `/matchmaking on/off/status` — Toggle cross-server availability board\n\n"
            "**Anyone:**\n"
            "• `/scrim` — Post a poll right now (only if today's poll isn't already up)\n"
            "• `/scrimhelp` — Show this message\n\n"
            "**Fill claims (admin only):**\n"
            "• Click 🇦/🇧/🇨… reaction on the board to claim a fill (claims ALL their times)\n"
            "• Remove the reaction to release them back to the pool\n"
            "• `/claim @user 8pm` / `/unclaim @user 8pm` — backup commands (per-slot)\n\n"
            "**Reset (admin only — use sparingly):**\n"
            "• `/refreshboard` — Delete & recreate the availability board\n"
            "• `/refreshpoll` — Delete & recreate today's poll (erases reactions!)\n\n"
            f"📅 Daily polls auto-post at **{POLL_HOUR:02d}:{POLL_MIN:02d} {HOST_TZ}**.\n"
            "🌍 Times shown in **each player's local timezone**.\n"
            f"📋 When your team has **{TEAM_SIZE}+ reactions** on a slot, your server appears on other teams' boards.\n"
            "✅ React with ✅ on the poll AND time slot(s) to flag yourself as a **fill** for any team."
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
        try:
            await interaction.response.send_message(
                "❌ You need the **Manage Server** permission.", ephemeral=True
            )
        except discord.InteractionResponded:
            pass
    else:
        print(f"[SLASH ERROR] {error}")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} — serving {len(bot.guilds)} servers")
    print(f"Data directory: {DATA_DIR}")
    print(f"Daily poll scheduled for {POLL_HOUR:02d}:{POLL_MIN:02d} {HOST_TZ}")

    # Verify Members Intent is actually working (helps diagnose username issues)
    members_intent_active = bot.intents.members
    if members_intent_active:
        # Check if we actually got members in any guild
        total_members_cached = sum(len(g.members) for g in bot.guilds)
        if total_members_cached < 2 and bot.guilds:
            print("[WARN] Members Intent is enabled in code but no members are cached.")
            print("[WARN] You may need to enable 'Server Members Intent' in the Discord Developer Portal:")
            print("[WARN]   https://discord.com/developers/applications → Bot → Privileged Gateway Intents")
        else:
            print(f"[OK] Members Intent active. Cached {total_members_cached} members across all servers.")
    else:
        print("[WARN] Members Intent is OFF in code — usernames will fall back to user IDs.")


async def setup_hook():
    bot.loop.create_task(daily_poll_loop())
    try:
        synced = await bot.tree.sync()
        print(f"[SLASH] Synced {len(synced)} slash command(s) globally.")
    except Exception as e:
        print(f"[SLASH] Failed to sync: {e}")

bot.setup_hook = setup_hook


bot.run(BOT_TOKEN)

#region Imports --------------------------------------------------------------------------------------------------------
import discord
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
import os
import datetime
from zoneinfo import ZoneInfo
from datetime import datetime, time, timedelta
import asyncio
import sqlite3
#endregion

#region Setup and Variables ---------------------------------------------------------------------------------------------

load_dotenv()  # Load environment variables from .env file
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

# SQLite
DB_PATH = "player_info.db"      
TABLE_NAME = "player_info"
db_logger = logging.getLogger(DB_PATH)
db_logger.setLevel(logging.DEBUG)
db_logger.addHandler(handler)


# Other constants
DATE_FORMAT = "%m-%d-%Y"

# Users
ZIREN1236 = 314500928290160640
RATTLEPOST = 499200328399323186

# Roles
GM_ROLE = 1424088644821454848

# Channels
THE_CROSSROADS = 1420451034639110278
THE_LAB = 1422696917464256655
DM_HUSH_HUT = 1424222020060577842

# Timezone
DETROIT = ZoneInfo("America/Detroit")

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guild_scheduled_events = True


bot = commands.Bot(command_prefix='!', intents=intents)
#endregion

#region Misc Events ---------------------------------------------------------------------------------------------------
@bot.event
async def on_ready():
    print(f'We are ready to go in, {bot.user.name}')
    if not weekly_sunday_job.is_running():
        weekly_sunday_job.start()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if "damn" in message.content.lower():
        await message.channel.send("Damn Daniel!")

    await bot.process_commands(message)
#endregion

#region Player Database Commands -----------------------------------------------------------------------------------------
def get_db_connection():
    try:
        db_logger.debug("Connecting to DB at %r", DB_PATH)
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row  # access columns by name
        return conn
    except sqlite3.Error:
        db_logger.exception("DB connect failed")
        return None

@bot.command()
async def info(ctx, *, player_name: str):
    requester = str(ctx.author.display_name)
    rq_role = discord.utils.get(ctx.author.roles, id=GM_ROLE)
    if rq_role is not None:
        await player_info(ctx, player_name=player_name, type="GM")
    elif requester == player_name:
        await player_info(ctx, player_name=player_name, type="USER")
    else:
        await ctx.reply("You can only view your own info. GMs can view anyone's info.")
async def player_info(ctx, *, player_name: str, type: str):

    conn = get_db_connection()
    if not conn:
        await ctx.reply("Database connection failed. See logs for details.")
        return
    
    cur = conn.cursor()
    sql = f"SELECT LEVEL, GOLD, QUEST_POINTS FROM {TABLE_NAME} WHERE PLAYER = ?"
    cur.execute(sql, (player_name,))
    row = cur.fetchone()

    if row is None:
        db_logger.warning("No record for PLAYER=%r", player_name)
        await ctx.reply(f"No player named `{player_name}` found.")
        return

    level = row["LEVEL"]
    gold = row["GOLD"]
    quest_points = row["QUEST_POINTS"]

    embed = discord.Embed(
        title=f"{player_name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Level", value=str(level), inline=True)
    embed.add_field(name="Gold", value=str(gold), inline=True)
    embed.add_field(name="QP", value=str(quest_points), inline=True)

    if type == "GM":
        channel = bot.get_channel(DM_HUSH_HUT)
        await channel.send(embed=embed)
    else:
        await ctx.author.send(embed=embed)
        await ctx.reply("I've sent your info in a DM!")

    cur.close()
    conn.close()

@bot.command()
@commands.has_role(GM_ROLE)
async def addGold(ctx, player_name: str, amount: int):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(f"SELECT GOLD FROM {TABLE_NAME} WHERE PLAYER = ?", (player_name,))
    row = cur.fetchone()

    if not row:
        await ctx.reply(f"Player `{player_name}` not found.")
        conn.close()
        return

    new_gold = row[0] + amount
    cur.execute(f"UPDATE {TABLE_NAME} SET GOLD = ? WHERE PLAYER = ?", (new_gold, player_name))
    conn.commit()
    conn.close()

    await ctx.reply(f"{player_name} now has {new_gold} gold.")

@bot.command()
@commands.has_role(GM_ROLE)
async def rmGold(ctx, player_name: str, amount: int):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(f"SELECT GOLD FROM {TABLE_NAME} WHERE PLAYER = ?", (player_name,))
    row = cur.fetchone()

    if not row:
        await ctx.reply(f"Player `{player_name}` not found.")
        conn.close()
        return

    new_gold = row[0] - amount
    if new_gold < 0:
        await ctx.reply(f"Cannot remove more than {amount} gold from {player_name}.")
        conn.close()
        return
    cur.execute(f"UPDATE {TABLE_NAME} SET GOLD = ? WHERE PLAYER = ?", (new_gold, player_name))
    conn.commit()
    conn.close()

    await ctx.reply(f"{player_name} now has {new_gold} gold.")

@bot.command()
async def giveGold(ctx, receiver: str, amount: int):
    conn = get_db_connection()
    cur = conn.cursor()
    giver = str(ctx.author.display_name)  # the command user’s server name

    # get giver row
    cur.execute(f"SELECT GOLD FROM {TABLE_NAME} WHERE PLAYER = ?", (giver,))
    giver_row = cur.fetchone()
    if not giver_row:
        await ctx.reply(f"Giver `{giver}` not found in the database.")
        conn.close()
        return

    giver_gold = giver_row[0]

    # get receiver row
    cur.execute(f"SELECT GOLD FROM {TABLE_NAME} WHERE PLAYER = ?", (receiver,))
    receiver_row = cur.fetchone()
    if not receiver_row:
        await ctx.reply(f"Receiver `{receiver}` not found in the database.")
        conn.close()
        return

    receiver_gold = receiver_row[0]

    # prevent negative
    if giver_gold < amount:
        await ctx.reply(f"❌ You don’t have enough gold to trade {amount}.")
        conn.close()
        return

    # update both
    new_giver_gold = giver_gold - amount
    new_receiver_gold = receiver_gold + amount

    cur.execute(f"UPDATE {TABLE_NAME} SET GOLD = ? WHERE PLAYER = ?", (new_giver_gold, giver))
    cur.execute(f"UPDATE {TABLE_NAME} SET GOLD = ? WHERE PLAYER = ?", (new_receiver_gold, receiver))
    conn.commit()
    conn.close()

    await ctx.send(
        f"💰 Trade complete!\n"
        f"- {giver} → {receiver}: {amount} gold\n"
    )
#endregion

#region Weekly Downtime Actions -----------------------------------------------------------------------------------------
@tasks.loop(time=time(10, 0, tzinfo=ZoneInfo("America/Detroit")))
async def weekly_sunday_job():
    if datetime.datetime.now(ZoneInfo("America/Detroit")).weekday() == 6:
        await run_weekly_job()
async def run_weekly_job():
    """Post a downtime poll, collect all reactions until end of day, DM a per-user summary."""
    # --- 1) Define actions & build embed ---
    actions = [
        ("🛠️", "Train a Trade"),
        ("🎲", "Odd Job"),
        ("🔮", "Craft an Item"),
        ("🪙", "Do Your Day Job"),
        ("💞", "Build Relationships"),
    ]

    desc_lines = [
        "Please select a downtime action from the list below.",
        "To select an action, react with the corresponding emoji.",
        "",
        *[f"{emoji}  —  **{label}**" for emoji, label in actions],
    ]
    description = "\n".join(desc_lines)

    embed = discord.Embed(
        title="Downtime Actions",
        description=description,
        color=0x00FF00,
    )

    # --- 2) Send poll message & add reactions ---
    channel = bot.get_channel(THE_CROSSROADS)
    if channel is None:
        try:
            channel = await bot.fetch_channel(THE_CROSSROADS)
        except Exception as e:
            logging.exception("Failed to get channel %s: %s", THE_CROSSROADS, e)
            return

    poll_message = await channel.send(embed=embed)

    for emoji, _ in actions:
        try:
            await poll_message.add_reaction(emoji)
        except Exception as e:
            logging.exception("Failed adding reaction %s: %s", emoji, e)

    # --- 3) Sleep until end of local day (23:59:30 Detroit) ---
    now_local = datetime.now(DETROIT)
    end_local = now_local.replace(hour=23, minute=59, second=30, microsecond=0)
    if end_local <= now_local:
        end_local += timedelta(days=1)

    await asyncio.sleep((end_local - now_local).total_seconds())

    # --- 4) Refetch message & gather ALL user choices (no winner logic) ---
    try:
        poll_message = await channel.fetch_message(poll_message.id)
    except Exception as e:
        logging.exception("Failed to refetch poll message: %s", e)
        return

    # Map: user_id -> set of (emoji, label)
    user_choices: dict[int, set[tuple[str, str]]] = {}

    for emoji, label in actions:
        react = discord.utils.get(poll_message.reactions, emoji=emoji)
        if not react:
            continue
        try:
            async for user in react.users(limit=None):
                if getattr(user, "bot", False):
                    continue
                user_choices.setdefault(user.id, set()).add((emoji, label))
        except Exception as e:
            logging.exception("Error reading users for %s: %s", emoji, e)

    date_str = datetime.now(DETROIT).strftime(DATE_FORMAT)

    # --- 5) Build DM summary (per-option counts + per-user selections) ---
    if not user_choices:
        summary_text = "No participants reacted today."
    else:
        # Per-user lines (try to include display name)
        per_user_lines = []
        for uid, choices in user_choices.items():
            # Order their choices by our actions order
            order_index = {e: i for i, (e, _) in enumerate(actions)}
            ordered = sorted(choices, key=lambda x: order_index.get(x[0], 999))
            pretty = ", ".join(f"{e} {l}" for e, l in ordered)

            name = f"<@{uid}>"
            try:
                member = channel.guild.get_member(uid) or await channel.guild.fetch_member(uid)
                if member and member.display_name:
                    name = f"<@{uid}>"
            except Exception:
                pass

            per_user_lines.append(f"- {name}: {pretty}")

        per_user_lines.sort(key=lambda s: s.lower())


        summary_text = "\n".join([
            f"## Downtime Actions for {date_str}",
            "",
            "**Per-user selections:**",
            *per_user_lines
        ])

    # --- 6) DM the summary to the target user ---
    try:
        target_user = await bot.fetch_user(ZIREN1236)
        await target_user.send(summary_text)
    except discord.Forbidden:
        logging.warning("Cannot DM target user (Forbidden).")
    except Exception as e:
        logging.exception("Failed to DM summary: %s", e)

   

    try:
        await poll_message.delete()
    except discord.Forbidden:
        logging.warning("Bot doesn't have permission to delete the poll message.")
    except Exception as e:
        logging.exception("Failed to delete poll message: %s", e)

    try:
        await channel.send(f"Downtime Actions for {date_str} have closed.")
        await channel.send(f"If you missed them, you will have to wait for next week.")
        
    except Exception as e:
        logging.exception("Failed to send closing notice: %s", e)

@bot.command()
async def test_poll(ctx):
    await run_weekly_job_test(ctx.author)
async def run_weekly_job_test(author):
    """Test version: posts a downtime poll and collects reactions after 30 seconds."""
    actions = [
        ("🛠️", "Train a Trade"),
        ("🎲", "Odd Job"),
        ("🔮", "Craft an Item"),
        ("🪙", "Do Your Day Job"),
        ("💞", "Build Relationships"),
    ]

    desc_lines = [
        "TEST MODE: This poll will close in 30 seconds.",
        "",
        *[f"{emoji}  —  **{label}**" for emoji, label in actions],
    ]
    description = "\n".join(desc_lines)

    embed = discord.Embed(
        title="Downtime Actions (TEST)",
        description=description,
        color=0xFF8800,
    )

    channel = bot.get_channel(THE_LAB)
    if channel is None:
        channel = await bot.fetch_channel(THE_LAB)

    poll_message = await channel.send(embed=embed)

    for emoji, _ in actions:
        await poll_message.add_reaction(emoji)

    # ----- TEST WAIT -----
    await asyncio.sleep(10)  # only 10 seconds instead of all day

    try:
        poll_message = await channel.fetch_message(poll_message.id)
    except Exception as e:
        logging.exception("Failed to refetch poll message: %s", e)
        return

    # Map: user_id -> set of (emoji, label)
    user_choices: dict[int, set[tuple[str, str]]] = {}

    for emoji, label in actions:
        react = discord.utils.get(poll_message.reactions, emoji=emoji)
        if not react:
            continue
        try:
            async for user in react.users(limit=None):
                if getattr(user, "bot", False):
                    continue
                user_choices.setdefault(user.id, set()).add((emoji, label))
        except Exception as e:
            logging.exception("Error reading users for %s: %s", emoji, e)

    date_str = datetime.now(DETROIT).strftime(DATE_FORMAT)

    # --- 5) Build DM summary (per-option counts + per-user selections) ---
    if not user_choices:
        summary_text = "No participants reacted today."
    else:
        # Per-user lines (try to include display name)
        per_user_lines = []
        for uid, choices in user_choices.items():
            # Order their choices by our actions order
            order_index = {e: i for i, (e, _) in enumerate(actions)}
            ordered = sorted(choices, key=lambda x: order_index.get(x[0], 999))
            pretty = ", ".join(f"{e} {l}" for e, l in ordered)

            name = f"<@{uid}>"
            try:
                member = channel.guild.get_member(uid) or await channel.guild.fetch_member(uid)
                if member and member.display_name:
                    name = f"<@{uid}>"
            except Exception:
                pass

            per_user_lines.append(f"- {name}: {pretty}")

        per_user_lines.sort(key=lambda s: s.lower())


        summary_text = "\n".join([
            f"## Downtime Actions for {date_str}",
            "",
            "**Per-user selections:**",
            *per_user_lines
        ])

    # --- 6) DM the summary to the target user ---
    try:
        target_user = await bot.fetch_user(author.id)
        await target_user.send(summary_text)
    except discord.Forbidden:
        logging.warning("Cannot DM target user (Forbidden).")
    except Exception as e:
        logging.exception("Failed to DM summary: %s", e)

   

    try:
        await poll_message.delete()
    except discord.Forbidden:
        logging.warning("Bot doesn't have permission to delete the poll message.")
    except Exception as e:
        logging.exception("Failed to delete poll message: %s", e)

    try:
        await channel.send(f"Downtime Actions for {date_str} have closed.")
        await channel.send(f"If you missed them, you will have to wait for next week.")
        
    except Exception as e:
        logging.exception("Failed to send closing notice: %s", e)
#endregion


# Runs the bot
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
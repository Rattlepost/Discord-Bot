import discord
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
import os
import datetime
from zoneinfo import ZoneInfo
from datetime import datetime, time, timedelta
import asyncio

load_dotenv()  # Load environment variables from .env file
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

# Other constants
DATE_FORMAT = "%m-%d-%Y"

# Users
ZIREN1236 = 314500928290160640  # <-- replace with the user ID to receive the DM
RATTLEPOST = 499200328399323186

# Channels
THE_CROSSROADS = 1420451034639110278
THE_LAB = 1422696917464256655

# Timezone
DETROIT = ZoneInfo("America/Detroit")

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guild_scheduled_events = True

#Roles
role_idgit = "idgit"


bot = commands.Bot(command_prefix='!', intents=intents)

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

    # --- 5) Build DM summary (per-option counts + per-user selections) ---
    if not user_choices:
        summary_text = "No participants reacted today."
    else:
        # Per-option unique-user counts
        option_counts = {label: 0 for _, label in actions}
        for choices in user_choices.values():
            for _, label in choices:
                option_counts[label] += 1

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
                    name = f"{member.display_name} (<@{uid}>)"
            except Exception:
                pass

            per_user_lines.append(f"- {name}: {pretty}")

        per_user_lines.sort(key=lambda s: s.lower())

        count_lines = [f"**{label}** — {option_counts[label]} participant(s)" for _, label in actions]

        summary_text = "\n".join([
            "**Downtime Reactions Summary (all selections recorded)**",
            "",
            *count_lines,
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

    date_str = datetime.now(DETROIT).strftime(DATE_FORMAT)

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

async def run_weekly_job_test():
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
    await asyncio.sleep(30)  # only 30 seconds instead of all day

    poll_message = await channel.fetch_message(poll_message.id)

    # collect all reactions
    user_choices: dict[int, set[tuple[str, str]]] = {}
    for emoji, label in actions:
        react = discord.utils.get(poll_message.reactions, emoji=emoji)
        if not react:
            continue
        async for user in react.users(limit=None):
            if user.bot:
                continue
            user_choices.setdefault(user.id, set()).add((emoji, label))

    # summary text
    if not user_choices:
        summary_text = "No participants reacted in the 30-second test window."
    else:
        lines = []
        for uid, choices in user_choices.items():
            pretty = ", ".join(f"{e} {l}" for e, l in choices)
            name = f"<@{uid}>"
            lines.append(f"- {name}: {pretty}")
        summary_text = "\n".join([
            "**TEST SUMMARY**",
            *lines
        ])

    target_user = await bot.fetch_user(RATTLEPOST)
    await target_user.send(summary_text)

    date_str = datetime.now(DETROIT).strftime(DATE_FORMAT)

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
async def test_poll():
    await run_weekly_job_test()

# Runs the bot
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
#region Imports --------------------------------------------------------------------------------------------------------
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
from config import handler, logging
#endregion

load_dotenv()  # Load environment variables from .env file
token = os.getenv('DISCORD_TOKEN')

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guild_scheduled_events = True

# Bot
bot = commands.Bot(command_prefix='!', intents=intents)

#region Misc Events ---------------------------------------------------------------------------------------------------
@bot.event
async def on_ready():
    print(f'We are ready to go in, {bot.user.name}')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if "damn" in message.content.lower():
        await message.channel.send("Damn Daniel!")

    await bot.process_commands(message)
#endregion


@bot.event
async def setup_hook():
    await bot.load_extension("cogs.player_info")
    await bot.load_extension("cogs.admin_commands")


# Runs the bot
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
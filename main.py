import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import webserver

load_dotenv()  # Load environment variables from .env file
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

#Roles
role_idgit = "idgit"

bot = commands.Bot(command_prefix='!', intents=intents)

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



# Runs the bot
webserver.keep_alive()
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
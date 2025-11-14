# OSRS Activity Log Bot: main.py
# - A Discord Bot by Dylan Hebert (The Green Donut)
# - Scrapes and posts players' OSRS events to a specific channel in Discord
# - See README.md for setup instructions
#

# IDEAS:
# - recentmilestones: shows a rundown of the last 5-10 milestones
# - add pause feature per server?
# - algorithm to space out all player hiscores scrapes within 15-30 mins
# - everyone in every server collectively votes for next skill of the week?
# - push back and add sotw player update when player has valid skill update


import json
import discord
from discord.ext import commands
import asyncio
import time
import datetime
import os
import sys, traceback
from common.logger import logger
import data.handlers as db

intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True

# Our data .jsons
db.verify_files('db_discord.json')
db.verify_files('db_runescape.json')

# Set prefix
def get_prefix(bot, message):
    prefixes = [';']
    if not message.guild:
        return ';'
    return commands.when_mentioned_or(*prefixes)(bot, message)

# Set help command
custom_help = commands.DefaultHelpCommand(
    width=140,
    sort_commands=False,
    no_category="Other Commands"
    )

# Set bot status
game_playing = discord.Streaming(
    name=';add <osrs-name>',
    url='https://www.youtube.com/watch?v=EfBMZoHbmU4')

# Create bot object
bot = commands.Bot(
    command_prefix = get_prefix,
    help_command = custom_help,
    description = 'OSRS Activity Log by Green Donut',
    intents=intents)

# Define extensions
initial_extensions =    [
                        'cogs.cmds.user',
                        'cogs.cmds.admin',
                        'cogs.cmds.super',
                        'cogs.looper',
                        'cogs.dink_webhook'
                        ]

# Load extensions
if __name__ == '__main__':
    for extension in initial_extensions:
        try:
            bot.load_extension(extension)
            logger.info(f'Loaded extension {extension}.')
        except Exception as e:
            logger.exception(f'Failed to load extension {extension}: {e}')

# Bot main start
@bot.event
async def on_ready():
    logger.info(f'\n** BOT STARTED: {bot.user.name} - {bot.user.id} **')
    await bot.change_presence(activity = game_playing)

# Bot disconnection, log it!
@bot.event
async def on_disconnect():
    logger.warning(f'\n** BOT DISCONNECTED: {bot.user.name} - {bot.user.id} **')
    

# Error and cooldown handling
# @bot.event
# async def on_application_command_error(ctx, error):
#     if isinstance(error, commands.CommandOnCooldown):
#         await ctx.respond(
#             f"You're on cooldown!", # Try again in {round(error.retry_after, 1)}s.
#             ephemeral=True
#         )
#     else:
#         raise error  # let other errors bubble up
    
# @bot.event
async def on_command_error(ctx, error):
    channel = ctx.message.channel
    if isinstance(error, commands.errors.CommandNotFound):
        #await ctx.send('idk that command')
        pass
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"You are missing the input **{error.param}** after this command")
    if isinstance(error, commands.errors.CommandOnCooldown):
        await ctx.send(f"You can use this command in {int(error.retry_after)} seconds")
    else:
        logger.exception(f'>> COMMAND ERROR: {error}')

# Bot joining server
@bot.event
async def on_guild_join(guild):
    sys_chan = False
    if guild.system_channel != None:
        sys_chan = True
        await guild.system_channel.send(f'Thanks for having me, {guild.name}\n'
                                'Set a channel for me to post in with **;posthere**\n'
                                'Set a role for me to mention for big announcements with **;rsrole**\n'
                                'Add your OSRS name to the Activity Log with **;add <your OSRS name>**')  
    logger.info('\n---------------------------------------\n'
            f'Joined {guild.name} with {guild.member_count} users!\n'
            f' System channel = {sys_chan}\n'
            '---------------------------------------')
    await db.add_server(guild)

# Bot leaving server
@bot.event
async def on_guild_remove(guild):
    await db.remove_server(guild)


bot.run(db.get_bot_token())

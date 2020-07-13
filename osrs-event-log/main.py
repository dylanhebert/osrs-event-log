# OSRS Activity Log Bot: main.py
# - A Discord Bot by Dylan Hebert (The Green Donut)
# - Scrapes and posts players' OSRS events to a specific channel in Discord
# - See README.md for setup instructions
#

# IDEAS:
# - recentmilestones: shows a rundown of the last 5-10 milestones


import json
import discord
from discord.ext import commands
import time
import datetime
import os
import sys, traceback
from common.logger import logger
import common.utils as fs

# Check if we have players/servers .json files, create them if not
def checkDataJson(file_name):
    if os.path.exists(file_name):
        logger.info(f'Found {file_name}...')
        pass
    else:
        data = {}
        with open(file_name, 'w') as outfile:  
            json.dump(data, outfile)
        logger.info(f'Created new {file_name}...')
# Our data .jsons
checkDataJson('data/servers.json')
checkDataJson('data/players.json')

# Get bot Token
with open('bot_config.json','r') as f:
    BOT_INFO_ALL = json.load(f)
BOT_TOKEN = BOT_INFO_ALL['BOT_TOKEN']

# Set prefix
def get_prefix(bot, message):
    prefixes = [';']
    if not message.guild:
        return ';'
    return commands.when_mentioned_or(*prefixes)(bot, message)

# Set help command
customHelp = commands.DefaultHelpCommand(
    width=140,
    sort_commands=False,
    no_category="Other Commands"
    )

# Set bot status
gamePlaying = discord.Streaming(
    name=';join <osrs-name>',
    url='https://www.youtube.com/watch?v=FADpdNyXzek')

# create bot object
bot = commands.Bot(
    command_prefix = get_prefix,
    help_command = customHelp,
    description = 'OSRS Activity Log by Green Donut')

# define extensions
initial_extensions =    [
                        'cogs.looper',
                        'cogs.cmds.user',
                        'cogs.cmds.admin',
                        'cogs.cmds.super'
                        ]

# load extensions
if __name__ == '__main__':
    for extension in initial_extensions:
        try:
            bot.load_extension(extension)
            logger.info(f'Loaded extension {extension}.')
        except Exception as e:
            logger.exception(f'Failed to load extension {extension}: {e}')

# bot main start
@bot.event
async def on_ready():
    logger.info(f'\n** BOT STARTED: {bot.user.name} - {bot.user.id} **')
    await bot.change_presence(activity = gamePlaying)

# bot disconnection, log it!
@bot.event
async def on_disconnect():
    logger.warning(f'\n** BOT DISCONNECTED: {bot.user.name} - {bot.user.id} **')
    

# error and cooldown handling
'''@bot.event
async def on_command_error(ctx, error):
    channel = ctx.message.channel
    if isinstance(error, commands.errors.CommandNotFound):
        #await ctx.send('idk that command')
        pass
    elif isinstance(error, commands.errors.CommandOnCooldown):
	    #await ctx.send(f"you can use this command in {int(error.retry_after)} seconds")
        pass'''

# bot joining server
@bot.event
async def on_guild_join(guild):
    sysChan = False
    if guild.system_channel != None:
        sysChan = True
        await guild.system_channel.send(f'Thanks for having me, {guild.name}\n'
                                'Set a channel for me to post in with **;posthere**\n'
                                'Set a role for me to mention for big announcements with **;rsrole**\n'
                                'Add your OSRS name to the Event Log List with **;join <your OSRS name>**\n'
                                'If you change your OSRS name, use the command again with your new name')  
    logger.info('\n---------------------------------------\n'
            f'Joined {guild.name} with {guild.member_count} users!\n'
            f' System channel = {sysChan}\n'
            '---------------------------------------')
    await fs.addServerDB(guild.id,guild.name)

# bot leaving server
@bot.event
async def on_guild_remove(guild):
    await fs.delServerDB(guild.id,guild.name)


bot.run(BOT_TOKEN, bot=True)

# OSRS Event Log Bot: Main File
# - A Discord Bot by Dylan Hebert (The Green Donut)
#
# Scrapes and posts players' OSRS events to a specific channel in Discord
#
# https://discordapp.com/api/oauth2/authorize?client_id=653740301269073922&permissions=3072&scope=bot
#

import json
import discord
from discord.ext import commands
import time
import datetime
import os
import sys, traceback
from conf.logger import logger
import conf.funcs as fs

with open('mycreds.json','r') as f:
    botInfo = json.load(f)
botToken = botInfo['BOT_TOKEN']# set prefix

def get_prefix(bot, message):
    prefixes = [';']
    if not message.guild:
        return ';'
    return commands.when_mentioned_or(*prefixes)(bot, message)

# create bot object
bot = commands.Bot( command_prefix = get_prefix,
                    description = 'OSRS Event Log by Green Donut')
# gamePlaying = discord.Game(name= ';join <osrs-name>')
gamePlaying = discord.Streaming(name=';join <osrs-name>',
                                url='https://www.youtube.com/watch?v=FADpdNyXzek')

# define extensions
initial_extensions =    [
                        'cogs.cmds',
                        'cogs.looper'
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


bot.run(botToken, bot=True)

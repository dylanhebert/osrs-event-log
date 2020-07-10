# OSRS Activity Log Bot: user.py
# - Commands & functions used by regular users & admins in servers connected to the bot
#

import discord
from discord.ext import commands
from bs4 import BeautifulSoup
import random
import asyncio
import re
from common.logger import logger
import common.utils as fs


class UserCommands(commands.Cog, name="General Commands"):

    def __init__(self, bot): # cog access bot
        self.bot = bot

    async def on_ready(self):
        logger.debug('UserCommands Cog Ready')


    # PLAYER JOINS LOG LOOP THEMSELVES
    @commands.command(  brief=";join <OSRS-Name> | Join the Activity Log",
                        usage="<OSRS-Name>",
                        description="Join the Activity Log with a specified OSRS username.")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def join(self, ctx, *, gameName):
        # serverEntry = await fs.getServerEntry(fs.playersPath,ctx.guild.id)
        nameRS = fs.NameToRS(gameName)
        await ctx.send("*Checking name...*")
        playerDict = await fs.PlayerIsAcceptable(nameRS)
        # If player is valid to be added
        if playerDict != None:
            await ctx.channel.purge(limit=1) # delete 'getting levels' messages
            # If player is already in DB
            if await fs.playerExistsInDB(str(ctx.author.id)):
                try:
                    # get old player data
                    playerEntry = await fs.getPlayerEntry(str(ctx.author.id))
                    # check against old player data
                    if str(ctx.guild.id) not in playerEntry['servers']:  # update player's server list
                        logger.info(f'New server [{ctx.guild.name}] for player [{ctx.author.name}]')
                        playerEntry['servers'][str(ctx.guild.id)] = {'mention' : True}
                    # add previous data to newer updated player dict
                    playerDict['servers'] = playerEntry['servers']
                    # update DB & send update
                    await fs.updatePlayerEntry(str(ctx.author.id),playerDict)
                    await ctx.send(f'**{ctx.author.name}** exists and has been updated in the Event Log List: *{nameRS}*')
                    logger.info(f'Updated player in {ctx.guild.name}: {ctx.author.name} | {nameRS}')
                except Exception as e:
                    logger.exception(f'Could not update player in guild id:{ctx.guild.id} for player id:{ctx.author.id} -- {e}')
                    await ctx.send('**Error updating this player!**')
            # Player is new to DB
            else:
                try:
                    # add current server to new player
                    playerDict['servers'] = {str(ctx.guild.id) : {'mention' : True}}
                    await fs.updatePlayerEntry(str(ctx.author.id),playerDict)
                    await ctx.send(f'**{ctx.author.name}** has been added to the Event Log List: *{nameRS}*\n'
                                    'Toggle on/off this bot mentioning you every update with ;togglemention')
                    logger.info(f'Added player in {ctx.guild.name}: {ctx.author.name} | {nameRS}')
                except Exception as e:
                    logger.exception(f'Could not add new player in guild id:{ctx.guild.id} for player id:{ctx.author.id} -- {e}')
                    await ctx.send('**Error adding this player!**')
        # Player is not valid to be added
        else:
            await ctx.channel.purge(limit=1) # delete 'getting levels' messages
            await ctx.send("**This player's event log can't be accessed!** Here are some reasons why:\n"
                            " -This RuneScape character doesn't exist\n"
                            " -Hiscores are not responding. Try again later")


    # MEMBER CAN REMOVE THEMSELVES FROM EVENT LOG
    @commands.command(  brief="Remove yourself from the Activity Log",
                        description="Remove yourself completely from the Activity Log's databases. "
                                    "You can use ;join to rejoin at any time.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def leave(self, ctx):
        try:
            if await fs.delPlayerEntry(ctx.author.id) == True:
                await ctx.send(f'**{ctx.author.name}** has been removed from the Event Log List!')
                logger.info(f'Removed player in {ctx.guild.name}: {ctx.author.name} | {ctx.author.id}')
            else:
                await ctx.send(f'**{ctx.author.name}** is not in the Event Log List!')
        except Exception as e:
            logger.exception(f'Could not remove player in guild id:{ctx.guild.id} for player id:{ctx.author.id} -- {e}')
            await ctx.send('**Error removing the member!**')


    # LIST PLAYERS IN LOOP
    @commands.command(  brief="See a list of players currently in the Activity Log",
                        description="See a list of players currently in the Activity Log within this server.")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def players(self, ctx):
        playersLst = []
        allPlayers = await fs.openJson(fs.playersPath)
        for k,v in allPlayers.items():
            try:
                # only get players that are in current server
                if str(ctx.guild.id) in v['servers']:
                    mem = ctx.guild.get_member(int(k))
                    playersLst.append(f"{mem.name}" +"  **|**  "+ f"*{v['rsName']}*\n")
            except:
                logger.debug(f'Skipped {k} in ;players')
                pass
        count = len(playersLst)
        playersLst = "".join(playersLst)
        await ctx.send(f'**Stored Players - {ctx.guild.name} - Total: {count}**\n'+playersLst)
        logger.info(f';players called in {ctx.guild.name} by {ctx.author.name}')


    # TOGGLES WHETHER TO MENTION THE PLAYER OR NOT FOR EVERY UPDATE
    @commands.command(  brief="Toggles whether or not to @ you on Discord for every update",
                        description="Toggles whether or not to @ you on Discord for every update. "
                                    "This is toggled on by default. "
                                    "You will still be notified for milestones from anyone in the server "
                                    "unless you mute notifications for the text channel or role this bot posts to.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def togglemention(self, ctx):
        if await fs.playerExistsInDB(str(ctx.author.id)):
            if await fs.serverExistsInPlayer(str(ctx.author.id),ctx.guild.id):
                try:
                    playerEntry = await fs.getPlayerEntry(str(ctx.author.id))
                    newToggle = not playerEntry['servers'][str(ctx.guild.id)]['mention']
                    playerEntry['servers'][str(ctx.guild.id)]['mention'] = newToggle  # toggle
                    await fs.updatePlayerEntry(str(ctx.author.id),playerEntry)
                    if newToggle == False: 
                        mentNot = ' NOT'
                        mentStr = ctx.author.name
                    else:
                        mentNot = ''
                        mentStr = ctx.author.mention
                    await ctx.send(f'**{mentStr}** *WILL{mentNot}* be mentioned in their updates for this server')
                    logger.info(f"Updated player in {ctx.guild.name}: {ctx.author.name} | mention = {newToggle}")
                except Exception as e:
                    logger.exception(f'Could not update togglemention in guild id:{ctx.guild.id} for player id:{ctx.author.id} -- {e}')
                    await ctx.send('**Error updating this player!**')
            else:
                await ctx.send('**You are in the Event Log List but not for this server! Use the ;join <osrs-name> command on this server**')
        else:
            await ctx.send('**You are not in the Event Log List! Use the ;help command for more info**')


    # SIT
    @commands.command(brief="ok", hidden=True)
    @commands.cooldown(1, 2, commands.BucketType.guild)
    async def sit(self, ctx):
        await ctx.send('**ok**')


def setup(bot):
    bot.add_cog(UserCommands(bot))
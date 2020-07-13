# OSRS Activity Log Bot: admin.py
# - Commands & functions used by admins in servers connected to the bot
#

import discord
from discord.ext import commands
from bs4 import BeautifulSoup
import random
import asyncio
import re
from common.logger import logger
import common.utils as fs


class AdminCommands(commands.Cog, name="Admin Commands"):

    def __init__(self, bot): # cog access bot
        self.bot = bot

    async def on_ready(self):
        logger.debug('AdminCommands Cog Ready')


    # CHOOSE POST CHANNEL
    @commands.command(  brief="Changes the channel where this bot posts to",
                        description="Changes the channel where this bot posts to. "
                                    "This command must be posted in the text channel where you want my notifications to go. "
                                    "If this command is never used, I will not post in your server.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def posthere(self, ctx):
        if await fs.isAdmin(ctx.author) or ctx.author.id == 134858274909585409:
            try:
                await fs.updateServerVal(fs.serversPath,ctx.guild.id,'chanID',ctx.channel.id)
                await ctx.send(f'I will now start posting in the {ctx.channel.mention} channel!')
                logger.info(f'\nUpdated post channel in {ctx.guild.name}: {ctx.channel.name} | {ctx.channel.id}')
            except Exception as e:
                logger.exception(f'Could not update post channel in guild id:{ctx.guild.id} for channel id:{ctx.channel.id} -- {e}')
                await ctx.send('**Error updating the post channel!**')
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')


    # CHOOSE MILESTONES ROLE TO NOTIFY
    @commands.command(  brief=";rsrole <@somerole> | A role to notify for milestone messages",
                        usage="<@somerole>",
                        description="A role to notify for milestone messages. If no role is selected, I will notify @here. "
                                    "Milestones include 99s and thresholds for XP, boss kills, and clue scrolls.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def rsrole(self, ctx, *, rsRole: discord.Role):
        if await fs.isAdmin(ctx.author) or ctx.author.id == 134858274909585409:
            try:
                await fs.updateServerVal(fs.serversPath,ctx.guild.id,'rsRoleID',rsRole.id)
                await ctx.send(f'I will now start posting big announcements with the **{rsRole.name}** role mentioned!')
                logger.info(f'\nUpdated RS Role in {ctx.guild.name}: {rsRole.name} | {rsRole.id}')
            except Exception as e:
                logger.exception(f'Could not update rs role in guild id:{ctx.guild.id} for role id:{rsRole.id} -- {e}')
                await ctx.send('**Error updating the RS Role! Check the role name!**')
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')

    
    # REMOVE STORED MILESTONES ROLE AND DEFAULT TO @here
    @commands.command(  brief="Defaults the milestone notify role to @here if not already",
                        description="Defaults the milestone notify role to @here if not already. "
                                    "Milestones include 99s and thresholds for XP, boss kills, and clue scrolls.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def resetrsrole(self, ctx):
        if await fs.isAdmin(ctx.author) or ctx.author.id == 134858274909585409:
            try:
                await fs.updateServerVal(fs.serversPath,ctx.guild.id,'rsRoleID',None)
                await ctx.send(f'I will now start posting big announcements with the **@here** role mentioned!')
                logger.info(f'\nReset RS Role in {ctx.guild.name}: @here | {None}')
            except Exception as e:
                logger.exception(f'Could not update rs role in guild id:{ctx.guild.id} for @-here -- {e}')
                await ctx.send('**Error resetting the RS Role!**')
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')


    # ADMINS CAN ADD ANYONE TO LOOP
    @commands.command(  brief=";add <@Discord-Member> <OSRS-Name> | Add someone to the Activity Log",
                        usage="<@Discord-Member> <OSRS-Name>",
                        description="Add someone else to the Activity Log that is not you. "
                                    "Anyone wishing to add themselves should use ;join.")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def add(self, ctx, member: discord.Member, *, player):
        # If player is admin
        if await fs.isAdmin(ctx.author) or ctx.author.id == 134858274909585409:
            print('admin!')
            # serverEntry = await fs.getServerEntry(fs.playersPath,ctx.guild.id)
            nameRS = fs.NameToRS(player)
            await ctx.send("*Checking name...*")
            playerDict = await fs.PlayerIsAcceptable(nameRS)
            # If player is valid to be added
            if playerDict != None:
                await ctx.channel.purge(limit=1) # delete 'getting levels' messages
                # If player is already in DB
                if await fs.playerExistsInDB(str(member.id)):
                    try:
                        # get old player data
                        playerEntry = await fs.getPlayerEntry(str(member.id))
                        # check against old player data
                        if str(ctx.guild.id) not in playerEntry['servers']:  # update player's server dict
                            playerEntry['servers'][str(ctx.guild.id)] = {'mention': True}
                        # add previous data to newer updated player dict
                        playerDict['servers'] = playerEntry['servers']
                        # update DB & send update
                        await fs.updatePlayerEntry(str(member.id),playerDict)
                        await ctx.send(f'**{member.name}** exists and has been updated in the Event Log List: *{nameRS}*')
                        logger.info(f'Updated player in {ctx.guild.name}: {member.name} | {nameRS}')
                    except Exception as e:
                        logger.exception(f'Could not update player in guild id:{ctx.guild.id} for player id:{member.id} -- {e}')
                        await ctx.send('**Error updating this player!**')
                # Player is new to DB
                else:
                    try:
                        # add current server to new player
                        playerDict['servers'] = {str(ctx.guild.id) : {'mention' : True}}
                        await fs.updatePlayerEntry(str(member.id),playerDict)
                        await ctx.send(f'**{member.name}** has been added to the Event Log List: *{nameRS}*')
                        logger.info(f'Added player in {ctx.guild.name}: {member.name} | {nameRS}')
                    except Exception as e:
                        logger.exception(f'Could not add new player in guild id:{ctx.guild.id} for player id:{member.id} -- {e}')
                        await ctx.send('**Error adding this player!**')
            # Player is not valid to be added
            else:
                await ctx.channel.purge(limit=1) # delete 'getting levels' messages
                await ctx.send("**This player's event log can't be accessed!** Here are some reasons why:\n"
                            " -This RuneScape character doesn't exist\n"
                            " -You may have to try again later")
        # Player is not admin
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')


    # ADMINS CAN REMOVE ANYONE FROM EVENT LOG
    @commands.command(  brief=";remove <@Discord-Member> | Remove someone from the Activity Log",
                        usage="<@Discord-Member>",
                        description="Remove someone else from the Activity Log that is not you. "
                                    "Anyone wishing to remove themselves should use ;leave.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def remove(self, ctx, *, member: discord.Member):
        if await fs.isAdmin(ctx.author) or ctx.author.id == 134858274909585409:
            try:
                if await fs.delPlayerEntry(member.id) == True:
                    await ctx.send(f'**{member.name}** has been removed from the Event Log List!')
                    logger.info(f'Removed player in {ctx.guild.name}: {member.name} | {member.id}')
                else:
                    await ctx.send(f'**{member.name}** is not in the Event Log List!')
            except Exception as e:
                logger.exception(f'Could not remove player in guild id:{ctx.guild.id} for player id:{ctx.author.id} -- {e}')
                await ctx.send('**Error removing the member! Check the spelling!**')
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')


def setup(bot):
    bot.add_cog(AdminCommands(bot))
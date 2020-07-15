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
import common.util as util
import database.handlers as db


class AdminCommands(commands.Cog, name="Admin Commands"):

    def __init__(self, bot): # cog access bot
        self.bot = bot

    async def on_ready(self):
        logger.debug('AdminCommands Cog Ready')


# ---------------------------- CHOOSE POST CHANNEL --------------------------- #

    @commands.command(  brief="Changes the channel where this bot posts to",
                        description="Changes the channel where this bot posts to. "
                                    "This command must be posted in the text channel where you want my notifications to go. "
                                    "If this command is never used, I will not post in your server.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def posthere(self, ctx):
        if await util.is_admin(ctx.author) or ctx.author.id == 134858274909585409:
            try:
                await db.update_server_entry(ctx.guild, 'channel', ctx.channel.id)
                await ctx.send(f'I will now start posting in the {ctx.channel.mention} channel!')
                logger.info(f'\nUpdated post channel in {ctx.guild.name}: {ctx.channel.name} | {ctx.channel.id}')
            except Exception as e:
                logger.exception(f'Could not update post channel in guild id:{ctx.guild.id} for channel id:{ctx.channel.id} -- {e}')
                await ctx.send('**Error updating the post channel!**')
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')


# --------------------- CHOOSE MILESTONES ROLE TO NOTIFY --------------------- #

    @commands.command(  brief=";rsrole <@somerole> | A role to notify for milestone messages",
                        usage="<@somerole>",
                        description="A role to notify for milestone messages. If no role is selected, I will notify @here. "
                                    "Milestones include 99s and thresholds for XP, boss kills, and clue scrolls.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def rsrole(self, ctx, *, rs_role: discord.Role):
        if await util.is_admin(ctx.author) or ctx.author.id == 134858274909585409:
            try:
                await db.update_server_entry(ctx.guild, 'role', rs_role.id)
                await ctx.send(f'I will now start posting big announcements with the **{rs_role.name}** role mentioned!')
                logger.info(f'\nUpdated RS Role in {ctx.guild.name}: {rs_role.name} | {rs_role.id}')
            except Exception as e:
                logger.exception(f'Could not update rs role in guild id:{ctx.guild.id} for role id:{rs_role.id} -- {e}')
                await ctx.send('**Error updating the RS Role! Check the role name!**')
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')

    
# ------------ REMOVE STORED MILESTONES ROLE AND DEFAULT TO @here ------------ #

    @commands.command(  brief="Defaults the milestone notify role to @here if not already",
                        description="Defaults the milestone notify role to @here if not already. "
                                    "Milestones include 99s and thresholds for XP, boss kills, and clue scrolls.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def resetrsrole(self, ctx):
        if await util.is_admin(ctx.author) or ctx.author.id == 134858274909585409:
            try:
                await db.update_server_entry(ctx.guild, 'role', None)
                await ctx.send(f'I will now start posting big announcements with the **@here** role mentioned!')
                logger.info(f'\nReset RS Role in {ctx.guild.name}: @here | {None}')
            except Exception as e:
                logger.exception(f'Could not update rs role in guild id:{ctx.guild.id} for @-here -- {e}')
                await ctx.send('**Error resetting the RS Role!**')
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')


# ----------------------- ADMINS CAN ADD ANYONE TO LOOP ---------------------- #

    @commands.command(  brief=";addother <@Discord-Member> <OSRS-Name> | Add someone to the Activity Log",
                        usage="<@Discord-Member> <OSRS-Name>",
                        description="Add someone else to the Activity Log that is not you. "
                                    "Anyone wishing to add themselves should use ;join.")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def addother(self, ctx, member: discord.Member, *, game_name):
        # If player is admin
        if await util.is_admin(ctx.author) or ctx.author.id == 134858274909585409:
            print('admin!')
            name_rs = util.name_to_rs(game_name)
            await ctx.send("*Checking name...*")
            player_dict = await util.check_player_validity(name_rs)
            # If player is valid to be added
            if player_dict != None:
                try:
                    await db.add_player(ctx.guild, member, name_rs, player_dict)
                    await ctx.send(f'**{member.name}** has added an account to the Activity Log: *{name_rs}*\n'
                                f'Toggle on/off this bot mentioning you every update with *;togglemention {game_name}*\n'
                                f'If you change this OSRS name, use *;transfer {game_name}>>{{new-name}}* to retain your Activity Log records')
                except Exception as e:
                    return await ctx.send(e)
            # Player is not valid to be added
            else:
                await ctx.send("**This player's event log can't be accessed!** Here are some reasons why:\n"
                            " -This RuneScape character doesn't exist\n"
                            " -You may have to try again later")
        # Player is not admin
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')


# ---------------- ADMINS CAN REMOVE ANYONE FROM ACTIVITY LOG ---------------- #

    @commands.command(  brief=";removeother <@Discord-Member> | Remove someone from the Activity Log",
                        usage="<@Discord-Member> <OSRS-Name>",
                        description="Remove someone else from the Activity Log that is not you. "
                                    "Anyone wishing to remove themselves should use ;remove.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def removeother(self, ctx, member: discord.Member, *, game_name):
        if await util.is_admin(ctx.author) or ctx.author.id == 134858274909585409:
            name_rs = util.name_to_rs(game_name)
            try:
                await db.remove_player(ctx.guild, member, name_rs, False)
                await ctx.send(f'**{ctx.author.name}** has removed an account listed under **{member.name}** from the Activity Log: *{name_rs}*')
            except Exception as e:
                return await ctx.send(e)
        else:
            await ctx.send('**Only members with admin privilages can use this command!**')


def setup(bot):
    bot.add_cog(AdminCommands(bot))
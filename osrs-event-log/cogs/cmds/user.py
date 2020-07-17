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
import common.util as util
import database.handlers as db


class UserCommands(commands.Cog, name="General Commands"):

    def __init__(self, bot): # cog access bot
        self.bot = bot

    async def on_ready(self):
        logger.debug('UserCommands Cog Ready')


# --------------------- PLAYER JOINS LOG LOOP THEMSELVES --------------------- #

    @commands.command(  brief=";add <OSRS-Name> | Add an account to your Activity Log",
                        usage="<OSRS-Name>",
                        description="Join the Activity Log with a specified OSRS username.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def add(self, ctx, *, game_name):
        name_rs = util.name_to_rs(game_name)
        await ctx.send("*Checking name...*")
        player_dict = await util.check_player_validity(name_rs)
        # If player is valid to be added
        if player_dict != None:
            try:
                await db.add_player(ctx.guild, ctx.author, name_rs, player_dict)
                await ctx.send(f'**{ctx.author.name}** has added an account to the Activity Log: *{name_rs}*\n'
                            f'Toggle on/off this bot mentioning you every update with *;togglemention {game_name}*\n'
                            f'If you change this OSRS name, use *;transfer {game_name}>>{{new-name}}* to retain your Activity Log records')
            except Exception as e:
                return await ctx.send(e)
        # Player is not valid to be added
        else:
            await ctx.send("**This player's RS name can't be accessed!** Here are some reasons why:\n"
                            " -This Runescape character doesn't exist\n"
                            " -They don't have any high enough levels on the Hiscores\n"
                            " -Hiscores are not responding. Try again later")


# -------------- MEMBER CAN REMOVE THEMSELVES FROM ACTIVITY LOG -------------- #

    @commands.command(  brief=";remove <OSRS-Name> | Remove an account from your Activity Log",
                        usage="<OSRS-Name>",
                        description="Remove one of your RS accounts from this server in the Activity Log's databases. "
                                    "You can use ;add to add another.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def remove(self, ctx, *, game_name):
        name_rs = util.name_to_rs(game_name)
        try:
            await db.remove_player(ctx.guild, ctx.author, name_rs, False)
            await ctx.send(f'**{ctx.author.name}** has removed an account from the Activity Log: *{name_rs}*')
        except Exception as e:
            return await ctx.send(e)
        
        
# --------------- PLAYER TRANSFERS PLAYER INFO TO ANOTHER NAME --------------- #

    @commands.command(  brief=";transfer {OSRS-Name}>>{new-name} | Transfer/rename an account's info",
                        usage="{old-name}>>{new-name}",
                        description="Mainly used if you rename one of your accounts. Tranfers all info for an old account to a new one.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def transfer(self, ctx, *, game_names):
        split_names = game_names.split(">>")
        old_rs_name = util.name_to_rs(split_names[0])
        new_rs_name = util.name_to_rs(split_names[1])
        await ctx.send("*Checking both names...*")
        player_dict = await util.check_player_validity(new_rs_name)
        # If player is valid to be added
        if player_dict != None:
            try:
                await db.rename_player(ctx.guild, ctx.author, old_rs_name, new_rs_name, player_dict)
                await ctx.send(f'**{ctx.author.name}** has transferred an account in the Activity Log: *{old_rs_name}* >> *{new_rs_name}*\n'
                            f'All of the old preferences and records have been moved over!\n')
            except Exception as e:
                return await ctx.send(e)
        # Player is not valid to be added
        else:
            await ctx.send("**This player's RS name can't be accessed!** Here are some reasons why:\n"
                            " -This Runescape character doesn't exist\n"
                            " -They don't have any high enough levels on the Hiscores\n"
                            " -Hiscores are not responding. Try again later")
        
    
# ------------------- MEMBER LISTS ACCOUNTS FOR THEMSELVES ------------------- #

    @commands.command(  brief="List all RS accounts associated with you in this server",
                        description="List all RS accounts associated with you in the Activity Log for this server.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def myaccounts(self, ctx):
        try:
            player_list = await db.get_member_entry(ctx.guild, ctx.author, 'players')
            await ctx.send(f"**{ctx.author.name}** - *{'*  **|**  *'.join(player_list)}*")
        except Exception:
            return await ctx.send(f'**{ctx.author.name}** does not have any RS accounts on this server!')


# ------------------- LIST PLAYERS IN LOOP FOR THIS SERVER ------------------- #

    @commands.command(  brief="See a list of all players currently in the Activity Log",
                        description="See a list of all players currently in the Activity Log within this server.")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def allaccounts(self, ctx):
        players_list = []
        members_players = await db.get_server_players(ctx.guild)
        for k,v in members_players.items():
            try:
                # only get players that are in current server
                mem = ctx.guild.get_member(int(k))
                players_list.append(f"**{mem.name}** - *{'*  **|**  *'.join(v)}*\n")
            except:
                logger.debug(f'Skipped {k} in ;players')
                pass
        count = len(players_list)
        players_list = "".join(players_list)
        await ctx.send(f'**Stored Players - {ctx.guild.name} - Total Members: {count}**\n'+players_list)
        logger.info(f';players called in {ctx.guild.name} by {ctx.author.name}')


# ------- TOGGLES WHETHER TO MENTION THE PLAYER OR NOT FOR EVERY UPDATE ------ #

    @commands.command(  brief=";togglemention {OSRS-Name} | Toggles whether or not to @ you on Discord for every update",
                        usage="<OSRS-Name>",
                        description="Toggles whether or not to @ you on Discord for every update. "
                                    "This is toggled on by default. "
                                    "You will still be notified for milestones from anyone in the server "
                                    "unless you mute notifications for the text channel or role this bot posts to.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def togglemention(self, ctx, *, game_name):
        name_rs = util.name_to_rs(game_name)
        try:
            new_toggle = await db.toggle_player_entry(ctx.guild, ctx.author, name_rs, 'mention')
            if new_toggle == False: 
                ment_not = ' NOT'
                ment_str = ctx.author.name
            else:
                ment_not = ''
                ment_str = ctx.author.mention
            await ctx.send(f'**{ment_str}** *WILL{ment_not}* be mentioned in their updates for this server')
        except Exception as e:
            return await ctx.send(e)


    # SIT
    @commands.command(brief="ok", hidden=True)
    @commands.cooldown(1, 2, commands.BucketType.guild)
    async def sit(self, ctx):
        await ctx.send('**ok**')


def setup(bot):
    bot.add_cog(UserCommands(bot))
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
import database.handler as db


class UserCommands(commands.Cog, name="General Commands"):

    def __init__(self, bot): # cog access bot
        self.bot = bot

    async def on_ready(self):
        logger.debug('UserCommands Cog Ready')


    # PLAYER JOINS LOG LOOP THEMSELVES
    @commands.command(  brief=";addaccount <OSRS-Name> | Add an account to your Activity Log",
                        usage="<OSRS-Name>",
                        description="Join the Activity Log with a specified OSRS username.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def addaccount(self, ctx, *, game_name):
        # server_entry = await util.get_server_entry(util.players_path,ctx.guild.id)
        name_rs = util.name_to_rs(game_name)
        await ctx.send("*Checking name...*")
        player_dict = await util.check_player_validity(name_rs)
        # If player is valid to be added
        if player_dict != None:
            await ctx.channel.purge(limit=1)  # delete 'getting levels' messages
            # ADD PLAYER (get exceptions working here)
            try:
                await db.add_player(ctx.guild, ctx.author, name_rs, player_dict)
                await ctx.send(f'**{ctx.author.name}** has added an account to the Activity Log: *{name_rs}*\n'
                            f'Toggle on/off this bot mentioning you every update with *;togglemention {game_name}*')
            except Exception as e:
                return await ctx.send(e)
        # Player is not valid to be added
        else:
            await ctx.channel.purge(limit=1) # delete 'getting levels' messages
            await ctx.send("**This player's RS name can't be accessed!** Here are some reasons why:\n"
                            " -This Runescape character doesn't exist\n"
                            " -They don't have any high enough levels on the Hiscores\n"
                            " -Hiscores are not responding. Try again later")


    # MEMBER CAN REMOVE THEMSELVES FROM EVENT LOG
    @commands.command(  brief=";removeaccount <OSRS-Name> | Remove an account from your Activity Log",
                        usage="<OSRS-Name>",
                        description="Remove one of your RS accounts from this server in the Activity Log's databases. "
                                    "You can use ;addaccount to add another.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def removeaccount(self, ctx, *, game_name):
        name_rs = util.name_to_rs(game_name)
        try:
            await db.remove_player(ctx.guild, ctx.author, name_rs)
            await ctx.send(f'**{ctx.author.name}** has removed an account from the Activity Log: *{name_rs}*')
        except Exception as e:
            return await ctx.send(e)
        
    
    # MEMBER LISTS ACCOUNTS FOR THEMSELVES
    @commands.command(  brief="List all RS accounts associated with you in this server",
                        description="List all RS accounts associated with you in the Activity Log for this server.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def myaccounts(self, ctx):
        try:
            player_list = await db.get_member_entry(ctx.guild, ctx.author, 'players')
            await ctx.send(f'**{ctx.author.name}**: *{"* **|** *".join(player_list)}*')
        except Exception as e:
            return await ctx.send(e)


    """# LIST PLAYERS IN LOOP
    @commands.command(  brief="See a list of players currently in the Activity Log",
                        description="See a list of players currently in the Activity Log within this server.")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def players(self, ctx):
        players_list = []
        all_players = await util.open_json(util.players_path)
        for k,v in all_players.items():
            try:
                # only get players that are in current server
                if str(ctx.guild.id) in v['servers']:
                    mem = ctx.guild.get_member(int(k))
                    players_list.append(f"{mem.name}" +"  **|**  "+ f"*{v['rs_name']}*\n")
            except:
                logger.debug(f'Skipped {k} in ;players')
                pass
        count = len(players_list)
        players_list = "".join(players_list)
        await ctx.send(f'**Stored Players - {ctx.guild.name} - Total: {count}**\n'+players_list)
        logger.info(f';players called in {ctx.guild.name} by {ctx.author.name}')


    # TOGGLES WHETHER TO MENTION THE PLAYER OR NOT FOR EVERY UPDATE
    @commands.command(  brief="Toggles whether or not to @ you on Discord for every update",
                        description="Toggles whether or not to @ you on Discord for every update. "
                                    "This is toggled on by default. "
                                    "You will still be notified for milestones from anyone in the server "
                                    "unless you mute notifications for the text channel or role this bot posts to.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def togglemention(self, ctx):
        if await util.player_exists_in_db(str(ctx.author.id)):
            if await util.server_exists_in_player(str(ctx.author.id),ctx.guild.id):
                try:
                    player_entry = await util.get_player_entry(str(ctx.author.id))
                    new_toggle = not player_entry['servers'][str(ctx.guild.id)]['mention']
                    player_entry['servers'][str(ctx.guild.id)]['mention'] = new_toggle  # toggle
                    await util.update_player_entry(str(ctx.author.id),player_entry)
                    if new_toggle == False: 
                        ment_not = ' NOT'
                        ment_str = ctx.author.name
                    else:
                        ment_not = ''
                        ment_str = ctx.author.mention
                    await ctx.send(f'**{ment_str}** *WILL{ment_not}* be mentioned in their updates for this server')
                    logger.info(f"Updated player in {ctx.guild.name}: {ctx.author.name} | mention = {new_toggle}")
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
        await ctx.send('**ok**')"""


def setup(bot):
    bot.add_cog(UserCommands(bot))
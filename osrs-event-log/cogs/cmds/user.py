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
import data.handlers as db
import datetime


class UserCommands(commands.Cog, name="General Commands"):

    def __init__(self, bot): # cog access bot
        self.bot = bot
        self.in_channel_parse = False
        self.cancel_channel_parse = False

    async def on_ready(self):
        logger.debug('UserCommands Cog Ready')


# --------------------- PLAYER JOINS LOG LOOP THEMSELVES --------------------- #

    @commands.command(  brief=";add <rs-name> | Add an account to your Activity Log",
                        usage="Zezima",
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
                            f'If you change this OSRS name, use **;transfer {game_name}>>new-name** to retain your Activity Log records')
            except Exception as e:
                return await ctx.send(e)
        # Player is not valid to be added
        else:
            await ctx.send("**This player's RS name can't be accessed!** Here are some reasons why:\n"
                            " -This Runescape character doesn't exist\n"
                            " -They don't have any high enough levels on the Hiscores\n"
                            " -Hiscores are not responding. Try again later")


# -------------- MEMBER CAN REMOVE THEMSELVES FROM ACTIVITY LOG -------------- #

    @commands.command(  brief=";remove <rs-name> | Remove an account from your Activity Log",
                        usage="Zezima",
                        description="Remove one of your RS accounts from this server in the Activity Log's databases.\n"
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

    @commands.command(  brief=";transfer old-name>>new-name | Transfer/rename an account's info",
                        usage="Zezima>>Lynx Titan",
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
        except Exception as e:
            logger.exception(f'Error fetching all accounts: {e}')
            return await ctx.send(f'Error fetching all accounts!')


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


# ------------- REMOVE MEMBERS AND THEIR PLAYERS THAT LEFT SERVER ------------ #

    @commands.command(  brief="Cleans up users from this server's activity log that have left the server",
                        description="Cleans up users from this server's activity log that have left the server")
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def cleanaccounts(self, ctx):
        logger.info(f';cleanaccounts called in {ctx.guild.name} by {ctx.author.name}')
        players_list = []
        members_players = await db.get_server_players(ctx.guild)
        for k,v in members_players.items():
            try:
                # only get players that are in current server
                mem = ctx.guild.get_member(int(k))
                logger.debug(f'  -cleanaccounts: {mem.name}: OK')
            except:
                for name_rs in v:
                    try:
                        await db.remove_player(ctx.guild, int(k), name_rs, False)
                        players_list.append(f"**{name_rs}** - *{int(k)}*\n")
                        logger.debug(f"  -cleanaccounts: REMOVED {k} - {name_rs}")
                        pass
                    except Exception as e:
                        await ctx.send(e)
        count = len(players_list)
        players_list = "".join(players_list)
        await ctx.send(f'**Removed inactive members - {ctx.guild.name} - Total Members: {count}**\n'+players_list)


# ------- TOGGLES WHETHER TO MENTION THE PLAYER OR NOT FOR EVERY UPDATE ------ #

    @commands.command(  brief=";togglemention <rs-name> | Toggles whether or not to @ you on Discord for every update",
                        usage="Zezima",
                        description="Toggles whether or not to @ you on Discord for every update.\n"
                                    "This is toggled on by default.\n"
                                    "You will still be notified for milestones from anyone in the server "
                                    "unless you mute notifications for the text channel or the role this bot notifies.")
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
            await ctx.send(f'**{ment_str}** *WILL{ment_not}* be mentioned for *{name_rs}* updates in this server')
        except Exception as e:
            return await ctx.send(e)


# ---------------------- SHOWS CURRENT SOTW AND HISCORES --------------------- #

    @commands.command(  brief="Show all basic Skill of the Week information",
                        description="Show all basic Skill of the Week information")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def skillweek(self, ctx):
        try:
            await ctx.send(await db.get_sotw_info(ctx.guild))
        except Exception as e:
            logger.exception(f'Error with this command.')
            return await ctx.send(f'Error with this command. Ask my creator')


# ---------------------- SHOWS CURRENT BOTW AND HISCORES --------------------- #

    @commands.command(  brief="Show all basic Boss of the Week information",
                        description="Show all basic Boss of the Week information")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def bossweek(self, ctx):
        try:
            await ctx.send(await db.get_botw_info(ctx.guild))
        except Exception as e:
            logger.exception(f'Error with this command.')
            return await ctx.send(f'Error with this command. Im new ok')
        
        
    # @commands.command(  brief="Show all SOTW history for this server",
    #                     description="Show all SOTW history for this server")
    # @commands.cooldown(1, 15, commands.BucketType.guild)
    # async def skillweekhistory(self, ctx):
    #     try:
    #         history_list = await db.get_sotw_history(ctx.guild)
    #         if history_list:
    #             for week in history_list:
    #                 await ctx.send(week)
    #         else:
    #             await ctx.send('This server has no Skill of the Week history!')
    #     except Exception as e:
    #         logger.exception(f'Error with this command.')
    #         return await ctx.send(f'Error with this command. Im new ok')


# ----------------------- SHOW SOTW STATS FOR A SERVER ----------------------- #

    @commands.command(  brief="Show SOTW player stats for this server",
                        description="Show SOTW player stats for this server")
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def skillweekstats(self, ctx):
        try:
            stats_list = await db.get_sotw_stats(ctx.guild)
            temp_lst = []
            counter = 0
            limit = 10
            if stats_list:
                for stat in stats_list:
                    temp_lst.append(stat)
                    counter += 1
                    if counter == limit or counter == len(stats_list):
                        await ctx.send('\n'.join(temp_lst))
                        limit += 10
                        temp_lst = []
            else:
                await ctx.send('This server has no Skill of the Week history!')
        except Exception as e:
            logger.exception(f'Error with this command.')
            return await ctx.send(f'Error with this command. Ask my creator')


# ----------------------- SHOW BOTW STATS FOR A SERVER ----------------------- #

    @commands.command(  brief="Show BOTW player stats for this server",
                        description="Show BOTW player stats for this server")
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def bossweekstats(self, ctx):
        try:
            stats_list = await db.get_botw_stats(ctx.guild)
            temp_lst = []
            counter = 0
            limit = 10
            if stats_list:
                for stat in stats_list:
                    temp_lst.append(stat)
                    counter += 1
                    if counter == limit or counter == len(stats_list):
                        await ctx.send('\n'.join(temp_lst))
                        limit += 10
                        temp_lst = []
            else:
                await ctx.send('This server has no Boss of the Week history!')
        except Exception as e:
            logger.exception(f'Error with this command.')
            return await ctx.send(f'Error with this command. Im new ok')

# -------------------------- SHOW RECENT MILESTONES -------------------------- #

    def milestone_filter(self, message):
        return message.author == self.bot.user

    def milestone_title_check(self, milestone_title, lookup_who):
        # milestone_title = milestone_title.strip("*")
        split_title = milestone_title.strip('*').split(' ')
        title_potential_name = " ".join( split_title[:len(lookup_who.split(' '))] )
        logger.debug(f'  -milestones: {title_potential_name}')
        return lookup_who == title_potential_name

    @commands.command(  brief=";milestones <rs-name> OR * | Show the most recent milestones",
                        usage="Zezima --count 10",
                        description="Show most recent milestones for a specific RS name or everyone in the server\n"
                                    "Required: <rs-name> (must be a valid RS name in this server's activity log)\n"
                                    "Optional: --count <int> (defaults to 5, large numbers can take awhile, has a limit)\n"
                                    "Optional: --searchmore (parses more of the channel, will take a lot longer depending on count)\n"
                                    "Use one of [all * .] instead of <rs-name> to get all players instead of 1\n"
                                    "Cancel a running milestones command by using ;stopmilestones")
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def milestones(self, ctx, *milestone_inputs):
        logger.info(f';milestones called in {ctx.guild.name} by {ctx.author.name}')
        game_name = None
        shorten_message_limit = 5
        count_limit_max = 25  # must be greater than shorten_message_limit to be read
        count_limit = 5
        high_parse_limit = False

        build_rs_name = []
        flags_start = None
        try:
            for i in range(len(milestone_inputs)):
                # check for flags
                if milestone_inputs[i].startswith("--"):
                    # player name should be first arg
                    if i == 0:
                        logger.debug(f'  -milestones: flag was found first in args: {milestone_inputs[i]}')
                        return await ctx.send(f'A player name must be the first input!')
                    if not flags_start: flags_start = i
                    # get count input
                    if milestone_inputs[i] == "--count":
                        potential_count = milestone_inputs[i+1]
                        if potential_count.isdigit():
                            count_limit = int(potential_count)
                            logger.debug(f'  -milestones: set count to {count_limit}')
                            continue
                        else:
                            logger.debug(f'  -milestones: count was not set to digit: {potential_count}')
                            return await ctx.send(f'Count input needs to be a positive whole number: **{potential_count}**')
                    # check for no parse limit
                    if milestone_inputs[i] == "--searchmore":
                        high_parse_limit = True
                        continue
                    # if we hit here its an unknown flag, skip it
                    logger.debug(f'  -milestones: unknown flag encountered {milestone_inputs[i]}')
                    await ctx.send(f'Ignoring unknown flag input: **{milestone_inputs[i]}**')
                    continue
                # arg did not start with flag value, this should be only words of the rs-name
                if not flags_start:
                    build_rs_name.append(milestone_inputs[i])
        except:
            logger.debug(f'  -milestones: error parsing arguments. exiting command...')
            return await ctx.send(f'Error parsing command inputs')

        # exit if no name given
        logger.debug(f'  -milestones: build_rs_name: {build_rs_name}')
        if not build_rs_name:
            logger.debug(f'  -milestones: no rs name given. exiting command...')
            return await ctx.send(f'No RS name was given!')

        # enforce count limits
        if count_limit > count_limit_max:
            count_limit = count_limit_max
            logger.debug(f'  -milestones: count_limit ({count_limit}) exceeded and set to count_limit_max ({count_limit_max})')
            await ctx.send(f'Resetting the count input to my max value of **{count_limit_max}**...')
        # put together game_name and find out what we need to parse for (all or rs-name)
        game_name = " ".join( build_rs_name )
        logger.debug(f'  -milestones: game_name: {game_name}')
        all_symbols = [ '.','*','all' ]
        if any(i == game_name for i in all_symbols):
            lookup_who = '*'
        else:
            lookup_who = util.name_to_discord(game_name)

        # get activity log channel
        parse_channel = None
        try:
            chan_id = await db.get_server_entry(ctx.guild, 'channel')
            parse_channel = ctx.guild.get_channel(chan_id)
        except:
            logger.debug(f'  -milestones: could not get parse_channel')
            return await ctx.send(f'Could not get the activity log channel')

        # get rs role for server
        try:
            role_id = await db.get_server_entry(ctx.guild, 'role')
            if not role_id:
                notify_role_str = "@here"
            else:
                notify_role = ctx.guild.get_role(role_id)
                notify_role_str = notify_role.mention
        except:
            logger.debug(f'  -milestones: could not get notify_role')
            return await ctx.send(f'Could not get the activity log role')

        # set what we use for channel parse limit
        if high_parse_limit:
            parse_limit = 10000
            await ctx.send(f'--searchmore flag was set. This may take awhile. Use **;stopmilestones** to cancel.')
        else:
            parse_limit = 2000

        logger.debug(f'  -milestones: lookup_who: {lookup_who}')
        logger.debug(f'  -milestones: count: {count_limit}')
        logger.debug(f'  -milestones: high_limit: {high_parse_limit}')

        # start parsing channel history
        count_current = 0
        milestone_list = []
        async with ctx.channel.typing():
            self.in_channel_parse = True
            async for message in parse_channel.history(limit=parse_limit).filter(self.milestone_filter):
                # check if stopmilestones was called
                if self.cancel_channel_parse:
                    self.in_channel_parse = False
                    self.cancel_channel_parse = False
                    logger.debug(f'  -milestones: stopped channel parse')
                    return await ctx.send(f'Stopped channel search!')
                if (f"**- {notify_role_str}") in message.content:
                    split_all = message.content.split("\n", 1)
                    milestone_title = split_all[1]
                    if lookup_who == '*' or self.milestone_title_check(milestone_title, lookup_who):
                        milestone_date = message.created_at.strftime("%m/%d/%Y")
                        milestone_list.append(f"*{milestone_date}* - {milestone_title}")
                        count_current += 1
                        if count_current >= count_limit:
                            logger.debug(f'  -milestones: reached count_limit')
                            break
            self.in_channel_parse = False
                    
            # get correct terms
            message_for_who = lookup_who
            if message_for_who == '*':
                message_for_who = 'all players'
            # if we couldnt find any milestones
            if len(milestone_list) == 0:
                message_for_who = lookup_who
                if message_for_who == '*':
                    message_for_who = 'any players'
                return await ctx.send(f'**Could not find any recent milestones for {message_for_who}!**')

            # found milestones
            logger.debug(f'  -milestones: building final_message')
            # shorten messages if milestone count is over the limit
            if len(milestone_list) > shorten_message_limit:
                logger.debug(f'  -milestones: milestone_list exceeded shorten_message_limit')
                for i in range(len(milestone_list)):
                    i_split = milestone_list[i].split("```", 1)
                    milestone_list[i] = i_split[0]
            # stagger messages to avoid char limit
            temp_lst = []
            stag_count = 0
            stag_limit = 10
            for m in milestone_list:
                temp_lst.append(m)
                stag_count += 1
                if stag_count == stag_limit or stag_count == len(milestone_list):
                    await ctx.send('\n'.join(temp_lst))
                    stag_limit += 10
                    temp_lst = []
            # final_message = "\n".join(milestone_list)
            # all done        
            logger.debug(f'  -milestones: all done')
            return await ctx.send(f'\n**--- End of the {count_current} most recent milestones for {message_for_who} ---**')

    @commands.command(  brief=";stopmilestones | Stops a running milestones search",
                        description="Stops a running milestones search. Does nothing if there's not a search running.")
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def stopmilestones(self, ctx, *milestone_inputs):
        if self.in_channel_parse:
            self.cancel_channel_parse = True
            logger.debug(f'  -milestones: stopping channel parse...')
            return await ctx.send(f'Stopping channel search...')

    # SIT
    @commands.command(brief="ok", hidden=True)
    @commands.cooldown(1, 2, commands.BucketType.guild)
    async def sit(self, ctx):
        await ctx.send('**ok**')


def setup(bot):
    bot.add_cog(UserCommands(bot))
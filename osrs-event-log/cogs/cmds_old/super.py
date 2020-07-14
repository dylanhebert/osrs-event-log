# OSRS Activity Log Bot: super.py
# - Commands & functions used by verified users that affect the bot as a whole
#

import discord
from discord.ext import commands
from bs4 import BeautifulSoup
import random
import asyncio
import re
from common.logger import logger
import common.util as util


class SuperCommands(commands.Cog, command_attrs=dict(hidden=True)):

    def __init__(self, bot): # cog access bot
        self.bot = bot

    async def on_ready(self):
        logger.debug('SuperCommands Cog Ready')


    # SEND AN ANNOUNCEMENT ABOUT THE BOT TO EVERY CHANNEL WITH A MENTION
    @commands.command(  brief="Sends an announcement to every server & channel connected to this bot",
                        usage="<announcement>",
                        description="Sends an announcement in bold text to every server & channel connected to this bot. "
                                    "This will notify the saved role for each server or @here if none specified.")
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def sendannouncement(self, ctx, *, announcement):
        if ctx.author.id == 134858274909585409:
            all_servers = await util.open_json(util.servers_path)
            for k,v in all_servers.items():
                try:
                    server = self.bot.get_guild(int(k))
                    # if not channel in this server then skip server
                    if v["chan_id"]:
                        rs_chan = server.get_channel(v["chan_id"])
                        # get mention role, if not then use @here
                        if v["rs_role_id"]:
                            rs_role = server.get_role(v["rs_role_id"])
                            rs_role_men = rs_role.mention
                        else:
                            rs_role_men = "@here"
                        # send message!
                        await rs_chan.send(f'**{announcement}** {rs_role_men}')
                        logger.info(f'Sent announcement in guild id:{k} | name: {v["serv_name"]} | channel: {rs_chan.name} | rs role: {rs_role_men}')
                    else:
                        logger.exception(f'Could not send announcement in guild id:{k} -- No channel specified')
                except Exception as e:
                    logger.exception(f'Could not send announcement in guild id:{k} -- {e}')
            logger.info(f"Done sending announcement: {announcement}")


    # SEND AN MESSAGE (THOUGHT) ABOUT THE BOT TO EVERY CHANNEL WITH NO MENTION
    @commands.command(  brief="Sends a message to every server & channel connected to this bot",
                        usage="<message>",
                        description="Sends a message to every server & channel connected to this bot. "
                                    "This will NOT notify the saved role for each server.")
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def sendthought(self, ctx, *, thought):
        if ctx.author.id == 134858274909585409:
            all_servers = await util.open_json(util.servers_path)
            for k,v in all_servers.items():
                try:
                    server = self.bot.get_guild(int(k))
                    # if not channel in this server then skip server
                    if v["chan_id"]:
                        rs_chan = server.get_channel(v["chan_id"])
                        # send message!
                        await rs_chan.send(f'{thought}')
                        logger.info(f'Sent thought in guild id:{k} | name: {v["serv_name"]} | channel: {rs_chan.name}')
                    else:
                        logger.exception(f'Could not send thought in guild id:{k} -- No channel specified')
                except Exception as e:
                    logger.exception(f'Could not send thought in guild id:{k} -- {e}')
            logger.info(f"Done sending thought: {thought}")


    # RENAME BOT
    # @commands.command()
    # async def rename(self, ctx, *, name):
    #     await self.bot.user.edit(username=name)

    # TESTING STUFF
    # @commands.command()
    # @commands.cooldown(1, 2, commands.BucketType.guild)
    # async def testeveryone(self, ctx):
    #     await ctx.send('@everyone this is a test im sorry pls dont hurt me')


def setup(bot):
    bot.add_cog(SuperCommands(bot))
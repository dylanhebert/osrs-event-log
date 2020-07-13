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
import common.utils as fs


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
            allServers = await fs.openJson(fs.serversPath)
            for k,v in allServers.items():
                try:
                    server = self.bot.get_guild(int(k))
                    # if not channel in this server then skip server
                    if v["chanID"]:
                        rsChan = server.get_channel(v["chanID"])
                        # get mention role, if not then use @here
                        if v["rsRoleID"]:
                            rsRole = server.get_role(v["rsRoleID"])
                            rsRoleMen = rsRole.mention
                        else:
                            rsRoleMen = "@here"
                        # send message!
                        await rsChan.send(f'**{announcement}** {rsRoleMen}')
                        logger.info(f'Sent announcement in guild id:{k} | name: {v["servName"]} | channel: {rsChan.name} | rs role: {rsRoleMen}')
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
            allServers = await fs.openJson(fs.serversPath)
            for k,v in allServers.items():
                try:
                    server = self.bot.get_guild(int(k))
                    # if not channel in this server then skip server
                    if v["chanID"]:
                        rsChan = server.get_channel(v["chanID"])
                        # send message!
                        await rsChan.send(f'{thought}')
                        logger.info(f'Sent thought in guild id:{k} | name: {v["servName"]} | channel: {rsChan.name}')
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
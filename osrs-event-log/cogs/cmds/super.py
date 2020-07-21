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
import data.handlers as db


class SuperCommands(commands.Cog, command_attrs=dict(hidden=True)):

    def __init__(self, bot): # cog access bot
        self.bot = bot

    async def on_ready(self):
        logger.debug('SuperCommands Cog Ready')


# -------------------- CHANGE MAX PLAYER COUNT PER MEMBER -------------------- #

    @commands.command(  brief="Changes the global max player count per Discord member",
                        usage="<integer>",
                        description="Changes the global max player count per Discord member")
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def changemaxplayers(self, ctx, *, new_count):
        if ctx.author.id == 134858274909585409:
            try: 
                await db.update_max_players(int(new_count))
                await ctx.send(f'**Updated player limit globally. New limit: {new_count}**')
                logger.info(f"UPDATED GLOBAL MAX PLAYER COUNT: {new_count} | Member ID: {ctx.author.id}")
            except:
                ctx.send("Could not update global player limit!")
                

    # SEND AN ANNOUNCEMENT ABOUT THE BOT TO EVERY CHANNEL WITH A MENTION
    @commands.command(  brief="Sends an announcement to every server & channel connected to this bot",
                        usage="<announcement>",
                        description="Sends an announcement in bold text to every server & channel connected to this bot. "
                                    "This will notify the saved role for each server or @here if none specified.")
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def sendannouncement(self, ctx, *, announcement):
        if ctx.author.id == 134858274909585409:
            all_servers = await db.get_all_servers(ctx.author)
            await util.message_all_servers(self.bot, all_servers, announcement, mention=True)
            logger.info(f"Done sending announcement: {announcement}")


    # SEND AN MESSAGE (THOUGHT) ABOUT THE BOT TO EVERY CHANNEL WITH NO MENTION
    @commands.command(  brief="Sends a message to every server & channel connected to this bot",
                        usage="<message>",
                        description="Sends a message to every server & channel connected to this bot. "
                                    "This will NOT notify the saved role for each server.")
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def sendthought(self, ctx, *, thought):
        if ctx.author.id == 134858274909585409:
            all_servers = await db.get_all_servers(ctx.author)
            await util.message_all_servers(self.bot, all_servers, thought, mention=False)
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
# OSRS Activity Log Bot: looper.py
# - Main file that initiates an async loop which fires off periodic functions
#

import discord
from discord.ext import commands
import time
import datetime
import asyncio
import aiohttp
from aiohttp import ClientSession, ClientResponseError
from concurrent.futures.thread import ThreadPoolExecutor
from bs4 import BeautifulSoup
from common.logger import logger
import common.utils as fs
from activity.player_updates import PlayerUpdate

# -------------- VARIABLES ------------- #
TIME_LOOP = 15
PLAYER_THREAD_LIMIT = asyncio.Semaphore( 5 )


# -------------------------------------------------- #
# --------------- RUN EVENT LOG -------------------- #
# -------------------------------------------------- #

# RUNNING MAIN LOOP
async def runOsrsEL(bot):
    logger.debug('In looped method...')
    dataServers = await fs.openJson(fs.serversPath)
    dataPlayers = await fs.openJson(fs.playersPath)
    # New code to thread scraping and to enfore a limit
    try:
        tasks = [
            asyncio.ensure_future(safeThreading(bot,disId,rsdata,dataServers))  # creating task starts coroutine
            for disId,rsdata in dataPlayers.items()
        ]
        await asyncio.gather(*tasks)  # await moment all downloads done
    finally:
        logger.info('Done looping all players!')
    return


# LIMIT THE NUMBER OF PLAYERS WE PARSE AT THE SAME TIME
async def safeThreading(bot,disId,rsdata,dataServers):
    async with PLAYER_THREAD_LIMIT:
        #await asyncio.sleep(5)
        return await threadPlayer(bot,disId,rsdata,dataServers)


# THREAD A PLAYER SEPARATELY
async def threadPlayer(bot,disId,rsdata,dataServers):
    logger.debug(f"checking player: {disId} -- {rsdata['rsName']}")
    parseMinigames = False
    ### Changed for aiohttp integration ###
    page = await fs.getPage(rsdata['rsName'])
    # if page isnt responding, skip player
    if page == None:
        logger.info(f"Unable to get player: {rsdata['rsName']} | Page status: None")
        return
    logger.debug(f"{rsdata['rsName']}: got final page...")
    soup = BeautifulSoup( page, 'html.parser' )
    logger.debug(f"{rsdata['rsName']}: got soup...")
    scores = soup.find(id="contentHiscores")
    logger.debug(f"{rsdata['rsName']}: got scores...")

    # check if player has no hiscore profile
    try:
        logger.debug(f"{rsdata['rsName']}: contents[1]: " + scores.contents[1].name)
    except:
        logger.error(f"Error getting hiscores table! Skipping {rsdata['rsName']}...")
        return
    if scores.contents[1].name != 'table':  # if there's no table, the player has no scores
        logger.info(f"{rsdata['rsName']} not found! Skipping player.")
        return

    # player has hiscore profile
    logger.debug(f"{rsdata['rsName']}: found player...")
    overallXpChanged = False
    Update = PlayerUpdate( rsdata, await fs.openJson(fs.messagesPath) )  # create player-update object
    for tr in scores.find_all('tr')[3:]:
        # find Overall row, skip if weve already found it
        if not overallXpChanged and 'Overall' in tr.get_text():
            logger.debug(f"{rsdata['rsName']}: found Overall row...")
            # if this fails then Overall is (likely) to be new to the json
            try:
                # if overall xp did not change, skip player
                if not fs.xpChanged( rsdata['skills']['Overall']['xp'], tr.find_all('td')[4].get_text() ):
                    overallXpChanged = False
                    logger.debug(f"{rsdata['rsName']}: Overall xp didnt change, skipping...")
                    break  # SKIP POINT HERE
                                    # overall xp changed, lets keep going and make the new player dict
                else:
                    overallXpChanged = True
                    logger.debug(f"{rsdata['rsName']}: Overall xp changed, continuing...")
            except:
                overallXpChanged = True
                logger.debug(f"{rsdata['rsName']}: Overall skill will be added to player, continuing...")

        # if we are in the Minigames section, we need to change how we parse
        if 'Minigame' in tr.get_text():
            parseMinigames = True
            logger.debug(f"{rsdata['rsName']}: found minigames...")
            continue  # skip minigame header row, moving onto 1st minigame row

        # do stuff with row/skill
        rowEntry = tr.find_all('td')
        skill = rowEntry[1].get_text().strip()
        skillDict = {}
        logger.debug(f"{rsdata['rsName']}: found row: {skill}...")

        # row is a skill row
        if not parseMinigames:
            skillDict['rank'] = rowEntry[2].get_text()
            skillDict['level'] = rowEntry[3].get_text()
            skillDict['xp'] = rowEntry[4].get_text()
            # check if this skill had an xp gain for a potential player-update
            if skill in rsdata['skills']:  # first check if skill already existed
                logger.debug(f"{rsdata['rsName']}: skill exists...")
                oldXP = rsdata['skills'][skill]['xp']
                if skillDict['xp'] != oldXP:
                    logger.debug(f"{rsdata['rsName']}: skill xp changed, sending to Update...")
                    overallXpChanged = True
                    Update.updateSkill(skillDict, skill, False)
            else:  # skill didnt exist before on player's hiscores
                logger.debug(f"{rsdata['rsName']}: skill doesnt exist, sending to Update...")
                overallXpChanged = True
                Update.updateSkill(skillDict, skill, True)
            # update skill to skills dict
            rsdata['skills'][skill] = skillDict

        # row is a minigame row, parseMinigames == True
        else:
            skillDict['rank'] = rowEntry[2].get_text()
            skillDict['score'] = rowEntry[3].get_text()
            # check if this skill had an xp gain for a potential player-update
            if skill in rsdata['minigames']:  # first check if skill already existed
                logger.debug(f"{rsdata['rsName']}: skill exists...")
                oldScore = rsdata['minigames'][skill]['score']
                if skillDict['score'] != oldScore:
                    logger.debug(f"{rsdata['rsName']}: minigame score changed, sending to Update...")
                    overallXpChanged = True
                    Update.updateMinigame(skillDict, skill, False)
            else:  # skill didnt exist before on player's hiscores
                logger.debug(f"{rsdata['rsName']}: minigame doesnt exist, sending to Update...")
                overallXpChanged = True
                Update.updateMinigame(skillDict, skill, True)
            # update clue/boss to minigames dict
            rsdata['minigames'][skill] = skillDict  

    # Finish up & post update
    if overallXpChanged:
        logger.debug(f"{rsdata['rsName']}: updating database value...")
        # await fs.updateServerVal(fs.playersPath,int(s),disId,rsdata)  # finally update player with new data
        await fs.updatePlayerEntry(disId,rsdata)  # finally update player with new data
        if Update.hasAnyUpdates():
            # get servers to post to for player
            for k in rsdata['servers'].keys():
                try:
                    logger.debug(f"{rsdata['rsName']}: In server: {k}...")
                    serverEntry = dataServers[k]
                    server = bot.get_guild(int(k))
                    servName = serverEntry['servName']
                    logger.debug(f"{rsdata['rsName']}: {servName}")
                    eventChannel = server.get_channel(serverEntry['chanID'])
                    if serverEntry['rsRoleID'] == None:
                        rsRole = None
                    else:
                        rsRole = discord.utils.get(server.roles, id = serverEntry['rsRoleID'])
                    await Update.postUpdate(bot,server,eventChannel,rsRole,int(disId))
                    #await asyncio.sleep(.3)
                # any kind of error posting to server
                except Exception as e:
                    logger.exception(f'Error with server in player: {k} -- {e}')
            logger.debug(f"{rsdata['rsName']}: posting update...")
        else:
            logger.debug(f"{rsdata['rsName']}: no good criteria for update...")

    logger.debug(f"{rsdata['rsName']}: Done with player!")
    


# ----------------------------------------------------
# ----------------------------------------------------

class MainLooper(commands.Cog):
    
    def __init__(self, bot):
        self.bot = bot

        # create the background task and run it in the background
        self.bot.bg_task = self.bot.loop.create_task(self.looperTask())

    async def on_ready(self):
        logger.debug('MainLooper Cog Ready')

    # @commands.command()
    # @commands.cooldown(1, 5, commands.BucketType.guild)
    # async def testscores(self, ctx):
    #     if ctx.author.id == 134858274909585409:
    #         logger.debug('running testscores')
    #         try:
    #             await runOsrsEL(self.bot)
    #         except Exception as e:
    #             logger.exception(e)

    async def looperTask(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(1.5)
        # --- START LOOPER ---
        logger.info('OSRS Event Log loop started!')
        while not self.bot.is_closed():
            logger.info('Starting player loop...')
            try:
                await runOsrsEL(self.bot)
            except Exception as e:  # catch any error in looper here
                logger.exception(f'Unknown error running main loop: {e}')
            logger.debug(f'Now sleeping for {TIME_LOOP} minutes...')
            await asyncio.sleep(await fs.timeMins( TIME_LOOP ))

            
            

def setup(bot):
    bot.add_cog(MainLooper(bot))
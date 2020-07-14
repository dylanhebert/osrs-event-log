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
import common.util as util
from activity.player_updates import PlayerUpdate

# -------------- VARIABLES ------------- #
TIME_LOOP = 15
PLAYER_THREAD_LIMIT = asyncio.Semaphore( 5 )


# -------------------------------------------------- #
# --------------- RUN EVENT LOG -------------------- #
# -------------------------------------------------- #

# RUNNING MAIN LOOP
async def run_osrs_loop(bot):
    logger.debug('In looped method...')
    data_servers = await util.open_json(util.servers_path)
    data_players = await util.open_json(util.players_path)
    # New code to thread scraping and to enfore a limit
    try:
        tasks = [
            asyncio.ensure_future(safe_threading(bot, dis_id, rs_data, data_servers))  # creating task starts coroutine
            for dis_id,rs_data in data_players.items()
        ]
        await asyncio.gather(*tasks)  # await moment all downloads done
    finally:
        logger.info('Done looping all players!')
    return


# LIMIT THE NUMBER OF PLAYERS WE PARSE AT THE SAME TIME
async def safe_threading(bot, dis_id, rs_data, data_servers):
    async with PLAYER_THREAD_LIMIT:
        #await asyncio.sleep(5)
        return await thread_player(bot, dis_id, rs_data, data_servers)


# THREAD A PLAYER SEPARATELY
async def thread_player(bot, dis_id, rs_data, data_servers):
    logger.debug(f"checking player: {dis_id} -- {rs_data['rs_name']}")
    parse_minigames = False
    ### Changed for aiohttp integration ###
    page = await util.get_page(rs_data['rs_name'])
    # if page isnt responding, skip player
    if page == None:
        logger.info(f"Unable to get player: {rs_data['rs_name']} | Page status: None")
        return
    logger.debug(f"{rs_data['rs_name']}: got final page...")
    soup = BeautifulSoup( page, 'html.parser' )
    logger.debug(f"{rs_data['rs_name']}: got soup...")
    scores = soup.find(id="contentHiscores")
    logger.debug(f"{rs_data['rs_name']}: got scores...")

    # check if player has no hiscore profile
    try:
        logger.debug(f"{rs_data['rs_name']}: contents[1]: " + scores.contents[1].name)
    except:
        logger.error(f"Error getting hiscores table! Skipping {rs_data['rs_name']}...")
        return
    if scores.contents[1].name != 'table':  # if there's no table, the player has no scores
        logger.info(f"{rs_data['rs_name']} not found! Skipping player.")
        return

    # player has hiscore profile
    logger.debug(f"{rs_data['rs_name']}: found player...")
    overall_xp_changed = False
    Update = PlayerUpdate( rs_data, await util.open_json(util.messages_path) )  # create player-update object
    for tr in scores.find_all('tr')[3:]:
        # find Overall row, skip if weve already found it
        if not overall_xp_changed and 'Overall' in tr.get_text():
            logger.debug(f"{rs_data['rs_name']}: found Overall row...")
            # if this fails then Overall is (likely) to be new to the json
            try:
                # if overall xp did not change, skip player
                if not util.xp_changed( rs_data['skills']['Overall']['xp'], tr.find_all('td')[4].get_text() ):
                    overall_xp_changed = False
                    logger.debug(f"{rs_data['rs_name']}: Overall xp didnt change, skipping...")
                    break  # SKIP POINT HERE
                                    # overall xp changed, lets keep going and make the new player dict
                else:
                    overall_xp_changed = True
                    logger.debug(f"{rs_data['rs_name']}: Overall xp changed, continuing...")
            except:
                overall_xp_changed = True
                logger.debug(f"{rs_data['rs_name']}: Overall skill will be added to player, continuing...")

        # if we are in the Minigames section, we need to change how we parse
        if 'Minigame' in tr.get_text():
            parse_minigames = True
            logger.debug(f"{rs_data['rs_name']}: found minigames...")
            continue  # skip minigame header row, moving onto 1st minigame row

        # do stuff with row/skill
        row_entry = tr.find_all('td')
        skill = row_entry[1].get_text().strip()
        skill_dict = {}
        logger.debug(f"{rs_data['rs_name']}: found row: {skill}...")

        # row is a skill row
        if not parse_minigames:
            skill_dict['rank'] = row_entry[2].get_text()
            skill_dict['level'] = row_entry[3].get_text()
            skill_dict['xp'] = row_entry[4].get_text()
            # check if this skill had an xp gain for a potential player-update
            if skill in rs_data['skills']:  # first check if skill already existed
                logger.debug(f"{rs_data['rs_name']}: skill exists...")
                oldXP = rs_data['skills'][skill]['xp']
                if skill_dict['xp'] != oldXP:
                    logger.debug(f"{rs_data['rs_name']}: skill xp changed, sending to Update...")
                    overall_xp_changed = True
                    Update.updateSkill(skill_dict, skill, False)
            else:  # skill didnt exist before on player's hiscores
                logger.debug(f"{rs_data['rs_name']}: skill doesnt exist, sending to Update...")
                overall_xp_changed = True
                Update.updateSkill(skill_dict, skill, True)
            # update skill to skills dict
            rs_data['skills'][skill] = skill_dict

        # row is a minigame row, parse_minigames == True
        else:
            skill_dict['rank'] = row_entry[2].get_text()
            skill_dict['score'] = row_entry[3].get_text()
            # check if this skill had an xp gain for a potential player-update
            if skill in rs_data['minigames']:  # first check if skill already existed
                logger.debug(f"{rs_data['rs_name']}: skill exists...")
                old_score = rs_data['minigames'][skill]['score']
                if skill_dict['score'] != old_score:
                    logger.debug(f"{rs_data['rs_name']}: minigame score changed, sending to Update...")
                    overall_xp_changed = True
                    Update.update_minigame(skill_dict, skill, False)
            else:  # skill didnt exist before on player's hiscores
                logger.debug(f"{rs_data['rs_name']}: minigame doesnt exist, sending to Update...")
                overall_xp_changed = True
                Update.update_minigame(skill_dict, skill, True)
            # update clue/boss to minigames dict
            rs_data['minigames'][skill] = skill_dict  

    # Finish up & post update
    if overall_xp_changed:
        logger.debug(f"{rs_data['rs_name']}: updating database value...")
        # await util.update_server_val(util.players_path,int(s),dis_id,rs_data)  # finally update player with new data
        await util.update_player_entry(dis_id, rs_data)  # finally update player with new data
        if Update.has_any_updates():
            # get servers to post to for player
            for k in rs_data['servers'].keys():
                try:
                    logger.debug(f"{rs_data['rs_name']}: In server: {k}...")
                    server_entry = data_servers[k]
                    server = bot.get_guild(int(k))
                    serv_name = server_entry['serv_name']
                    logger.debug(f"{rs_data['rs_name']}: {serv_name}")
                    event_channel = server.get_channel(server_entry['chan_id'])
                    if server_entry['rs_role_id'] == None:
                        rs_role = None
                    else:
                        rs_role = discord.util.get(server.roles, id = server_entry['rs_role_id'])
                    await Update.post_update(bot, server, event_channel, rs_role, int(dis_id))
                    #await asyncio.sleep(.3)
                # any kind of error posting to server
                except Exception as e:
                    logger.exception(f'Error with server in player: {k} -- {e}')
            logger.debug(f"{rs_data['rs_name']}: posting update...")
        else:
            logger.debug(f"{rs_data['rs_name']}: no good criteria for update...")

    logger.debug(f"{rs_data['rs_name']}: Done with player!")
    


# ----------------------------------------------------
# ----------------------------------------------------

class MainLooper(commands.Cog):
    
    def __init__(self, bot):
        self.bot = bot

        # create the background task and run it in the background
        # self.bot.bg_task = self.bot.loop.create_task(self.looperTask())

    async def on_ready(self):
        logger.debug('MainLooper Cog Ready')

    @commands.command()
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def testscores(self, ctx):
        if ctx.author.id == 134858274909585409:
            logger.debug('running testscores')
            try:
                await run_osrs_loop(self.bot)
            except Exception as e:
                logger.exception(e)

    # async def looperTask(self):
    #     await self.bot.wait_until_ready()
    #     await asyncio.sleep(1.5)
    #     # --- START LOOPER ---
    #     logger.info('OSRS Event Log loop started!')
    #     while not self.bot.is_closed():
    #         logger.info('Starting player loop...')
    #         try:
    #             await run_osrs_loop(self.bot)
    #         except Exception as e:  # catch any error in looper here
    #             logger.exception(f'Unknown error running main loop: {e}')
    #         logger.debug(f'Now sleeping for {TIME_LOOP} minutes...')
    #         await asyncio.sleep(await util.time_mins( TIME_LOOP ))

            
            

def setup(bot):
    bot.add_cog(MainLooper(bot))
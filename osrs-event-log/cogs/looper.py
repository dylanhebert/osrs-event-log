# OSRS Activity Log Bot: looper.py
# - Main file that initiates an async loop which fires off periodic functions
#

import discord
from discord.ext import commands
import datetime
import asyncio
import aiohttp
from aiohttp import ClientSession, ClientResponseError
from concurrent.futures.thread import ThreadPoolExecutor
from bs4 import BeautifulSoup
from common.logger import logger
import common.util as util
import data.handlers as db
from data.handlers.LoopPlayerHandler import LoopPlayerHandler
from activity.PlayerUpdate import PlayerUpdate
# import threading, queue


# --------------------------------- VARIABLES -------------------------------- #

TIME_LOOP_MINUTES =             20  # Should be less than 1 hour to account for SOTW
MIN_SECS_BETWEEN_PLAYERS =      20  # Also determines how many players we parse at once

# IN USE TEMPORARILY
PLAYER_THREAD_LIMIT = asyncio.Semaphore( 5 )

PLAYER_HANDLER = LoopPlayerHandler()


# ---------------------------------------------------------------------------- #
#                               RUN ACTIVITY LOG                               #
# ---------------------------------------------------------------------------- #

# RUNNING MAIN LOOP
async def run_osrs_loop(bot):
    logger.debug('Started main loop method...')
    # Build cache for handler obj
    await PLAYER_HANDLER.build_cache()
    logger.debug('Built PLAYER_HANDLER cache...')

    # Space out hiscores requests
    player_total = len(PLAYER_HANDLER.data_runescape.items())
    logger.debug(f'Player total: {player_total}')
    loop_secs = TIME_LOOP_MINUTES * 60
    time_between_players = int(round(loop_secs / player_total))
    players_per_request = 1
    # Keep minimum amount of time between players
    while time_between_players < MIN_SECS_BETWEEN_PLAYERS:
        logger.debug(f'Consolidating seconds between players: {time_between_players}...')
        time_between_players *= 2
        players_per_request += 1
    logger.debug(f'Final seconds between players: {time_between_players}')
    logger.debug(f'Players per request: {players_per_request}')

    try:
        # Using old method for now
        tasks = []
        for rs_name, rs_data in PLAYER_HANDLER.data_runescape.items():
            task = asyncio.create_task( safe_threading(bot, rs_name, rs_data) )
            tasks.append(task)
        await asyncio.gather(*tasks)
        # -- NEED TO RESOLVE CACHE ISSUE ---
        # queue = asyncio.Queue()
        # # Add player tuples to queue
        # for rs_name, rs_data in PLAYER_HANDLER.data_runescape.items():
        #     queue.put_nowait((rs_name, rs_data))
        # # Make certain amount of tasks based on players & times
        # tasks = []
        # for i in range(players_per_request):
        #     task = asyncio.create_task( player_queue_worker(queue, bot, time_between_players, player_total) )
        #     tasks.append(task)
        # # Wait till all player tasks are done in queue
        # await queue.join()
        # # Close tasks
        # for task in tasks:
        #     task.cancel()
        # # Wait till tasks are closed
        # await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        # Clear our cached DBs
        await PLAYER_HANDLER.remove_cache()
        logger.debug('Done looping all players! Cleared data cache.')
    return


# --- NEED TO FIX CACHING ISSUE ---
# QUEUE AND LIMIT AMOUNT OF PLAYER PAGES WE SCRAPE
async def player_queue_worker(queue, bot, time_between_players, player_total):
    while True:
        # time_between_players = 3  # for testing
        player = await queue.get()
        rs_name = player[0]
        rs_data = player[1]
        logger.debug(f'Got player in queue: {rs_name} | Players left in queue: {queue.qsize()}')
        await thread_player(bot, rs_name, rs_data)
        logger.debug(f'Sleeping player in queue: {rs_name}')
        await asyncio.sleep(time_between_players)
        queue.task_done()
        logger.debug(f'Done with player in queue: {rs_name} | Players left in queue: {queue.qsize()}')


# --- DEPRECATED ---
# LIMIT THE NUMBER OF PLAYERS WE PARSE AT THE SAME TIME
async def safe_threading(bot, rs_name, rs_data):
    # sem = asyncio.Semaphore( 5 )
    async with PLAYER_THREAD_LIMIT:
        return await thread_player(bot, rs_name, rs_data)


# THREAD A PLAYER SEPARATELY
async def thread_player(bot, rs_name, rs_data):
    logger.debug(f"Checking player: {rs_name}")
    parse_minigames = False
    # Check if we need to scrape this player
    player_discord_info = await PLAYER_HANDLER.get_all_player_info(rs_name)
    if not player_discord_info:  # SET TO 'NOT' WHEN ACTUALLY RUNNING!
        logger.info(f"{rs_name}: Skipping player not in any active servers")
        return
    ### Changed for aiohttp integration ###
    page = await util.get_page(rs_name)
    # if page isnt responding, skip player
    if page == None:
        logger.info(f"{rs_name}: Unable to get player | Page status: None")
        return
    logger.debug(f"{rs_name}: got final page...")
    soup = BeautifulSoup( page, 'html.parser' )
    logger.debug(f"{rs_name}: got soup...")
    scores = soup.find(id="contentHiscores")
    logger.debug(f"{rs_name}: got scores...")

    # check if player has no hiscore profile
    try:
        logger.debug(f"{rs_name}: contents[1]: " + scores.contents[1].name)
    except:
        logger.error(f"Error getting hiscores table! Skipping {rs_name}...")
        return
    if scores.contents[1].name != 'table':  # if there's no table, the player has no scores
        logger.info(f"{rs_name} not found! Skipping player.")
        return

    # player has hiscore profile
    logger.debug(f"{rs_name}: found player...")
    overall_xp_changed = False
    # Create player-update object
    Update = PlayerUpdate(rs_name, rs_data, player_discord_info)
    # Start looping through website rows
    for tr in scores.find_all('tr')[3:]:
        # find Overall row, skip if weve already found it
        if not overall_xp_changed and 'Overall' in tr.get_text():
            logger.debug(f"{rs_name}: found Overall row...")
            # if this fails then Overall is (likely) to be new to the json
            try:
                # if overall xp did not change, skip player
                if not util.xp_changed( rs_data['skills']['Overall']['xp'], tr.find_all('td')[4].get_text() ):
                    overall_xp_changed = False
                    logger.debug(f"{rs_name}: Overall xp didnt change, skipping...")
                    break  # SKIP POINT HERE
                                    # overall xp changed, lets keep going and make the new player dict
                else:
                    overall_xp_changed = True
                    logger.debug(f"{rs_name}: Overall xp changed, continuing...")
            except:
                overall_xp_changed = True
                logger.debug(f"{rs_name}: Overall skill will be added to player, continuing...")

        # if we are in the Minigames section, we need to change how we parse
        if 'Minigame' in tr.get_text():
            parse_minigames = True
            logger.debug(f"{rs_name}: found minigames...")
            continue  # skip minigame header row, moving onto 1st minigame row

        # do stuff with row/skill
        row_entry = tr.find_all('td')
        skill = row_entry[1].get_text().strip()
        skill_dict = {}
        logger.debug(f"{rs_name}: found row: {skill}...")

        # row is a skill row
        if not parse_minigames:
            skill_dict['rank'] = row_entry[2].get_text()
            skill_dict['level'] = row_entry[3].get_text()
            skill_dict['xp'] = row_entry[4].get_text()
            # check if this skill had an xp gain for a potential player-update
            if skill in rs_data['skills']:  # first check if skill already existed
                logger.debug(f"{rs_name}: skill exists...")
                oldXP = rs_data['skills'][skill]['xp']
                if skill_dict['xp'] != oldXP:
                    logger.debug(f"{rs_name}: skill xp changed, sending to Update...")
                    overall_xp_changed = True
                    await Update.update_skill(skill_dict, skill, False)
            else:  # skill didnt exist before on player's hiscores
                logger.debug(f"{rs_name}: skill doesnt exist, sending to Update...")
                overall_xp_changed = True
                await Update.update_skill(skill_dict, skill, True)
            # update skill to skills dict
            rs_data['skills'][skill] = skill_dict

        # row is a minigame row, parse_minigames == True
        else:
            skill_dict['rank'] = row_entry[2].get_text()
            skill_dict['score'] = row_entry[3].get_text()
            # check if this skill had an xp gain for a potential player-update
            if skill in rs_data['minigames']:  # first check if skill already existed
                logger.debug(f"{rs_name}: skill exists...")
                old_score = rs_data['minigames'][skill]['score']
                if skill_dict['score'] != old_score:
                    logger.debug(f"{rs_name}: minigame score changed, sending to Update...")
                    overall_xp_changed = True
                    await Update.update_minigame(skill_dict, skill, False)
            else:  # skill didnt exist before on player's hiscores
                logger.debug(f"{rs_name}: minigame doesnt exist, sending to Update...")
                overall_xp_changed = True
                await Update.update_minigame(skill_dict, skill, True)
            # update clue/boss to minigames dict
            rs_data['minigames'][skill] = skill_dict  

    # Finish up & post update
    if overall_xp_changed:
        logger.debug(f"{rs_name}: updating database value...")
        PLAYER_HANDLER.data_runescape[rs_name] = rs_data
        if Update.has_any_updates():
            # Get servers to post to for player
            for player_server in player_discord_info:
                try:
                    server = bot.get_guild(player_server['server'])
                    serv_name = server.name
                    logger.debug(f"{rs_name}: In server: {serv_name}...")
                    server_info = PLAYER_HANDLER.server_info_all[str(player_server['server'])]
                    logger.debug(f"{rs_name}: {serv_name}")
                    event_channel = server.get_channel(server_info['channel'])
                    if server_info['role'] == None:
                        rs_role = None
                    else:
                        rs_role = server.get_role(server_info['role'])
                    await Update.post_update(bot, server, event_channel, rs_role, player_server)
                # Any kind of error posting to server
                except Exception as e:
                    logger.exception(f"Error with server in player: {player_server['server']} -- {e}")
            logger.debug(f"{rs_name}: Posting update...")
        else:
            logger.debug(f"{rs_name}: No good criteria for update...")            

    logger.debug(f"{rs_name}: Done with player!")

# ----------------------------- END ACTIVITY LOG ----------------------------- #
    
    
# ---------------------------------------------------------------------------- #
#                             RUN SKILL OF THE WEEK                            #
# ---------------------------------------------------------------------------- #

# RUN MAIN LOOP
async def run_sotw_loop(bot):
    logger.debug('Checking times for SOTW...')
    # Check time now
    now_time = datetime.datetime.now()
    # Check for deadline + an hour before reminder & progress times
    pick_time_event = await db.check_sotw_times(now_time)
    if pick_time_event:
        # gather all_servers that are opted in for this next stuff...
        if pick_time_event == 'progress_time':
            await message_sotw_servers_progress(bot)
            logger.info('Sent SOTW progress to all servers!')
        elif pick_time_event == 'pre_time':
            await message_sotw_servers_pre(bot)
            logger.info('Sent SOTW pre-time to all servers!')
        elif pick_time_event == 'pick_time':
            await message_sotw_servers_reset(bot, now_time)
            logger.info('Sent SOTW RESET to all servers!')
    logger.debug('Done checking times for SOTW!')
    
    
# POST PROGRESS TO ALL ENABLED SERVERS
async def message_sotw_servers_progress(bot):
    all_servers = await db.get_sotw_servers(progress=True)
    for serv_dict in all_servers:
        Server = bot.get_guild(serv_dict['id'])
        await util.message_server(Server, serv_dict, await db.get_sotw_info(Server), False)
            

# POST PRE MESSAGE TO ALL ENABLED SERVERS
async def message_sotw_servers_pre(bot):
    all_servers = await db.get_sotw_servers(progress=False)
    for serv_dict in all_servers:
        Server = bot.get_guild(serv_dict['id'])
        await util.message_server(Server, serv_dict, await db.get_sotw_info(Server, pre_time=True), False)
        

# POST FINAL RANKS TO ALL ENABLED SERVERS & REST SOTW
async def message_sotw_servers_reset(bot, now_time):
    final_server_messages = await db.build_sotw_final(now_time)
    logger.debug('Built all server final messages...')
    await util.message_separate_servers(bot, final_server_messages, False)
    logger.info('Messaged all final rankings!')
    new_sotw_message = await db.change_new_sotw(now_time)
    logger.debug('Changed to new SOTW...')
    await util.message_all_servers(bot, final_server_messages['all_servers'], new_sotw_message, True)
    logger.info('Messaged all servers the new SOTW!')


# --------------------------- END SKILL OF THE WEEK -------------------------- #


# ---------------------------------------------------------------------------- #
#                             RUN BOSS OF THE WEEK                             #
# ---------------------------------------------------------------------------- #

# RUN MAIN LOOP
async def run_botw_loop(bot):
    logger.debug('Checking times for BOTW...')
    # Check time now
    now_time = datetime.datetime.now()
    # Check for deadline + an hour before reminder & progress times
    pick_time_event = await db.check_botw_times(now_time)
    if pick_time_event:
        # gather all_servers that are opted in for this next stuff...
        if pick_time_event == 'progress_time':
            await message_botw_servers_progress(bot)
            logger.info('Sent BOTW progress to all servers!')
        elif pick_time_event == 'pre_time':
            await message_botw_servers_pre(bot)
            logger.info('Sent BOTW pre-time to all servers!')
        elif pick_time_event == 'pick_time':
            await message_botw_servers_reset(bot, now_time)
            logger.info('Sent BOTW RESET to all servers!')
    logger.debug('Done checking times for BOTW!')
    
    
# POST PROGRESS TO ALL ENABLED SERVERS
async def message_botw_servers_progress(bot):
    all_servers = await db.get_botw_servers(progress=True)
    for serv_dict in all_servers:
        Server = bot.get_guild(serv_dict['id'])
        await util.message_server(Server, serv_dict, await db.get_botw_info(Server), False)
            

# POST PRE MESSAGE TO ALL ENABLED SERVERS
async def message_botw_servers_pre(bot):
    all_servers = await db.get_botw_servers(progress=False)
    for serv_dict in all_servers:
        Server = bot.get_guild(serv_dict['id'])
        await util.message_server(Server, serv_dict, await db.get_botw_info(Server, pre_time=True), False)
        

# POST FINAL RANKS TO ALL ENABLED SERVERS & REST BOTW
async def message_botw_servers_reset(bot, now_time):
    final_server_messages = await db.build_botw_final(now_time)
    logger.debug('Built all server final messages...')
    await util.message_separate_servers(bot, final_server_messages, False)
    logger.info('Messaged all final rankings!')
    new_botw_message = await db.change_new_botw(now_time)
    logger.debug('Changed to new BOTW...')
    await util.message_all_servers(bot, final_server_messages['all_servers'], new_botw_message, True)
    logger.info('Messaged all servers the new BOTW!')


# --------------------------- END BOSS OF THE WEEK --------------------------- #


# ---------------------------------------------------------------------------- #
#                               MAINLOOPER CLASS                               #
# ---------------------------------------------------------------------------- #

class MainLooper(commands.Cog):
    
    def __init__(self, bot):
        self.bot = bot

        # create the background task and run it in the background
        self.bot.bg_task = self.bot.loop.create_task(self.looper_task())

    async def on_ready(self):
        logger.debug('MainLooper Cog Ready')

    async def main_loop(self):
        logger.info('Starting main loop...')
        # Run player loop
        try: await run_osrs_loop(self.bot)
        except Exception as e: logger.exception(f'Unknown error running main loop: {e}')
        # Run Skill of the Week
        try: await run_sotw_loop(self.bot)
        except Exception as e: logger.exception(f'Unknown error running SOTW loop: {e}')
        # Run Boss of the Week
        try: await run_botw_loop(self.bot)
        except Exception as e: logger.exception(f'Unknown error running BOTW loop: {e}')

    async def looper_task(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(1.5)
        # --- START LOOPER ---
        logger.info('OSRS Event Log loop started!')
        while not self.bot.is_closed():
            await self.main_loop()
            logger.debug(f'Now sleeping for {TIME_LOOP_MINUTES} minutes...')
            await asyncio.sleep(await util.time_mins( TIME_LOOP_MINUTES ))


    # @commands.command()
    # @commands.cooldown(1, 5, commands.BucketType.guild)
    # async def testscores(self, ctx):
    #     if ctx.author.id == 134858274909585409:
    #         logger.debug('Running testscores...')
    #         await self.main_loop()
    #         logger.debug('Done with testscores!')
           

def setup(bot):
    bot.add_cog(MainLooper(bot))
# Member = A Discord member
# Player = A Runescape account

import asyncio
from common.logger import logger
from common import exceptions as ex
from . import helpers as h
from operator import itemgetter
import common.util as util

SOTW_PATH = h.FULL_DATA_PATH + "sotw/"
SOTW_POOL = SOTW_PATH + "all_skills.json"
SOTW_CONFIG = h.db_open_non_async(SOTW_PATH + "config.json")


async def get_sotw_info(Server):
    """Get all basic SOTW info for the server"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET SOTW INFO - Server: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    all_players = []
    try:
        # Loop all players in this server
        for player in db[f'server:{Server.id}#all_players']:
            # Igonore players with 0 xp
            if db[f'player:{player}#sotw_xp'] > 0:
                all_players.append( {'player': player, 'xp': db[f'player:{player}#sotw_xp']} )
        # Sort List by xp
        all_players = sorted(all_players, key=itemgetter('xp'), reverse = True)
        # Create full ranking string, top 10 people
        ranks_list = []
        i = 1
        for player in all_players[:10]:
            ranks_list.append(f"{i}: **{util.name_to_discord(player['player'])}** - {util.format_int_str(player['xp'])} XP\n")
            i += 1
    except Exception as e:
        logger.exception(e)
        ranks_list = ['No players!']
    # append list to string with ranks to send to bot
    ranks_list = "".join(ranks_list)
    final_str = f"Skill of the Week: **{SOTW_CONFIG['current_skill']}**  |  Deadline: **{SOTW_CONFIG['next_deadline']}**\n" + ranks_list
    logger.info(f"FINISHED GET SOTW INFO - Server: {Server.name} | ID: {Server.id}")
    return final_str

   
# NEEDS WORK
async def reset_sotw_all():
    """Reset all servers for Skill of the week and add final rankings to players"""
    logger.info('------------------------------')
    logger.info(f'Initialized UPDATE SOTW ENTRY - Name: {Server.name} | ID: {Server.id}')
    db = await h.db_open(SOTW_ACTIVE_PATH)
    db[f'server:{Server.id}#{entry}'] = new_val
    await h.db_write(SOTW_ACTIVE_PATH, db)
    logger.info(f"UPDATED SOTW ENTRY - Name: {Server.name} | ID: {Server.id} | Entry: {entry} | Value: {new_val}")


# NEEDS WORK
async def update_sotw_config(Server, entry, new_val):
    """Update the sotw config once a week"""
    pass

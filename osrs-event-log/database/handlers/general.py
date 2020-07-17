# Member = A Discord member
# Player = A Runescape account

import json
import os
from common.logger import logger
from common import exceptions as ex
from . import helpers as h


# ----------------------------- SIMPLE GET THINGS ---------------------------- #

def get_bot_token():
    return h.BOT_TOKEN

async def get_db_discord():
    return await h.db_open(h.DB_DISCORD_PATH)

async def get_db_runescape():
    return await h.db_open(h.DB_RUNESCAPE_PATH)

def get_custom_messages():
    return h.db_open_non_async(h.MESSAGES_PATH)


# ------------------------------- Verify Files ------------------------------- #

def verify_files(file_name):
    """Verify if a file is present in a path"""
    path_check = h.DATA_PATH + file_name
    if os.path.exists(path_check):
        logger.debug(f'Found {path_check}')
        pass
    else:
        if file_name == 'db_discord.json':
            db = {'active_servers': [],'removed_servers': []}
        else:
            db = {}
        with open(path_check, 'w') as outfile:  
            json.dump(db, outfile)
        logger.info(f'CREATED NEW FILE: {path_check}')
        
        
# ----------------------- Update Max Players Per Member ---------------------- #

async def update_max_players(new_val):
    """Updates max OSRS accounts per Discord member"""
    config_path = h.DIR_PATH + "/bot_config.json"
    try:
        config_all = await h.db_open(config_path)
        logger.debug(f'Old max players: {config_all["MAX_PLAYERS_PER_MEMBER"]}')
        config_all['MAX_PLAYERS_PER_MEMBER'] = new_val
        await h.db_write(config_path, config_all)
        h.MAX_PLAYERS_PER_MEMBER = new_val
    except Exception as e:
        raise ex.DataHandlerError(f'COULD NOT LOAD BOT CONFIG!')
        
        
# ---------------------------------- TESTING --------------------------------- #

# def verify_files(file_name):
#     """Verify if a file is present in a path"""
#     path_check = DATA_PATH + file_name
#     if os.path.exists(path_check):
#         logger.debug(f'Found {path_check}')
#         TEMP CODE FOR TESTING
#         if file_name == 'db_discord.json':
#             db = {'active_servers': [],'removed_servers': []}
#             with open(DB_DISCORD_PATH, 'w') as outfile:  
#                 json.dump(db, outfile, indent=4, sort_keys=False)
#         else:
#             db = {}
#             with open(DB_RUNESCAPE_PATH, 'w') as outfile:  
#                 json.dump(db, outfile, indent=4, sort_keys=False)
#         pass
#     else:
#         if file_name == 'db_discord.json':
#             db = {'active_servers': [],'removed_servers': []}
#         else:
#             db = {}
#         with open(path_check, 'w') as outfile:  
#             json.dump(db, outfile)
#         logger.info(f'CREATED NEW FILE: {path_check}')
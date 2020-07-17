# Data handler helpers
#

import pathlib
import asyncio
import json
from common.logger import logger
from common import exceptions as ex


# ------------------ Non-Async Json Read for Specific Things ----------------- #

def db_open_non_async(path):
    """Opens a json file as a python dict/list non-asyncronously"""
    with open(path,"r") as f:
        return json.load(f)

# --------------------------------- Constants -------------------------------- #

DIR_PATH = str(pathlib.Path().absolute())

BOT_INFO_ALL = db_open_non_async(DIR_PATH + "/bot_config.json")
BOT_TOKEN = BOT_INFO_ALL['BOT_TOKEN']
MAX_PLAYERS_PER_MEMBER = BOT_INFO_ALL['MAX_PLAYERS_PER_MEMBER']

DATA_PATH = "data/"
FULL_DATA_PATH = DIR_PATH + "/" + DATA_PATH
DB_DISCORD_PATH = FULL_DATA_PATH + "db_discord.json"
DB_RUNESCAPE_PATH = FULL_DATA_PATH + "db_runescape.json"
MESSAGES_PATH = FULL_DATA_PATH + "custom_messages.json"



# ------------------------------ Json Read/Write ----------------------------- #

async def db_open(path):
    """Opens a json file as a python dict/list"""
    with open(path,"r") as f:
        return json.load(f)

async def db_write(path, db):
    """Writes a python dict/list as a json file"""
    with open(path,"w") as f:
        json.dump(db, f, indent=4, sort_keys=False)
        # json.dump(db, f)
        


# ---------------------------- Specific Functions ---------------------------- #

async def check_player_member_link(db_dis, Server, Member, rs_name):
    """Check if a player already has a link to a server"""
    try:
        # This member already has this player
        if db_dis[f'player:{rs_name}#server:{Server.id}#member'] == Member.id:
            raise ex.DataHandlerError(f'**{Member.name}** is already linked to OSRS account: *{rs_name}*!')
        # This player had a member on this server but is now open (deprecated)
        elif db_dis[f'player:{rs_name}#server:{Server.id}#member'] == None:
            logger.debug(f'{rs_name} was used in this server before. {Member.name} will now try to take it')
            return True
        # Another member is using this player
        else:
            raise ex.DataHandlerError(f'OSRS account *{rs_name}* is already linked to another member on this server!')
    # This is an open player for this server
    except KeyError:
        return True


async def player_add_server(db_dis, Server, rs_name):
    """Try to add a server id to a player's all_servers list\n
    Add all_servers entry for the player if none already
    """
    try: 
        db_dis[f'player:{rs_name}#all_servers'].append(Server.id)
        logger.debug(f'{rs_name} is an existing player name...')
    except KeyError:
        db_dis[f'player:{rs_name}#all_servers'] = [Server.id]
        logger.debug(f'{rs_name} is a brand new player name...')


async def player_remove_server(db_dis, Server, rs_name):
    """Try to remove a server id from a player's all_servers list"""
    try: 
        db_dis[f'player:{rs_name}#all_servers'].remove(Server.id)
        logger.info(f'Removed server ID {Server.id} from {rs_name} in DB')
    except KeyError:
        raise ex.DataHandlerError(f'OSRS account *{rs_name}* is not present in any Activity Log!')
    except ValueError:
        raise ex.DataHandlerError(f"OSRS account *{rs_name}* is not present in this server's Activity Log!")


async def player_in_server_member(db_dis, Server, Member, rs_name):
    """Check if a player is in a member for this server\n
    Returns True or False"""
    try:
        # This member is using this player in this server
        if db_dis[f'player:{rs_name}#server:{Server.id}#member'] == Member.id:
            return True
        # Another member is using this player
        else:
            return False
    # This is an open player for this server
    except KeyError:
        raise ex.DataHandlerError(f"OSRS account *{rs_name}* is not present in this server's Activity Log!")

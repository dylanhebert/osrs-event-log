# Member = A Discord member
# Player = A Runescape account

import asyncio
from common.logger import logger
from common import exceptions as ex
from . import helpers as h


# -------------------------------- Add Server -------------------------------- #

async def add_server(Server):
    """Add a server to the bot"""
    logger.info('------------------------------')
    logger.info(f'Initialized ADD SERVER: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Check if bot has been removed before
    try: db['removed_servers'].remove(Server.id)
    except ValueError:
        db[f'server:{Server.id}#all_players'] = []
        db[f'server:{Server.id}#channel'] = None
        db[f'server:{Server.id}#role'] = None
        db[f'server:{Server.id}#sotw_opt'] = True
        db[f'server:{Server.id}#sotw_progress'] = True
        db[f'server:{Server.id}#sotw_history'] = []
        db[f'server:{Server.id}#botw_opt'] = True
        db[f'server:{Server.id}#botw_progress'] = True
        db[f'server:{Server.id}#botw_history'] = []
        logger.debug('New server...')
    db['active_servers'].append(Server.id)
    await h.db_write(h.DB_DISCORD_PATH, db)
    logger.info(f"ADDED NEW SERVER - Name: {Server.name} | ID: {Server.id}")
    return True


# ------------------------------- Remove Server ------------------------------ #

async def remove_server(Server):
    """Remove a server from the bot\n
    Retains server info in case server is added back"""
    logger.info('------------------------------')
    logger.info(f'Initialized REMOVE SERVER: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Remove from active servers list
    db['active_servers'].remove(Server.id)
    # Keep a list of removed servers
    db['removed_servers'].append(Server.id)
    await h.db_write(h.DB_DISCORD_PATH, db)
    logger.info(f"REMOVED SERVER - Name: {Server.name} | ID: {Server.id}")
    return True


# ---------------------------- Update Server Entry --------------------------- #

async def update_server_entry(Server, entry, new_val):
    """Update a server entry's value"""
    logger.info('------------------------------')
    logger.info(f'Initialized UPDATE SERVER ENTRY - Name: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    db[f'server:{Server.id}#{entry}'] = new_val
    await h.db_write(h.DB_DISCORD_PATH, db)
    logger.info(f"UPDATED SERVER ENTRY - Name: {Server.name} | ID: {Server.id} | Entry: {entry} | Value: {new_val}")


# ----------------------------- Get Server Entry ----------------------------- #

async def get_server_entry(Server, entry):
    """Get a server entry's value"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET SERVER ENTRY - Name: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    return db[f'server:{Server.id}#{entry}']


# ---------------------------- Get Server Players ---------------------------- #

async def get_server_players(Server):
    """Gets member IDs with all players in a server"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET SERVER PLAYERS - Name: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Loop through db to get member IDs for each player name
    members_players = {}
    for player in db[f'server:{Server.id}#all_players']:
        try: members_players[str(db[f'player:{player}#server:{Server.id}#member'])].append(player)
        except: members_players[str(db[f'player:{player}#server:{Server.id}#member'])] = [player]
    logger.info(f"GET SERVER PLAYERS - Name: {Server.name} | ID: {Server.id}")
    return members_players


# ---------------------------- Get Server Settings --------------------------- #

async def get_all_servers(Member):
    """Gets all settings in all servers"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET ALL SERVERS - Name: {Member.name} | ID: {Member.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Loop through db to get servers
    all_servers = []
    for server in db['active_servers']:
        serv_dict = {}
        serv_dict['id'] = server
        serv_dict['channel'] = db[f'server:{server}#channel']
        serv_dict['role'] = db[f'server:{server}#role']
        all_servers.append(serv_dict)
    logger.info(f"GET ALL SERVERS - Name: {Member.name} | ID: {Member.id}")
    return all_servers


async def toggle_server_entry(Server, entry):
    """Toggles a server entry's value between True and False"""
    logger.info('------------------------------')
    logger.info(f"Initialized TOGGLE SERVER ENTRY - Server: {Server.name} | ID: {Server.id} | Entry: {entry}")
    db = await h.db_open(h.DB_DISCORD_PATH)
    try: 
        new_toggle = not db[f'server:{Server.id}#{entry}']
        db[f'server:{Server.id}#{entry}'] = new_toggle
        await h.db_write(h.DB_DISCORD_PATH, db)
        logger.info(f"Finished TOGGLE SERVER ENTRY - Server: {Server.name} | ID: {Server.id} | Entry: {entry} = {str(new_toggle)}")
        return new_toggle
    except Exception as e: raise e

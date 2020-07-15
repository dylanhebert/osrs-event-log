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


# ---------------------------- Get Server Players ---------------------------- #

async def get_server_players(Server, Member, entry):
    """Gets info for all players in a server"""
    logger.info('------------------------------')
    logger.info(f'Initialized UPDATE SERVER ENTRY - Name: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    db[f'server:{Server.id}#{entry}'] = new_val
    await h.db_write(h.DB_DISCORD_PATH, db)
    logger.info(f"UPDATED SERVER ENTRY - Name: {Server.name} | ID: {Server.id} | Entry: {entry} | Value: {new_val}")
    return db[f'server:{Server.id}#{entry}']
# Member = A Discord member
# Player = A Runescape account
#
# Adapter layer — see general.py. Signatures unchanged; storage is data/repo.

from common.logger import logger
from data import repo


# -------------------------------- Add Server -------------------------------- #

async def add_server(Server):
    """Add a server to the bot"""
    logger.info('------------------------------')
    logger.info(f'Initialized ADD SERVER: {Server.id}')
    repo.servers.add(Server.id)
    logger.info(f"ADDED NEW SERVER - Name: {Server.name} | ID: {Server.id}")
    return True


# ------------------------------- Remove Server ------------------------------ #

async def remove_server(Server):
    """Remove a server from the bot\n
    Retains server info in case server is added back"""
    logger.info('------------------------------')
    logger.info(f'Initialized REMOVE SERVER: {Server.id}')
    repo.servers.remove(Server.id)
    logger.info(f"REMOVED SERVER - Name: {Server.name} | ID: {Server.id}")
    return True


# ---------------------------- Update Server Entry --------------------------- #

async def update_server_entry(Server, entry, new_val):
    """Update a server entry's value"""
    logger.info('------------------------------')
    logger.info(f'Initialized UPDATE SERVER ENTRY - Name: {Server.name} | ID: {Server.id}')
    repo.servers.set_option(Server.id, entry, new_val)
    logger.info(f"UPDATED SERVER ENTRY - Name: {Server.name} | ID: {Server.id} | Entry: {entry} | Value: {new_val}")


# ----------------------------- Get Server Entry ----------------------------- #

async def get_server_entry(Server, entry):
    """Get a server entry's value"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET SERVER ENTRY - Name: {Server.name} | ID: {Server.id}')
    return repo.servers.get_option(Server.id, entry)


# ---------------------------- Get Server Players ---------------------------- #

async def get_server_players(Server):
    """Gets member IDs with all players in a server"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET SERVER PLAYERS - Name: {Server.name} | ID: {Server.id}')
    members_players = repo.servers.members_players(Server.id)
    logger.info(f"GET SERVER PLAYERS - Name: {Server.name} | ID: {Server.id}")
    return members_players


# ---------------------------- Get Server Settings --------------------------- #

async def get_all_servers(Member):
    """Gets all settings in all servers"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET ALL SERVERS - Name: {Member.name} | ID: {Member.id}')
    all_servers = repo.servers.list_active()
    logger.info(f"GET ALL SERVERS - Name: {Member.name} | ID: {Member.id}")
    return all_servers


async def toggle_server_entry(Server, entry):
    """Toggles a server entry's value between True and False"""
    logger.info('------------------------------')
    logger.info(f"Initialized TOGGLE SERVER ENTRY - Server: {Server.name} | ID: {Server.id} | Entry: {entry}")
    new_toggle = repo.servers.toggle_option(Server.id, entry)
    logger.info(f"Finished TOGGLE SERVER ENTRY - Server: {Server.name} | ID: {Server.id} | Entry: {entry} = {str(new_toggle)}")
    return new_toggle

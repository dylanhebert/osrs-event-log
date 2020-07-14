# Member = A Discord member
# Player = A Runescape account
#

import pathlib
import json
import os
import asyncio
from common.logger import logger
from . import helpers as h
from common import exceptions as ex


# --------------------------------- Constants -------------------------------- #

DIR_PATH = str(pathlib.Path().absolute())
DATA_PATH = "database/"
FULL_DATA_PATH = DIR_PATH + "/" + DATA_PATH
DB_DISCORD_PATH = FULL_DATA_PATH + "db_discord.json"
DB_RUNESCAPE_PATH = FULL_DATA_PATH + "db_runescape.json"

MAX_PLAYERS_PER_MEMBER = 2


# ------------------------------ Json Read/Write ----------------------------- #

async def db_open(path):
    """Opens a json file as a python dict/list"""
    with open(path,"r") as f:
        return json.load(f)

async def db_write(path,db):
    """Writes a python dict/list as a json file"""
    with open(path,"w") as f:
        json.dump(db, f, indent=4, sort_keys=False)
        # json.dump(db, f)

# async def db_add(path,key,val):
#     db = await db_open(path)
#     db[key] = val
#     await db_write(path,db)

# async def db_append_list(path,key,val):
#     db = await db_open(path)
#     db[key].append(val)
#     await db_write(path,db)


# ------------------------------- Verify Files ------------------------------- #

def verify_files(file_name):
    """Verify if a file is present in a path"""
    path_check = DATA_PATH + file_name
    if os.path.exists(path_check):
        logger.debug(f'Found {path_check}')
        # TEMP CODE FOR TESTING
        # if file_name == 'db_discord.json':
        #     db = {'active_servers': [],'removed_servers': []}
        #     with open(DB_DISCORD_PATH, 'w') as outfile:  
        #         json.dump(db, outfile, indent=4, sort_keys=False)
        # else:
        #     db = {}
        #     with open(DB_RUNESCAPE_PATH, 'w') as outfile:  
        #         json.dump(db, outfile, indent=4, sort_keys=False)
        pass
    else:
        if file_name == 'db_discord.json':
            db = {'active_servers': [],'removed_servers': []}
        else:
            db = {}
        with open(path_check, 'w') as outfile:  
            json.dump(db, outfile)
        logger.info(f'CREATED NEW FILE: {path_check}')


# -------------------------------- Add Server -------------------------------- #

async def add_server(Server):
    """Add a server to the bot"""
    logger.info('------------------------------')
    logger.info(f'Initialized ADD SERVER: {Server.id}')
    db = await db_open(DB_DISCORD_PATH)
    # Check if bot has been removed before
    try: db['removed_servers'].remove(Server.id)
    except ValueError:
        db[f'server:{Server.id}#all_players'] = []
        db[f'server:{Server.id}#channel'] = None
        db[f'server:{Server.id}#role'] = None
        logger.debug('New server...')
    db['active_servers'].append(Server.id)
    await db_write(DB_DISCORD_PATH, db)
    logger.info(f"ADDED NEW SERVER - Name: {Server.name} | ID: {Server.id}")
    return True


# ------------------------------- Remove Server ------------------------------ #

async def remove_server(Server):
    """Remove a server from the bot\n
    Retains server info in case server is added back"""
    logger.info('------------------------------')
    logger.info(f'Initialized REMOVE SERVER: {Server.id}')
    db = await db_open(DB_DISCORD_PATH)
    # Remove from active servers list
    db['active_servers'].remove(Server.id)
    # Keep a list of removed servers
    db['removed_servers'].append(Server.id)
    await db_write(DB_DISCORD_PATH, db)
    logger.info(f"REMOVED SERVER - Name: {Server.name} | ID: {Server.id}")
    return True


# ---------------------------- Update Server Entry --------------------------- #

async def update_server_entry(Server, entry, new_val):
    """Update a server entry's value"""
    logger.info('------------------------------')
    logger.info(f'Initialized UPDATE SERVER ENTRY - Name: {Server.name} | ID: {Server.id}')
    db = await db_open(DB_DISCORD_PATH)
    db[f'server:{Server.id}#{entry}'] = new_val
    await db_write(DB_DISCORD_PATH, db)
    logger.info(f"UPDATED SERVER ENTRY - Name: {Server.name} | ID: {Server.id} | Entry: {entry} | Value: {new_val}")


# -------------------------------- Add Player -------------------------------- #

async def add_player(Server, Member, rs_name, stats_dict):
    """Add a player to a specific server\n
    Create new member if this member's id doesnt exist\n
    Returns False if player could not be added"""
    logger.info('------------------------------')
    logger.info(f'Initialized ADD PLAYER: {rs_name} | Added by: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}')

    # Open Discord DB
    db_dis = await db_open(DB_DISCORD_PATH)

    # Check if player is already in this server linked with a member
    try: await h.check_player_member_link(db_dis, Server, Member, rs_name)
    except Exception as e: raise e

    # Get list of existing players for this member in this server
    player_path = f'player:{rs_name}#server:{Server.id}'
    member_path = f'member:{Member.id}#server:{Server.id}'
    try: 
        # Member already has a player in this server
        player_list = db_dis[f'{member_path}#players']
        logger.debug(f'Found player list for member: {Member.id} in server: {Server.id}...')
    except KeyError:
        # Member doesn't have a player in this server
        player_list = []
        logger.info(f"ADDED NEW MEMBER - Name: {Member.name} | ID: {Member.id} | Server ID {Server.id}")
    if len(player_list) >= MAX_PLAYERS_PER_MEMBER:
        # Member has too many players for them in this server
        raise ex.DataHandlerError(f'You can only have up to **{MAX_PLAYERS_PER_MEMBER}** OSRS accounts connected to a Discord member per server.\n' 
                                f'Please remove one to add another. Current accounts: *{", ".join(player_list)}*\n'
                                'If you are changing an OSRS name, use *;transfer {old-name}>>{new-name}* to retain your Activity Log records')
    player_list.append(rs_name)

    # Add server to player (my method)
    await h.player_add_server(db_dis, Server, rs_name)
    # Add updated player list to member for this server
    db_dis[f'{member_path}#players'] = player_list
    # Add generic entries about this member
    db_dis[f'server:{Server.id}#all_players'].append(rs_name)
    db_dis[f'{player_path}#member'] = Member.id
    db_dis[f'{player_path}#mention'] = True
    db_dis[f'{player_path}#weekly_skill'] = {}
    await db_write(DB_DISCORD_PATH, db_dis)

    # Edit Runescape DB
    db_rs = await db_open(DB_RUNESCAPE_PATH)  # open Runescape DB
    db_rs[rs_name] = stats_dict
    await db_write(DB_RUNESCAPE_PATH, db_rs)
    logger.info(f"ADDED NEW PLAYER - RS name : {rs_name} | Member: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    return True


# ------------------------------- Remove Player ------------------------------ #

async def remove_player(Server, Member, rs_name):
    """Remove a player from a specific server\n
    Remove player from runescape.json if there are no more servers for player\n
    Returns False if player could not be removed"""
    logger.info('------------------------------')
    logger.info(f'Initialized REMOVE PLAYER: {rs_name} | Removed by: {Member.name}')
    db_dis = await db_open(DB_DISCORD_PATH)  # open Discord DB

    # Check if this player is in this server, try removing server from player
    try: await h.player_remove_server(db_dis, Server, rs_name)
    except Exception as e: raise e

    # Get ID of member in this server with this player (admin could be removing)
    player_path = f'player:{rs_name}#server:{Server.id}'
    linked_member = db_dis[f'{player_path}#member']
    # Update all DB entries for this player
    db_dis[f'member:{linked_member}#server:{Server.id}#players'].remove(rs_name)
    # Check if member has any more players in this server
    if not db_dis[f'member:{linked_member}#server:{Server.id}#players']:
        del db_dis[f'member:{linked_member}#server:{Server.id}#players']
    db_dis[f'server:{Server.id}#all_players'].remove(rs_name)
    del db_dis[f'{player_path}#member']
    del db_dis[f'{player_path}#mention']
    del db_dis[f'{player_path}#weekly_skill']

    # Check if there are no more instances of this player in any server
    if len(db_dis[f'player:{rs_name}#all_servers']) == 0:
        del db_dis[f'player:{rs_name}#all_servers']
        # Remove player from Runescape DB
        db_rs = await db_open(DB_RUNESCAPE_PATH)  # open Runescape DB
        del db_rs[rs_name]
        await db_write(DB_RUNESCAPE_PATH, db_rs)
        logger.info(f"Completely removed player from all DBs | RS name: {rs_name}")
    await db_write(DB_DISCORD_PATH, db_dis)
    logger.info(f"REMOVED PLAYER - RS name : {rs_name} | Linked Member ID : {linked_member} | Remover ID: {Member.id} | Server ID {Server.id}")
    return True


# ------------------------------- Rename Player ------------------------------ #

async def rename_player(Server, Member, old_rs_name, new_rs_name):
    """Rename a player in a specific server\n
    Move all info from old player to new player\n
    Returns False if player could not be renamed"""
    logger.info('------------------------------')
    logger.info(f'Initialized RENAME PLAYER: Old: {old_rs_name} | New: {new_rs_name} | Updated by: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}')
    if old_rs_name == new_rs_name:
        raise ex.DataHandlerError('These are the same names!')
    db_dis = await db_open(DB_DISCORD_PATH)  # open Discord DB
    
    # Check if new player is already in this server linked with a member
    try: await h.check_player_member_link(db_dis, Server, Member, new_rs_name)
    except Exception as e: raise e

    # Check if this server is in this player, try removing server from player
    try: await h.player_remove_server(db_dis, Server, rs_name)
    except Exception as e: raise e

    # Get list of existing players for this member in this server
    old_player_path = f'player:{old_rs_name}#server:{Server.id}'
    new_player_path = f'player:{new_rs_name}#server:{Server.id}'
    member_path = f'member:{Member.id}#server:{Server.id}'

    # Add server to player (my method)
    await h.player_add_server(db_dis, Server, new_rs_name)
    # Replace player in member's player list for this server
    db_dis[f'{member_path}#players'].remove(old_rs_name)
    db_dis[f'{member_path}#players'].append(new_rs_name)
    # Replace player in server's player list
    db_dis[f'server:{Server.id}#all_players'].remove(old_rs_name)
    db_dis[f'server:{Server.id}#all_players'].append(new_rs_name)
    # Replace old entries with new, updated entries
    db_dis[f'{new_player_path}#member'] = db_dis[f'{old_player_path}#member']
    db_dis[f'{new_player_path}#mention'] = db_dis[f'{old_player_path}#mention']
    db_dis[f'{new_player_path}#weekly_skill'] = db_dis[f'{old_player_path}#weekly_skill']
    # Remove old entries (MAY CHANGE LATER)
    del db_dis[f'{old_player_path}#member']
    del db_dis[f'{old_player_path}#mention']
    del db_dis[f'{old_player_path}#weekly_skill']

    # Edit Runescape DB
    # Check if there are no more instances of old player in any server
    db_rs = await db_open(DB_RUNESCAPE_PATH)  # open Runescape DB
    if len(db_dis[f'player:{old_rs_name}#all_servers']) == 0:
        del db_dis[f'player:{old_rs_name}#all_servers']
        # Remove old player from Runescape DB
        del db_rs[old_rs_name]
        await db_write(DB_RUNESCAPE_PATH, db_rs)
        logger.info(f"Completely removed player from all DBs | RS name : {old_rs_name}")
    await db_write(DB_DISCORD_PATH, db_dis)
    db_rs[new_rs_name] = {'skills': {}, 'minigames': {}}  # <-- this should already be built
    await db_write(DB_RUNESCAPE_PATH, db_rs)
    logger.info(f"RENAMED PLAYER: Old: {old_rs_name} | New: {new_rs_name} | Updated by: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    return True


# ----------------------------- Get Member Entry ----------------------------- #

async def get_member_entry(Server, Member, entry):
    """Get and return member entry's value"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET MEMBER ENTRY - Member: {Member.name} | ID: {Member.id} | Entry: {entry}')
    db = await db_open(DB_DISCORD_PATH)
    try: return db[f'member:{Member.id}#server:{Server.id}#{entry}']
    except KeyError:
        raise ex.DataHandlerError(f'Could not find {entry} for {Member.name}')

# ---------------------------- Toggle Player Entry --------------------------- #

async def toggle_player_entry(Server, Member, entry):
    """Toggles a player entry's value between True and False"""
    logger.info('------------------------------')
    logger.info(f'Initialized UPDATE SERVER ENTRY - Name: {Server.name} | ID: {Server.id}')
    db = await db_open(DB_DISCORD_PATH)
    db[f'server:{Server.id}#{entry}'] = new_val
    await db_write(DB_DISCORD_PATH, db)
    logger.info(f"UPDATED SERVER ENTRY - Name: {Server.name} | ID: {Server.id} | Entry: {entry} | Value: {new_val}")
    return db[f'server:{Server.id}#{entry}']
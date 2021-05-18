# Member = A Discord member
# Player = A Runescape account

import asyncio
from common.logger import logger
from common import exceptions as ex
from . import helpers as h


# -------------------------------- Add Player -------------------------------- #

async def add_player(Server, Member, rs_name, stats_dict):
    """Add a player to a specific server\n
    Create new member if this member's id doesnt exist\n
    Returns False if player could not be added"""
    logger.info('------------------------------')
    logger.info(f'Initialized ADD PLAYER: {rs_name} | Added by: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}')

    # Open Discord DB
    db_dis = await h.db_open(h.DB_DISCORD_PATH)

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
    if len(player_list) >= h.MAX_PLAYERS_PER_MEMBER:
        # Member has too many players for them in this server
        raise ex.DataHandlerError(f'You can only have up to **{h.MAX_PLAYERS_PER_MEMBER}** OSRS accounts connected to a Discord member per server.\n' 
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
    db_dis[f'{player_path}#sotw_opt'] = True
    await h.db_write(h.DB_DISCORD_PATH, db_dis)

    # Edit Runescape DB
    db_rs = await h.db_open(h.DB_RUNESCAPE_PATH)  # open Runescape DB
    db_rs[rs_name] = stats_dict
    await h.db_write(h.DB_RUNESCAPE_PATH, db_rs)
    logger.info(f"ADDED NEW PLAYER - RS name : {rs_name} | Member: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    return True


# ------------------------------- Remove Player ------------------------------ #

async def remove_player(Server, Member, rs_name, force_rm):
    """Remove a player from a specific server\n
    Remove player from runescape.json if there are no more servers for player\n
    Returns False if player could not be removed"""

    member_key_only = False
    if isinstance(Member, int):
        member_key_only = True
        member_name = Member
        member_id = Member
        logger.debug(f'Removing player with member key only: {member_name}, {rs_name}')
    else:
        member_name = Member.name
        member_id = Member.id

    logger.info('------------------------------')
    logger.info(f'Initialized REMOVE PLAYER: {rs_name} | Removed by: {member_name}')
    db_dis = await h.db_open(h.DB_DISCORD_PATH)  # open Discord DB

    # Check if Member passed is tied to this player on this server (non-admin remove)
    if not force_rm:
        try: 
            if not await h.player_in_server_member(db_dis, Server, member_id, rs_name):
                raise ex.DataHandlerError(f'**{member_name}** does not use OSRS account: *{rs_name}*')
        except Exception as e: raise e

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
    del db_dis[f'{player_path}#sotw_opt']

    # Check if there are no more instances of this player in any server
    if len(db_dis[f'player:{rs_name}#all_servers']) == 0:
        # Delete entries that apply to all instances of this player
        del db_dis[f'player:{rs_name}#all_servers']
        del db_dis[f'player:{rs_name}#sotw_xp']
        # Remove player from Runescape DB
        db_rs = await h.db_open(h.DB_RUNESCAPE_PATH)  # open Runescape DB
        try:
            del db_rs[rs_name]
        except:
            logger.debug(f"  -{rs_name} was not found in RS DB. Continuing...")
        await h.db_write(h.DB_RUNESCAPE_PATH, db_rs)
        logger.info(f"Completely removed player from all DBs | RS name: {rs_name}")
    await h.db_write(h.DB_DISCORD_PATH, db_dis)
    logger.info(f"REMOVED PLAYER - RS name : {rs_name} | Linked Member ID : {linked_member} | Remover ID: {member_id} | Server: {Server.name} | ID: {Server.id}")
    return True


# ------------------------------- Rename Player ------------------------------ #

async def rename_player(Server, Member, old_rs_name, new_rs_name, stats_dict):
    """Rename a player in a specific server\n
    Move all info from old player to new player\n
    Returns False if player could not be renamed"""
    logger.info('------------------------------')
    logger.info(f'Initialized RENAME PLAYER: Old: {old_rs_name} | New: {new_rs_name} | Updated by: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}')
    if old_rs_name == new_rs_name:
        raise ex.DataHandlerError('These are the same names!')
    db_dis = await h.db_open(h.DB_DISCORD_PATH)  # open Discord DB
    
    # Check if new player is already in this server linked with a member
    try: await h.check_player_member_link(db_dis, Server, Member, new_rs_name)
    except Exception as e: raise e

    # Check if this server is in this player, try removing server from player
    try: await h.player_remove_server(db_dis, Server, old_rs_name)
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
    db_dis[f'{new_player_path}#sotw_opt'] = db_dis[f'{old_player_path}#sotw_opt']
    db_dis[f'player:{new_rs_name}#sotw_xp'] = db_dis[f'player:{old_rs_name}#sotw_xp']
    # Remove old entries (MAY CHANGE LATER)
    del db_dis[f'{old_player_path}#member']
    del db_dis[f'{old_player_path}#mention']
    del db_dis[f'{old_player_path}#sotw_opt']

    # Edit Runescape DB
    # Check if there are no more instances of old player in any server
    db_rs = await h.db_open(h.DB_RUNESCAPE_PATH)  # open Runescape DB
    if len(db_dis[f'player:{old_rs_name}#all_servers']) == 0:
        # Delete entries that apply to all instances of this player
        del db_dis[f'player:{old_rs_name}#all_servers']
        del db_dis[f'player:{old_rs_name}#sotw_xp']
        # Remove old player from Runescape DB
        del db_rs[old_rs_name]
        await h.db_write(h.DB_RUNESCAPE_PATH, db_rs)
        logger.info(f"Completely removed player from all DBs | RS name : {old_rs_name}")
    await h.db_write(h.DB_DISCORD_PATH, db_dis)
    db_rs[new_rs_name] = stats_dict
    await h.db_write(h.DB_RUNESCAPE_PATH, db_rs)
    logger.info(f"RENAMED PLAYER: Old: {old_rs_name} | New: {new_rs_name} | Updated by: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    return True


# ---------------------------- Toggle Player Entry --------------------------- #

async def toggle_player_entry(Server, Member, rs_name, entry):
    """Toggles a player entry's value between True and False"""
    logger.info('------------------------------')
    logger.info(f"Initialized TOGGLE PLAYER ENTRY - Player: {rs_name} | Member: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    db = await h.db_open(h.DB_DISCORD_PATH)
    try: 
        if not await h.player_in_server_member(db, Server, Member, rs_name):
            raise ex.DataHandlerError(f'**{Member.name}** does not use OSRS account: *{rs_name}*')
    except Exception as e: raise e
    new_toggle = not db[f'player:{rs_name}#server:{Server.id}#{entry}']
    db[f'player:{rs_name}#server:{Server.id}#{entry}'] = new_toggle
    await h.db_write(h.DB_DISCORD_PATH, db)
    logger.info(f"FINISHED TOGGLE PLAYER ENTRY - Player: {rs_name} | Member: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    return new_toggle


# ----------------------- Update a global player entry ----------------------- #

async def update_player_entry_global(rs_name, entry, new_val):
    """Update a player's global entry"""
    logger.info('------------------------------')
    logger.info(f"Initialized UPDATE GLOBAL PLAYER ENTRY - Player: {rs_name} | Entry: {entry} | New Value: {new_val}")
    db = await h.db_open(h.DB_DISCORD_PATH)
    db[f'player:{rs_name}#{entry}'] = new_val
    await h.db_write(h.DB_DISCORD_PATH, db)
    logger.info(f"FINISHED UPDATE GLOBAL PLAYER ENTRY - Player: {rs_name} | Entry: {entry} | New Value: {new_val}")
    return new_toggle


# ---------------------- Add to a player's global entry ---------------------- #

async def add_to_player_entry_global(rs_name, entry, add_val):
    """Add to a player's global entry"""
    logger.info('------------------------------')
    logger.info(f"Initialized ADD TO GLOBAL PLAYER ENTRY - Player: {rs_name} | Entry: {entry} | Add Value: {add_val}")
    db = await h.db_open(h.DB_DISCORD_PATH)
    new_val = db[f'player:{rs_name}#{entry}'] + add_val
    db[f'player:{rs_name}#{entry}'] = new_val
    await h.db_write(h.DB_DISCORD_PATH, db)
    logger.info(f"FINISHED ADD TO GLOBAL PLAYER ENTRY - Player: {rs_name} | Entry: {entry} | New Value: {new_val}")
    return new_val

# Member = A Discord member
# Player = A Runescape account
#
# Adapter layer — see general.py. Signatures unchanged; storage is data/repo.

from common.logger import logger
from common import exceptions as ex
from data import repo
from . import helpers as h


# -------------------------------- Add Player -------------------------------- #

async def add_player(Server, Member, rs_name, stats_dict):
    """Add a player to a specific server\n
    Create new member if this member's id doesnt exist\n
    Returns False if player could not be added"""
    logger.info('------------------------------')
    logger.info(f'Initialized ADD PLAYER: {rs_name} | Added by: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}')

    existing_member = repo.players.linked_member(rs_name, Server.id)
    if existing_member is not None:
        if existing_member == Member.id:
            raise ex.DataHandlerError(
                f'**{Member.name}** is already linked to OSRS account: *{rs_name}*!')
        raise ex.DataHandlerError(
            f'OSRS account *{rs_name}* is already linked to another member on this server!')

    player_list = repo.players.member_players(Server.id, Member.id)
    if len(player_list) >= h.MAX_PLAYERS_PER_MEMBER:
        raise ex.DataHandlerError(f'You can only have up to **{h.MAX_PLAYERS_PER_MEMBER}** OSRS accounts connected to a Discord member per server.\n'
                                f'Please remove one to add another. Current accounts: *{", ".join(player_list)}*\n'
                                'If you are changing an OSRS name, use *;transfer {old-name}>>{new-name}* to retain your Activity Log records')

    with repo.transaction():
        player_id = repo.players.add_link(rs_name, Server.id, Member.id,
                                          mention=True, sotw_opt=True, botw_opt=True)
        repo.stats.replace_all(player_id, stats_dict)

    logger.info(f"ADDED NEW PLAYER - RS name : {rs_name} | Member: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    return True


# ------------------------------- Remove Player ------------------------------ #

async def remove_player(Server, Member, rs_name, force_rm):
    """Remove a player from a specific server\n
    Stop tracking the player if there are no more servers for them\n
    Returns False if player could not be removed"""

    if isinstance(Member, int):
        member_name = member_id = Member
        logger.debug(f'Removing player with member key only: {member_name}, {rs_name}')
    else:
        member_name = Member.name
        member_id = Member.id

    logger.info('------------------------------')
    logger.info(f'Initialized REMOVE PLAYER: {rs_name} | Removed by: {member_name}')

    if not repo.players.exists(rs_name):
        raise ex.DataHandlerError(f'OSRS account *{rs_name}* is not present in any Activity Log!')

    linked_member = repo.players.linked_member(rs_name, Server.id)
    if repo.players.link(rs_name, Server.id) is None:
        raise ex.DataHandlerError(f"OSRS account *{rs_name}* is not present in this server's Activity Log!")

    # A non-admin may only remove a player they are themselves linked to.
    if not force_rm and linked_member != member_id:
        raise ex.DataHandlerError(f'**{member_name}** does not use OSRS account: *{rs_name}*')

    with repo.transaction():
        repo.players.remove_link(rs_name, Server.id)
        remaining = repo.players.server_ids(rs_name)
        if not remaining:
            # Matches the old behaviour: the db_runescape entry went away but
            # sotw_xp / botw_kills stayed behind in db_discord.json.
            repo.players.untrack(rs_name)
            logger.info(f"Completely removed player from all DBs | RS name: {rs_name}")

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

    existing_member = repo.players.linked_member(new_rs_name, Server.id)
    if existing_member is not None:
        if existing_member == Member.id:
            raise ex.DataHandlerError(
                f'**{Member.name}** is already linked to OSRS account: *{new_rs_name}*!')
        raise ex.DataHandlerError(
            f'OSRS account *{new_rs_name}* is already linked to another member on this server!')

    if repo.players.link(old_rs_name, Server.id) is None:
        raise ex.DataHandlerError(f"OSRS account *{old_rs_name}* is not present in this server's Activity Log!")

    other_servers = [sid for sid in repo.players.server_ids(old_rs_name) if sid != Server.id]

    with repo.transaction():
        if other_servers:
            # The player is still in another server under the old name, so the
            # old identity has to survive. Create the new one alongside it, the
            # way the JSON version did by copying keys.
            player_id = repo.players.add_link(new_rs_name, Server.id, Member.id)
            repo.players.set_global(new_rs_name, 'sotw_xp',
                                    repo.players.get_global(old_rs_name, 'sotw_xp'))
            repo.players.set_global(new_rs_name, 'botw_kills',
                                    repo.players.get_global(old_rs_name, 'botw_kills'))
            repo.players.remove_link(old_rs_name, Server.id)
            repo.stats.replace_all(player_id, stats_dict)
        else:
            # Rename in place, keeping the id — so SOTW/BOTW history placements
            # and the whole stat history stay attached instead of detaching.
            repo.players.rename(old_rs_name, new_rs_name)
            player_id = repo.players.get_id(new_rs_name)
            repo.stats.replace_all(player_id, stats_dict)
            logger.info(f"Renamed player in place | Old: {old_rs_name} | New: {new_rs_name}")

    logger.info(f"RENAMED PLAYER: Old: {old_rs_name} | New: {new_rs_name} | Updated by: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    return True


# ---------------------------- Toggle Player Entry --------------------------- #

async def toggle_player_entry(Server, Member, rs_name, entry):
    """Toggles a player entry's value between True and False"""
    logger.info('------------------------------')
    logger.info(f"Initialized TOGGLE PLAYER ENTRY - Player: {rs_name} | Member: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    link = repo.players.link(rs_name, Server.id)
    if link is None:
        raise ex.DataHandlerError(f"OSRS account *{rs_name}* is not present in this server's Activity Log!")
    if link['member_id'] != Member.id:
        raise ex.DataHandlerError(f'**{Member.name}** does not use OSRS account: *{rs_name}*')

    new_toggle = not repo.players.get_link_option(rs_name, Server.id, entry)
    repo.players.set_link_option(rs_name, Server.id, entry, new_toggle)
    logger.info(f"FINISHED TOGGLE PLAYER ENTRY - Player: {rs_name} | Member: {Member.name} | ID: {Member.id} | Server: {Server.name} | ID: {Server.id}")
    return new_toggle


# ----------------------- Update a global player entry ----------------------- #

async def update_player_entry_global(rs_name, entry, new_val):
    """Update a player's global entry"""
    logger.info('------------------------------')
    logger.info(f"Initialized UPDATE GLOBAL PLAYER ENTRY - Player: {rs_name} | Entry: {entry} | New Value: {new_val}")
    repo.players.set_global(rs_name, entry, new_val)
    logger.info(f"FINISHED UPDATE GLOBAL PLAYER ENTRY - Player: {rs_name} | Entry: {entry} | New Value: {new_val}")
    return new_val


# ---------------------- Add to a player's global entry ---------------------- #

async def add_to_player_entry_global(rs_name, entry, add_val):
    """Add to a player's global entry"""
    logger.info('------------------------------')
    logger.info(f"Initialized ADD TO GLOBAL PLAYER ENTRY - Player: {rs_name} | Entry: {entry} | Add Value: {add_val}")
    new_val = repo.players.add_to_global(rs_name, entry, add_val)
    logger.info(f"FINISHED ADD TO GLOBAL PLAYER ENTRY - Player: {rs_name} | Entry: {entry} | New Value: {new_val}")
    return new_val


async def update_player_dinklink(rs_name, new_val):
    """Update a player's global dinklink"""
    logger.info('------------------------------')
    logger.info(f"Initialized UPDATE GLOBAL PLAYER DINKLINK - Player: {rs_name} | New Value: {new_val}")
    repo.players.set_dink_key(rs_name, new_val)
    logger.info(f"FINISHED UPDATE GLOBAL PLAYER DINKLINK - Player: {rs_name} | New Value: {new_val}")
    return new_val


async def is_member_linked_to_player(Server, Member, rs_name):
    linked = repo.players.linked_member(rs_name, int(Server))
    return linked is not None and int(linked) == int(Member)

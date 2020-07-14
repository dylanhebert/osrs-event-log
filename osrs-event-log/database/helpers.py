# Data handler helpers
#

import asyncio
from common.logger import logger
from common import exceptions as ex


async def check_player_member_link(db_dis, Server, Member, rs_name):
    """Check if a player already has a link to a server"""
    try:
        # This member already has this player
        if db_dis[f'player:{rs_name}#server:{Server.id}#member'] == Member.id:
            raise ex.DataHandlerError(f'**{Member.name}** is already linked to RS player *{rs_name}*!')
        # This player had a member on this server but is now open (removed)
        elif db_dis[f'player:{rs_name}#server:{Server.id}#member'] == None:
            logger.debug(f'{rs_name} was used in this server before. {Member.name} will now try to take it')
            return True
        # Another member is using this player
        else:
            raise ex.DataHandlerError(f'RS player *{rs_name}* is already linked to another member on this server!')
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
        raise ex.DataHandlerError(f'RS player *{rs_name}* is not present in any Activity Log!')
    except ValueError:
        raise ex.DataHandlerError(f"RS player *{rs_name}* is not present in this server's Activity Log!")

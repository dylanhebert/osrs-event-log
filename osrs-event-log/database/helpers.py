# data handler helpers
import asyncio


async def check_player_member_link(db_dis, Server, Member, rs_name):
    """Check if a player already has a link to a server"""
    try:
        # This member already has this player
        if db_dis[f'player:{rs_name}#server:{Server.id}#member'] == Member.id:
            print(f'{Member.name} is already linked to {rs_name}!')
            return False
        # This player had a member on this server but is now open
        elif db_dis[f'player:{rs_name}#server:{Server.id}#member'] == None:
            print(f'{rs_name} was used in this server before. {Member.name} will now try to take it')
            return True
        # Another member is using this player
        else:
            print(f'{rs_name} is already linked with a member in this server!')
            return False
    # This is an open player for this server
    except KeyError:
        return True


async def player_add_server(db_dis, Server, rs_name):
    """Try to add a server id to a player's all_servers list\n
    Add all_servers entry for the player if none already
    """
    try: 
        db_dis[f'player:{rs_name}#all_servers'].append(Server.id)
        print(f'{rs_name} is an existing player name...')
    except KeyError:
        db_dis[f'player:{rs_name}#all_servers'] = [Server.id]
        print(f'{rs_name} is a brand new player name...')


async def player_remove_server(db_dis, Server, rs_name):
    """Try to remove a server id from a player's all_servers list"""
    try: 
        db_dis[f'player:{rs_name}#all_servers'].remove(Server.id)
        print(f'Removed server ID {Server.id} from {rs_name} in DB')
        return db_dis
    except KeyError:
        print(f'{rs_name} is not present in the DB!')
        return None
    except ValueError:
        print(f'Server ID {Server.id} does not contain player {rs_name}!')
        return None

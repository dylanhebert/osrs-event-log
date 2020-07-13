# Member = A Discord member
# Player = A Runescape account
#

import pathlib
import json
import os


# --- VARIABLES ---
# paths to json files
DIR_PATH = str(pathlib.Path().absolute())
DB_DISCORD_PATH = DIR_PATH + "/db_discord.json"
DB_RUNESCAPE_PATH = DIR_PATH + "/db_runescape.json"

MAX_PLAYERS_PER_MEMBER = 2


def db_open(path):
    """Opens a json file as a python dict/list"""
    with open(path,"r") as f:
        return json.load(f)

def db_write(path,db):
    """Writes a python dict/list as a json file"""
    with open(path,"w") as f:
        json.dump(db, f, indent=4, sort_keys=False)
        # json.dump(db, f)

# def db_add(path,key,val):
#     db = db_open(path)
#     db[key] = val
#     db_write(path,db)

# def db_append_list(path,key,val):
#     db = db_open(path)
#     db[key].append(val)
#     db_write(path,db)


def check_player_member_link(db_dis, Server, Member, rs_name):
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


def player_add_server(db_dis, Server, rs_name):
    """Try to add a server id to a player's all_servers list\n
    Add all_servers entry for the player if none already
    """
    try: 
        db_dis[f'player:{rs_name}#all_servers'].append(Server.id)
        print(f'{rs_name} is an existing player name...')
    except KeyError:
        db_dis[f'player:{rs_name}#all_servers'] = [Server.id]
        print(f'{rs_name} is a brand new player name...')


def player_remove_server(db_dis, Server, rs_name):
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



class DataHandler:
    """Contains functions for handling all database operations"""
    def __init__(self):
        pass


    def verify_files(self,file_name):
        """Verify if a file is present in a path"""
        if os.path.exists(file_name):
            print(f'Found {file_name}')
            # TEMP CODE FOR TESTING
            if file_name == 'db_discord.json':
                db = {'active_servers': [],'removed_servers': []}
                db_write(DB_DISCORD_PATH, db)
            else:
                db = {}
                db_write(DB_RUNESCAPE_PATH, db)
            pass
        else:
            if file_name == 'db_discord.json':
                db = {'active_servers': [],'removed_servers': []}
            else:
                db = {}
            with open(file_name, 'w') as outfile:  
                json.dump(db, outfile)
            print(f'Created new {file_name}')


    def add_server(self, Server):
        """Add a server to the bot"""
        print('------------------------------')
        print(f'Initialized ADD SERVER: {Server.id}')
        db = db_open(DB_DISCORD_PATH)
        # Check if bot has been removed before
        try: db['removed_servers'].remove(Server.id)
        except ValueError:
            db[f'server:{Server.id}#all_players'] = []
            print('New server...')
        db['active_servers'].append(Server.id)
        db_write(DB_DISCORD_PATH, db)
        print(f"ADDED NEW SERVER - Name: {Server.name} | ID: {Server.id}")
        return True

    def remove_server(self, Server):
        """Remove a server from the bot\n
        Retains server info in case server is added back"""
        print('------------------------------')
        print(f'Initialized REMOVE SERVER: {Server.id}')
        db = db_open(DB_DISCORD_PATH)
        # Remove from active servers list
        db['active_servers'].remove(Server.id)
        # Keep a list of removed servers
        db['removed_servers'].append(Server.id)
        db_write(DB_DISCORD_PATH, db)
        print(f"REMOVED SERVER - Name: {Server.name} | ID: {Server.id}")
        return True

    
    def add_player(self, Server, Member, rs_name):
        """Add a player to a specific server\n
        Create new member if this member's id doesnt exist\n
        Returns False if player could not be added"""
        print('------------------------------')
        print(f'Initialized ADD PLAYER: {rs_name} | Added by: {Member.name}')
        # do RS name checking/verfying here...
        nameOK = True
        if not nameOK:
            print('This Runescape name is not valid!')
            return False
        print(f'Validated name: {rs_name}...')

        # Name is valid
        db_dis = db_open(DB_DISCORD_PATH)  # open Discord DB

        # Check if player is already in this server linked with a member
        if not check_player_member_link(db_dis, Server, Member, rs_name):
            print('Could not verify player-member link!')
            return False

        # Get list of existing players for this member in this server
        player_path = f'player:{rs_name}#server:{Server.id}'
        member_path = f'member:{Member.id}#server:{Server.id}'
        try: 
            # Member already has a player in this server
            player_list = db_dis[f'{member_path}#players']
            print(f'Found player list for member: {Member.id} in server: {Server.id}...')
        except KeyError:
            # Member doesn't have a player in this server
            player_list = []
            print(f"ADDED NEW MEMBER - Name: {Member.name} | ID: {Member.id} | Server ID {Server.id}")
        if len(player_list) >= MAX_PLAYERS_PER_MEMBER:
            # Member has too many players for them in this server
            print(f'You can only have up to {MAX_PLAYERS_PER_MEMBER} OSRS accounts connected to a Discord member per server.\n' 
                f'Please remove one to add another. Current accounts: {", ".join(player_list)}')
            return False
        player_list.append(rs_name)

        # Add server to player (my method)
        player_add_server(db_dis, Server, rs_name)
        # Add updated player list to member for this server
        db_dis[f'{member_path}#players'] = player_list
        # Add generic entries about this member
        db_dis[f'server:{Server.id}#all_players'].append(rs_name)
        db_dis[f'{player_path}#member'] = Member.id
        db_dis[f'{player_path}#mention'] = True
        db_dis[f'{player_path}#weekly_skill'] = {}
        db_write(DB_DISCORD_PATH, db_dis)

        # Edit Runescape DB
        db_rs = db_open(DB_RUNESCAPE_PATH)  # open Runescape DB
        db_rs[rs_name] = {'skills': {}, 'minigames': {}}  # <-- this should already be built
        db_write(DB_RUNESCAPE_PATH, db_rs)
        print(f"ADDED NEW PLAYER - RS name : {rs_name} | Member: {Member.name} | ID: {Member.id} | Server ID {Server.id}")
        return True


    def remove_player(self, Server, Member, rs_name):
        """Remove a player from a specific server\n
        Remove player from runescape.json if there are no more servers for player\n
        Returns False if player could not be removed"""
        print('------------------------------')
        print(f'Initialized REMOVE PLAYER: {rs_name} | Removed by: {Member.name}')
        db_dis = db_open(DB_DISCORD_PATH)  # open Discord DB

        # Check if this player is in this server, try removing server from player
        if not player_remove_server(db_dis,Server,rs_name):
            print(f'Could not remove player: {rs_name}')
            return False

        # Get ID of member in this server with this player (admin could be removing)
        player_path = f'player:{rs_name}#server:{Server.id}'
        linked_member = db_dis[f'{player_path}#member']
        # Update all DB entries for this player
        db_dis[f'member:{linked_member}#server:{Server.id}#players'].remove(rs_name)
        db_dis[f'server:{Server.id}#all_players'].remove(rs_name)
        # db_dis[f'{player_path}#member'] = None
        del db_dis[f'{player_path}#member']
        del db_dis[f'{player_path}#mention']
        del db_dis[f'{player_path}#weekly_skill']
        db_write(DB_DISCORD_PATH, db_dis)

        # Check if there are no more instances of this player in any server
        if len(db_dis[f'player:{rs_name}#all_servers']) == 0:
            # Remove player from Runescape DB
            db_rs = db_open(DB_RUNESCAPE_PATH)  # open Runescape DB
            del db_rs[rs_name]
            db_write(DB_RUNESCAPE_PATH, db_rs)
            print(f"Completely removed player from all DBs | RS name: {rs_name}")
        print(f"REMOVED PLAYER - RS name : {rs_name} | Linked Member ID : {linked_member} | Remover ID: {Member.id} | Server ID {Server.id}")
        return True


    def rename_player(self, Server, Member, old_rs_name, new_rs_name):
        """Rename a player in a specific server\n
        Move all info from old player to new player\n
        Returns False if player could not be renamed"""
        print('------------------------------')
        print(f'Initialized RENAME PLAYER: Old: {old_rs_name} | New: {new_rs_name} | Updated by: {Member.name}')
        if old_rs_name == new_rs_name:
            print('These are the same names!')
            return False
        db_dis = db_open(DB_DISCORD_PATH)  # open Discord DB
        
        # Check if new player is already in this server linked with a member
        if not check_player_member_link(db_dis, Server, Member, new_rs_name):
            print('Could not verify player-member link!')
            return False

        # Check if this server is in this player, try removing server from player
        if not player_remove_server(db_dis,Server,old_rs_name):
            print(f'Could not remove player: {old_rs_name}')
            return False

        # Get list of existing players for this member in this server
        old_player_path = f'player:{old_rs_name}#server:{Server.id}'
        new_player_path = f'player:{new_rs_name}#server:{Server.id}'
        member_path = f'member:{Member.id}#server:{Server.id}'

        # Add server to player (my method)
        player_add_server(db_dis, Server, new_rs_name)
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
        db_write(DB_DISCORD_PATH, db_dis)

        # Edit Runescape DB
        # Check if there are no more instances of old player in any server
        db_rs = db_open(DB_RUNESCAPE_PATH)  # open Runescape DB
        if len(db_dis[f'player:{old_rs_name}#all_servers']) == 0:
            # Remove old player from Runescape DB
            del db_rs[old_rs_name]
            db_write(DB_RUNESCAPE_PATH, db_rs)
            print(f"Completely removed player from all DBs | RS name : {old_rs_name}")
        db_rs[new_rs_name] = {'skills': {}, 'minigames': {}}  # <-- this should already be built
        db_write(DB_RUNESCAPE_PATH, db_rs)
        print(f"RENAMED PLAYER: Old: {old_rs_name} | New: {new_rs_name} | Updated by ID: {Member.id} | Server ID {Server.id}")
        return True

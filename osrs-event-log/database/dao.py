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


# OPEN JSON FILE
def db_open(path):
    with open(path,"r") as f:
        return json.load(f)

# WRITE JSON FILE
def db_write(path,db):
    with open(path,"w") as f:
        json.dump(db, f, indent=4, sort_keys=False)
        # json.dump(db, f)

def db_add(path,key,val):
    db = db_open(path)
    db[key] = val
    db_write(path,db)

def db_append_list(path,key,val):
    db = db_open(path)
    db[key].append(val)
    db_write(path,db)



class DataHandler:
    def __init__(self):
        pass


    def verify_files(self,file_name):
        if os.path.exists(file_name):
            print(f'Found {file_name}')
            # TEMP CODE FOR TESTING
            if file_name == 'db_discord.json':
                db = {'all_servers': []}
                db_write(DB_DISCORD_PATH, db)
            else:
                db = {}
                db_write(DB_RUNESCAPE_PATH, db)
            pass
        else:
            if file_name == 'db_discord.json':
                db = {'all_servers': []}
            else:
                db = {}
            with open(file_name, 'w') as outfile:  
                json.dump(db, outfile)
            print(f'Created new {file_name}')


    def add_server(self, Server):
        db = db_open(DB_DISCORD_PATH)
        # If server is not in DB
        if not Server.id in db['all_servers']:
            db[f'server:{Server.id}#all_members'] = []
        # Set this no matter what
        db['all_servers'].append(Server.id)
        # {'id': Server.id, 'name': Server.name, 'active': True}
        db_write(DB_DISCORD_PATH, db)
        print(f"Added new server | Name: {Server.name} | ID: {Server.id}")

    
    def add_player(self, Server, Member, rs_name):
        # do RS name checking/verfying here...
        nameOK = True
        if not nameOK:
            return print('This Runescape name is not valid!')
        print(f'Validated name: {rs_name}...')
        # Name is valid
        db_dis = db_open(DB_DISCORD_PATH)  # open Discord DB
        member_path = f'server:{Server.id}#member:{Member.id}'
        # Member doesn't have a player for this server
        if f'{member_path}#all_rs_names' not in db_dis:
            db_dis[f'{member_path}#all_rs_names'] = [rs_name]
            db_dis[f'server:{Server.id}#all_members'].append(Member.id)
            print(f"Added new member | Name: {Member.name} | ID: {Member.id} | Server ID {Server.id}")
        # Member has at least 1 player for this server
        else:
            # Member has too many players for them in this server
            print('Current names: ' + str(db_dis[f'{member_path}#all_rs_names']))
            if len(db_dis[f'{member_path}#all_rs_names']) >= MAX_PLAYERS_PER_MEMBER:
                return print(f'You can only have up to {MAX_PLAYERS_PER_MEMBER} OSRS accounts connected to your Discord account per server.\n' 
                            f'Please remove one to add another. Current accounts: {", ".join(db_dis[f"{member_path}#all_rs_names"])}')
            # Member can add another player to this server
            db_dis[f'{member_path}#all_rs_names'].append(rs_name)
        # Add generic entries about this member
        db_dis[f'{member_path}#{rs_name}#mention'] = True
        db_dis[f'{member_path}#{rs_name}#weekly_skill'] = {}
        db_write(DB_DISCORD_PATH, db_dis)
        # Edit Runescape DB
        db_rs = db_open(DB_RUNESCAPE_PATH)  # open Runescape DB
        db_rs[rs_name] = {'skills': {}, 'minigames': {}}  # <-- this should already be built
        db_write(DB_RUNESCAPE_PATH, db_rs)
        print(f"Added new player | RS name : {rs_name} | Member: {Member.name} | ID: {Member.id} | Server ID {Server.id}")

    

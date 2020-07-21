# Member = A Discord member
# Player = A Runescape account

import asyncio
from common.logger import logger
from common import exceptions as ex
from . import helpers as h
from operator import itemgetter
import common.util as util
import datetime
import calendar
import random

# --------------------------------- CONSTANTS -------------------------------- #

SOTW_PATH = h.FULL_DATA_PATH + "sotw/"
SOTW_POOL = SOTW_PATH + "all_skills.json"
SOTW_CONFIG_PATH = SOTW_PATH + "config.json"
SOTW_CONFIG = h.db_open_non_async(SOTW_CONFIG_PATH)
logger.debug('Loaded SOTW config into cache.')

SOTW_BASIC_FMT = "%m-%d-%y"         # String format for basic SOTW displaying and saving
SOTW_COMPARE_FMT = "%m-%d-%y %H"    # String format for comparing times
PRE_PICK_HOURS = 1                  # Hours before pick time to show hiscores once more
TOP_PLAYERS_COUNT = 10              # Number of players to show on SOTW info and get SOTW histories
DAYS_BETWEEN_SOTW = 8               # SHOULD BE 7, Days to the next SOTW reset

RANK_AWARDS = {
    1: 'Rune Trophy',
    2: 'Adamant Trophy',
    3: 'Mithril Trophy'
}

MESSAGE_DIVIDER = "\n- - - - - - - - - - - - - - - - - - - - - - - - - - -\n"


# --------------------- Get top SOTW players in a server --------------------- #

async def get_sotw_top_players(db, server_id):
    all_players = []
    # Loop all players in this server
    for player in db[f'server:{server_id}#all_players']:
        # Igonore players with 0 xp
        if db[f'player:{player}#sotw_xp'] > 0:
            all_players.append( {'player': player, 'xp': db[f'player:{player}#sotw_xp']} )
    # Sort List by xp
    all_players = sorted(all_players, key=itemgetter('xp'), reverse = True)
    return all_players[:TOP_PLAYERS_COUNT]


# --------------------- Reset every player's XP for SOTW --------------------- #

async def reset_sotw_xp(db_dis):
    db_rs = await h.db_open(h.DB_RUNESCAPE_PATH)
    for player in db_rs.keys():
        db_dis[f'player:{player}#sotw_xp'] = 0


# ----------------------- Build ranks from top players ----------------------- #

async def ranks_from_top_players(top_players, join_to_str=True, give_awards=False):
    try:
        ranks_list = []
        i = 1
        for player in top_players:
            if give_awards and i <= 3: award = f'  - **{RANK_AWARDS[i]}**'
            else: award = ''
            ranks_list.append(f"{i}: **{util.name_to_discord(player['player'])}** - {util.format_int_str(player['xp'])} XP{award}")
            i += 1
    except Exception as e:
        logger.exception(e)
        ranks_list = ['Error building ranks!']
    if join_to_str:
        ranks_list = '\n'.join(ranks_list)
    return ranks_list

# Build the Final String for ranks
async def build_final_rank_str(ranks_list, skill, old_date=None):
    if old_date:
        # Bring in an old date, may be checking history
        deadline = datetime.datetime.strptime(old_date, SOTW_BASIC_FMT)
        return f"Skill of the Week: **{skill}**  |  **Final Rankings**  |  *{deadline.strftime('%A, %B %d, %Y')}*\n" + ranks_list
    else:
        # Progress report or command called
        deadline = datetime.datetime.strptime(f"{SOTW_CONFIG['pick_next']} {SOTW_CONFIG['pick_hour']}", SOTW_COMPARE_FMT)
        return f"Skill of the Week: **{skill}**  |  Deadline: **{deadline.strftime('%A, %B %d at %-I%p')} CST**\n" + ranks_list



# ------------------------- Get SOTW Info for Server ------------------------- #

async def get_sotw_info(Server, pre_time=False):
    """Get all basic SOTW info for the server"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET SOTW INFO - Server: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Create full ranking string, top 10 people
    top_players = await get_sotw_top_players(db, Server.id)
    ranks_list = await ranks_from_top_players(top_players)
    final_str = await build_final_rank_str(ranks_list, skill=SOTW_CONFIG['current_skill'])
    # Add notice if we're posting progress for pre_time
    if pre_time:
        final_str = "**LAST CHANCE!** This Skill of the Week is almost over!" + MESSAGE_DIVIDER + final_str
    logger.info(f"FINISHED GET SOTW INFO - Server: {Server.name} | ID: {Server.id}")
    return final_str


async def get_sotw_history(Server):
    """Get all basic SOTW history for the server"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET SOTW HISTORY - Server: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    history_list = []
    # Loop through all weeks in server
    for week in db[f'server:{Server.id}#sotw_history']:
        ranks_list = await ranks_from_top_players(week['players'], give_awards=True)
        history_list.append(await build_final_rank_str(ranks_list, skill=week['skill'], old_date=week['date']))
    logger.info(f"FINISHED GET SOTW HISTORY - Server: {Server.name} | ID: {Server.id}")
    return history_list


# ----------------------------- Check SOTW Times ----------------------------- #

async def check_sotw_times(now_time):
    """Checks the datetime.now with the time in SOTW config"""
    ## ADD CHECK TO MAKE SURE PICK_NEXT ISNT BEFORE NOW_TIME
    logger.debug('------------------------------')
    logger.debug(f'Initialized CHECK SOTW TIMES - Time Now: {now_time}')
    # If it's time to pick new SOTW
    if now_time.strftime(SOTW_COMPARE_FMT) == f"{SOTW_CONFIG['pick_next']} {SOTW_CONFIG['pick_hour']}":
        SOTW_CONFIG['pick_imminent'] = False
        logger.info('Pick Time! Reset pick_imminent.')
        return 'pick_time'
    # Remind for 1 hour left
    if not SOTW_CONFIG['pick_imminent']:
        if now_time.strftime(SOTW_COMPARE_FMT) == f"{SOTW_CONFIG['pick_next']} {SOTW_CONFIG['pick_hour'] - PRE_PICK_HOURS}":
            SOTW_CONFIG['pick_imminent'] = True
            await update_sotw_config(SOTW_CONFIG)
            logger.info('Pre Time! Enabled pick_imminent')
            return 'pre_time'
    # If it's time to post progress
    for post_hour in SOTW_CONFIG['progress_hours']:
        if not post_hour['done']:
            # Valid progress hour
            if now_time.hour == post_hour['hour']:
                post_hour['done'] = True
                await update_sotw_config(SOTW_CONFIG)
                logger.info(f"Progress time! Hour: {post_hour['hour']}")
                return 'progress_time'                
        else:
            # Past hour that was done, reset it for tomorrow
            if now_time.hour != post_hour['hour']:
                post_hour['done'] = False
                await update_sotw_config(SOTW_CONFIG)
                logger.info(f"Reset Done parameter for hour: {post_hour['hour']}")
    logger.debug(f'No time matches!')
    return None

   
# -------- Build final SOTW strings for servers & update players in DB ------- #

async def build_sotw_final(now_time):
    """Reset all servers for Skill of the week and add final rankings to players"""
    logger.info('------------------------------')
    logger.info(f'Initialized SOTW RESET')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Loop through db to get servers
    all_servers = []
    all_messages = {}
    for server in db['active_servers']:
        logger.debug(f'In server {server}...')
        # Make sure server is opted in for SOTW
        if db[f'server:{server}#sotw_opt']:
            serv_dict = {}
            serv_dict['id'] = server
            serv_dict['channel'] = db[f'server:{server}#channel']
            serv_dict['role'] = db[f'server:{server}#role']
            all_servers.append(serv_dict)
            # Get top players
            top_players = await get_sotw_top_players(db, server)
            ranks_list = await ranks_from_top_players(top_players, give_awards=True)
            final_str = ("**Congratulations** to the winners!" + MESSAGE_DIVIDER + 
                    await build_final_rank_str(ranks_list, skill=SOTW_CONFIG['current_skill'], old_date=now_time.strftime(SOTW_BASIC_FMT)) 
                    + MESSAGE_DIVIDER)
            logger.debug('Got top players...')
            # New history record for server
            new_history = {
                'date': now_time.strftime(SOTW_BASIC_FMT),
                'skill': SOTW_CONFIG['current_skill'],
                'players': []
            }
            i = 1
            # Loop through top 3 players
            for pd in top_players[:3]:
                new_history['players'].append({ 
                    'player': pd['player'],
                    'xp': pd['xp'],
                    'rank': i
                })
                i += 1
            db[f'server:{server}#sotw_history'].append(new_history)
            logger.debug('Appended history!')
            all_messages[str(server)] = final_str
            logger.debug('Added final message!')
            # Loop to next server
    await reset_sotw_xp(db)
    logger.info('Set all SOTW XP to 0!')
    await h.db_write(h.DB_DISCORD_PATH, db)
    logger.debug('Wrote all to DB!')
    return {
        'all_servers': all_servers,
        'all_messages': all_messages
    }
    

# --------------------- Change to a new Skill of the Week -------------------- #

async def change_new_sotw(now_time):
    """Change to new SOTW & build a message string with new SOTW"""
    logger.info('------------------------------')
    logger.info(f"Initialized CHANGE NEW SOTW - Old SOTW: {SOTW_CONFIG['current_skill']}")
    # Update recent skills
    current_skill = SOTW_CONFIG['current_skill']
    del SOTW_CONFIG['recent_skills'][0]
    SOTW_CONFIG['recent_skills'].append(current_skill)
    # Make sure new skill is not in recent skills
    skill_pool = await h.db_open(SOTW_POOL)
    while current_skill in SOTW_CONFIG['recent_skills']:
        current_skill = random.choice(skill_pool['all_skills'])
    # Got new skill
    SOTW_CONFIG['current_skill'] = current_skill
    # Make new deadline a week later from now
    new_deadline = (now_time+datetime.timedelta(days=DAYS_BETWEEN_SOTW))
    SOTW_CONFIG['pick_next'] = new_deadline.strftime(SOTW_BASIC_FMT)
    await update_sotw_config(SOTW_CONFIG)
    new_sotw_message = f"The new Skill of the Week is **{current_skill}**! The deadline is on *{new_deadline.strftime('%A, %B %d')}*. Get skilling!"
    logger.info(f"FINISHED CHANGE NEW SOTW - New SOTW: {current_skill} | New deadline: {new_deadline.strftime(SOTW_BASIC_FMT)}")
    return new_sotw_message


# NEEDS WORK
async def update_sotw_config(config_new):
    """Update the entire SOTW config with current config in cache"""
    logger.info('------------------------------')
    logger.info(f'Initialized UPDATE SOTW CONFIG')
    global SOTW_CONFIG
    SOTW_CONFIG = config_new
    await h.db_write(SOTW_CONFIG_PATH, SOTW_CONFIG)
    logger.info(f'FINISHED UPDATE SOTW CONFIG')


async def get_sotw_servers(progress):
    """Gets all settings in all servers with sotw enabled"""
    logger.debug('------------------------------')
    logger.debug(f'Initialized GET SOTW SERVERS - Progress report: {progress}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Loop through db to get servers
    all_servers = []
    for server in db['active_servers']:
        # Make sure server is opted in for SOTW
        if db[f'server:{server}#sotw_opt']:
            # Only add servers with progress reports enabled, or all if not asking for progresses
            if progress and db[f'server:{server}#sotw_progress'] or not progress:
                serv_dict = {}
                serv_dict['id'] = server
                serv_dict['channel'] = db[f'server:{server}#channel']
                serv_dict['role'] = db[f'server:{server}#role']
                all_servers.append(serv_dict)
    logger.debug(f"FINISHED GET SOTW SERVERS - Progress report: {progress}")
    return all_servers


# NECESSARY?
async def get_sotw_entry(entry):
    """Gets a single entry from SOTW config"""
    return SOTW_CONFIG[entry]


# NEEDS WORK
async def add_sotw_progress_hour(new_hour):
    """Adds a new sotw progress hour, reorganizes list by hour"""
    pass


# NEEDS WORK
async def remove_sotw_progress_hour(rm_hour):
    """Removes an existing sotw progress hour, sends back exception if hour not there"""
    pass

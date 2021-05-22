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

BOTW_PATH = h.FULL_DATA_PATH + "botw/"
BOTW_POOL = BOTW_PATH + "all_bosses.json"
BOTW_CONFIG_PATH = BOTW_PATH + "botw_config.json"
BOTW_CONFIG = h.db_open_non_async(BOTW_CONFIG_PATH)
logger.debug('Loaded BOTW config into cache.')

BOTW_BASIC_FMT = "%m-%d-%y"         # String format for basic BOTW displaying and saving
BOTW_COMPARE_FMT = "%m-%d-%y %H"    # String format for comparing times
PRE_PICK_HOURS = 1                  # Hours before pick time to show hiscores once more
TOP_PLAYERS_COUNT = 10              # Number of players to show on BOTW info and get BOTW histories
DAYS_BETWEEN_BOTW = 7               # SHOULD BE 7, Days to the next BOTW reset

RANK_AWARDS = {
    1: 'Rune Trophy',
    2: 'Adamant Trophy',
    3: 'Mithril Trophy'
}

MESSAGE_DIVIDER = "\n- - - - - - - - - - - - - - - - - - - - - - - - - - -\n"


# --------------------- Get top BOTW players in a server --------------------- #

async def get_botw_top_players(db, server_id):
    all_players = []
    # Loop all players in this server
    for player in db[f'server:{server_id}#all_players']:
        # Igonore players with 0 kills
        if db[f'player:{player}#botw_kills'] > 0:
            all_players.append( {'player': player, 'kills': db[f'player:{player}#botw_kills']} )
    # Sort List by kills
    all_players = sorted(all_players, key=itemgetter('kills'), reverse = True)
    return all_players[:TOP_PLAYERS_COUNT]


# --------------------- Reset every player's kills for BOTW --------------------- #

async def reset_botw_kills(db_dis):
    db_rs = await h.db_open(h.DB_RUNESCAPE_PATH)
    for player in db_rs.keys():
        db_dis[f'player:{player}#botw_kills'] = 0


# ----------------------- Build ranks from top players ----------------------- #

async def ranks_from_top_players(top_players, join_to_str=True, give_awards=False):
    try:
        ranks_list = []
        i = 1
        for player in top_players:
            if give_awards and i <= 3: award = f'  - **{RANK_AWARDS[i]}**'
            else: award = ''
            ranks_list.append(f"{i}: **{util.name_to_discord(player['player'])}** - {util.format_int_str(player['kills'])} kills{award}")
            i += 1
    except Exception as e:
        logger.exception(e)
        ranks_list = ['Error building ranks!']
    if join_to_str:
        ranks_list = '\n'.join(ranks_list)
    return ranks_list

# Build the Final String for ranks
async def build_final_rank_str(ranks_list, boss, old_date=None):
    if old_date:
        # Bring in an old date, may be checking history
        deadline = datetime.datetime.strptime(old_date, BOTW_BASIC_FMT)
        return f"Boss of the Week: **{boss}**  |  **Final Rankings**  |  *{deadline.strftime('%A, %B %d, %Y')}*\n" + ranks_list
    else:
        # Progress report or command called
        deadline = datetime.datetime.strptime(f"{BOTW_CONFIG['pick_next']} {BOTW_CONFIG['pick_hour']}", BOTW_COMPARE_FMT)
        return f"Boss of the Week: **{boss}**  |  Deadline: **{deadline.strftime('%A, %B %d at %-I%p')} CST**\n" + ranks_list


# Build the Final String for stats
async def build_final_stats_str(sort_players):
    try:
        ranks_list = [f"Boss of the Week: **Player Trophies**"]
        for player in sort_players:
            player_str = f"**{player['name']}** - Score Total: **{player['rank_weight']}**"
            if player['rank_1'] > 0:
                player_str = player_str + f" | Rune: **{player['rank_1']}**"
            if player['rank_2'] > 0:
                player_str = player_str + f" | Adamant: **{player['rank_2']}**"
            if player['rank_3'] > 0:
                player_str = player_str + f" | Mithril: **{player['rank_3']}**"
            ranks_list.append(player_str)
        # ranks_list = '\n'.join(ranks_list)
    except Exception as e:
        logger.exception(e)
        ranks_list = ['Error building ranks!']
    return ranks_list


async def week_stats_from_players(week_players, all_server_stats):
    try:
        for player in week_players:
            p_name = player['player']
            # build init player dict if not there
            if not p_name in all_server_stats:
                all_server_stats[p_name] = {
                        'name' : util.name_to_discord(p_name),
                        'kills_all': 0,
                        'rank_weight' : 0,
                        'rank_1' : 0,
                        'rank_2' : 0,
                        'rank_3' : 0 }
            p_stats = all_server_stats[p_name]
            # add to total kills
            p_stats['kills_all'] += player['kills']
            # rank stuff
            rank = player['rank']
            if rank == 1:
                p_stats['rank_1'] += 1
                p_stats['rank_weight'] += 3
            if rank == 2:
                p_stats['rank_2'] += 1
                p_stats['rank_weight'] += 2
            if rank == 3:
                p_stats['rank_3'] += 1
                p_stats['rank_weight'] += 1
    except Exception as e:
        logger.exception(e)


# ------------------------- Get BOTW Info for Server ------------------------- #

async def get_botw_info(Server, pre_time=False):
    """Get all basic BOTW info for the server"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET BOTW INFO - Server: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Create full ranking string, top 10 people
    top_players = await get_botw_top_players(db, Server.id)
    ranks_list = await ranks_from_top_players(top_players)
    final_str = await build_final_rank_str(ranks_list, boss=BOTW_CONFIG['current_boss'])
    # Add notice if we're posting progress for pre_time
    if pre_time:
        final_str = "**LAST CHANCE!** This Boss of the Week is almost over!" + MESSAGE_DIVIDER + final_str
    logger.info(f"FINISHED GET BOTW INFO - Server: {Server.name} | ID: {Server.id}")
    return final_str


async def get_botw_history(Server):
    """Get all basic BOTW history for the server"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET BOTW HISTORY - Server: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    history_list = []
    # Loop through all weeks in server
    for week in db[f'server:{Server.id}#botw_history']:
        ranks_list = await ranks_from_top_players(week['players'], give_awards=True)
        history_list.append(await build_final_rank_str(ranks_list, boss=week['boss'], old_date=week['date']))
    logger.info(f"FINISHED GET BOTW HISTORY - Server: {Server.name} | ID: {Server.id}")
    return history_list


async def get_botw_stats(Server):
    """Get all basic BOTW player stats for the server"""
    logger.info('------------------------------')
    logger.info(f'Initialized GET BOTW STATS - Server: {Server.name} | ID: {Server.id}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    all_server_stats = {}
    # Loop through all weeks in server
    for week in db[f'server:{Server.id}#botw_history']:
        await week_stats_from_players(week['players'], all_server_stats)
    sort_players = []
    for k,v in all_server_stats.items():
        sort_players.append(v)
    sort_players = sorted(sort_players, key=itemgetter('rank_weight'), reverse=True)
    final_players = await build_final_stats_str(sort_players)
    logger.info(f"FINISHED GET BOTW STATS - Server: {Server.name} | ID: {Server.id}")
    return final_players


# ----------------------------- Check BOTW Times ----------------------------- #

async def check_botw_times(now_time):
    """Checks the datetime.now with the time in BOTW config"""
    ## ADD CHECK TO MAKE SURE PICK_NEXT ISNT BEFORE NOW_TIME
    logger.debug('------------------------------')
    logger.debug(f'Initialized CHECK BOTW TIMES - Time Now: {now_time}')
    # fix for somparing strings with single digit ints
    if len(str(BOTW_CONFIG['pick_hour'])) == 1:
        pick_hour = f"0{BOTW_CONFIG['pick_hour']}"
    else:
        pick_hour = str(BOTW_CONFIG['pick_hour'])
    logger.debug(f"now_time: {now_time.strftime(BOTW_COMPARE_FMT)}")
    logger.debug(f"pick_time: {BOTW_CONFIG['pick_next']} {pick_hour}")
    # If it's time to pick new BOTW
    if now_time.strftime(BOTW_COMPARE_FMT) == f"{BOTW_CONFIG['pick_next']} {pick_hour}":
        BOTW_CONFIG['pick_imminent'] = False
        logger.info('Pick Time! Reset pick_imminent.')
        return 'pick_time'
    # Remind for 1 hour left
    if not BOTW_CONFIG['pick_imminent']:
        if now_time.strftime(BOTW_COMPARE_FMT) == f"{BOTW_CONFIG['pick_next']} {int(pick_hour) - PRE_PICK_HOURS}":
            BOTW_CONFIG['pick_imminent'] = True
            await update_botw_config(BOTW_CONFIG)
            logger.info('Pre Time! Enabled pick_imminent')
            return 'pre_time'
    # If it's time to post progress
    for post_hour in BOTW_CONFIG['progress_hours']:
        if not post_hour['done']:
            # Valid progress hour
            if now_time.hour == post_hour['hour']:
                post_hour['done'] = True
                await update_botw_config(BOTW_CONFIG)
                logger.info(f"Progress time! Hour: {post_hour['hour']}")
                return 'progress_time'                
        else:
            # Past hour that was done, reset it for tomorrow
            if now_time.hour != post_hour['hour']:
                post_hour['done'] = False
                await update_botw_config(BOTW_CONFIG)
                logger.info(f"Reset Done parameter for hour: {post_hour['hour']}")
    logger.debug(f'No time matches!')
    return None

   
# -------- Build final BOTW strings for servers & update players in DB ------- #

async def build_botw_final(now_time):
    """Reset all servers for Boss of the week and add final rankings to players"""
    logger.info('------------------------------')
    logger.info(f'Initialized BOTW RESET')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Loop through db to get servers
    all_servers = []
    all_messages = {}
    for server in db['active_servers']:
        logger.debug(f'In server {server}...')
        # Make sure server is opted in for BOTW
        if db[f'server:{server}#botw_opt']:
            serv_dict = {}
            serv_dict['id'] = server
            serv_dict['channel'] = db[f'server:{server}#channel']
            serv_dict['role'] = db[f'server:{server}#role']
            all_servers.append(serv_dict)
            # Get top players
            top_players = await get_botw_top_players(db, server)
            ranks_list = await ranks_from_top_players(top_players, give_awards=True)
            final_str = ("**Congratulations** to the winners!" + MESSAGE_DIVIDER + 
                    await build_final_rank_str(ranks_list, boss=BOTW_CONFIG['current_boss'], old_date=now_time.strftime(BOTW_BASIC_FMT)) 
                    + MESSAGE_DIVIDER)
            logger.debug('Got top players...')
            # New history record for server
            new_history = {
                'date': now_time.strftime(BOTW_BASIC_FMT),
                'boss': BOTW_CONFIG['current_boss'],
                'players': []
            }
            i = 1
            # Loop through top 3 players
            for pd in top_players[:3]:
                new_history['players'].append({ 
                    'player': pd['player'],
                    'kills': pd['kills'],
                    'rank': i
                })
                i += 1
            db[f'server:{server}#botw_history'].append(new_history)
            logger.debug('Appended history!')
            all_messages[str(server)] = final_str
            logger.debug('Added final message!')
            # Loop to next server
    await reset_botw_kills(db)
    logger.info('Set all BOTW kills to 0!')
    await h.db_write(h.DB_DISCORD_PATH, db)
    logger.debug('Wrote all to DB!')
    return {
        'all_servers': all_servers,
        'all_messages': all_messages
    }
    

# --------------------- Change to a new Boss of the Week -------------------- #

async def change_new_botw(now_time):
    """Change to new BOTW & build a message string with new BOTW"""
    logger.info('------------------------------')
    logger.info(f"Initialized CHANGE NEW BOTW - Old BOTW: {BOTW_CONFIG['current_boss']}")
    # Update recent bosses
    current_boss = BOTW_CONFIG['current_boss']
    del BOTW_CONFIG['recent_bosses'][0]
    BOTW_CONFIG['recent_bosses'].append(current_boss)
    # Make sure new boss is not in recent bosses
    boss_pool = await h.db_open(BOTW_POOL)
    while current_boss in BOTW_CONFIG['recent_bosses']:
        current_boss = random.choice(boss_pool['all_bosses'])
    # Got new boss
    BOTW_CONFIG['current_boss'] = current_boss
    # Make new deadline a week later from now
    new_deadline = (now_time+datetime.timedelta(days=DAYS_BETWEEN_BOTW))
    BOTW_CONFIG['pick_next'] = new_deadline.strftime(BOTW_BASIC_FMT)
    await update_botw_config(BOTW_CONFIG)
    new_botw_message = f"The new Boss of the Week is **{current_boss}**! The deadline is on *{new_deadline.strftime('%A, %B %d')}*. Get bossing!"
    logger.info(f"FINISHED CHANGE NEW BOTW - New BOTW: {current_boss} | New deadline: {new_deadline.strftime(BOTW_BASIC_FMT)}")
    return new_botw_message


# NEEDS WORK
async def update_botw_config(config_new):
    """Update the entire BOTW config with current config in cache"""
    logger.info('------------------------------')
    logger.info(f'Initialized UPDATE BOTW CONFIG')
    global BOTW_CONFIG
    BOTW_CONFIG = config_new
    await h.db_write(BOTW_CONFIG_PATH, BOTW_CONFIG)
    logger.info(f'FINISHED UPDATE BOTW CONFIG')


async def get_botw_servers(progress):
    """Gets all settings in all servers with botw enabled"""
    logger.debug('------------------------------')
    logger.debug(f'Initialized GET BOTW SERVERS - Progress report: {progress}')
    db = await h.db_open(h.DB_DISCORD_PATH)
    # Loop through db to get servers
    all_servers = []
    for server in db['active_servers']:
        # Make sure server is opted in for BOTW
        if db[f'server:{server}#botw_opt']:
            # Only add servers with progress reports enabled, or all if not asking for progresses
            if progress and db[f'server:{server}#botw_progress'] or not progress:
                serv_dict = {}
                serv_dict['id'] = server
                serv_dict['channel'] = db[f'server:{server}#channel']
                serv_dict['role'] = db[f'server:{server}#role']
                all_servers.append(serv_dict)
    logger.debug(f"FINISHED GET BOTW SERVERS - Progress report: {progress}")
    return all_servers


# NECESSARY?
async def get_botw_entry(entry):
    """Gets a single entry from BOTW config"""
    return BOTW_CONFIG[entry]


# NEEDS WORK
async def add_botw_progress_hour(new_hour):
    """Adds a new botw progress hour, reorganizes list by hour"""
    pass


# NEEDS WORK
async def remove_botw_progress_hour(rm_hour):
    """Removes an existing botw progress hour, sends back exception if hour not there"""
    pass

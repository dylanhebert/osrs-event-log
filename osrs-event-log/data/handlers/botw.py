# Member = A Discord member
# Player = A Runescape account
#
# Adapter layer — see general.py. Mirrors sotw.py; every message string is
# byte-for-byte what it was before the migration.

import datetime
import random

from common.logger import logger
import common.util as util
from data import repo
from . import helpers as h

# --------------------------------- CONSTANTS -------------------------------- #

BOTW_PATH = h.FULL_DATA_PATH + "botw/"
BOTW_POOL = BOTW_PATH + "all_bosses.json"          # tracked in git, still a file

# Import must not create the database — see the matching note in sotw.py.
BOTW_CONFIG = repo.competitions.get_config('botw') if h.open_db_if_exists() else {}
logger.debug('Loaded BOTW config into cache.')


def reload_config():
    """Re-read the config from whichever database is currently open.
    See the matching note in sotw.py."""
    global BOTW_CONFIG
    BOTW_CONFIG = repo.competitions.get_config('botw')
    return BOTW_CONFIG

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

MESSAGE_DIVIDER = "\n~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n"


# --------------------- Get top BOTW players in a server --------------------- #

async def get_botw_top_players(server_id):
    """Players with kills > 0, highest first, capped at TOP_PLAYERS_COUNT."""
    return repo.competitions.top_players(server_id, 'botw', TOP_PLAYERS_COUNT)


# --------------------- Reset every player's kills for BOTW --------------------- #

async def reset_botw_kills():
    repo.competitions.reset_scores('botw')


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
        deadline = datetime.datetime.strptime(old_date, BOTW_BASIC_FMT)
        return f"Boss of the Week: **{boss}**  |  **Final Rankings**  |  *{deadline.strftime('%A, %B %d, %Y')}*\n" + ranks_list
    else:
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
    except Exception as e:
        logger.exception(e)
        ranks_list = ['Error building ranks!']
    return ranks_list


# ------------------------- Get BOTW Info for Server ------------------------- #

async def get_botw_info(Server, pre_time=False):
    """Get all basic BOTW info for the server"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized GET BOTW INFO - Server: {Server.name} | ID: {Server.id}')
    top_players = await get_botw_top_players(Server.id)
    ranks_list = await ranks_from_top_players(top_players)
    final_str = await build_final_rank_str(ranks_list, boss=BOTW_CONFIG['current_boss'])
    if pre_time:
        final_str = "**LAST CHANCE!** This Boss of the Week is almost over!" + MESSAGE_DIVIDER + final_str
    logger.info(f"FINISHED GET BOTW INFO - Server: {Server.name} | ID: {Server.id}")
    return final_str


async def get_botw_history(Server):
    """Get all basic BOTW history for the server"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized GET BOTW HISTORY - Server: {Server.name} | ID: {Server.id}')
    history_list = []
    for week in repo.competitions.history(Server.id, 'botw'):
        ranks_list = await ranks_from_top_players(week['players'], give_awards=True)
        history_list.append(await build_final_rank_str(ranks_list, boss=week['boss'], old_date=week['date']))
    logger.info(f"FINISHED GET BOTW HISTORY - Server: {Server.name} | ID: {Server.id}")
    return history_list


async def get_botw_stats(Server):
    """Get all basic BOTW player stats for the server"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized GET BOTW STATS - Server: {Server.name} | ID: {Server.id}')
    sort_players = repo.competitions.standings(Server.id, 'botw')
    final_players = await build_final_stats_str(sort_players)
    logger.info(f"FINISHED GET BOTW STATS - Server: {Server.name} | ID: {Server.id}")
    return final_players


# ----------------------------- Check BOTW Times ----------------------------- #

async def check_botw_times(now_time):
    """Checks the datetime.now with the time in BOTW config"""
    logger.debug('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.debug(f'Initialized CHECK BOTW TIMES - Time Now: {now_time}')
    if len(str(BOTW_CONFIG['pick_hour'])) == 1:
        pick_hour = f"0{BOTW_CONFIG['pick_hour']}"
    else:
        pick_hour = str(BOTW_CONFIG['pick_hour'])
    logger.debug(f"now_time: {now_time.strftime(BOTW_COMPARE_FMT)}")
    logger.debug(f"pick_time: {BOTW_CONFIG['pick_next']} {pick_hour}")
    pick_time_str = f"{BOTW_CONFIG['pick_next']} {pick_hour}"
    pick_time_dt = datetime.datetime.strptime(pick_time_str, BOTW_COMPARE_FMT)
    if now_time >= pick_time_dt:
        BOTW_CONFIG['pick_imminent'] = False
        logger.info('Pick Time! Reset pick_imminent.')
        return 'pick_time'
    if not BOTW_CONFIG['pick_imminent']:
        pick_imm_str = f"{BOTW_CONFIG['pick_next']} {int(pick_hour) - PRE_PICK_HOURS}"
        pick_imm_dt = datetime.datetime.strptime(pick_imm_str, BOTW_COMPARE_FMT)
        if now_time >= pick_imm_dt:
            BOTW_CONFIG['pick_imminent'] = True
            await update_botw_config(BOTW_CONFIG)
            logger.info('Pre Time! Enabled pick_imminent')
            return 'pre_time'
    for post_hour in BOTW_CONFIG['progress_hours']:
        if not post_hour['done']:
            if now_time.hour == post_hour['hour']:
                post_hour['done'] = True
                await update_botw_config(BOTW_CONFIG)
                logger.info(f"Progress time! Hour: {post_hour['hour']}")
                return 'progress_time'
        else:
            if now_time.hour != post_hour['hour']:
                post_hour['done'] = False
                await update_botw_config(BOTW_CONFIG)
                logger.info(f"Reset Done parameter for hour: {post_hour['hour']}")
    logger.debug(f'No time matches!')
    return None


# -------- Build final BOTW strings for servers & update players in DB ------- #

async def build_botw_final(now_time):
    """Reset all servers for Boss of the week and add final rankings to players"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized BOTW RESET')
    all_servers = []
    all_messages = {}

    with repo.transaction():
        for serv_dict in repo.servers.list_for_competition('botw'):
            server = serv_dict['id']
            logger.debug(f'In server {server}...')
            all_servers.append(serv_dict)
            top_players = await get_botw_top_players(server)
            ranks_list = await ranks_from_top_players(top_players, give_awards=True)
            final_str = ("**Congratulations** to the winners!" + MESSAGE_DIVIDER +
                    await build_final_rank_str(ranks_list, boss=BOTW_CONFIG['current_boss'], old_date=now_time.strftime(BOTW_BASIC_FMT))
                    + MESSAGE_DIVIDER)
            logger.debug('Got top players...')

            placements = []
            i = 1
            for pd in top_players[:3]:
                placements.append({'player': pd['player'], 'kills': pd['kills'], 'rank': i})
                i += 1
            repo.competitions.record_week(
                server, 'botw', BOTW_CONFIG['current_boss'],
                now_time.strftime(BOTW_BASIC_FMT), placements)
            logger.debug('Appended history!')
            all_messages[str(server)] = final_str
            logger.debug('Added final message!')

        await reset_botw_kills()
        logger.info('Set all BOTW kills to 0!')

    logger.debug('Wrote all to DB!')
    return {
        'all_servers': all_servers,
        'all_messages': all_messages
    }


# --------------------- Change to a new Boss of the Week -------------------- #

async def change_new_botw(now_time):
    """Change to new BOTW & build a message string with new BOTW"""
    global BOTW_CONFIG
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f"Initialized CHANGE NEW BOTW - Old BOTW: {BOTW_CONFIG['current_boss']}")
    current_boss = BOTW_CONFIG['current_boss']
    boss_pool = await h.db_open(BOTW_POOL)
    new_boss_override = None
    BOTW_CONFIG_TEMP = repo.competitions.get_config('botw')
    if BOTW_CONFIG_TEMP.get('pick_override') and BOTW_CONFIG_TEMP['pick_override'] in boss_pool['all_bosses']:
        new_boss_override = BOTW_CONFIG_TEMP['pick_override']
        BOTW_CONFIG = BOTW_CONFIG_TEMP
    BOTW_CONFIG['pick_override'] = None
    del BOTW_CONFIG['recent_bosses'][0]
    BOTW_CONFIG['recent_bosses'].append(current_boss)
    if new_boss_override:
        BOTW_CONFIG['current_boss'] = new_boss_override
    else:
        while current_boss in BOTW_CONFIG['recent_bosses']:
            current_boss = random.choice(boss_pool['all_bosses'])
        BOTW_CONFIG['current_boss'] = current_boss

    target_weekday = BOTW_CONFIG["pick_weekday"]
    days_ahead = (target_weekday - now_time.weekday() + 7) % 7
    if days_ahead == 0:
        days_ahead = 7  # Always get the *next* occurrence
    new_deadline = now_time + datetime.timedelta(days=days_ahead)
    BOTW_CONFIG['pick_next'] = new_deadline.strftime(BOTW_BASIC_FMT)

    await update_botw_config(BOTW_CONFIG)
    new_botw_message = f"The new Boss of the Week is **{BOTW_CONFIG['current_boss']}**! The deadline is on *{new_deadline.strftime('%A, %B %d')}*. Get bossing!"
    logger.info(f"FINISHED CHANGE NEW BOTW - New BOTW: {BOTW_CONFIG['current_boss']} | New deadline: {new_deadline.strftime(BOTW_BASIC_FMT)}")
    return new_botw_message


async def update_botw_config(config_new):
    """Update the entire BOTW config with current config in cache"""
    logger.info('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.info(f'Initialized UPDATE BOTW CONFIG')
    global BOTW_CONFIG
    BOTW_CONFIG = config_new
    repo.competitions.set_config('botw', BOTW_CONFIG)
    logger.info(f'FINISHED UPDATE BOTW CONFIG')


async def get_botw_servers(progress):
    """Gets all settings in all servers with botw enabled"""
    logger.debug('~~~~~~~~~~~~~~~~~~~~~~~~')
    logger.debug(f'Initialized GET BOTW SERVERS - Progress report: {progress}')
    all_servers = repo.servers.list_for_competition('botw', progress_only=bool(progress))
    logger.debug(f"FINISHED GET BOTW SERVERS - Progress report: {progress}")
    return all_servers


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

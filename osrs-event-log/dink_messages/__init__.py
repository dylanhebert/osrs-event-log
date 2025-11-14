from common.logger import logger

from .loot import format_loot
from .kill_count import format_kill_count
from .pet import format_pet
from .grand_exchange import format_grand_exchange
from .collection import format_collection
from .quest import format_quest
from .clue import format_clue
from .combat_achievement import format_combat_achievement
from .achievement_diary import format_achievement_diary
from .death import format_death
from .slayer import format_slayer
from .player_kill import format_player_kill
from .toa_unique import format_toa_unique


_FORMATTERS = {
    "LOOT": format_loot,
    "KILL_COUNT": format_kill_count,
    "PET": format_pet,
    "GRAND_EXCHANGE": format_grand_exchange,
    "COLLECTION": format_collection,
    "QUEST": format_quest,
    "CLUE": format_clue,
    "COMBAT_ACHIEVEMENT": format_combat_achievement,
    "ACHIEVEMENT_DIARY": format_achievement_diary,
    "DEATH": format_death,
    "SLAYER": format_slayer,
    "PLAYER_KILL": format_player_kill,
    "TOA_UNIQUE": format_toa_unique,
}


def format_dink_message(payload: dict, user_tag: str) -> str:
    event_type = payload.get("type")
    formatter = _FORMATTERS.get(event_type)

    if formatter:
        message = formatter(payload, user_tag)
        logger.info(f'Dink Event: {message}')
        return message

    # Fallback if you haven't specialised this type yet
    content = payload.get("content")
    logger.debug(content)
    return content or f"{user_tag} triggered {event_type or 'UNKNOWN'}"

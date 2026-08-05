from common.logger import logger
from data import repo


class LoopPlayerHandler:
    """Per-cycle state for the hiscores looper.

    build_cache() / remove_cache() keep their names and call sites, but they no
    longer carry the write. In the JSON version remove_cache() was what actually
    persisted the whole runescape file, once, at the end of a loop — so a
    process killed mid-loop had already posted to Discord but recorded nothing,
    and the next loop re-posted the same milestones. Stats are now written per
    player, transactionally, as they change.

    The cache is now just a snapshot for iteration, not a write buffer.
    """

    def __init__(self):
        self.data_runescape = None
        self.server_info_all = None

    async def build_cache(self):
        repo.stats.reset_caches()
        # Only pollable players — never the full players table. See the
        # pollable_players view in data/schema.sql: the 12 ghost players have
        # never been polled, and polling them would make every skill read as new
        # and post "first time on the Hiscores" for all of them at once.
        self.data_runescape = repo.stats.load_all_pollable()
        self.server_info_all = await self.get_server_info_all()

    async def remove_cache(self):
        # Nothing to flush: writes already committed.
        self.data_runescape = None
        self.server_info_all = None

    async def get_server_info_all(self):
        return repo.servers.info_all(active_only=True)

    async def get_all_player_info(self, rs_name):
        """Gets all servers and members connected to a player"""
        logger.debug('------------------------------')
        logger.debug(f'Initialized GET PLAYER LOOPER INFO - Player: {rs_name}')
        player_servers_all = repo.players.active_links(rs_name)
        logger.debug(f"Finished GET PLAYER LOOPER INFO - Player: {rs_name}")
        return player_servers_all

    async def mark_polled(self, rs_name):
        """Record that this player's hiscores were successfully fetched.

        Separate from save_player() on purpose. That only runs when something
        actually changed, so last_polled used to mean "last written" — after two
        full cycles only 3 of 70 players had it set, and those three only
        because they have no Overall row and so always take the write path.

        A UI showing "last updated" needs to distinguish "nothing has changed
        since Tuesday" from "we have not been able to reach this account since
        Tuesday", and last_polled is the column that answers that.

        Best-effort: a bookkeeping column must never take down a poll cycle.
        """
        try:
            player_id = repo.players.get_id(rs_name)
            if player_id is not None:
                repo.players.touch_polled(player_id)
        except Exception as e:
            logger.exception(f'{rs_name}: could not update last_polled -- {e}')

    async def save_player(self, rs_name, stats):
        """Persist one player's stats, appending history only where a value moved."""
        player_id = repo.players.get_id(rs_name)
        if player_id is None:
            logger.debug(f'{rs_name}: not in the database, nothing saved')
            return 0, 0
        return repo.stats.apply_changes(player_id, stats)

    async def record_events(self, rs_name, update, posted=True):
        """Record what was posted, for the activity feed.

        Best-effort: recording must never be the reason a milestone fails to
        reach Discord, so anything raised here is logged and swallowed.

        Called once per player rather than once per server. The messages are
        identical across servers, and which servers saw them is derivable from
        player_servers, so a row per server would only duplicate text.

        `title` is left NULL for hiscores events. PlayerUpdate does not track
        which skill produced which message, and threading that through would
        mean touching every message-building branch. The message text carries
        it; enriching this later is additive.
        """
        try:
            player_id = repo.players.get_id(rs_name)
            if player_id is None:
                return 0
            # The milestone bucket is exactly what PlayerUpdate decided was
            # worth pinging the role for, so it is the authority for the
            # is_milestone flag rather than anything re-derived from the text.
            buckets = (('MILESTONE', update.milestones, True),
                       ('SKILL', update.skills, False),
                       ('MINIGAME', update.minigames, False))
            written = 0
            with repo.transaction():
                for event_type, messages, milestone in buckets:
                    for message in messages:
                        repo.events.log_event(
                            player_id, None, repo.events.SOURCE_HISCORES,
                            event_type, message, posted=posted,
                            is_milestone=milestone)
                        written += 1
            return written
        except Exception as e:
            logger.exception(f'{rs_name}: could not record events -- {e}')
            return 0

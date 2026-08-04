"""Offline dry-run harness. Runs the update logic without Discord or the network.

The bot has no dry-run mode — the only way to find out what it would post is to
let it post. This module supplies one, so the migration can be checked against
real data without a token, a network call, or a message reaching a server.

Two pieces:

  * FakeHiscores — serves frozen index_lite.json payloads from a dict, so a run
    is deterministic and repeatable and Jagex is never contacted.
  * run_player() — drives the same comparison the looper does and returns the
    messages that WOULD have been posted, instead of sending them.

run_player() deliberately reimplements looper.thread_player()'s comparison
rather than importing it, because the looper imports discord.py at module level.
The logic below must stay in step with cogs/looper.py; test_golden_diff.py is
what proves it has, by running the real pre-migration code path over the same
inputs and diffing the output.
"""

import copy
from contextlib import contextmanager

import common.util as util
from activity.PlayerUpdate import PlayerUpdate


def quiet_logging(level="WARNING"):
    """Silence the bot's very chatty DEBUG stream during a test run.

    common/logger.py attaches a StreamHandler at DEBUG to a logger named 'REL',
    which buries test output under thousands of lines. It also attaches a
    FileHandler that appends to logs.log — a test has no business growing that,
    so the file handler is dropped entirely.
    """
    import logging

    log = logging.getLogger("REL")
    log.setLevel(getattr(logging, level))
    for handler in list(log.handlers):
        if isinstance(handler, logging.FileHandler):
            log.removeHandler(handler)
            handler.close()
        else:
            handler.setLevel(getattr(logging, level))


@contextmanager
def dry_run():
    """Neutralise the one write PlayerUpdate performs.

    update_skill() and update_minigame() call db.add_to_player_entry_global() to
    accumulate Skill/Boss of the Week totals, and that writes straight to
    db_discord.json (or, after the migration, to the players table). A dry run
    that is meant to touch nothing must not do that, so the accumulator is
    swapped for one that records the call and returns the value.

    Every run_* function here must be called inside this. The recorded calls are
    yielded so a test can assert on the SOTW/BOTW arithmetic too.
    """
    import data.handlers as handlers

    calls = []
    original = handlers.add_to_player_entry_global

    async def recording(rs_name, entry, amount):
        calls.append({"player": rs_name, "entry": entry, "amount": amount})
        return amount

    handlers.add_to_player_entry_global = recording
    try:
        yield calls
    finally:
        handlers.add_to_player_entry_global = original


class FakeHiscores:
    """Stands in for util.get_page(). Payloads keyed by rs_name."""

    def __init__(self, payloads=None):
        self.payloads = payloads or {}
        self.requested = []

    def add(self, rs_name, payload):
        self.payloads[rs_name] = payload

    async def get_page(self, rs_name):
        self.requested.append(rs_name)
        return self.payloads.get(rs_name)

    @staticmethod
    def payload_from_stats(stats, unranked_as_missing=True):
        """Rebuild an index_lite.json payload from a stored stats dict.

        This is what makes the zero-delta test (T2) possible with no network:
        feed the database's own contents back in as if Jagex had returned them,
        and nothing should read as changed. If anything does, the stored form
        and the parsed form disagree — which is exactly the condition that makes
        the bot spam a milestone for every skill of every player.

        Accepts either the int-valued shape (SQLite) or the comma-string shape
        (the old JSON), so the same fixture drives both sides of T3.
        """
        def as_int(value):
            if value is None:
                return -1
            if isinstance(value, int):
                return value
            text = str(value).strip()
            if text in ("--", "", "-"):
                return -1
            return int(text.replace(",", ""))

        skills = [{"id": i, "name": name,
                   "rank": as_int(values.get("rank")),
                   "level": as_int(values.get("level")),
                   "xp": as_int(values.get("xp"))}
                  for i, (name, values) in enumerate(stats.get("skills", {}).items())]
        activities = [{"id": i, "name": name,
                       "rank": as_int(values.get("rank")),
                       "score": as_int(values.get("score"))}
                      for i, (name, values) in enumerate(stats.get("minigames", {}).items())]
        if not skills and unranked_as_missing:
            # A player with no skills has no hiscores profile at all, which is
            # what get_player_scores() returns an empty dict for.
            return {"skills": [], "activities": activities}
        return {"skills": skills, "activities": activities}


class CapturedUpdate:
    """What one player's poll would have produced."""

    def __init__(self, rs_name):
        self.rs_name = rs_name
        self.skipped = None          # reason string, or None if processed
        self.skills = []
        self.minigames = []
        self.milestones = []
        self.error = None

    @property
    def messages(self):
        return list(self.milestones) + list(self.skills) + list(self.minigames)

    @property
    def changed(self):
        return bool(self.skills or self.minigames or self.milestones)

    def __repr__(self):
        if self.skipped:
            return f"<{self.rs_name}: skipped ({self.skipped})>"
        return (f"<{self.rs_name}: {len(self.milestones)} milestones, "
                f"{len(self.skills)} skills, {len(self.minigames)} minigames>")


async def run_player(rs_name, stored_stats, payload, player_discord_info=None,
                     mutate=True):
    """Mirror of looper.thread_player() with the Discord posting removed.

    `stored_stats` is the player's current state, in the same shape either
    storage layer produces. Returns a CapturedUpdate. When `mutate` is False the
    caller's dict is left untouched.
    """
    captured = CapturedUpdate(rs_name)
    rs_data = stored_stats if mutate else copy.deepcopy(stored_stats)

    if player_discord_info is None:
        # One server, mentions on — enough for message construction. The real
        # looper skips players with no active server before it ever fetches.
        player_discord_info = [{"server": 1, "member": 1, "mention": True}]

    if payload is None:
        captured.skipped = "no page"
        return captured

    new_scores = await util.get_player_scores(rs_name, payload)
    if not new_scores["skills"]:
        captured.skipped = "no hiscores profile"
        return captured

    update = PlayerUpdate(rs_name, rs_data, player_discord_info)

    try:
        # Overall is the cheap early-out, exactly as in the looper.
        try:
            if not util.xp_changed(rs_data["skills"]["Overall"]["xp"],
                                   new_scores["skills"]["Overall"]["xp"]):
                captured.skipped = "overall xp unchanged"
                return captured
        except (KeyError, TypeError):
            pass

        for skill, values in new_scores["skills"].items():
            if skill in rs_data["skills"]:
                if values["xp"] != rs_data["skills"][skill]["xp"]:
                    await update.update_skill(values, skill, False)
            else:
                await update.update_skill(values, skill, True)
            rs_data["skills"][skill] = values

        for activity, values in new_scores["minigames"].items():
            if activity in rs_data["minigames"]:
                if values["score"] != rs_data["minigames"][activity]["score"]:
                    await update.update_minigame(values, activity, False)
            else:
                await update.update_minigame(values, activity, True)
            rs_data["minigames"][activity] = values
    except Exception as exc:                      # noqa: BLE001 - reported, not raised
        captured.error = f"{type(exc).__name__}: {exc}"
        return captured

    captured.skills = list(update.skills)
    captured.minigames = list(update.minigames)
    captured.milestones = list(update.milestones)
    return captured


async def run_all(players, hiscores, mutate=False):
    """Run every player. `players` is {rs_name: stored_stats}."""
    results = {}
    for rs_name, stored in players.items():
        payload = await hiscores.get_page(rs_name)
        results[rs_name] = await run_player(rs_name, stored, payload, mutate=mutate)
    return results


def summarise(results):
    """Counts in the same terms the 2026-08-04 healthy baseline used:
    "53 skipped, 5 with real updates, 12 fetch failures, 0 crashes"."""
    values = list(results.values())
    return {
        "players": len(values),
        "unchanged": sum(1 for r in values if r.skipped == "overall xp unchanged"),
        "no_profile": sum(1 for r in values if r.skipped == "no hiscores profile"),
        "fetch_failed": sum(1 for r in values if r.skipped == "no page"),
        # Reached the per-skill loop but nothing differed. Players with no
        # Overall row land here: the early-out cannot apply to them, so every
        # skill is compared individually.
        "walked_no_change": sum(1 for r in values if not r.skipped and not r.changed
                                and not r.error),
        "changed": sum(1 for r in values if r.changed),
        "errors": sum(1 for r in values if r.error),
        "messages": sum(len(r.messages) for r in values),
    }

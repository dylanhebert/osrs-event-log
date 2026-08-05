"""Recover the event feed from a Discord channel's history.

The `events` table is newer than the bot. Every milestone posted before the
SQLite migration was formatted, sent to Discord and thrown away, so the only
surviving record is the channel itself. This reads that channel back and
reconstructs the rows.

    python tools/backfill_events_from_discord.py --channel <id>            # dry run
    python tools/backfill_events_from_discord.py --channel <id> --apply

The channel id is an argument and never a constant in this file: it is a real
Discord id and this repository is public.

WHY IT PARSES BY STRUCTURE, NOT BY WORDING
------------------------------------------
The message wording has changed repeatedly over the years, so anything matching
on phrases would silently miss whole eras. What has NOT changed is the shape,
because it is Discord's own markup:

    **<bold title>**```[lang]
    <code block>```

post_update() concatenates several of those into ONE message and appends the
role and member mentions, while record_events() stores each unit as its own
row. So one Discord message expands into several events, and the job is to cut
a message back into units.

Three unit shapes carry no player name at all, because they are footers
appended to whichever player's update they belong to:

    ```c\\nTotal level: ... | Total Overall XP: ...```
    ```c\\nSkill of the Week - ...```
    ```c\\nBoss of the Week - ...```

They inherit the player named by the other units in the same message.

Player attribution matches the start of a bold title against the display names
already in the database, longest first, because RuneScape names contain spaces.
That is robust to any rewording around the name.

Wording is used ONLY to guess event_type, and an unrecognised phrasing falls
back to a generic type rather than failing. NOTHING IS SILENTLY DROPPED: every
message that yields no rows is counted and sampled in the report.

THE SAME EVENT IS POSTED TO EVERY SERVER THE PLAYER IS IN
---------------------------------------------------------
post_update() runs once per server, so one milestone appears in as many
channels as that player belongs to. record_events() deliberately does NOT work
that way: it runs once per player after the server loop, storing a single row
with server_id NULL, on the reasoning that the text is identical everywhere and
which servers saw it is derivable from player_servers.

This backfill matches that. Rows are written with server_id NULL, and a
candidate is dropped when an equivalent row already exists: same player, same
text, within a short time window. The window is what separates a cross-server
duplicate, posted seconds apart in the same loop iteration, from a genuine
repeat of the same wording months later.

Pass --channel more than once to sweep every server in one run, which lets the
duplicate check see them all together.

NO GATEWAY CONNECTION
---------------------
It reads the REST API directly rather than starting a discord.py client, so it
never opens a second bot session alongside the live one. It needs only the
token and "Read Message History" in the channel.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import repo  # noqa: E402

# Reports print real message text, which is full of emoji, and the Windows
# console is cp1252. Losing a whole run to an encode error while printing a
# sample would be a poor trade.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

API = "https://discord.com/api/v10"
PAGE = 100

# --------------------------------------------------------------------------- #
# Message structure
# --------------------------------------------------------------------------- #

# One unit: an optional bold title, optional text between it and the code
# block (the MAXED message has an italic line in between), then a code block.
# Non-greedy throughout so consecutive units do not swallow each other.
# The language tag is only a language tag when a NEWLINE follows it. Without
# that requirement the matcher eats the first word of an untagged block, so
# ```Skill of the Week - ...``` parses with a body of " of the Week - ..." and
# stops looking like the footer it is. Older messages had no tag at all.
UNIT = re.compile(
    r"(?:\*\*(?P<title>.+?)\*\*(?P<between>[^`]*?))?"
    r"```(?:(?P<lang>[A-Za-z0-9+#-]*)\n)?(?P<body>.*?)```",
    re.DOTALL)

# Trailing mentions appended by post_update: role then member, either of which
# may be empty or @here.
TRAILING = re.compile(r"(?:\s|<@[!&]?\d+>|@here|@everyone)+$")

# A bold run, used to spot units the UNIT pattern could not claim.
BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)

# An older format put the mentions FIRST, as their own bold line:
#
#     **~ <@123> ~**
#     **Someone levelled up Hunter to 97**```c ... ```
#
# Left alone that line is taken as the unit's title, which costs the real title
# (so the event classifies as a generic UPDATE) and stores a raw Discord member
# id in the message text. A real event title never contains a mention: the
# current code appends them outside the bold entirely, and the old code put
# them in a line of their own. So a bold run containing a mention is never a
# title, and dropping it fixes the classification and removes the id together.
#
# Two shapes, because the mention did not always resolve to a real mention:
#   **~ <@123> ~**        an actual mention
#   **~ somename ~**       the role written out as plain text
# The tildes are the constant, so a bold run wrapped in them is a mention line
# whether or not it contains an id.
MENTION_LINE = re.compile(
    r"\*\*(?:[^*]*<@[!&]?\d+>[^*]*|\s*~[^*]*~\s*)\*\*\s*", re.DOTALL)

# THE MILESTONE MARKER.
#
# A milestone is whatever was worth pinging the server's role for, and it is
# not a kind of event: a pet drop is a PET event AND a milestone. Both sources
# produce them:
#
#   hiscores  the ten triggers in PlayerUpdate.py that append to
#             self.milestones, sent as
#             f'{all_milestones}{mention_role} {mention_member}'
#   dink      a formatter returning notify=True, sent as
#             f'{message}{mention_role} {mention_member}'
#
# A routine update gets f'{...}{mention_member}' with NO role. So the ROLE
# mention is the signal, and it survives the format change: the old messages
# carried it in a leading "**~ @role ~**" line, the current ones append it.
# ;milestones keys on exactly this.
#
# @here is included because get_mention_role() falls back to it when a server
# has set no role.
ROLE_MENTION = re.compile(r"<@&\d+>|@here|@everyone")

FOOTERS = (
    ("Total level:", "OVERALL"),
    ("Skill of the Week", "SOTW"),
    ("Boss of the Week", "BOTW"),
)

# Wording hints for event_type, MOST SPECIFIC FIRST because the first match
# wins. "the first time" has to beat "levelled up", since reaching a skill's
# first hiscores entry is phrased as a level-up with a first-time body.
#
# Missing a hint is fine and expected: the wording has changed over the years,
# so anything unrecognised becomes UPDATE rather than failing.
TYPE_HINTS = (
    ("HAS MAXED", "MAXED"),
    ("the first time", "FIRST"),
    ("has achieved", "MILESTONE"),
    ("at least", "MILESTONE"),
    ("total level", "MILESTONE"),
    ("Clue Scroll", "CLUE"),
    ("clues completed", "CLUE"),
    ("levelled up", "LEVEL"),
    ("leveled up", "LEVEL"),
    # The hiscores activity updates are all "<verb>ed <thing> N times" with a
    # "New <noun>s logged" body: killed, subdued, progressed, completed, and
    # whatever verb the next boss gets. Matching the body shape rather than the
    # verb list is what survives a new activity being added.
    ("logged:", "KC"),
    ("kill count", "KC"),
    ("count:", "KC"),
    (" times", "KC"),
)

# Dink events reached the same channel, formatted by dink_messages/. They are
# told apart by what the code block contains rather than by wording: every
# hiscores unit is built by PlayerUpdate.py and carries one of these markers,
# because they all print a rank, an XP figure or a total.
HISCORES_MARKERS = (
    "Current rank:", "XP gained", "Overall XP:", "Total level:",
    "Skill of the Week", "Boss of the Week", "clues completed",
    "on the Hiscores", "Overall rank:", "logged:",
    # Title phrases, needed because an older format emitted the header ALONE
    # with no code block, so there is no body to carry a marker:
    #     **Someone has killed Abyssal Sire at least 500 times**
    # Without these those units match no side and are reported as unknown.
    # They come before the Dink check, so "completed ... enough times to be on
    # the hiscores" cannot be mistaken for a Dink quest completion.
    "levelled up", "leveled up", "has killed", "has achieved",
    "at least", "HAS MAXED", "on the hiscores", "Clue Scroll",
)

# Dink types, taken from dink_messages/ rather than guessed from output. The
# header phrase is the reliable half: the stat lines are all conditional on the
# payload carrying that field, so a message may have none of them.
#
# Order matters, most specific first. "completed a Slayer task" has to beat the
# bare "completed", and the clue and combat-achievement headers both contain
# words the others use.
DINK_HINTS = (
    ("Achievement Diary", "ACHIEVEMENT_DIARY"),      # achievement_diary.py
    ("completed a Slayer task", "SLAYER"),           # slayer.py
    ("combat task", "COMBAT_ACHIEVEMENT"),           # combat_achievement.py
    ("Task points:", "COMBAT_ACHIEVEMENT"),
    ("Total points:", "COMBAT_ACHIEVEMENT"),
    ("Collection Log", "COLLECTION"),                # collection.py
    ("on the Grand Exchange", "GRAND_EXCHANGE"),     # grand_exchange.py
    ("Personal Best", "KILL_COUNT"),                 # kill_count.py
    ("purple drop from Tombs of Amascut", "TOA_UNIQUE"),   # toa_unique.py
    ("just received", "PET"),                        # pet.py
    ("was PK'd by", "DEATH"),                        # death.py
    ("has PK'd", "PLAYER_KILL"),                     # player_kill.py
    (" clue**", "CLUE"),                             # clue.py
    ("completed a ", "CLUE"),
    ("QP:", "QUEST"),                                # quest.py
    ("Quests:", "QUEST"),
    ("from ", "LOOT"),                               # loot.py
    ("Value:", "LOOT"),
)

# BOTH sides are matched positively, and a unit matching neither is reported as
# 'unknown' rather than assumed. Treating "not hiscores" as "therefore dink"
# would silently misfile any older hiscores wording that predates every marker
# above, and the whole reason this parser is structural is that the formats
# have changed over the years.
#
# Every stat line each formatter can emit, so a message is recognised even when
# its header wording has drifted.
DINK_MARKERS = tuple(phrase for phrase, _ in DINK_HINTS) + (
    "Diaries:", "Tasks:",                            # achievement_diary
    "Completed:", "Loot:", "High value:",            # clue
    "Entries:", "Price:", "From:",                   # collection
    "Tier (", "Final task:", "Next tier:",           # combat_achievement
    "Lost:",                                         # death
    "Each:", "Tax:",                                 # grand_exchange
    "KC:", "Time:",                                  # kill_count
    "Chance:",                                       # loot
    "Milestone:",                                    # pet
    "Combat Lvl:", "Last hit:", "Loot Value:",       # player_kill
    "Tasks completed:", "Points gained:", "Monster:", "Kill count:",  # slayer
    "Points:", "Raid Level:",                        # toa_unique
)


def source_of(text):
    """'hiscores', 'dink', or 'unknown' for one unit.

    'unknown' is a real answer, not a failure. It means the wording matches
    neither side's markers, which is what a format from an earlier era looks
    like. Those are reported and, by default, not imported: guessing would put
    rows in the feed under a source that is simply wrong.
    """
    if any(marker in text for marker in HISCORES_MARKERS):
        return "hiscores"
    if any(marker in text for marker in DINK_MARKERS):
        return "dink"
    return "unknown"

_STRIP_TITLE = re.compile(r"^\*\*.*?\*\*", re.DOTALL)
# Same newline requirement as UNIT, and for the same reason: this is what the
# footer checks read, so eating the first word of an untagged block is what
# made "Skill of the Week - ..." unrecognisable.
_CODE_BODY = re.compile(r"```(?:[A-Za-z0-9+#-]*\n)?(.*?)```", re.DOTALL)


def classify(title, text):
    """(source, event_type) for one unit.

    `text` is the whole unit, bold and fences included, which is what gets
    stored. The footer checks need the code block's contents on their own, so
    they are pulled out here rather than making every caller do it.
    """
    body = _CODE_BODY.search(_STRIP_TITLE.sub("", text or "", count=1))
    inner = (body.group(1) if body else "").strip()
    haystack = f"{title or ''} {inner}"

    # Footers are exactly the units that carry no bold title, so requiring an
    # absent title stops the "2,200 total level" milestone, whose body also
    # starts "Total level:", from being mistaken for one.
    #
    # They get SKILL, not a type of their own, because that is what the live
    # bot stores: check_sotw_update() appends the footer to self.skills (or
    # self.milestones, which the caller promotes), so record_events() files it
    # under the list it landed in. Giving backfilled footers OVERALL/SOTW/BOTW
    # would put the same thing under two different types depending on how old
    # it is. The feed identifies them by their text instead, which works for
    # both.
    if not title:
        for needle, _ in FOOTERS:
            if inner.startswith(needle):
                return "hiscores", "SKILL"

    source = source_of(haystack)
    if source == "dink":
        # Dink keeps its payload type, which is what the live webhook stores.
        for needle, kind in DINK_HINTS:
            if needle in haystack:
                return "dink", kind
        return "dink", "UPDATE"
    if source == "unknown":
        return "unknown", "UPDATE"

    # Hiscores uses the live bot's own three buckets rather than a finer set
    # invented here, so backfilled rows are indistinguishable from recorded
    # ones. MILESTONE is decided by the role mention, not by wording, and is
    # applied by the caller; what is left is telling a skill update from an
    # activity update, which is what PlayerUpdate's two lists mean.
    if any(marker in haystack for marker in
           ("XP gained", "levelled up", "leveled up", "Total level:",
            "Overall XP:", "on the Hiscores", "Skill of the Week")):
        return "hiscores", "SKILL"
    return "hiscores", "MINIGAME"


def split_units(content, accept_bare_bold=None):
    """Cut one Discord message into its constituent event texts.

    Returns (units, leftover). `units` are (title, text) in order, where text
    is reassembled to match what record_events() would have stored. `leftover`
    is anything neither pattern could claim, which the caller reports rather
    than discards.

    TWO SHAPES, and the second is easy to miss. Every hiscores unit ends in a
    code block, but TEN of the thirteen Dink formatters `return header` with no
    block at all when the payload carried no stats to show, e.g. a pet with no
    milestone or a quest with no completion counts. Matching only the
    block-terminated shape drops those on the floor.
    """
    trimmed = MENTION_LINE.sub("", TRAILING.sub("", content))

    units, spans = [], []
    for match in UNIT.finditer(trimmed):
        title = (match.group("title") or "").strip()
        units.append((match.start(), title, trimmed[match.start():match.end()]))
        spans.append((match.start(), match.end()))

    # Bold runs that no code-block unit already covers may be units in their
    # own right, but bold is also used for ordinary emphasis: the weekly
    # announcement is "Skill of the Week: **Sailing** | Deadline: **...**", and
    # people bold each other's names in chat. Taking every bold run turns all
    # of that into events.
    #
    # accept_bare_bold is the discriminator. Every Dink formatter builds its
    # header as f"**{user_tag} ...**", so a bare bold run is only an event if
    # it begins with a known player's name, which is exactly what the caller
    # checks. Without a predicate, bare bold is ignored rather than guessed at.
    for match in BOLD.finditer(trimmed):
        if any(start <= match.start() < end for start, end in spans):
            continue
        title = match.group(1).strip()
        if accept_bare_bold is None or not accept_bare_bold(title):
            continue
        units.append((match.start(), title,
                      trimmed[match.start():match.end()]))
        spans.append((match.start(), match.end()))

    units.sort(key=lambda item: item[0])

    # Whatever sits outside every claimed span.
    leftover, cursor = [], 0
    for start, end in sorted(spans):
        if start > cursor:
            leftover.append(trimmed[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(trimmed):
        leftover.append(trimmed[cursor:])

    return [(title, text) for _, title, text in units], "".join(leftover).strip()


# --------------------------------------------------------------------------- #
# Player attribution
# --------------------------------------------------------------------------- #

def build_name_index():
    """{display name lowered: player_id}, longest names first when matching.

    Matches on the display form ("Zezima Alt") because that is what the bot
    prints; rs_name is the '+' form. Sorting by length stops "Zezima" claiming
    a title that belongs to "Zezima Alt".
    """
    rows = repo.db.query("SELECT id, rs_name, display_name FROM players")
    index = {}
    for row in rows:
        for form in (row["display_name"], row["rs_name"].replace("+", " ")):
            if form:
                index.setdefault(form.lower(), row["id"])
    return index, sorted(index, key=len, reverse=True)


def _match_name(title, names_by_length):
    """(player_name, remainder) for a title that starts with a known name."""
    if not title:
        return None, ""
    lowered = title.lower()
    for name in names_by_length:
        if lowered.startswith(name):
            # Guard against "Zezimaa" matching "Zezima": the next character
            # must be a boundary.
            rest = lowered[len(name):]
            if not rest or not (rest[0].isalnum() or rest[0] in "_-+"):
                return name, rest.strip()
    return None, ""


def attribute(title, names_by_length, index):
    """The player a bold title refers to, or None."""
    name, _ = _match_name(title, names_by_length)
    return index[name] if name else None


def looks_like_event_header(title, names_by_length):
    """Whether a bare bold run is a Dink header rather than emphasis.

    Every Dink formatter builds `f"**{user_tag} <something happened>**"`, so a
    header is a player name FOLLOWED BY a verb phrase. A bold run that is only
    the name is something else: the weekly results announcement bolds each
    podium player, and people bold each other in chat. Both attribute
    perfectly well, which is why attribution alone is not enough of a test.
    """
    name, rest = _match_name(title, names_by_length)
    return bool(name) and len(rest) > 3 and " " in rest


# --------------------------------------------------------------------------- #
# Discord REST
# --------------------------------------------------------------------------- #

def read_token(path):
    with open(path, "r", encoding="utf-8") as handle:
        token = json.load(handle).get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(f"BOT_TOKEN missing from {path}")
    return token


def api_get(url, token, attempt=0):
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bot {token}",
        "User-Agent": "osrs-event-log-backfill/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        if e.code == 429 and attempt < 5:
            body = {}
            try:
                body = json.loads(e.read())
            except Exception:
                pass
            wait = float(body.get("retry_after", 2)) + 0.5
            print(f"    rate limited, waiting {wait:.1f}s")
            time.sleep(wait)
            return api_get(url, token, attempt + 1)
        if e.code == 403:
            raise SystemExit(
                "403 from Discord. The bot needs View Channel and Read Message "
                "History in that channel.")
        if e.code == 404:
            raise SystemExit("404 from Discord: no such channel, or the bot "
                             "cannot see it.")
        raise


def iter_messages(channel_id, token, limit=None, since=None, on_page=None):
    """Every message in the channel, newest first, paginated.

    `since` is a UTC cutoff. Discord returns newest first, so the first message
    older than it ends this channel: there is nothing newer further back.
    """
    before, seen = None, 0
    while True:
        params = {"limit": PAGE}
        if before:
            params["before"] = before
        page = api_get(f"{API}/channels/{channel_id}/messages?"
                       + urllib.parse.urlencode(params), token)
        if not page:
            return
        for message in page:
            stamp = to_utc(message["timestamp"])
            if since and stamp < since:
                return
            yield message
            seen += 1
            if limit and seen >= limit:
                return
        if on_page:
            on_page(to_utc(page[-1]["timestamp"]), seen)
        before = page[-1]["id"]
        # Courtesy pacing. The REST limit is generous but this walks years.
        time.sleep(0.25)


def to_utc(timestamp):
    """Discord ISO8601 -> the bot's '%Y-%m-%dT%H:%M:%SZ'."""
    cleaned = timestamp.replace("Z", "+00:00")
    return (datetime.fromisoformat(cleaned).astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


def epoch(stamp):
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).timestamp()


# --------------------------------------------------------------------------- #
# Cross-server duplicates
# --------------------------------------------------------------------------- #

class Deduper:
    """Drops the copies of an event posted to a player's other servers.

    Keyed on (player_id, exact text). Two rows sharing both, close together in
    time, are the same event seen in two channels: post_update() sends byte
    identical text to each server within the same loop iteration.

    The time window is what keeps this from eating real repeats. Almost every
    message embeds an absolute value (an XP total, a kill count, a level) that
    cannot recur, but a Skill of the Week footer can legitimately repeat if two
    updates land on the same running total, and that is worth keeping when it
    happens months apart rather than seconds.
    """

    def __init__(self, window_minutes):
        self.window = window_minutes * 60
        self.seen = {}      # (player_id, text) -> [timestamps]
        self.dropped = 0

    def load_existing(self):
        """Seed from rows already in the database, so a second run does not
        re-add what a first run recovered from another channel."""
        for row in repo.db.query(
                "SELECT player_id, message, occurred_at FROM events"
                " WHERE player_id IS NOT NULL"):
            try:
                self.seen.setdefault((row["player_id"], row["message"]), []).append(
                    epoch(row["occurred_at"]))
            except (ValueError, TypeError):
                continue
        return len(self.seen)

    def accept(self, player_id, text, occurred_at):
        when = epoch(occurred_at)
        key = (player_id, text)
        for previous in self.seen.get(key, ()):
            if abs(previous - when) <= self.window:
                self.dropped += 1
                return False
        self.seen.setdefault(key, []).append(when)
        return True


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--channel", action="append", metavar="ID",
                        help="Discord channel id to read. Repeat to add more. "
                             "Omit it and every active server's configured "
                             "channel is swept, which is the normal use.")
    parser.add_argument("--db", default=os.path.join("data", "osrs.db"))
    parser.add_argument("--config", default="bot_config.json")
    parser.add_argument("--dedupe-window", type=int, default=15,
                        metavar="MINUTES",
                        help="treat identical text for the same player within "
                             "this many minutes as one event posted to several "
                             "servers (default 15)")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after N messages PER CHANNEL, for a quick look")
    parser.add_argument("--since", metavar="YYYY-MM-DD", default=None,
                        help="stop walking back at this date. Without it the "
                             "sweep runs to the first message in the channel, "
                             "which for these channels is years.")
    parser.add_argument("--months", type=int, default=None, metavar="N",
                        help="shorthand for --since N months ago")
    parser.add_argument("--include-dink", action="store_true",
                        help="also import Dink events (drops, pets, quests, "
                             "collection log). Off by default: the hiscores "
                             "formats are generated by one file and are the "
                             "safer half to land first.")
    parser.add_argument("--include-unknown", action="store_true",
                        help="also import units whose source could not be "
                             "determined. Off by default: filing them under a "
                             "guessed source is worse than leaving them out.")
    parser.add_argument("--apply", action="store_true",
                        help="write. Without this nothing is written.")
    parser.add_argument("--samples", type=int, default=8)
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        raise SystemExit(f"{args.db} does not exist.")

    token = read_token(args.config)
    repo.db.connect(args.db)

    if repo.db.one("PRAGMA table_info(events)") is None:
        raise SystemExit("no events table; run migrate_add_web_auth.py first")
    columns = [r[1] for r in repo.db.query("PRAGMA table_info(events)")]
    if "discord_message_id" not in columns:
        raise SystemExit(
            "events.discord_message_id is missing. Run\n"
            "  python tools/migrate_add_web_auth.py --db " + args.db)

    # The channels the bot posts to are already recorded per server, so the
    # normal run needs no ids typed at all. That also keeps real Discord ids
    # out of shell history and out of this repository, which is public.
    channels = args.channel
    if not channels:
        rows_ = repo.db.query(
            "SELECT id, name, channel_id FROM servers"
            " WHERE is_active = 1 AND channel_id IS NOT NULL ORDER BY id")
        channels = [str(r["channel_id"]) for r in rows_]
        if not channels:
            raise SystemExit(
                "No active server has a channel configured, so there is "
                "nothing to sweep. Pass --channel explicitly if you know one.")
        print("sweeping every active server's configured channel:")
        for r in rows_:
            print(f"  - {r['name'] or 'an unnamed server'}")
        skipped = repo.db.scalar(
            "SELECT COUNT(*) FROM servers WHERE is_active = 1"
            " AND channel_id IS NULL", (), 0)
        if skipped:
            print(f"  ({skipped} active server(s) have no channel set, skipped)")
        print()

    cutoff = None
    if args.months:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=30 * args.months)).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif args.since:
        cutoff = f"{args.since}T00:00:00Z"

    print(f"database  {args.db}")
    print(f"range     {'from ' + cutoff[:10] if cutoff else 'the entire channel history'}")
    print(f"mode      {'APPLY (will write)' if args.apply else 'dry run, writes nothing'}")
    print(f"dedupe    identical text for one player within "
          f"{args.dedupe_window} min counts once")
    print()

    index, names_by_length = build_name_index()
    print(f"{len(names_by_length)} known player names to match against")

    already = {r["discord_message_id"] for r in repo.db.query(
        "SELECT DISTINCT discord_message_id FROM events"
        " WHERE discord_message_id IS NOT NULL")}
    if already:
        print(f"{len(already)} messages already imported, they will be skipped")

    deduper = Deduper(args.dedupe_window)
    print(f"{deduper.load_existing()} existing events loaded for duplicate checking")
    print()

    stats = Counter()
    types = Counter()
    per_year = Counter()
    per_channel = Counter()
    unmatched_titles, unparsed_messages = [], []
    leftovers, unclassified, unknown_units = [], [], []
    rows = []

    for channel_id in channels:
        channel = api_get(f"{API}/channels/{channel_id}", token)
        print(f"reading #{channel.get('name')}")

        def progress(oldest, seen, _name=channel.get("name")):
            print(f"    #{_name}: back to {oldest[:10]}, "
                  f"{stats['messages']} read, {stats['rows']} rows kept",
                  flush=True)

        for message in iter_messages(channel_id, token, args.limit,
                                     since=cutoff, on_page=progress):
            stats["messages"] += 1

            message_id = int(message["id"])
            if message_id in already:
                stats["skipped_already"] += 1
                continue

            content = message.get("content") or ""
            if not content.strip():
                stats["empty"] += 1
                continue

            # Read the role mention before split_units() strips it away.
            milestone = bool(ROLE_MENTION.search(content))
            units, leftover = split_units(
                content,
                accept_bare_bold=lambda t: looks_like_event_header(
                    t, names_by_length))
            if leftover:
                stats["messages_with_leftover"] += 1
                if len(leftovers) < args.samples:
                    leftovers.append(leftover[:200])
            if not units:
                stats["messages_unparsed"] += 1
                if len(unparsed_messages) < args.samples:
                    unparsed_messages.append(content[:200])
                continue

            # Attribute the whole message from whichever unit names a player,
            # then give the unnamed footers the same owner.
            owner = None
            for title, _ in units:
                owner = attribute(title, names_by_length, index)
                if owner:
                    break
            if owner is None:
                # Over a long sweep this bucket is mostly players who have
                # since been removed from the log: their messages are real
                # events with nobody left to attach them to. Always sample it,
                # including units with no bold title at all, or the reason for
                # the drop is invisible.
                stats["messages_no_player"] += 1
                if len(unmatched_titles) < args.samples:
                    titled = [t for t, _ in units if t]
                    sample = titled[0] if titled else content
                    unmatched_titles.append(sample[:120].replace(chr(10), " "))
                continue

            occurred = to_utc(message["timestamp"])
            kept_any = False
            for title, text in units:
                text = text.strip()
                # server_id stays NULL, matching what record_events() writes:
                # one row per event, not one per server that saw it.
                if not deduper.accept(owner, text, occurred):
                    continue
                source, kind = classify(title, text)
                # A hiscores milestone is stored as MILESTONE, matching the
                # live bucket name. Dink keeps its payload type either way,
                # because that is what the webhook records; the flag is what
                # carries "this pinged the role" for both sources.
                if milestone and source == "hiscores":
                    kind = "MILESTONE"
                if source == "dink" and not args.include_dink:
                    stats["dink_skipped"] += 1
                    continue
                if source == "unknown":
                    # Neither side's markers matched, so the source would be a
                    # guess. Report it rather than filing it wrongly.
                    stats["unknown_skipped"] += 1
                    if len(unknown_units) < args.samples:
                        unknown_units.append(text[:150].replace("\n", "\\n"))
                    if not args.include_unknown:
                        continue
                types[f"{source}/{kind}"] += 1
                if kind == "UPDATE" and len(unclassified) < args.samples:
                    unclassified.append(text[:150].replace("\n", "\\n"))
                rows.append((owner, None, source, kind, None,
                             text, None, occurred, 1, message_id,
                             1 if milestone else 0))
                stats["rows"] += 1
                if milestone:
                    stats["milestones"] += 1
                kept_any = True
            if kept_any:
                per_year[occurred[:4]] += 1
                per_channel[channel.get("name") or channel_id] += 1

    # ------------------------------------------------------------------ #
    print()
    print("=" * 62)
    print(f"  messages read              {stats['messages']:>7}")
    print(f"  already imported, skipped  {stats['skipped_already']:>7}")
    print(f"  empty / attachment only    {stats['empty']:>7}")
    print(f"  no unit could be parsed    {stats['messages_unparsed']:>7}")
    print(f"  no player matched          {stats['messages_no_player']:>7}")
    print(f"  had unclaimed leftover     {stats['messages_with_leftover']:>7}")
    print(f"  same event in another server{deduper.dropped:>6}")
    if stats["dink_skipped"]:
        print(f"  Dink rows skipped          {stats['dink_skipped']:>7}"
              f"  (--include-dink to keep them)")
    if stats["unknown_skipped"]:
        print(f"  unknown source             {stats['unknown_skipped']:>7}"
              f"  (--include-unknown to keep them)")
    print(f"  EVENT ROWS RECOVERED       {stats['rows']:>7}")
    print("=" * 62)

    if len(per_channel) > 1:
        print("\n  new rows by channel (later channels contribute less,")
        print("  because the duplicate check has already seen the events):")
        for name, count in per_channel.most_common():
            print(f"    #{name:<24} {count:>7} messages")

    print(f"\n  milestones (pinged the role)  {stats['milestones']:>7}")

    if types:
        print("\n  by event_type:")
        for kind, count in types.most_common():
            flag = "  <- wording not recognised" if kind == "UPDATE" else ""
            print(f"    {kind:<12} {count:>7}{flag}")

    # UPDATE is the catch-all, so a large count means the hint list is missing
    # a phrasing. Showing examples is the whole point of the dry run.
    if unclassified:
        print(f"\n  SAMPLES OF 'UPDATE' (first {len(unclassified)}), so the "
              f"hints can be improved:")
        for sample in unclassified:
            print(f"    - {sample}")
    if per_year:
        print("\n  by year:")
        for year in sorted(per_year):
            print(f"    {year}         {per_year[year]:>7} messages")

    def show(label, samples):
        if samples:
            print(f"\n  {label} (first {len(samples)}):")
            for sample in samples:
                collapsed = sample.replace("\n", "\\n")
                print(f"    - {collapsed}")

    show("UNITS WHOSE SOURCE COULD NOT BE DETERMINED", unknown_units)
    show("MESSAGES WITH NO PARSEABLE UNIT", unparsed_messages)
    show("TITLES THAT MATCHED NO KNOWN PLAYER", unmatched_titles)
    show("TEXT LEFT OVER AFTER PARSING", leftovers)

    if not args.apply:
        print("\nDry run. Nothing was written. Re-run with --apply to insert.")
        return 0

    if not rows:
        print("\nNothing to insert.")
        return 0

    print(f"\nInserting {len(rows)} rows...")
    with repo.transaction():
        repo.db.executemany(
            "INSERT INTO events (player_id, server_id, source, event_type,"
            " title, message, payload, occurred_at, posted,"
            " discord_message_id, is_milestone)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    total = repo.db.scalar("SELECT COUNT(*) FROM events", (), 0)
    print(f"Done. events now holds {total} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

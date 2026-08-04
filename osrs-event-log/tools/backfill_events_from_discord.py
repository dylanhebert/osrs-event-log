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

API = "https://discord.com/api/v10"
PAGE = 100

# --------------------------------------------------------------------------- #
# Message structure
# --------------------------------------------------------------------------- #

# One unit: an optional bold title, optional text between it and the code
# block (the MAXED message has an italic line in between), then a code block.
# Non-greedy throughout so consecutive units do not swallow each other.
UNIT = re.compile(
    r"(?:\*\*(?P<title>.+?)\*\*(?P<between>[^`]*?))?"
    r"```(?P<lang>[A-Za-z0-9+#-]*)\n?(?P<body>.*?)```",
    re.DOTALL)

# Trailing mentions appended by post_update: role then member, either of which
# may be empty or @here.
TRAILING = re.compile(r"(?:\s|<@[!&]?\d+>|@here|@everyone)+$")

# A bold run, used to spot units the UNIT pattern could not claim.
BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)

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
)

# BOTH sides are matched positively, and a unit matching neither is reported as
# 'unknown' rather than being assumed. Treating "not hiscores" as "therefore
# dink" would silently misfile any older hiscores wording that predates every
# marker above, and the whole reason this parser is structural is that the
# formats have changed over the years.
DINK_MARKERS = (
    "Entries:", "QP:", "Quests:", "Value:", "Price:", "Collection Log",
    "Combat achievement", "funny feeling", "Killed by", "KC:",
    "Total value:", "Personal best", "has died",
)

# Dink types, checked only once a unit is known not to be from the hiscores.
DINK_HINTS = (
    ("Collection Log", "COLLECTION"),
    ("Entries:", "COLLECTION"),
    ("QP:", "QUEST"),
    ("Quests:", "QUEST"),
    ("Combat achievement", "COMBAT_ACHIEVEMENT"),
    ("has a funny feeling", "PET"),
    ("pet", "PET"),
    ("Value:", "LOOT"),
    ("Price:", "LOOT"),
    ("died", "DEATH"),
    ("defeated", "PVP"),
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
_CODE_BODY = re.compile(r"```[A-Za-z0-9+#-]*\n?(.*?)```", re.DOTALL)


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
    if not title:
        for needle, kind in FOOTERS:
            if inner.startswith(needle):
                return "hiscores", kind

    source = source_of(haystack)
    if source == "dink":
        for needle, kind in DINK_HINTS:
            if needle in haystack:
                return "dink", kind
        return "dink", "UPDATE"
    if source == "unknown":
        return "unknown", "UPDATE"

    for needle, kind in TYPE_HINTS:
        if needle in haystack:
            return "hiscores", kind
    return "hiscores", "UPDATE"


def split_units(content):
    """Cut one Discord message into its constituent event texts.

    Returns (units, leftover). `units` are (title, text) in order, where text
    is reassembled to match what record_events() would have stored. `leftover`
    is anything the pattern could not claim, which the caller reports rather
    than discards.
    """
    trimmed = TRAILING.sub("", content)
    units, consumed, last_end = [], [], 0
    for match in UNIT.finditer(trimmed):
        if match.start() > last_end:
            consumed.append(trimmed[last_end:match.start()])
        title = (match.group("title") or "").strip()
        units.append((title, trimmed[match.start():match.end()]))
        last_end = match.end()
    if last_end < len(trimmed):
        consumed.append(trimmed[last_end:])

    leftover = "".join(consumed).strip()
    # A bold run in the leftover means a unit shape this pattern does not know,
    # which is exactly what an old message format would look like.
    return units, leftover


# --------------------------------------------------------------------------- #
# Player attribution
# --------------------------------------------------------------------------- #

def build_name_index():
    """{display name lowered: player_id}, longest names first when matching.

    Matches on the display form ("Green Donut") because that is what the bot
    prints; rs_name is the '+' form. Sorting by length stops "Green" claiming a
    title that belongs to "Green Donut".
    """
    rows = repo.db.query("SELECT id, rs_name, display_name FROM players")
    index = {}
    for row in rows:
        for form in (row["display_name"], row["rs_name"].replace("+", " ")):
            if form:
                index.setdefault(form.lower(), row["id"])
    return index, sorted(index, key=len, reverse=True)


def attribute(title, names_by_length, index):
    """The player a bold title refers to, or None."""
    if not title:
        return None
    lowered = title.lower()
    for name in names_by_length:
        if lowered.startswith(name):
            # Guard against "Zezimaa" matching "Zezima": the next character
            # must be a boundary.
            rest = lowered[len(name):]
            if not rest or not (rest[0].isalnum() or rest[0] in "_-+"):
                return index[name]
    return None


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


def iter_messages(channel_id, token, limit=None):
    """Every message in the channel, newest first, paginated."""
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
            yield message
            seen += 1
            if limit and seen >= limit:
                return
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

    print(f"database  {args.db}")
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

        for message in iter_messages(channel_id, token, args.limit):
            stats["messages"] += 1
            if stats["messages"] % 500 == 0:
                print(f"  ...{stats['messages']} messages read, "
                      f"{stats['rows']} rows kept, {deduper.dropped} duplicates")

            message_id = int(message["id"])
            if message_id in already:
                stats["skipped_already"] += 1
                continue

            content = message.get("content") or ""
            if not content.strip():
                stats["empty"] += 1
                continue

            units, leftover = split_units(content)
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
                stats["messages_no_player"] += 1
                titled = [t for t, _ in units if t]
                if titled and len(unmatched_titles) < args.samples:
                    unmatched_titles.append(titled[0][:120])
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
                             text, None, occurred, 1, message_id))
                stats["rows"] += 1
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
            " title, message, payload, occurred_at, posted, discord_message_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    total = repo.db.scalar("SELECT COUNT(*) FROM events", (), 0)
    print(f"Done. events now holds {total} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

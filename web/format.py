"""Display formatting. Jinja filters, registered in app.py.

The database stores real integers; the JSON it replaced stored comma-formatted
strings because the old scraped hiscores page rendered them that way. All of
that formatting now happens here, at display time, which is the same split the
bot uses (common/util.py format_int_str / format_rank_str).
"""

import re
from datetime import datetime, timezone

from markupsafe import Markup, escape

TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, TS_FMT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def num(value):
    """102315637 -> '102,315,637'. None -> '-'."""
    if value is None:
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def rank(value):
    """NULL rank means unranked, which the old hiscores page rendered '--'.
    Keeping that spelling means the UI reads the same way the Discord messages
    do."""
    if value is None:
        return "--"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def compact(value):
    """13,034,431 -> '13.0M'. For tiles where the exact figure is noise."""
    if value is None:
        return "-"
    try:
        value = int(value)
    except (TypeError, ValueError):
        return str(value)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(value) >= limit:
            return f"{value / limit:.1f}{suffix}".replace(".0", "")
    return str(value)


def ago(value, now=None):
    """'14 minutes ago'. Poll cadence is 20 minutes, so minute precision is the
    smallest unit that means anything here."""
    moment = parse_ts(value)
    if moment is None:
        return "never"
    now = now or datetime.now(timezone.utc)
    seconds = (now - moment).total_seconds()
    if seconds < 0:
        return "just now"
    for limit, divisor, unit in (
            (90, 1, "second"),
            (5400, 60, "minute"),
            (129600, 3600, "hour"),
            (5184000, 86400, "day"),
    ):
        if seconds < limit:
            count = max(1, int(round(seconds / divisor)))
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    count = max(1, int(round(seconds / 2592000)))
    return f"{count} month{'s' if count != 1 else ''} ago"


def stamp(value):
    """The exact moment, in UTC.

    Never guesses a local timezone: this is rendered on the server, which has
    no idea where the reader is, and a wrong timezone is worse than a labelled
    one. UTC is what the database holds and what the label says.

    Used as visible text in the event feed, and as the title attribute wherever
    a relative time is shown instead.
    """
    moment = parse_ts(value)
    return moment.strftime("%Y-%m-%d %H:%M UTC") if moment else "unknown"


def day(value):
    """'2026-06-24' -> '24 Jun 2026'.

    Accepts a full UTC timestamp too, because the same filter is used for
    sotw_weeks.ended_on (a bare ISO date) and for history timestamps (a full
    '...T..:..:..Z'). Taking the first 10 characters handles both without the
    caller having to know which it holds.
    """
    if not value:
        return "unknown"
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except (ValueError, TypeError):
        return str(value)


def medal(rank_value):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(rank_value, f"{rank_value}th")


# --------------------------------------------------------------------------- #
# Skill and activity icons
# --------------------------------------------------------------------------- #
# Vendored from the OSRS Wiki and packed into ONE sprite sheet
# (static/img/icons.png), indexed by static/img/icon-manifest.json which maps
# the exact name stored in the database to a CSS class.
#
# A sprite rather than 114 <img> tags: a single page can reference over a
# hundred icons, and a request each for a 3 KB file is a lot of round trips for
# very little payload. It also means an icon cannot individually fail to load.
#
# A manifest rather than deriving the class at request time, because the
# mapping is not mechanical: several activities are not wiki page titles
# ("Rifts closed", "LMS - Rank") and a few skills use a differently named file.
#
# A missing entry is normal, not an error. Jagex adds bosses and skills, and the
# repo layer inserts unknown names on sight, so a name can exist in the database
# before anyone has fetched an icon for it. Callers render nothing in that case.

_MANIFEST = None


def _manifest():
    global _MANIFEST
    if _MANIFEST is None:
        import json
        from pathlib import Path
        path = Path(__file__).resolve().parent / "static" / "img" / "icon-manifest.json"
        try:
            _MANIFEST = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _MANIFEST = {"skills": {}, "activities": {}}
    return _MANIFEST


def skill_icon(name):
    """Sprite CSS class for a skill icon, or None."""
    entry = _manifest()["skills"].get(name)
    return entry["cls"] if entry else None


def activity_icon(name):
    """Sprite CSS class for an activity icon, or None."""
    entry = _manifest()["activities"].get(name)
    return entry["cls"] if entry else None


# --------------------------------------------------------------------------- #
# The icon for one feed row
# --------------------------------------------------------------------------- #
# An event has no skill or activity column. It has the text that was posted to
# Discord, and for anything from the hiscores that text always names what
# happened: "levelled up Hitpoints to 57", "has killed Zulrah 500 times".
# Reading the name back out of it gives the exact icon, which is worth far more
# than one generic badge per event_type: the whole feed is levelling events, and
# the skill is the only thing that distinguishes one from the next.
#
# Measured over 64,155 real events spanning 2019-2026: 99.3% of hiscores rows
# resolve this way, and 97.7% of all rows. What is left is Dink events whose
# text names a quest, an item or another player, and those fall back to an icon
# for the type. Nothing renders without one.
#
# Matching is against the icon manifest rather than the database. The manifest
# is the set of names an icon actually exists for, so a name it does not know
# could not be drawn anyway, and the lookup needs no query.

# Wording the hiscores uses that is not the name stored in the database. The
# clue tiers are the whole list: the message says "14 Beginner Clue Scrolls",
# the activity is "Clue Scrolls (beginner)". Without these, clue rows are the
# only hiscores events that miss, and there are thousands of them.
_NAME_ALIASES = {
    "total clue scrolls": "Clue Scrolls (all)",
    "total clues": "Clue Scrolls (all)",
    "clues completed": "Clue Scrolls (all)",
    "clue scrolls": "Clue Scrolls (all)",
}
for _tier in ("beginner", "easy", "medium", "hard", "elite", "master"):
    _NAME_ALIASES[f"{_tier} clue scrolls"] = f"Clue Scrolls ({_tier})"
    _NAME_ALIASES[f"{_tier} clue"] = f"Clue Scrolls ({_tier})"

# Types whose art is already in the sprite under another name. Fetching a
# second copy of the same picture under a second name would only make the
# sprite bigger. The keys not listed here are in the manifest's "types".
_TYPE_BORROWS = {
    "COLLECTION": ("activities", "Collections Logged"),
    "CLUE": ("activities", "Clue Scrolls (all)"),
    "SLAYER": ("skills", "Slayer"),
    "PLAYER_KILL": ("activities", "Bounty Hunter - Hunter"),
}

# The last resort, for a type nobody has drawn and text that named nothing.
# Overall borrows the hiscores stats icon, which is the right shape for "some
# event happened" and is already loaded.
_FALLBACK = ("skills", "Overall")

_MATCHER = None


def _matcher():
    """(compiled alternation, {lowercased match: css class}), built once.

    One regex rather than 121, because a feed page renders 50 messages and
    scanning each of them for every name separately is a hundredfold more work
    for the same answer. Alternation is ordered longest first so that at a
    given position the longest name wins: "Clue Scrolls (all)" must not lose to
    a shorter name that is a prefix of it.
    """
    global _MATCHER
    if _MATCHER is None:
        import re
        manifest = _manifest()
        lookup = {}
        for kind in ("skills", "activities"):
            for name, entry in manifest.get(kind, {}).items():
                lookup[name.lower()] = entry["cls"]
        for phrase, name in _NAME_ALIASES.items():
            cls = lookup.get(name.lower())
            if cls:
                lookup[phrase] = cls
        # A name the wiki spells with a leading "The" is written both ways in
        # practice ("set a new Royal Titans Personal Best").
        for name, entry in list(manifest.get("activities", {}).items()):
            if name.lower().startswith("the "):
                lookup.setdefault(name[4:].lower(), entry["cls"])
        pattern = "|".join(
            re.escape(k) for k in sorted(lookup, key=len, reverse=True))
        _MATCHER = (re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE), lookup)
    return _MATCHER


def _borrowed(kind, name):
    entry = _manifest().get(kind, {}).get(name)
    return entry["cls"] if entry else None


def event_icon(event):
    """Sprite CSS class for one feed row. Never None.

    `event` is a row from queries.events_feed: source, event_type, message and
    display_name.
    """
    message = event["message"] or ""

    # The message opens with the player's own name, and a player is free to be
    # called Sailing. Dropping the name first stops an account being mistaken
    # for the thing that happened to it.
    name = (event["display_name"] or "").strip()
    if name and message[:120].lower().find(name.lower()) != -1:
        cut = message.lower().index(name.lower(), 0, 120) + len(name)
        message = message[cut:]

    pattern, lookup = _matcher()
    found = pattern.search(message)
    if found:
        cls = lookup.get(found.group(0).lower())
        if cls:
            return cls

    event_type = event["event_type"] or ""
    borrow = _TYPE_BORROWS.get(event_type)
    if borrow:
        cls = _borrowed(*borrow)
        if cls:
            return cls

    entry = _manifest().get("types", {}).get(event_type)
    if entry:
        return entry["cls"]

    return _borrowed(*_FALLBACK)


# --------------------------------------------------------------------------- #
# Discord markup
# --------------------------------------------------------------------------- #
# events.message is the exact text posted to Discord, so it arrives full of
# Discord's markup: **bold**, ```c fenced blocks```, mentions. Rendered raw it
# shows the punctuation instead of the formatting.
#
# THIS FILTER RETURNS HTML, SO ESCAPING IS NOT OPTIONAL.
#
# Dink message text is derived from a payload POSTed by a player's RuneLite
# client to a public endpoint, authenticated only by a bearer token that two
# accounts are already known to share. Treat it as attacker-controlled. Every
# path below escapes before it emits, and the code-block contents are escaped
# separately on reinsertion; nothing reaches the page unescaped.

_FENCE = re.compile(r"```(?:([A-Za-z0-9+#_-]*)\r?\n)?(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")

# Mentions carry raw Discord ids. They are replaced with a neutral label rather
# than escaped through, both because an id is meaningless to a reader and
# because real Discord ids must never reach a page.
_MENTION_PATTERNS = [
    (re.compile(r"<@!?\d+>"), "@someone"),
    (re.compile(r"<@&\d+>"), "@role"),
    (re.compile(r"<#\d+>"), "#channel"),
    (re.compile(r"<a?:([A-Za-z0-9_]+):\d+>"), r":\1:"),
]

# Applied to already-escaped text, longest markers first so ** is not eaten by
# the * rule and ~~ is not eaten by anything.
_STYLES = [
    (re.compile(r"\*\*\*(.+?)\*\*\*", re.DOTALL), r"<strong><em>\1</em></strong>"),
    (re.compile(r"\*\*(.+?)\*\*", re.DOTALL), r"<strong>\1</strong>"),
    (re.compile(r"__(.+?)__", re.DOTALL), r"<u>\1</u>"),
    (re.compile(r"~~(.+?)~~", re.DOTALL), r"<del>\1</del>"),
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", re.DOTALL), r"<em>\1</em>"),
    (re.compile(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", re.DOTALL), r"<em>\1</em>"),
]

_PLACEHOLDER = "\x00{}\x00"


def discord_markup(text):
    """Render Discord message markup as HTML.

    Code is pulled out first so that formatting characters inside a fenced
    block stay literal, which matters because the bot's stat lines are fenced
    and contain characters this would otherwise interpret.
    """
    if not text:
        return Markup("")

    blocks = []

    def stash(html):
        blocks.append(html)
        return _PLACEHOLDER.format(len(blocks) - 1)

    def take_fence(match):
        language, body = match.group(1), match.group(2)
        css = f' class="lang-{escape(language)}"' if language else ""
        return stash(f"<pre><code{css}>{escape(body.strip())}</code></pre>")

    def take_inline(match):
        return stash(f"<code>{escape(match.group(1))}</code>")

    working = _FENCE.sub(take_fence, str(text))
    working = _INLINE_CODE.sub(take_inline, working)

    for pattern, replacement in _MENTION_PATTERNS:
        working = pattern.sub(replacement, working)

    # Everything that is not code gets escaped here, before any tag is added.
    working = str(escape(working))

    for pattern, replacement in _STYLES:
        working = pattern.sub(replacement, working)

    working = working.replace("\n", "<br>")

    for index, html in enumerate(blocks):
        working = working.replace(_PLACEHOLDER.format(index), html)

    return Markup(working)


# --------------------------------------------------------------------------- #
# Pagination
# --------------------------------------------------------------------------- #

def page_numbers(page, total_pages, window=2, edge=1):
    """Page numbers to offer, with None marking a run that was left out.

    The events feed runs to 963 pages, so listing them all is not an option and
    a bare "Older" link is not either: it makes the far end of six years of
    history reachable only by clicking a thousand times. This gives the shape
    every paginated site uses, `1 ... 5 6 7 ... 963`, which is enough to step
    one page, jump to either end, or land near where you were.

    `window` is how many pages either side of the current one; `edge` is how
    many at each end. A gap is only drawn when it actually skips something --
    eliding a single page would take the same width as showing it.
    """
    if total_pages < 1:
        return []
    page = min(max(page, 1), total_pages)
    wanted = set(range(1, min(edge, total_pages) + 1))
    wanted |= set(range(max(total_pages - edge + 1, 1), total_pages + 1))
    wanted |= set(range(max(page - window, 1), min(page + window, total_pages) + 1))

    out, previous = [], 0
    for number in sorted(wanted):
        if previous and number > previous + 1:
            # Only worth a gap if more than one page is hidden by it.
            if number == previous + 2:
                out.append(previous + 1)
            else:
                out.append(None)
        out.append(number)
        previous = number
    return out


def page_count(total, per_page):
    """How many pages `total` rows fill. At least 1, so "page 1 of 0" cannot happen."""
    if per_page <= 0:
        return 1
    return max(1, (total + per_page - 1) // per_page)


def register(app):
    for name, func in (("num", num), ("rank", rank), ("compact", compact),
                       ("ago", ago), ("stamp", stamp), ("day", day),
                       ("medal", medal), ("discord_markup", discord_markup),
                       ("skill_icon", skill_icon), ("activity_icon", activity_icon),
                       ("event_icon", event_icon)):
        app.jinja_env.filters[name] = func
    app.jinja_env.globals["page_numbers"] = page_numbers
    app.jinja_env.globals["page_count"] = page_count

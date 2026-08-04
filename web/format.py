"""Display formatting. Jinja filters, registered in app.py.

The database stores real integers; the JSON it replaced stored comma-formatted
strings because the old scraped hiscores page rendered them that way. All of
that formatting now happens here, at display time, which is the same split the
bot uses (common/util.py format_int_str / format_rank_str).
"""

from datetime import datetime, timezone

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
    """Absolute UTC, for title attributes. Never guesses a local timezone."""
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


def register(app):
    for name, func in (("num", num), ("rank", rank), ("compact", compact),
                       ("ago", ago), ("stamp", stamp), ("day", day),
                       ("medal", medal)):
        app.jinja_env.filters[name] = func

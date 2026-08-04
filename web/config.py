"""Configuration for the read-only web UI.

THE WORKING DIRECTORY IS NOT LOAD-BEARING HERE, AND MUST NEVER BECOME SO.

The bot builds every path from pathlib.Path().absolute(), i.e. the process's
current directory, which is why it dies at import if it is started from anywhere
but its inner directory. That trap is not inherited: everything below is derived
from __file__, and the database path is an explicit setting with no default.
Gunicorn's WorkingDirectory therefore does not matter to this service.
"""

import os
import sys
from pathlib import Path

# web/config.py -> web/ -> repo root
WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent
# The bot's inner package directory, which holds `data/`. Putting it on sys.path
# is what lets this process do `from data import repo` and reuse the bot's data
# layer without importing any of the bot itself (data/repo pulls in no
# discord.py, no aiohttp, no bot config).
BOT_DIR = REPO_ROOT / "osrs-event-log"

if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))


class ConfigError(RuntimeError):
    pass


def _require(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. Copy web/.env.example to web/.env for local "
            f"development, or add an Environment= line to the systemd unit.")
    return value


class Config:
    """Read once at app creation so a misconfiguration fails at startup rather
    than on the first request that happens to need the setting."""

    def __init__(self, env=None):
        env = env if env is not None else os.environ

        # No default on purpose. A default would eventually point at the bot's
        # own working database, and the one thing this service must never do is
        # open the file the bot is writing to under a path nobody chose.
        self.db_path = env.get("OSRS_DB_PATH", "").strip()
        if not self.db_path:
            raise ConfigError(
                "OSRS_DB_PATH is not set. It must be an explicit path to an "
                "existing osrs.db. The UI never creates a database.")
        self.db_path = str(Path(self.db_path).expanduser())

        # Signs the session cookie. Rotating it signs everyone out, which is the
        # emergency lever if a session is ever suspected of leaking.
        self.secret_key = env.get("SECRET_KEY", "").strip()
        if not self.secret_key:
            raise ConfigError(
                "SECRET_KEY is not set. Generate one with:\n"
                "  python -c \"import secrets; print(secrets.token_hex(32))\"")

        self.session_days = int(env.get("SESSION_DAYS", "60"))
        # Off locally (plain http), on behind Caddy.
        self.secure_cookies = env.get("SECURE_COOKIES", "0") == "1"

        # Discord guild ids are semi-private and this repo is public, so display
        # names live in configuration, never in source. Format:
        #   SERVER_NAMES=123456789:Main clan,987654321:Alt server
        # Anything unmapped renders as "Server 1", "Server 2", ... in a stable
        # order, so an unset value is merely less friendly, never a leak.
        self.server_names = _parse_server_names(env.get("SERVER_NAMES", ""))

        self.rate_limit_attempts = int(env.get("LOGIN_ATTEMPTS", "10"))
        self.rate_limit_window = int(env.get("LOGIN_WINDOW_SECONDS", "300"))


def _parse_server_names(raw):
    names = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        server_id, _, label = chunk.partition(":")
        try:
            names[int(server_id.strip())] = label.strip()
        except ValueError:
            continue
    return names

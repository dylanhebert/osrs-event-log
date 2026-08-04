"""Gunicorn entry point.

    gunicorn web.wsgi:app --workers 2 --bind 127.0.0.1:8007

SYNC workers, not gthread. The bot's repo layer keeps one module-global sqlite3
connection; sync workers are separate processes so each gets its own, and no
cursor is ever shared across threads. Switching to threads without first giving
web/db.py a thread-local connection would be a real bug.

Run this from anywhere. Unlike the bot, nothing here is derived from the current
working directory.
"""

from .app import build

app = build()

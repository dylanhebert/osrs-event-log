"""Read-only web UI for osrs-event-log.

Runs as its own service (own venv, own systemd unit, own port) and shares
nothing with the Discord bot except the SQLite file, which it opens read-only.
See docs/web-ui.md.
"""

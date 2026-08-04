from .general import *
from .server import *
from .player import *
from .member import *
from .sotw import *
from .botw import *

from . import botw as _botw
from . import sotw as _sotw

# `from .sotw import *` binds a COPY of the SOTW_CONFIG reference into this
# namespace. sotw.py rebinds its own global in several places — reload_config(),
# and change_new_sotw() when a pick_override is set — and every one of those
# left db.SOTW_CONFIG here pointing at the previous dict.
#
# activity/PlayerUpdate.py reads db.SOTW_CONFIG['current_skill'] to decide
# whether a levelled skill counts toward Skill of the Week, so a stale binding
# means it silently scores against the *previous* week's skill. The common path
# happened to survive it because the config is usually mutated in place rather
# than replaced, which is presumably why it went unnoticed.
#
# Dropping the copies and resolving through the submodule on every access means
# there is only ever one live value.
del SOTW_CONFIG, BOTW_CONFIG


def __getattr__(name):
    if name == 'SOTW_CONFIG':
        return _sotw.SOTW_CONFIG
    if name == 'BOTW_CONFIG':
        return _botw.BOTW_CONFIG
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def reload_configs():
    """Re-read the SOTW and BOTW configs from the database that is open now.

    Both modules cache their config in a module global at import time, and
    PlayerUpdate reads db.SOTW_CONFIG / db.BOTW_CONFIG directly. Anything that
    points the repo at a different database after import — a test on a scratch
    copy, most obviously — must call this or it keeps the config it loaded from
    the database that happened to be open during import.
    """
    return {'sotw': _sotw.reload_config(), 'botw': _botw.reload_config()}


_verify_files = verify_files


def verify_files(file_name=None):
    """Open the real database and load the competition configs from it.

    Wraps general.verify_files() so the two stay in step. Importing sotw.py and
    botw.py deliberately does not create the database, so on a first run their
    configs are empty until this has run — which is why the reload belongs here
    rather than at the call sites in osrs-event-log.py.
    """
    connection = _verify_files(file_name)
    reload_configs()
    return connection
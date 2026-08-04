"""Sign-in, sessions and the visibility context.

HOW IT WORKS
------------
A member runs ;webpassword in Discord. The bot generates a 256-bit password,
stores only its sha256, and DMs it. They paste it into the login box here; the
hash is looked up, and the resulting member id goes into a Flask signed cookie.

The cookie holds the member id and nothing else. Everything that follows from
being that member (which servers, which players, which events) is recomputed
from the database on every request. That means:

  * removing someone from every server revokes their access immediately, with
    no session store to invalidate and nothing for the bot to clean up
  * the UI needs no writes at all to support sessions, which is what keeps the
    "never writes to the database" rule intact

RATE LIMITING
-------------
In-process and per worker, so with two Gunicorn workers the effective allowance
is roughly double the configured number. That is fine and is not worth a shared
store: the passwords are 256-bit random values, so this exists to stop a login
form being used as a free CPU sink, not to make guessing infeasible. Guessing is
already infeasible.
"""

import time
from functools import wraps

from flask import (abort, current_app, g, redirect, request, session, url_for)

from . import queries
from data import repo

SESSION_KEY = "member_id"
# A short fingerprint of the credential the session was created with. Checked on
# every request, so ;webpassword (rotate) and ;webrevoke both sign out browsers
# that are already open, rather than only affecting the next sign-in.
FINGERPRINT_KEY = "cred"

# {ip: [timestamp, ...]} of recent failed attempts. Bounded by pruning on write.
_attempts = {}


def _client_ip():
    """Behind Cloudflare then Caddy, so the socket address is always a proxy.

    Trusting a forwarded header is only safe because nothing but Caddy can reach
    the port: Gunicorn binds 127.0.0.1 and UFW blocks the port from outside. If
    that ever changes, this becomes spoofable and the rate limit becomes
    decorative.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limited(ip=None):
    ip = ip or _client_ip()
    window = current_app.config["RATE_WINDOW"]
    cutoff = time.monotonic() - window
    recent = [t for t in _attempts.get(ip, []) if t > cutoff]
    if recent:
        _attempts[ip] = recent
    else:
        _attempts.pop(ip, None)
    return len(recent) >= current_app.config["RATE_ATTEMPTS"]


def record_failure(ip=None):
    ip = ip or _client_ip()
    _attempts.setdefault(ip, []).append(time.monotonic())
    # Keep the dict from growing without bound on a long-lived worker.
    if len(_attempts) > 2048:
        cutoff = time.monotonic() - current_app.config["RATE_WINDOW"]
        for key in [k for k, v in _attempts.items() if not any(t > cutoff for t in v)]:
            _attempts.pop(key, None)


def sign_in(password):
    """Returns the member id on success, None on failure."""
    member_id = repo.webauth.member_for_password(password)
    if member_id is None:
        return None
    # A valid password for someone who is no longer in any active server signs
    # in to nothing, so refuse rather than showing an empty site they cannot
    # explain.
    if not repo.webauth.is_known_member(member_id):
        return None
    session.clear()
    session[SESSION_KEY] = member_id
    session[FINGERPRINT_KEY] = repo.webauth.fingerprint(member_id)
    session.permanent = True
    return member_id


def sign_out():
    session.clear()


def load_context():
    """Populate `g` for this request. Registered as a before_request hook.

    Sets:
      g.member_id     signed-in member, or None
      g.player_ids    visible players (empty when signed out)
      g.servers       [{'id', 'label'}] visible servers
      g.own_players   the member's own rs_names, for the "yours" marker
    """
    g.member_id = None
    g.player_ids = []
    g.servers = []
    g.own_players = set()

    # Static files never need to know who is asking. Skipping them is not just
    # tidiness: a page pulls ~120 icons, and running five queries per icon meant
    # the database did hundreds of pointless lookups per page view, all of them
    # concurrent. Serving a PNG should not touch the database at all.
    if request.endpoint == "static":
        return

    member_id = session.get(SESSION_KEY)
    if member_id is None:
        return

    # Two checks per request, both cheap, both re-read from the database rather
    # than trusted from the cookie:
    #
    #   1. the member is still in at least one active server, so losing every
    #      link revokes access with nothing having to clean up
    #   2. the credential the session was minted against is still the current
    #      one, so ;webpassword and ;webrevoke sign out open browsers
    if not repo.webauth.is_known_member(member_id):
        session.clear()
        return
    if session.get(FINGERPRINT_KEY) != repo.webauth.fingerprint(member_id):
        session.clear()
        return

    g.member_id = member_id
    g.player_ids = queries.visible_player_ids(member_id)
    g.servers = queries.visible_servers(member_id, current_app.config["SERVER_NAMES"])
    g.own_players = set(repo.webauth.own_player_names(member_id))


def signed_in():
    return getattr(g, "member_id", None) is not None


def require_login(view):
    """Redirect anonymous visitors to the login page.

    Every page that renders anything about a real person is behind this. The
    public pages render aggregates only.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not signed_in():
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapper


def optional_server(requested=None):
    """A server the member is in, or None meaning "all of them".

    For pages where showing every visible player at once is meaningful, so
    "all servers" is a real choice rather than a missing one. Competitions use
    current_server() instead, because standings only exist per server.

    A server the member is not in still 404s. Falling back to "all" would turn a
    guessed id into a silent, wrong-looking answer.
    """
    if requested is None:
        return None
    for server in g.servers:
        if server["id"] == requested:
            return server
    abort(404)


def current_server(requested=None):
    """The server a per-server page should show.

    Defaults to the member's first, and 404s on a server they are not in rather
    than silently falling back, so a guessed id in the URL cannot quietly show
    someone else's competition.
    """
    if not g.servers:
        abort(404)
    if requested is None:
        return g.servers[0]
    for server in g.servers:
        if server["id"] == requested:
            return server
    abort(404)

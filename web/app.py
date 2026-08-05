"""Flask application factory for the read-only OSRS event log UI.

Separate process, separate venv, separate systemd unit from the Discord bot.
It shares one thing with the bot: the SQLite file, which it opens read-only.
"""

import os
from datetime import timedelta

from flask import (Flask, abort, g, jsonify, redirect, render_template,
                   request, url_for)

# `format` is bound as `fmt` so it does not shadow the builtin inside this
# module.
from . import auth, config, db, queries
from . import format as fmt
from data import repo


def create_app(env=None):
    settings = config.Config(env)

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.secure_cookies,
        PERMANENT_SESSION_LIFETIME=timedelta(days=settings.session_days),
        SERVER_NAMES=settings.server_names,
        RATE_ATTEMPTS=settings.rate_limit_attempts,
        RATE_WINDOW=settings.rate_limit_window,
        DB_PATH=settings.db_path,
    )

    db.open_readonly(settings.db_path)
    # Refuse to start if the connection turned out to be writable. A read-only
    # service that can quietly write to the bot's live database is worse than
    # one that does not start.
    db.assert_read_only()

    fmt.register(app)
    app.before_request(auth.load_context)

    @app.after_request
    def no_shared_caching(response):
        """Anything rendered for a signed-in member is private.

        Cloudflare sits in front of this. Without an explicit header it may
        cache a page built for one member's server set and serve it to another,
        which would be a data leak dressed up as a performance win.

        STATIC FILES ARE EXEMPT, and must be. They are skill icons, CSS and a
        charting library: the same bytes for everyone, containing nothing about
        anybody. Marking them `no-store` told browsers they may not be kept at
        all, so every page load re-fetched all ~120 icons. On the dev server
        that produced randomly missing images, because a handful of the
        parallel requests lost; in production it would have meant Cloudflare
        never caching them and every view pulling the whole set down again.

        setdefault, not assignment, so Flask's own debug behaviour (which sends
        no-cache for static) still wins and edited CSS shows up on reload.
        """
        if request.endpoint == "static":
            # Flask's own default is `no-cache`, which stores the file but
            # revalidates every single time: 120 conditional requests per page
            # view even when nothing changed. Give them a real lifetime in
            # production, and leave debug alone so an edited stylesheet still
            # appears on reload.
            response.headers["Cache-Control"] = (
                "no-cache" if app.debug else "public, max-age=86400")
        elif auth.signed_in():
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
        else:
            response.headers.setdefault("Cache-Control", "public, max-age=60")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    # A day of caching is only safe if changing the file changes its URL.
    #
    # It was not, and the first deploy after a stylesheet change proved it: the
    # CDN kept serving the previous app.css on a HIT with an age of nearly an
    # hour while the origin had the new one, so a whole rewrite of the mobile
    # layout was invisible to anybody who had loaded the site that day. The
    # sprite has the same problem and is worse, because a stale sprite lines
    # every icon up against the wrong cell.
    #
    # Appending the file's mtime gives each version its own URL. The old one
    # stays cached and unreferenced, the new one is a miss, and neither the CDN
    # nor a browser has to be told anything.
    _asset_versions = {}

    @app.url_defaults
    def stamp_static_url(endpoint, values):
        if endpoint != "static" or "filename" not in values:
            return
        filename = values["filename"]
        # Memoised, because this runs for every icon on every page render and
        # a stat() each time would be thousands of syscalls a page. A deploy
        # restarts the process, which is what clears it. Not memoised under the
        # dev server, where the point is to see an edit without restarting.
        version = _asset_versions.get(filename) if not app.debug else None
        if version is None:
            try:
                version = int(os.stat(
                    os.path.join(app.static_folder, filename)).st_mtime)
            except OSError:
                # A missing file is the 404's problem, not this hook's.
                version = 0
            if not app.debug:
                _asset_versions[filename] = version
        if version:
            values["v"] = version

    @app.context_processor
    def template_globals():
        return {
            "signed_in": auth.signed_in(),
            "nav_servers": getattr(g, "servers", []),
            "own_players": getattr(g, "own_players", set()),
        }

    # ----------------------------------------------------------------- #
    # Public
    # ----------------------------------------------------------------- #

    @app.route("/")
    def home():
        if not auth.signed_in():
            return render_template("public.html", summary=queries.public_summary())

        players = queries.players_index(g.player_ids)
        events = queries.events_feed(g.player_ids, limit=8)
        # Milestones separately rather than filtered out of the list above.
        # They are 2.5% of the feed, so the most recent eight of them can be
        # weeks older than the most recent eight events, and a single query
        # cannot answer both questions.
        milestones = queries.events_feed(g.player_ids, limit=8,
                                         milestones_only=True)
        server = g.servers[0] if g.servers else None
        return render_template(
            "home.html",
            summary=queries.public_summary(),
            players=players[:8],
            player_count=len(players),
            events=events,
            milestones=milestones,
            server=server,
            sotw=queries.live_standings(server["id"], "sotw", limit=5) if server else [],
            botw=queries.live_standings(server["id"], "botw", limit=5) if server else [],
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            if auth.rate_limited():
                error = ("Too many attempts. Wait a few minutes and try again.")
            else:
                password = request.form.get("password", "").strip()
                if auth.sign_in(password):
                    target = request.args.get("next") or url_for("home")
                    # Only ever redirect within this site.
                    if not target.startswith("/") or target.startswith("//"):
                        target = url_for("home")
                    return redirect(target)
                auth.record_failure()
                error = ("That password was not recognised. Run ;webpassword in "
                         "Discord to have a new one sent to you.")
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    def logout():
        auth.sign_out()
        return redirect(url_for("home"))

    # ----------------------------------------------------------------- #
    # Your own accounts
    # ----------------------------------------------------------------- #

    @app.route("/me")
    @auth.require_login
    def me():
        names = app.config["SERVER_NAMES"]
        accounts = []
        for row in queries.own_accounts(g.member_id):
            accounts.append({
                "player": row,
                "links": queries.own_account_links(row["id"], g.member_id, names),
                "elsewhere": queries.other_owner_servers(row["id"], g.member_id),
                "sotw_podiums": queries.podium_count(row["id"], row["rs_name"], "sotw"),
                "botw_podiums": queries.podium_count(row["id"], row["rs_name"], "botw"),
                "depth": queries.history_depth(row["id"]),
            })
        return render_template(
            "me.html",
            accounts=accounts,
            me=queries.my_identity(g.member_id),
            credential=queries.credential_info(g.member_id),
            visible_count=len(g.player_ids),
        )

    # ----------------------------------------------------------------- #
    # Players
    # ----------------------------------------------------------------- #

    @app.route("/players")
    @auth.require_login
    def players():
        rows = queries.players_index(g.player_ids)
        show_all = request.args.get("all") == "1"
        # Players with no stat rows are the documented odd cases: tracked with
        # an empty skills dict, or in a server list but never polled. Hidden by
        # default so the table is not padded with rows of dashes.
        visible = rows if show_all else [r for r in rows if r["skill_rows"]]
        return render_template(
            "players.html", players=visible, total=len(rows),
            hidden=len(rows) - len(visible), show_all=show_all)

    @app.route("/players/<rs_name>")
    @auth.require_login
    def player(rs_name):
        row = queries.player_by_name(rs_name, g.player_ids)
        if row is None:
            abort(404)
        player_id = row["id"]
        server_ids = [s["id"] for s in g.servers]
        moved = queries.skills_with_movement(player_id)
        moved_activities = queries.activities_with_movement(player_id)
        skills = queries.player_skills(player_id)
        default_skill = moved[0] if moved else (
            "Overall" if any(s["name"] == "Overall" for s in skills)
            else (skills[0]["name"] if skills else None))
        return render_template(
            "player.html",
            player=row,
            skills=skills,
            activities=queries.player_activities(player_id),
            servers=queries.player_server_labels(
                player_id, app.config["SERVER_NAMES"]),
            # Two queries, not one filtered in the template, for the reason the
            # home page needs two: milestones are a fortieth of the feed, so
            # this account's ten most recent can be years older than its ten
            # most recent events.
            events=queries.events_feed(g.player_ids, limit=10,
                                       player_id=player_id),
            event_count=queries.events_count(g.player_ids, player_id=player_id),
            milestones=queries.events_feed(g.player_ids, limit=10,
                                           player_id=player_id,
                                           milestones_only=True),
            milestone_count=queries.events_count(g.player_ids,
                                                 player_id=player_id,
                                                 milestones_only=True),
            owners=queries.player_owners(player_id),
            depth=queries.history_depth(player_id),
            movers=moved,
            active_movers=moved_activities,
            default_skill=default_skill,
            sotw_podiums=queries.player_podiums(
                player_id, row["rs_name"], "sotw", server_ids),
            botw_podiums=queries.player_podiums(
                player_id, row["rs_name"], "botw", server_ids),
        )

    @app.route("/members")
    @auth.require_login
    def members():
        return render_template(
            "members.html",
            members=queries.members_index(g.member_id, g.player_ids))

    @app.route("/members/<handle>")
    @auth.require_login
    def member(handle):
        """One Discord member and the accounts they own.

        Addressed by an opaque handle rather than by Discord id: a member id
        may appear on this site only inside an avatar URL, and `/members/<id>`
        is one of the cases test_privacy.py exists to catch.

        Visibility is the same rule as everywhere else and is applied twice
        over. member_by_handle only considers members who share an active
        server with the viewer, so an unknown handle and somebody else's handle
        are indistinguishable; and the accounts listed are intersected with the
        viewer's own visible players, so an account this member owns in a
        server the viewer is not in does not appear.
        """
        row = queries.member_by_handle(handle, g.member_id)
        if row is None:
            abort(404)
        return render_template(
            "member.html",
            member=row,
            is_you=row["id"] == g.member_id,
            accounts=queries.member_accounts(row["id"], g.player_ids),
            servers=queries.member_shared_servers(
                row["id"], g.member_id, app.config["SERVER_NAMES"]),
        )

    @app.route("/players/<rs_name>/history.json")
    @auth.require_login
    def player_history(rs_name):
        row = queries.player_by_name(rs_name, g.player_ids)
        if row is None:
            abort(404)
        skill = request.args.get("skill")
        activity = request.args.get("activity")

        if activity:
            rows = queries.activity_history(row["id"], activity)
            series = [{"t": fmt.parse_ts(r["recorded_at"]).timestamp() * 1000,
                       "y": r["score"], "at": r["recorded_at"],
                       "r": r["recovered"]}
                      for r in rows if fmt.parse_ts(r["recorded_at"])]
            return jsonify({"label": activity, "unit": "KC", "points": series})

        if not skill:
            abort(400)
        rows = queries.skill_history(row["id"], skill)
        series = [{"t": fmt.parse_ts(r["recorded_at"]).timestamp() * 1000,
                   "y": r["xp"], "level": r["level"], "at": r["recorded_at"],
                   # 1 where the value was read back out of an old Discord
                   # post rather than polled. The chart joins those with a
                   # straight line and steps the polled ones.
                   "r": r["recovered"]}
                  for r in rows if fmt.parse_ts(r["recorded_at"])]
        return jsonify({"label": skill, "unit": "XP", "points": series})

    # ----------------------------------------------------------------- #
    # Events
    # ----------------------------------------------------------------- #

    @app.route("/events")
    @auth.require_login
    def events():
        page = max(1, request.args.get("page", type=int, default=1))
        per_page = 50
        source = request.args.get("source") or None
        event_type = request.args.get("type") or None
        milestones_only = request.args.get("milestones") == "1"
        # Footers (Overall, SOTW, BOTW totals) are stored but hidden by
        # default. They ride along on other players' updates rather than being
        # events, and there are enough of them to bury everything else.
        include_footers = request.args.get("footers") == "1"

        # ?player=<rs_name> narrows the feed to one account, which is how the
        # player page links here: the tabs, the type menu and the pager are all
        # already built, so this reuses them rather than growing a second feed
        # on the player page that would need its own copy of each.
        #
        # Resolved through player_by_name, which is the SAME visibility rule
        # the player page itself uses. A name outside the member's servers 404s
        # rather than silently widening to everybody, so this cannot be used to
        # confirm that an account exists.
        player_name = request.args.get("player") or None
        player = None
        if player_name:
            player = queries.player_by_name(player_name, g.player_ids)
            if player is None:
                abort(404)

        player_id = player["id"] if player else None
        filters = dict(source=source, event_type=event_type,
                       player_id=player_id,
                       milestones_only=milestones_only,
                       include_footers=include_footers)
        return render_template(
            "events.html",
            events=queries.events_feed(
                g.player_ids, limit=per_page, offset=(page - 1) * per_page,
                **filters),
            total=queries.events_count(g.player_ids, **filters),
            page=page, per_page=per_page,
            source=source, event_type=event_type,
            player=player,
            milestones_only=milestones_only, include_footers=include_footers,
            kinds=queries.event_types(g.player_ids,
                                      include_footers=include_footers,
                                      player_id=player_id))

    # ----------------------------------------------------------------- #
    # Competitions
    # ----------------------------------------------------------------- #

    @app.route("/competitions/<kind>")
    @auth.require_login
    def competitions(kind):
        if kind not in ("sotw", "botw"):
            abort(404)
        conf = queries.comp(kind)
        server = auth.current_server(request.args.get("server", type=int))
        page = max(1, request.args.get("page", type=int, default=1))
        per_page = 25
        return render_template(
            "competitions.html",
            kind=kind, conf=conf, server=server,
            current=queries._config_value(
                kind, "current_skill" if kind == "sotw" else "current_boss"),
            live=queries.live_standings(server["id"], kind),
            standings=queries.all_time_standings(server["id"], kind),
            weeks=queries.past_weeks(server["id"], kind, limit=per_page,
                                     offset=(page - 1) * per_page),
            weeks_total=queries.weeks_count(server["id"], kind),
            page=page, per_page=per_page,
        )

    # ----------------------------------------------------------------- #
    # Leaderboards
    # ----------------------------------------------------------------- #

    @app.route("/leaderboards")
    @auth.require_login
    def leaderboards():
        skills = queries.skill_names()
        activities = queries.activity_names()
        activity = request.args.get("activity") or None
        skill = request.args.get("skill") or (None if activity else "Overall")
        if skill and skill not in skills:
            abort(404)
        if activity and activity not in activities:
            abort(404)

        # No `server` argument means every server the member is in, which is the
        # default because a combined leaderboard is the more useful view when
        # you are in several. Competitions differ: standings are stored per
        # server, so there is no meaningful "all".
        server = auth.optional_server(request.args.get("server", type=int))
        ids = (queries.narrow_to_server(g.player_ids, server["id"])
               if server else g.player_ids)

        return render_template(
            "leaderboards.html",
            skills=skills, activities=activities,
            skill=skill, activity=activity, server=server,
            shown=len(ids), total=len(g.player_ids),
            rows=(queries.activity_leaderboard(ids, activity)
                  if activity else
                  queries.skill_leaderboard(ids, skill)),
        )

    # ----------------------------------------------------------------- #
    # Errors
    # ----------------------------------------------------------------- #

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404,
                               message="Nothing here."), 404

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403,
                               message="Not yours to see."), 403

    @app.errorhandler(500)
    def server_error(_):
        # No exception detail in the response. Tracebacks can echo query text
        # and row values, and this database holds bearer tokens and Discord ids.
        return render_template("error.html", code=500,
                               message="Something went wrong."), 500

    @app.route("/healthz")
    def healthz():
        return jsonify({
            "ok": True,
            "players": repo.db.scalar("SELECT COUNT(*) FROM players", (), 0),
            "read_only": True,
        })

    return app


def build():
    """Entry point for `flask --app web.app:build run` and for wsgi.py."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    return create_app()

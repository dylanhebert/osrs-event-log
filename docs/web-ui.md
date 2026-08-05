# Read-only web UI

A Flask app that renders the bot's SQLite database. Separate process, separate
virtualenv, separate systemd unit, separate port. It shares exactly one thing
with the bot: the database file, which it opens read-only.

Shell snippets use the same placeholders as
[sqlite-migration.md](sqlite-migration.md):

| | |
|---|---|
| `$APP_ROOT` | the repo checkout on the server |
| `$APP_DIR` | the inner `osrs-event-log` directory |
| `$WEB_VENV` | the UI's virtualenv, `$APP_ROOT/web/.venv` |
| `$WEB_HOST` | the hostname this UI is served on |
| `$DINK_HOST` | the existing hostname the Dink webhook uses, which can never change |

---

## Why it lives in this repo

The UI imports `data/repo/` directly, which is the reason that package has no
discord.py dependency. Splitting it into its own repository would mean a
submodule, a published package, or a second copy of every query, and schema
changes would have to land in two places at once for a database both services
share.

The cost is that one `git pull` updates both. That is managed by a rule rather
than by separation:

> a change that touches only `web/` never requires a bot restart

which is checkable before deploying:

```bash
git diff --stat <old>..<new> -- osrs-event-log/
```

Empty output means the bot's code did not move, so only the UI needs
restarting. This is why UI query logic lives in `web/queries.py` rather than in
`data/repo/`.

---

## Layout

```
web/
  config.py          settings; puts the bot's package on sys.path
  db.py              opens the database read-only, once per process
  queries.py         every SQL statement the UI runs
  auth.py            sign-in, sessions, the visibility rule
  app.py             routes
  wsgi.py            gunicorn entry point
  format.py          Jinja filters (commas, ranks, relative times)
  templates/         public, login, home, me, players, player, events,
                     competitions, leaderboards, error
  static/
  tests/
    smoke.py         every route renders, signed out and signed in
    test_privacy.py  no private column reaches any response
  tools/
    dev_issue_password.py   stands in for the bot locally
```

Inside the bot's package, this project added:

```
data/repo/webauth.py            credentials (bot writes, UI reads)
data/repo/db.py                 + connect_readonly(), nothing else changed
data/schema.sql                 + web_credentials table
cogs/cmds/web.py                ;webpassword and ;webrevoke
osrs-event-log.py               + one line in initial_extensions
tools/migrate_add_web_auth.py   applies the new table to a live database
tools/test_web_auth.py          credential and visibility tests
tools/test_cog_load.py          constructs the Bot and loads every extension
```

---

## The working directory is not load-bearing here

The bot builds every path from `pathlib.Path().absolute()`, so it dies at import
if started from the wrong directory. The UI deliberately does not inherit that:
paths come from `__file__`, and the database path is an explicit setting with no
default. Gunicorn's `WorkingDirectory` does not matter to this service.

---

## Read-only, three ways

1. The database is opened `file:...?mode=ro`.
2. `PRAGMA query_only = ON`.
3. Nothing in `web/` calls a repo write function.

At startup the app also *proves* the connection is read-only by attempting a
`CREATE TABLE` and refusing to start if it succeeds. A read-only service that is
quietly writable is worse than one that does not boot.

`connect_readonly()` deliberately does **not** set `PRAGMA journal_mode`. That
pragma writes the database header, which is the one thing a reader must never
do. WAL is already on; the bot set it.

### The WAL caveat that will eventually bite

A read-only connection to a WAL database still needs **write permission on the
`-shm` lock file**, or on the directory if `-shm` does not exist. `mode=ro`
restricts the database file, not the locking machinery.

Bot and UI run as the same user, so this works today. The day the UI is given
its own user, reads start failing with `unable to open database file`. The fix
is file permissions. It is **not** `immutable=1`, which would hand the UI a
stale and potentially torn view of a database that is actively being written.

---

## Who can see what

Sign-in identity is the **Discord member**, not the player: a member may own up
to three accounts, and the access rule is a property of the member.

```
servers(M) = active servers where M has any player_servers row
players(M) = every player linked to any server in servers(M)
```

Recomputed on every request from `player_servers`, never cached in the cookie.
Removing someone from every server therefore revokes their access immediately,
with no session store to clean up and nothing for the bot to do.

Signed out, the site shows **aggregates only**: counts, totals, the current
skill and boss. No player names, no server names, no ids. Nothing on the public
page identifies a real person.

### Passwords

`;webpassword` generates a 256-bit value, stores **only its sha256**, and DMs
it. Running it again issues a new one and retires the old. There is deliberately
no way to read a password back out, so a stolen database or a nightly backup
contains no usable credential.

Unsalted sha256 is correct for this and is not the usual password-storage
mistake: these are `secrets.token_urlsafe(32)` values, not human-chosen
passwords, so there is no dictionary to attack and nothing for a slow KDF to
buy. A salt would also break sign-in, which finds the member *by* hash because
the browser sends only a password.

The session cookie carries the member id plus a short fingerprint of the
credential. Both are re-checked per request, so `;webpassword` and `;webrevoke`
sign out browsers that are already open rather than only affecting future
sign-ins.

### Server names and icons

The database never held guild names: the bot always had `discord.Guild` objects
to hand. The UI has no Discord connection, so `servers.name` and
`servers.icon_hash` (schema version 3) are filled in by the bot from listeners
in `cogs/cmds/web.py`, on ready and on join or rename. Nothing has to be
configured, and a rename shows up on its own.

A label resolves in this order:

1. `SERVER_NAMES`, if you want something friendlier than the real guild name
2. `servers.name`, kept in step by the bot
3. `Server 1`, `Server 2`, ...

Never the raw snowflake. Until the bot has restarted once after the migration,
every name is NULL and the UI shows ordinals; that is the designed degraded
state, not a failure.

Icon URLs are built from `(id, hash)` rather than stored, so the CDN host stays
Discord's to change. They are the **only** external request the site makes,
appear on authenticated pages only, and `Referrer-Policy: same-origin` keeps the
page path from reaching Discord. A guild with no icon falls back to a monogram,
so the layout does not shift.

> **Cog listeners must be decorated.** A bare `async def on_ready` inside a Cog
> is never called by py-cord. The undecorated `on_ready` methods in `user.py`,
> `admin.py` and `looper.py` are dead code; the sync listeners carry
> `@commands.Cog.listener()` for that reason.

### Event text

`events.message` is the exact text posted to Discord, so it arrives full of
Discord markup: `**bold**`, ```` ```c ```` fenced blocks, mentions. The
`discord_markup` Jinja filter renders it.

**That filter emits HTML, so escaping is not optional.** Dink message text is
built from a payload a player's RuneLite client POSTs to a public endpoint,
authenticated only by a bearer token that two accounts already share: treat it
as attacker-controlled. Code is extracted first so markup inside a fence stays
literal, everything else is escaped before a single tag is added, and mentions
become `@someone` / `@role` rather than rendering a Discord id.

`web/tests/test_markup.py` covers the injection cases first and the formatting
second, which is the right order of importance.

### Server scoping

Competitions are per server, so `/competitions/<kind>` always shows exactly one
and defaults to the member's first. Leaderboards default to **all** the
member's servers, with tabs to narrow to one, because a combined board is the
more useful view when you are in several.

Narrowing filters the already-visible list rather than querying the server
directly, so a server filter can only ever remove players, never add them. A
server the member is not in returns 404 rather than falling back to "all",
which would turn a guessed id into a silent, wrong-looking answer.

### Member names and avatars

`discord_members` (schema version 4) holds the name and avatar hash of people
who own an account, synced by the same cog listeners. **Only members who already
appear in `player_servers`.** The bot can see everyone in every guild it is in;
storing the rest would mean holding profile data about people who have nothing
to do with this log.

`repo.members.prune_unlinked()` exists so that leaving the log can be made to
drop the profile data too. It is not called automatically.

### Never rendered

| column | why |
|---|---|
| `players.dink_link_key` | bearer tokens for the public webhook. Anyone holding one can post events as any player. |
| `player_servers.member_id` | real Discord user ids, **except inside an avatar URL** |
| `events.payload` | raw Dink bodies, which carry `dinkAccountHash` |
| `web_credentials.token_hash` | sign-in hashes |

**The one sanctioned exception.** A Discord avatar lives at
`cdn.discordapp.com/avatars/<user_id>/<hash>`, so rendering one unavoidably puts
that id in the page. That trade was taken deliberately: the page is only ever
served to someone who shares a Discord server with that member, and they can
already read the same id in Discord with developer mode on.

The rule is narrowed, not dropped. A member id may appear **only** inside an
avatar URL on the CDN host. `test_privacy.py` strips exactly that pattern before
checking, and has cases proving an id is still caught as page text, in a link,
on another host, and inside a guild icon URL. It also asserts that avatar URLs
actually rendered, so the exemption cannot pass vacuously.

Queries enumerate columns for this reason. `SELECT *` is banned in
`web/queries.py`, including via repo helpers: `repo.players.get()` does
`SELECT *` and returns the Dink key, so the UI must not call it.

---

## Charts

Chart.js 4.4.7, vendored (see `web/static/js/VENDOR.md`). Three deliberate
choices:

- **Polled points are stepped, `tension: 0`.** A history row is written only
  when a value actually changes, so between two recorded points the value was
  *constant*. A smooth or straight-line join would draw XP the player never
  had, at times they never had it.
- **Recovered points are not stepped.** See below.
- **A linear x axis over epoch milliseconds**, not a category axis and not a
  time scale. A time scale needs a date adapter, which is a second library to
  vendor; a category axis would space a year of silence and twenty minutes
  identically.

Where a player has fewer than two distinct recorded timestamps, the page says so
instead of drawing a chart.

### History recovered from Discord

Nothing recorded a player's numbers before the storage migration: the looper
compared them, posted a message and threw them away. So the charts began with
one day of data and drew nothing for 66 of 69 players.

The numbers survived in the messages, though, and the Discord backfill has
since pulled six years of those into `events`.
`tools/backfill_history_from_events.py` reads the totals back out of that text
and writes them as history with `recovered = 1` (schema version 7).

Only two shapes count as a lifetime total, both written by `PlayerUpdate` from
the hiscores payload itself:

```
Total <Skill> XP: 217,223                       -> that skill
Total level: 977 | Total Overall XP: 3,358,189  -> Overall, with its level
```

> **`Skill of the Week - Current <Skill> XP: N` is not one of them.** It has the
> same shape and is a *weekly accumulator*: `PlayerUpdate` builds it from
> `new_sotw_xp`, which `add_to_player_entry_global` adds to across the week and
> resets when the week rolls over. Read as a lifetime total it would draw a
> sawtooth of weekly gains under every curve, with nothing to suggest anything
> was wrong. `tools/test_history_backfill.py` guards this first.

The tool filters as well as parses, because a single wrong point rescales a
chart's whole y axis. A point is dropped when the message's bold title names a
different player, when it would make the series go *backwards* (XP never
decreases, so a value below the running maximum cannot belong here), or when it
exceeds what the player had at the time. Everything dropped is counted and
sampled in the report. On the live data that was 900 points in 29,000.

**Why the two halves are drawn differently.** A polled value was written only
when it changed, so a step is honest. A recovered one exists only where a
message happened to be posted — every level below 99, but only the occasional
threshold above it — so between two of them the player was climbing, often for
months. Stepping those would draw a flat year followed by a cliff, which is a
bigger lie than the straight line. The series is split at the boundary, the
recovered half is dashed to say outright that it is reconstructed, and the
boundary point belongs to both halves so the line does not break.

Safe to run, and safe to undo:

```sql
DELETE FROM player_skill_history WHERE recovered = 1;
```

Nothing in the bot's change-detection path reads these tables — `repo.stats`
only inserts into them, and the looper compares against
`player_skill_current` — so writing here cannot make a poll see a change, and
cannot cause a Discord post.

---

## Local development

Python **3.14** locally, matching the droplet.

```bash
py -V:3.14 -m venv web/.venv          # Windows
web/.venv/Scripts/pip install -r requirements-web.txt

cp web/.env.example web/.env
python -c "import secrets; print(secrets.token_hex(32))"   # SECRET_KEY
```

`gunicorn` is in `requirements-web.txt` but is server-only: it imports `fcntl`,
which does not exist on Windows.

### Get real data

Take an **atomic snapshot**. The bot is writing to the live file, so a plain
`scp` of it can catch a torn read.

```bash
ssh <deploy-user>@<host> \
  'sqlite3 $APP_DIR/data/osrs.db ".backup /tmp/ui-dev.db"'
scp <deploy-user>@<host>:/tmp/ui-dev.db fixtures/ui-dev.db
ssh <deploy-user>@<host> 'rm -f /tmp/ui-dev.db'

cd $APP_DIR && python tools/migrate_add_web_auth.py --db ../fixtures/ui-dev.db
```

`fixtures/` and `*.db` are gitignored. **Never develop against
`osrs-event-log/data/osrs.db`** — that is the bot's own working database.

### Sign in locally

There is no bot running locally, so a helper plays its part. It refuses to write
anywhere but `fixtures/`.

```
web\.venv\Scripts\python.exe -m web.tools.dev_issue_password --list
web\.venv\Scripts\python.exe -m web.tools.dev_issue_password
```

### Start and stop

Run from the repo root.

**Do not activate a virtualenv first, and in particular not the bot's.** The
repo's top-level `.venv` is the Discord bot's: different Python version,
py-cord, and no Flask at all. Calling the UI interpreter by its full path
selects the right environment on its own, which is why nothing below activates
anything.

Backslashes. `cmd.exe` reads a leading `web/...` as a command name and fails
with *'web' is not recognized*; the backslash form works in `cmd.exe`,
PowerShell and Git Bash alike.

`--debug` turns on the auto-reloader so template and Python edits take effect
without a restart. It also turns on the interactive debugger, so it is for local
use only, never the droplet.

```
:: start
web\.venv\Scripts\python.exe -m flask --app "web.app:build" run --port 5007 --debug

:: stop
:: Ctrl+C in that terminal
```

If a stale process is still holding the port:

```powershell
Get-NetTCPConnection -LocalPort 5007 -State Listen |
  Select-Object -ExpandProperty OwningProcess |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

Then open http://127.0.0.1:5007 and sign in with the password the helper
printed.

---

## Tests

```
web\.venv\Scripts\python.exe -m web.tests.smoke         # every route renders
web\.venv\Scripts\python.exe -m web.tests.test_privacy  # no secret reaches a response
web\.venv\Scripts\python.exe -m web.tests.test_markup   # message rendering cannot inject HTML

cd $APP_DIR && python tools/test_web_auth.py            # credentials + visibility
cd $APP_DIR && python tools/test_cog_load.py            # every cog still loads
```

The bot-side tests must keep passing under the **bot's** virtualenv, which has
no Flask in it. That is the check that the UI's dependencies have not crept into
the bot's: `data/repo/` already avoids discord.py so the UI can import it, and
the reverse has to hold too. The access rule therefore lives in
`data/repo/webauth.py` rather than in `web/queries.py`.

**Snapshot databases with SQLite's backup API, never `shutil.copy2`.** The
database is in WAL mode, so recent commits can still be sitting in the `-wal`
file and copying the `.db` alone yields a silently stale snapshot. That is the
same reason the server pull uses `.backup`, and it has already bitten once here:
a schema migration applied moments earlier was invisible to a copied fixture and
every page 500'd with *no such column*.

`test_privacy.py` is the one that matters. Code review does not enforce a
privacy rule: one `SELECT *`, one debug template, one error page that echoes a
row, and a webhook bearer token is public. It pulls the real secrets out of the
database, crawls every route signed in, and fails if any appears in any response
body or header. It plants canaries first so it cannot pass vacuously, and it
prints **no secret values** on failure, only what leaked and where.

It has been verified to fail when it should, by temporarily selecting and
rendering `dink_link_key`.

---

## Deploying

Port **8007**. The Dink webhook keeps `$DINK_HOST` on **8006** and
`DINK_BASE_URL` never changes: that URL is baked into every player's RuneLite
config and cannot move. Two hostnames, two Caddy blocks, one droplet.

```bash
ssh <deploy-user>@<host>

# 0. an atomic snapshot to roll back to. Not a copy: see the WAL note below.
sqlite3 $APP_DIR/data/osrs.db ".backup $BACKUPS/pre-webui-deploy.db"
sqlite3 $BACKUPS/pre-webui-deploy.db "pragma integrity_check;"

# 1. code
git -C $APP_ROOT pull

# 2. the new tables and columns. Idempotent, additive, safe to run twice.
cd $APP_DIR
python tools/migrate_add_web_auth.py --report
python tools/migrate_add_web_auth.py --db data/osrs.db

# 3. the UI's own venv. `python` here is the pyenv shim, so it depends on
#    .python-version naming a version that is actually installed.
cd $APP_ROOT
python -V                          # must succeed before the next line
python -m venv web/.venv
web/.venv/bin/pip install -r requirements-web.txt

# 4. check it serves before wiring anything up
$WEB_VENV/bin/gunicorn web.wsgi:app --workers 2 --bind 127.0.0.1:8007
```

The migration can run against the live database with the bot up. Adding a
column takes a brief write lock and rewrites no row, and every statement in the
bot enumerates its columns, so the running process keeps working against the
new schema until it is restarted.

### `.python-version` has to name an installed version

Step 3 is the first thing in a deploy that goes through a pyenv shim. The bot
never does: systemd invokes `.venv/bin/python` by absolute path, so a
`.python-version` naming an uninstalled release can sit there indefinitely
without the running service noticing, and then fail the first time somebody
creates a virtualenv:

```
pyenv: version `3.11.2' is not installed
```

The file is tracked, so fixing it only on the server gets reverted by the next
pull. It names a *prefix* (`3.14`), which pyenv resolves to whichever patch
release is installed, so a server-side patch upgrade needs no commit here.

### Order matters: DNS before Caddy

Caddy asks Let's Encrypt for a certificate the moment the new block loads, and
the challenge is served through Cloudflare. **Add the A record first.** Restart
Caddy against a name that does not resolve yet and the issuance fails and backs
off, so the site 502s for a while after everything is otherwise correct.

Working order:

1. Cloudflare A record → the droplet, proxied
2. restart the bot, if bot code moved
3. install, `enable --now`, and check the web unit
4. append the Caddy block and restart Caddy

### Nobody can sign in until a password is issued

A freshly deployed instance has **zero rows in `web_credentials`**, and the UI
has no way to create one — by design, the bot is the only writer. The last step
of a deploy is running `;webpassword` in Discord. Until then every sign-in
attempt correctly fails and the site shows only the anonymous aggregate page,
which looks identical to a broken deploy from the outside.

The first deploy also changes bot code (the new cog and one line in
`initial_extensions`), so the bot needs restarting once. Later UI-only deploys
do not — check with the `git diff --stat -- osrs-event-log/` above.

### systemd

```ini
[Unit]
Description=OSRS Event Log web UI
After=network.target

[Service]
User=deploy
Group=deploy
WorkingDirectory=$APP_ROOT
Environment=OSRS_DB_PATH=$APP_DIR/data/osrs.db
Environment=SECRET_KEY=<64 hex chars>
Environment=SECURE_COOKIES=1
Environment=SERVER_NAMES=<id>:<label>,<id>:<label>
ExecStart=$WEB_VENV/bin/gunicorn web.wsgi:app --workers 2 --bind 127.0.0.1:8007
Restart=always

[Install]
WantedBy=multi-user.target
```

**Sync workers, not `gthread`.** The repo layer keeps one module-global sqlite3
connection; sync workers are separate processes so each gets its own. Using
threads without first giving `web/db.py` a thread-local connection is a real
bug, not a theoretical one.

`SECURE_COOKIES=1` behind Caddy. A secure cookie is not sent over plain http, so
setting it locally silently breaks sign-in.

`SERVER_NAMES` is optional and usually better left out. The bot already syncs
real guild names into `servers.name` and keeps them in step through a rename;
setting this overrides them everywhere and has to be maintained by hand.

**Name the unit for the service, not for the subdomain.** The convention
elsewhere on this host is `<subdomain>.service`, which here would give
`osrseventlog.service` sitting next to the bot's `osrs-event-log.service` —
two names differing only by hyphens, where picking the wrong one takes down the
Dink webhook. `osrs-event-log-web.service` cannot be confused with it.

Write the unit file with `SECRET_KEY` already substituted rather than pasting
the value through a terminal, and delete whatever staged it afterwards:

```bash
python -c "import secrets; print(secrets.token_hex(32))" > /tmp/k && chmod 600 /tmp/k
# ... build the unit from it ...
sudo install -o root -g root -m 644 /tmp/<unit> /etc/systemd/system/<unit>
shred -u /tmp/k /tmp/<unit>
```

Rotating `SECRET_KEY` invalidates every session cookie, so it signs everyone
out but costs nothing else: the credentials themselves live in the database.

### Caddy

```
$WEB_HOST {
    reverse_proxy 127.0.0.1:8007
}
```

**Leave the existing `$DINK_HOST` block on 8006 alone.** Breaking that route
breaks every player's Dink plugin, and Dink does not retry.

### Cloudflare

An A record for the UI's subdomain pointing at the droplet, proxied. The app sends
`Cache-Control: private, no-store` on authenticated responses; without it
Cloudflare could cache a page built for one member's servers and serve it to
another.

### Backups

None needed. The UI holds no state of its own, and `backup-db.sh` already covers
the database.
